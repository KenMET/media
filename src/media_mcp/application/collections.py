"""Work-level library views and frozen, explicitly approved maintenance plans."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import uuid

from sqlalchemy import text

from media_mcp.config import contained, download_root
from media_mcp.runtime.state import media_mutation_lock, assert_mutation_lock
from media_mcp.storage.records import require_fresh
from media_mcp.storage.media import _json_object

MAX_FILES = 500
READY_SUBTITLE_STATUSES = {'translated','linked','exists','completed','verified','extracted','converted','embedded_extracted','downloaded'}
EPISODE = re.compile(r'(?i)(?<![a-z0-9])s(\d{1,2})[ ._-]*e(\d{1,3})(?!\d)')
EXTRA_FOLDER = re.compile('(?i)^(?:extras?|bonus(?:[ ._-]+features?)?|featurettes?|behind[ ._-]+the[ ._-]+scenes|deleted[ ._-]+scenes|trailers?|samples?|\u7279\u5178|\u82b1\u7d6e|\u5e55\u540e|\u5e55\u540e\u82b1\u7d6e|\u9884\u544a\u7247|\u9644\u52a0\u5185\u5bb9)$')
EXTRA_NAME = re.compile('(?i)(?:^|[\\s._\\[(-])(?:sample|trailer|featurette|NCOP|NCED|PV|CM)(?:$|[\\s._\\])\\d-])|\u7279\u5178|\u82b1\u7d6e|\u5e55\u540e\u5236\u4f5c|\u5220\u51cf\u7247\u6bb5|\u9884\u544a\u7247')


def classify(file):
    """Explicit evidence only: a short or unfamiliar title is never enough."""
    if file.get('media_type')=='tv_extra' or file.get('season')==0:
        return {'category':'extra','reason':'record_special','owner':None}
    for raw in (file.get('source_path'),file.get('target_path')):
        if not raw:
            continue
        path=Path(raw)
        root=download_root() if raw==file.get('source_path') else library_root()
        try:parts=path.relative_to(root).parts
        except ValueError:continue
        for index,part in enumerate(parts[:-1]):
            if EXTRA_FOLDER.fullmatch(part):
                parent=Path(root).joinpath(*parts[:index])
                return {'category':'extra','reason':'extra_directory','owner':str(parent) if index else None}
        if (not file.get('media_tmdb_id') and not file.get('identity') and EXTRA_NAME.search(path.stem)) or (EPISODE.search(path.stem) and int(EPISODE.search(path.stem)[1])==0):
            return {'category':'extra','reason':'extra_filename','owner':None}
    return {'category':'main','reason':'no_extra_marker','owner':None}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def library_root():
    return Path(os.environ.get('MEDIA_LIBRARY_ROOT', '/data/media_hub')).resolve()


def file_state(path, role):
    if not path:
        return None
    value = contained(path, download_root() if role == 'source' else library_root(), exists=False)
    try:
        info = value.stat(follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('library_file_not_regular')
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def mapping_state(file):
    source, target = file_state(file.get('source_path'), 'source'), file_state(file.get('target_path'), 'target')
    if source and target:
        status = 'linked' if source[:2] == target[:2] else 'conflict'
    elif source:
        status = 'target_missing' if file.get('target_path') else 'unorganized'
    elif target:
        status = 'source_missing' if file.get('source_path') else 'library_only'
    else:
        status = 'missing'
    return {'source':source, 'target':target, 'status':status}


def video_changed(file,state):
    payload=_json_object(file.get('agent_result_json'))
    annotation=file.get('identity') or payload.get('library_identity')
    expected=annotation.get('video_fingerprint') if annotation else payload.get('_source_fingerprint')
    actual=state['source'] or state['target']
    return bool(actual) and (expected!=actual if expected else bool(file.get('title_id')))


def guess(file):
    path = Path(file.get('target_path') or file.get('source_path') or file['name'])
    match = EPISODE.search(path.stem)
    season, episode = (int(match[1]), int(match[2])) if match else (None, None)
    cleaned=re.sub(r'(?i)[ ._-]+(?:2160p|1080p|720p|web.?dl|bluray|x26[45]).*$', '', path.stem)
    release=re.search(r'\s+-\s+((?:19|20)\d{2})$',cleaned) or re.search(r'[.(（]((?:19|20)\d{2})[)）]?$',cleaned)
    try:
        parts = path.relative_to(library_root()).parts
    except ValueError:
        parts = ()
    if len(parts) >= 3 and parts[0] == 'series':
        title, kind, scope = parts[1], 'tv', 'series/'+parts[1]
    else:
        title = EPISODE.split(cleaned)[0] if match else cleaned[:release.start()] if release else cleaned
        title = title.strip(' ._-')
        kind = 'tv' if match else ('movie' if parts and parts[0] == 'movie' else 'unknown')
        # Unconfirmed TV folders from different locations never merge just by name.
        parent=path.parent
        if kind=='tv' and re.fullmatch('(?i)(?:season[ ._-]*\\d+|s\\d+|\u7b2c\\d+\u5b63)',parent.name):
            parent=parent.parent
        scope = str(parent)+':'+re.sub(r'[\W_]+','',title.casefold()) if kind == 'tv' else 'movie:'+title.casefold()+':'+(release[1] if release else '')
    return {'title':title or path.stem, 'kind':kind, 'scope':scope, 'season_hint':season,
            'episode_hint':episode, 'year_hint':int(release[1]) if release else None}


class Collections:
    def __init__(self, service):
        self.service, self.records = service, service.records
        self.db, self.actor = self.records.db, service.actor
        self.db.execute('''CREATE TABLE IF NOT EXISTS media_library_identity (
            path TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        self.db.execute('''CREATE TABLE IF NOT EXISTS media_library_classification (
            path TEXT PRIMARY KEY, category TEXT NOT NULL, fingerprint TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        self._title_cache=None

    def manage(self):
        if not self.actor.can_manage_media:
            raise ValueError('media_management_permission_required')

    def files(self):
        rows = self.db.execute('SELECT * FROM media_link ORDER BY id').mappings().all()
        files, seen = [], set()
        annotations = {row['path']:json.loads(row['data']) for row in self.db.execute('SELECT path,data FROM media_library_identity').mappings()}
        inventory=[]
        if self.db.table_exists('media_inventory'):
            latest=self.db.execute("SELECT id FROM media_mcp_record WHERE kind='inventory_scan' AND state='imported' ORDER BY updated_at DESC,rowid DESC LIMIT 1").scalar()
            inventory=[{**dict(row),'raw':json.loads(row['data'])} for row in self.db.execute('SELECT id,path,data FROM media_inventory WHERE scan_id=:scan ORDER BY id',{'scan':latest or ''}).mappings()]
        subtitles=defaultdict(list);ready_paths=defaultdict(list);known=set()
        for sub in self.db.execute('SELECT matched_video_target_path,target_subtitle_path,language,status,format FROM media_subtitle ORDER BY id').mappings():
            subtitles[sub['matched_video_target_path']].append({key:sub[key] for key in ('language','status','format')})
            if sub['status'] in READY_SUBTITLE_STATUSES:
                ready_paths[sub['matched_video_target_path']].append(sub['target_subtitle_path'])
            known.add((sub['matched_video_target_path'],sub['target_subtitle_path']))
        for item in inventory:
            raw=item['raw'];video=raw.get('video_path')
            if raw.get('kind')=='subtitle' and video and (video,item['path']) not in known:
                subtitles[video].append({'status':'discovered','language':None,'format':Path(item['path']).suffix.lstrip('.')})
        for row in rows:
            if not self.service._media_allowed(row):
                continue
            item = dict(row)
            item.update(key='m:'+str(row['id']), media_id=row['id'], name=Path(row['target_path'] or row['source_path']).name)
            item['identity'] = annotations.get(row['source_path']) or annotations.get(row['target_path'])
            item['subtitles'] = subtitles[row['target_path']]
            item['_ready_subtitle_paths']=ready_paths[row['target_path']]
            files.append(item); seen.update((row['source_path'],row['target_path']))
        if self.actor.can_manage_media:
            for row in inventory:
                raw = row['raw']
                if raw.get('kind') != 'video' or row['path'] in seen:
                    continue
                # A paired physical file already represented by a mapping is not another edition.
                if any(peer in seen for peer in raw.get('peers',[])):
                    continue
                item = {'key':'i:'+str(row['id']), 'media_id':None, 'name':raw['name'], 'status':raw['status'],
                        'source_path':row['path'] if raw['role']=='download' else None,
                        'target_path':row['path'] if raw['role']=='library' else None,
                        'identity':annotations.get(row['path']), 'subtitles':[{'status':'discovered','language':None,'format':Path(p).suffix.lstrip('.')} for p in raw.get('subtitles',[])]}
                files.append(item)
        classifications={row['path']:dict(row) for row in self.db.execute('SELECT path,category,fingerprint FROM media_library_classification').mappings()}
        for file in files:
            file['guess'] = guess(file)
            file['classification']=classify(file)
            for role in ('source','target'):
                override=classifications.get(file.get(role+'_path'))
                if override:
                    try:valid=json.loads(override['fingerprint'])==file_state(file.get(role+'_path'),role)
                    except ValueError:valid=False
                    if valid:
                        file['classification']={'category':override['category'],'reason':'user_classified',
                            'owner':file['classification'].get('owner') if override['category']=='extra' else None}
                        break
            annotation = file.get('identity')
            if file.get('media_tmdb_id') and file.get('media_type') in ('movie','tv','tv_extra'):
                kind = 'tv' if file['media_type']=='tv_extra' else file['media_type']
                file['title_id'] = f"{kind}:{file['media_tmdb_id']}"
            elif annotation:
                file['title_id'] = annotation['identity']['title_id']
                file.update(media_type=annotation['identity']['kind'], media_tmdb_id=annotation['identity']['tmdb_id'],
                            season=annotation.get('season'), episode=annotation.get('episode'))
            else:
                file['title_id'] = None
        return files

    def groups(self):
        groups = {}
        files=self.files();scopes=defaultdict(set)
        for file in files:
            if file['title_id']:
                scopes[(file['guess']['kind'],file['guess']['scope'])].add(file['title_id'])
        for file in files:
            identities=scopes[(file['guess']['kind'],file['guess']['scope'])]
            known=file['title_id'] or (next(iter(identities)) if len(identities)==1 else None)
            key = known or ('pending:extra:'+file['classification']['owner'] if file['classification']['category']=='extra' and file['classification'].get('owner') else 'pending:'+file['guess']['kind']+':'+file['guess']['scope'])
            ident = digest(key)[:32]
            group = groups.setdefault(ident, {'collection_id':ident, 'title_id':known, 'files':[]})
            group['files'].append(file)
        # Group extras inside an explicit bonus folder, or attach to a unique parent work.
        for ident,group in list(groups.items()):
            if ident not in groups or group['title_id'] or not all(f['classification']['category']=='extra' for f in group['files']):
                continue
            owner=group['files'][0]['classification'].get('owner')
            if not owner:continue
            parents=[(gid,g) for gid,g in groups.items() if gid!=ident and any(
                f['classification']['category']=='main' and any(p and Path(owner) in Path(p).parents for p in (f.get('source_path'),f.get('target_path')))
                for f in g['files'])]
            if len(parents)==1:
                destination=parents[0][1]
            else:
                gid=digest('extras:'+owner)[:32]
                destination=groups.setdefault(gid,{'collection_id':gid,'title_id':None,'files':[],'extra_title':Path(owner).name})
            destination['files'].extend(group['files']);del groups[ident]
        return groups

    def _title(self, group):
        if self._title_cache is None:
            self._title_cache={}
            for row in self.db.execute("SELECT json_extract(data,'$.identity') AS identity FROM media_mcp_record WHERE kind='acquisition'").mappings():
                identity=json.loads(row['identity']) if row['identity'] else None
                if isinstance(identity,dict) and identity.get('title_id'):
                    self._title_cache[identity['title_id']]={'identity':identity}
            for row in self.db.execute("SELECT data FROM media_mcp_record WHERE kind='library_title'").mappings():
                meta=json.loads(row['data']);self._title_cache[meta['identity']['title_id']]=meta
        meta=self._title_cache.get(group['title_id'],{})
        first = next((f for f in group['files'] if f['title_id']),next((f for f in group['files'] if f['classification']['category']=='main'),group['files'][0]))
        identity = meta.get('identity') or (first.get('identity') or {}).get('identity') or {}
        return {'title':identity.get('title') or (first.get('media_name') if group['title_id'] else None) or group.get('extra_title') or first['guess']['title'],
                'kind':identity.get('kind') or ('tv' if first.get('media_type')=='tv_extra' else first.get('media_type')) or first['guess']['kind'],
                'year':(identity.get('date') or '')[:4] or first.get('year') or first['guess']['year_hint'],
                'poster_url':identity.get('poster_url'), 'overview':meta.get('overview',''),
                'identified':all(f['title_id'] for f in group['files'] if f['classification']['category']=='main') and any(f['classification']['category']=='main' for f in group['files'])}

    @staticmethod
    def summary(files):
        ready=READY_SUBTITLE_STATUSES
        main=[f for f in files if f['classification']['category']=='main']
        main_verified=sum(any(s['status'] in ready for s in f['subtitles']) for f in main)
        main_discovered=sum(any(s['status']=='discovered' for s in f['subtitles']) and not any(s['status'] in ready for s in f['subtitles']) for f in main)
        verified = sum(any(s['status'] in ready for s in f['subtitles']) for f in files)
        discovered = sum(any(s['status']=='discovered' for s in f['subtitles']) and not any(s['status'] in ready for s in f['subtitles']) for f in files)
        return {'files':len(files), 'extras':sum(f['classification']['category']=='extra' for f in files), 'mapped':sum(f['status']=='linked' for f in files),
                'main_files':len(main),'main_mapped':sum(f['status']=='linked' for f in main),
                'main_subtitle_verified':main_verified,'main_subtitle_discovered':main_discovered,
                'main_subtitle_missing':len(main)-main_verified-main_discovered,
                'identity_pending':sum(not f['title_id'] for f in main),
                'subtitle_verified':verified, 'subtitle_discovered':discovered,
                'subtitle_missing':len(files)-verified-discovered,
                'seasons':len({f.get('season') for f in main if f.get('season') is not None}),
                'episodes':len({(f.get('season'),f.get('episode')) for f in main if f.get('episode') is not None})}

    def list(self, after='', limit=24, query='',kind='all'):
        items = [{**{k:v for k,v in group.items() if k!='files'}, **self._title(group),
                  'summary':self.summary(group['files'])} for group in self.groups().values()]
        items = sorted((g for g in items if query.casefold() in g['title'].casefold() and
                        (kind=='extra' and g['summary']['extras']>0 or g['summary']['files']>g['summary']['extras'] and
                         (kind=='all' or kind=='pending' and not g['identified'] or kind in ('movie','tv') and g['kind']==kind))), key=lambda g:(g['title'].casefold(),g['collection_id']))
        start = 0
        if after:
            positions = [i for i,g in enumerate(items) if g['collection_id']==after]
            if not positions:
                raise ValueError('collection_cursor_changed')
            start = positions[0]+1
        page = items[start:start+limit]
        tasks=[]
        if self.actor.can_manage_media:
            tasks=[task_public(self.records.decode(row)) for row in self.db.execute("""SELECT * FROM media_mcp_record
                WHERE kind='library_task' AND state!='deleted' AND json_extract(data,'$.owner')=:owner AND json_extract(data,'$.action') IN ('analysis','auto')
                AND (json_extract(data,'$.action')!='auto' OR json_extract(data,'$.total')>0)
                ORDER BY updated_at DESC,rowid DESC LIMIT 10""",{'owner':self.actor.id}).mappings()]
        return {'collections':page, 'total':len(items), 'can_manage':self.actor.can_manage_media, 'analysis_tasks':tasks,
                'next_cursor':page[-1]['collection_id'] if start+limit<len(items) and page else None}

    def group(self, collection_id):
        groups=self.groups();group=groups.get(collection_id)
        visited=set()
        while not group and collection_id not in visited and len(visited)<8:
            visited.add(collection_id)
            alias=self.records.by_key(digest(['library-alias',self.actor.id,collection_id]))
            if not alias:break
            collection_id=alias['data']['target'];group=groups.get(collection_id)
        if not group:
            raise ValueError('collection_not_found')
        return group

    def _public_file(self, file):
        result = {key:file.get(key) for key in ('key','media_id','name','season','episode','status','subtitles')}
        result.update(season_hint=file['guess']['season_hint'],episode_hint=file['guess']['episode_hint'],classification=file['classification'])
        result['classification']={k:v for k,v in file['classification'].items() if k!='owner'}
        result['identified']=bool(file['title_id'])
        if self.actor.can_manage_media:
            result.update(source_path=file.get('source_path'),target_path=file.get('target_path'))
            try:
                state=mapping_state(file)
                result['mapping'] = 'source_changed' if video_changed(file,state) else state['status']
            except ValueError:
                result['mapping'] = 'unsafe_path'
        else:
            result['mapping'] = file['status']
        return result

    def detail(self, collection_id):
        group = self.group(collection_id)
        collection_id=group['collection_id']
        files = group['files']
        seasons = defaultdict(list)
        for file in files:
            season = file.get('season') if file['title_id'] else file['guess']['season_hint']
            seasons[season].append(self._public_file(file))
        for values in seasons.values():
            values.sort(key=lambda f:((f.get('episode') if f.get('episode') is not None else f.get('episode_hint')) or 0,f['name']))
        buckets=[]
        kind=self._title(group)['kind']
        for season,values in sorted(seasons.items(),key=lambda pair:pair[0] if pair[0] is not None else -1):
            episodes={}
            for file in values:
                number=file.get('episode') if file['identified'] else file.get('episode_hint')
                key=str(number) if number is not None else 'movie' if kind=='movie' else file['key']
                episodes.setdefault(key,{'episode':number,'versions':[]})['versions'].append(file)
            buckets.append({'season':season,'provisional':any(not f['identified'] for f in values),'files':values,'episodes':list(episodes.values())})
        tasks=[task_public(self.records.decode(row)) for row in self.db.execute("""SELECT * FROM media_mcp_record
            WHERE kind='library_task' AND state!='deleted' AND json_extract(data,'$.owner')=:owner AND (json_extract(data,'$.collection_id')=:collection OR json_extract(data,'$.result_collection_id')=:collection)
            ORDER BY updated_at DESC,rowid DESC LIMIT 5""",{'owner':self.actor.id,'collection':collection_id}).mappings()]
        return {'collection_id':collection_id, 'title_id':group['title_id'], **self._title(group),
                'summary':self.summary(files), 'can_manage':self.actor.can_manage_media,
                'seasons':buckets,'tasks':tasks}

    def selection(self, collection_id, selection=None, season=None):
        group = self.group(collection_id)
        files = group['files']
        if season is not None:
            files = [f for f in files if (f.get('season') if f['title_id'] else f['guess']['season_hint'])==season]
        if selection is not None:
            selected = set(selection)
            files = [f for f in files if f['key'] in selected]
            if {f['key'] for f in files} != selected:
                raise ValueError('collection_selection_changed')
        if not files or len(files)>MAX_FILES:
            raise ValueError('collection_select_smaller_scope')
        return group,files

    @staticmethod
    def freeze(file):
        return {'key':file['key'], 'media_id':file.get('media_id'), 'source_path':file.get('source_path'),
                'target_path':file.get('target_path'), 'title_id':file.get('title_id'), 'season':file.get('season'),
                'episode':file.get('episode'), 'metadata':{key:file.get(key) for key in ('media_type','media_tmdb_id','media_name','year','identity','agent_result_json','status','reason','fail_stage','classification')}, 'state':mapping_state(file)}

    def validate(self, frozen):
        current = {f['key']:f for f in self.files()}
        for expected in frozen:
            file = current.get(expected['key'])
            if not file or self.freeze(file) != expected:
                raise ValueError('collection_changed_rebuild_plan')

    def active_overlap(self,files,excluded=()):
        paths={f.get(key) for f in files for key in ('source_path','target_path') if f.get(key)}
        for row in self.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_task' AND state IN ('queued','running')").mappings():
            row=self.records.decode(row)
            if row['id'] in excluded:continue
            other={f.get(key) for f in row['data']['files'] for key in ('source_path','target_path') if f.get(key)}
            if paths&other:
                return row
        return None

    def identity_context(self, collection_id, selection=None, season=None):
        self.manage()
        _, files = self.selection(collection_id,selection,season)
        files=[f for f in files if f['classification']['category']=='main']
        if not files:raise ValueError('collection_no_main_files')
        snapshot = [self.freeze(f) for f in files]
        row = self.records.put('library_context', {'owner':self.actor.id,'collection_id':collection_id,
            'files':snapshot,'expires_at':time.time()+900})
        return {'context_id':row['id'], 'user_id':self.actor.id,
                'files':[{'key':f['key'],'name':f['name'], 'season':f.get('season') if f['title_id'] else f['guess']['season_hint'],
                          'episode':f.get('episode') if f['title_id'] else f['guess']['episode_hint']} for f in files]}

    def classify(self, collection_id, category, selection=None, season=None):
        self.manage()
        if category not in ('main','extra'):raise ValueError('invalid_classification')
        with media_mutation_lock(self.db):
            _,files=self.selection(collection_id,selection,season)
            if self.active_overlap(files):raise ValueError('collection_operation_busy')
            with self.db.begin() as conn:
                for file in files:
                    assert_mutation_lock()
                    role='source' if file.get('source_path') else 'target';path=file[role+'_path']
                    conn.execute(text('''INSERT INTO media_library_classification(path,category,fingerprint) VALUES(:path,:category,:fingerprint)
                        ON CONFLICT(path) DO UPDATE SET category=excluded.category,fingerprint=excluded.fingerprint,updated_at=CURRENT_TIMESTAMP'''),
                        {'path':path,'category':category,'fingerprint':json.dumps(file_state(path,role))})
        self.service.accounts.event(self.actor,'collection_classified','collection',collection_id)
        return {'updated_files':len(files),'category':category}

    def owned(self, ident, kind):
        row = self.records.get(ident,kind)
        if row['data']['owner'] != self.actor.id:
            raise ValueError('permission_denied')
        return row

    def identity_preview(self, context_id, snapshot):
        self.manage()
        context = self.owned(context_id,'library_context')
        require_fresh(context['data']);require_fresh(snapshot)
        self.validate(context['data']['files'])
        identity = snapshot['identity']
        if identity['title_id'] != f"{identity['kind']}:{identity['tmdb_id']}":
            raise ValueError('inconsistent_identity')
        if {a['key'] for a in snapshot['assignments']} != {f['key'] for f in context['data']['files']}:
            raise ValueError('collection_selection_changed')
        if len(snapshot['assignments'])!=len(context['data']['files']):
            raise ValueError('collection_selection_changed')
        expected = {(s['season'],e) for s in snapshot['seasons'] for e in s['episodes']}
        for item in snapshot['assignments']:
            if identity['kind']=='tv' and (item.get('season'),item.get('episode')) not in expected:
                raise ValueError('collection_episode_requires_review')
            if identity['kind']=='movie' and (item.get('season') is not None or item.get('episode') is not None):
                raise ValueError('movie_has_no_episodes')
        row = self.records.put('library_identity', {**context['data'], 'snapshot':snapshot}, 'preview')
        return {'plan_id':row['id'], 'identity':identity, 'assignments':snapshot['assignments'],
                'total':len(context['data']['files']), 'expires_at':context['data']['expires_at']}

    def write_identity(self,conn,file,identity,item,confirmation='user'):
        annotation={'identity':identity,'season':item.get('season'),'episode':item.get('episode'),
                    'video_fingerprint':file['state']['source'] or file['state']['target'],'approval_mode':confirmation}
        if item.get('runtime_seconds'):annotation['runtime_seconds']=item['runtime_seconds']
        path=file['source_path'] or file['target_path']
        conn.execute(text('''INSERT INTO media_library_identity(path,data) VALUES(:path,:data)
            ON CONFLICT(path) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP'''),
            {'path':path,'data':json.dumps(annotation,ensure_ascii=False)})
        if file['media_id']:
            payload=_json_object(file['metadata'].get('agent_result_json'))
            if file['state']['source']:
                payload['_source_fingerprint']=file['state']['source']
            payload['library_identity']={'confirmed_by_user':confirmation=='user','approval_mode':confirmation,'title_id':identity['title_id'],
                                         'video_fingerprint':annotation['video_fingerprint']}
            conn.execute(text('''UPDATE media_link SET media_type=:kind,media_tmdb_id=:tmdb_id,
                season_tmdb_id=NULL,episode_tmdb_id=NULL,extra_type=NULL,extra_index=NULL,confidence=NULL,
                media_name=:title,base_title=:title,alt_name=:original_title,
                original_language=:original_language,year=:year,season=:season,episode=:episode,
                agent_result_json=:payload,updated_at=CURRENT_TIMESTAMP WHERE id=:id'''),
                {**identity,'year':int(identity['date'][:4]) if identity.get('date') else None,
                 'season':item.get('season'),'episode':item.get('episode'),'id':file['media_id'],
                 'payload':json.dumps(payload,ensure_ascii=False)})

    def identity_apply(self, plan_id):
        self.manage()
        with media_mutation_lock(self.db):
            row = self.owned(plan_id,'library_identity');data=row['data']
            if row['state']=='applied':
                return data['receipt']
            require_fresh(data);require_fresh(data['snapshot']);self.validate(data['files'])
            if self.active_overlap(data['files']):
                raise ValueError('collection_operation_busy')
            identity=data['snapshot']['identity'];assigned={f['key']:f for f in data['snapshot']['assignments']}
            with self.db.begin() as conn:
                for file in data['files']:
                    item=assigned[file['key']]
                    self.write_identity(conn,file,identity,item)
                key=digest('library-title:'+identity['title_id'])
                conn.execute(text('''INSERT INTO media_mcp_record(id,kind,data,state,key_hash,created_at,updated_at)
                    VALUES(:id,'library_title',:data,'confirmed',:key,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                    ON CONFLICT(key_hash) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP,revision=revision+1'''),
                    {'id':uuid.uuid4().hex,'data':json.dumps(data['snapshot'],ensure_ascii=False),'key':key})
                receipt={'collection_id':digest(identity['title_id'])[:32],'updated_files':len(data['files'])}
                data['receipt']=receipt
                assert_mutation_lock()
                conn.execute(text("UPDATE media_mcp_record SET state='applied',data=:data,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
                             {'id':plan_id,'data':json.dumps(data,ensure_ascii=False)})
            return receipt

    def mapping_preview(self, collection_id, selection=None, season=None):
        self.manage()
        _,files=self.selection(collection_id,selection,season)
        frozen=[self.freeze(f) for f in files]
        operations=[]
        for file,state in zip(files,frozen):
            target=file.get('target_path')
            if state['state']['status']=='unorganized' and file['title_id']:
                from media_mcp.ingest.domain.path_builder import build_hardlink_path
                title=(file.get('identity') or {}).get('identity')
                if not title:
                    meta=self.records.by_key(digest('library-title:'+file['title_id']))
                    title=meta['data']['identity'] if meta else None
                if title:
                    target=build_hardlink_path({'kind':title['kind'],'title':{'zh':title['title'],'original':title.get('original_title')},
                        'year':int(title['date'][:4]) if title.get('date') else 0,'season':file.get('season'),
                        'episode':file.get('episode')},Path(file['source_path']).suffix, str(library_root()))
            status=state['state']['status']
            action='keep' if status in ('linked','source_missing','library_only') else 'review'
            reason=None
            if file['classification']['category']=='extra':
                action='review';reason='extra_requires_review'
            elif file.get('media_id') and file.get('status')=='unlinked':
                action='review';reason='version_selection_required'
            elif video_changed(file,state['state']):
                action='review';reason='source_identity_changed'
            elif status=='linked' and file.get('media_id') and file.get('status')!='linked':
                action='refresh_record'
            elif status in ('target_missing','unorganized'):
                if not file['title_id']:
                    reason='identity_required'
                elif not target:
                    reason='canonical_target_unavailable'
                else:
                    contained(target,library_root(),exists=False)
                    if os.path.lexists(target):
                        reason='target_already_exists'
                    else:
                        owner=self.db.execute('SELECT id FROM media_link WHERE target_path=:path AND id!=:id',{'path':target,'id':file.get('media_id') or -1}).first()
                        if owner:
                            reason='target_owned_by_other_media'
                        else:
                            action='create_link'
            operations.append({'key':file['key'],'name':file['name'],'action':action,'reason':reason,
                               'source_path':file.get('source_path'),'target_path':target})
        row=self.records.put('library_mapping',{'owner':self.actor.id,'collection_id':collection_id,
            'files':frozen,'operations':operations,'expires_at':time.time()+900},'preview')
        return {'plan_id':row['id'],'operations':operations,'total':len(operations)}



    def _queue(self, action, collection_id, files, operations, idempotency_key, blocked=None, plan_id=None, request=None,label=None,analysis_roots=None):
        self.manage()
        from media_mcp.runtime.state import MediaJobs
        jobs=MediaJobs();jobs.initialize()
        request_key=digest(['library',self.actor.id,idempotency_key])
        intent={'action':action,'collection_id':collection_id,'keys':[f['key'] for f in files], 'operations':operations,'request':request}
        with media_mutation_lock(self.db):
            previous=self.records.by_key(request_key)
            if previous:
                if previous['data']['intent'] != intent:
                    raise ValueError('idempotency_key_reused_with_different_request')
                return task_public(previous)
            self.validate(files)
            effect=digest([action,files,operations,request,analysis_roots]) if action=='analysis' else digest([action,files,operations])
            running=self.active_overlap(files)
            if running:
                if running['data']['owner'] != self.actor.id or running['data']['effect']!=effect:
                    raise ValueError('collection_operation_busy')
                return task_public(running)
            from media_mcp.platform.limits import Budget
            Budget(self.db,self.service.accounts.clock).admit_job(self.actor.id)
            ident=uuid.uuid4().hex
            data={'owner':self.actor.id,'action':action,'label':label,'collection_id':collection_id,'files':files,
                  'operations':operations,'results':[],'blocked':blocked or [],'intent':intent,'effect':effect,
                  'processing_key':digest('library:'+ident),'plan_id':plan_id,'analysis_roots':analysis_roots}
            with self.db.begin() as conn:
                conn.execute(text('''INSERT INTO media_mcp_record(id,kind,data,state,key_hash,created_at,updated_at)
                    VALUES(:id,'library_task',:data,'queued',:key,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'''),
                    {'id':ident,'data':json.dumps(data,ensure_ascii=False),'key':request_key})
                conn.execute(text('''INSERT INTO media_processing_job(delivery_key,stage,path,state,next_attempt_at,created_at,updated_at)
                    VALUES(:key,'library',:path,'queued',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'''),
                    {'key':data['processing_key'],'path':collection_id})
            self.service.accounts.event(self.actor,'collection_'+action+'_requested','collection',collection_id)
            return self.task(ident)


    def queue_mapping(self, plan_id, idempotency_key):
        self.manage()
        plan=self.owned(plan_id,'library_mapping')
        previous=self.records.by_key(digest(['library',self.actor.id,idempotency_key]))
        if previous:
            if previous['data'].get('plan_id') != plan_id:
                raise ValueError('idempotency_key_reused_with_different_request')
            return task_public(previous)
        require_fresh(plan['data'])
        operations=[op for op in plan['data']['operations'] if op['action'] in ('create_link','refresh_record')]
        selected={op['key'] for op in operations}
        if not selected:
            raise ValueError('collection_no_safe_repairs')
        files=[f for f in plan['data']['files'] if f['key'] in selected]
        return self._queue('mapping',plan['data']['collection_id'],files,operations,idempotency_key,plan_id=plan_id)



    def queue_subtitles(self, collection_id, idempotency_key, selection=None, season=None, mode='missing'):
        self.manage()
        request={'selection':sorted(selection) if selection is not None else None,'season':season,'mode':mode}
        previous=self.records.by_key(digest(['library',self.actor.id,idempotency_key]))
        if previous:
            if previous['data']['action']!='subtitles' or previous['data']['collection_id']!=collection_id or previous['data']['intent'].get('request')!=request:
                raise ValueError('idempotency_key_reused_with_different_request')
            return task_public(previous)
        _,files=self.selection(collection_id,selection,season)
        eligible=[];blocked=[]
        for file in files:
            if file['classification']['category']=='extra':
                blocked.append({'key':file['key'],'reason':'extra_requires_review'});continue
            state=mapping_state(file)
            if video_changed(file,state):
                blocked.append({'key':file['key'],'reason':'identify_again'});continue
            ready=False
            for path in file.get('_ready_subtitle_paths',[]):
                try:
                    ready=ready or bool(contained(path,library_root(),exists=False).is_file())
                except ValueError:
                    pass
            if mode=='missing' and ready:
                continue
            status=state['status']
            if not file.get('media_id') or not file['title_id'] or status not in ('linked','source_missing'):
                blocked.append({'key':file['key'],'reason':'identify_and_repair_first'});continue
            raw=self.db.execute('SELECT media_type,media_tmdb_id,status FROM media_link WHERE id=:id',{'id':file['media_id']}).mappings().one()
            if not raw['media_tmdb_id'] or f"{raw['media_type']}:{raw['media_tmdb_id']}" != file['title_id']:
                blocked.append({'key':file['key'],'reason':'identify_again'});continue
            if raw['status'] not in ('linked','source_missing','target_missing'):
                blocked.append({'key':file['key'],'reason':'check_mapping_first'});continue
            if status=='source_missing' and self.db.execute('SELECT COUNT(*) FROM media_link WHERE target_path=:path',{'path':file['target_path']}).scalar()!=1:
                blocked.append({'key':file['key'],'reason':'ambiguous_mapping'});continue
            eligible.append(self.freeze(file))
        if not eligible:
            raise ValueError('collection_no_eligible_subtitles')
        return self._queue('subtitles',collection_id,eligible,[],idempotency_key,blocked,request=request)


    def task(self, job_id):
        self.manage()
        return task_public(self.owned(job_id,'library_task'))


def prepare_identity(provider, context, title_id, season_override=None, assignments=None):
    """Runs where the TMDB provider lives: cloud, or an isolated single-host preview."""
    identity=provider.detail(title_id)
    if identity['title_id']!=title_id:
        raise ValueError('provider_identity_mismatch')
    kind=identity['kind'];seasons=[]
    supplied={item['key']:item for item in (assignments or [])}
    if len(supplied)!=len(assignments or []) or set(supplied)-{file['key'] for file in context['files']}:
        raise ValueError('collection_selection_changed')
    result=[]
    for file in context['files']:
        chosen=supplied.get(file['key'],{})
        season=chosen.get('season',season_override if season_override is not None else file.get('season'))
        episode=chosen.get('episode',file.get('episode'))
        result.append({'key':file['key'],'season':season if kind=='tv' else None,'episode':episode if kind=='tv' else None})
    row=provider.get(title_id.replace(':','/'))
    if kind=='tv':
        allowed={s['season_number'] for s in row.get('seasons',[]) if type(s.get('season_number')) is int}
        selected={a['season'] for a in result}
        if None in selected or not selected<=allowed or len(selected)>30:
            raise ValueError('collection_season_requires_review')
        for season in sorted(selected):
            season_data=provider.get(f"tv/{identity['tmdb_id']}/season/{season}")
            seasons.append({'season':season,'episodes':[e['episode_number'] for e in season_data.get('episodes',[]) if type(e.get('episode_number')) is int]})
    return {'identity':identity,'overview':str(row.get('overview') or '')[:5000],
            'assignments':result,'seasons':seasons,'expires_at':time.time()+900}


def task_public(row):
    data=row['data']
    results=data.get('results',[])
    visible=[item for item in results if item['state']!='completed'][:50] if data.get('automatic') else results
    return {'job_id':row['id'],'state':row['state'],'action':data['action'],'automatic':data.get('automatic',False),'result_collection_id':data.get('result_collection_id'),'summary':data.get('summary',{}),
            'collection_id':data['collection_id'],'label':data.get('label'),'analysis_plan_id':data.get('analysis_plan_id'),'analysis_progress':data.get('analysis_progress'),'analysis_applied':data.get('analysis_applied',0),'total':data.get('total',len(data['files'])),
            'completed':len(results), 'succeeded':sum(item['state']=='completed' for item in results),
            'results':visible,'review_count':sum(item['state']!='completed' for item in results),
            'quota_wait':data.get('quota_wait'), 'session_recovery':data.get('session_recovery'), 'error_code':data.get('error_code'), 'model_failure':data.get('model_failure'), 'model_retry_count':data.get('model_retry_count',0), 'blocked':data.get('blocked',[])}
