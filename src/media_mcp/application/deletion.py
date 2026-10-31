"""Explicit, frozen deletion plans. Torrent removal never delegates payload deletion."""
import json
import os
import time
from contextlib import ExitStack
from pathlib import Path

from sqlalchemy import text

from media_mcp.adapters.download import Downloader
from media_mcp.application.collections import Collections,file_state,library_root
from media_mcp.config import contained,download_root
from media_mcp.ingest.domain.file_utils import is_video_file
from media_mcp.runtime.state import media_mutation_lock,assert_mutation_lock
from media_mcp.storage.records import require_fresh


class Deletions:
    def __init__(self,service,downloader=None):
        self.service=service;self.records=service.records;self.db=self.records.db
        self.downloader=downloader or Downloader()

    @staticmethod
    def _task_identity(row):
        return {k:row['data'].get(k) for k in ('_platform_owner','identity','infohash',
                'source_path','delivery_hash','workflow','submission_attempted')}

    def _torrent(self,row):
        data=row['data'];hash_value=data.get('infohash')
        torrent=self.downloader.find(hash_value) if hash_value else None
        if torrent:
            expected=os.environ.get('MEDIA_TORRENT_CATEGORY','media-mcp')
            if (torrent['hash']!=hash_value or torrent['category']!=expected or
                'media-mcp-'+row['id'] not in {t.strip() for t in torrent['tags'].split(',')}):
                raise ValueError('torrent_owner_mismatch')
            contained(torrent['save_path']+'/placeholder',download_root(),exists=False)
            if torrent.get('content_path'):contained(torrent['content_path'],exists=False)
            return {k:torrent.get(k) for k in ('hash','category','tags','save_path','content_path','added_on')}
        if row['state'] in ('submitting','submission_unknown'):
            raise ValueError('download_submission_outcome_unknown')
        return None

    @staticmethod
    def _library_task_identity(row):
        return {k:row['data'].get(k) for k in ('owner','action','files','processing_key','collection_id','request')}

    def _classification(self,file):
        return [dict(row) for row in self.db.execute(
            'SELECT path,category,fingerprint FROM media_library_classification WHERE path IN (:source,:target) ORDER BY path',
            {'source':file.get('source_path'),'target':file.get('target_path')}).mappings()]

    @staticmethod
    def _object_keys(objects,files_only=False):
        return {o['snapshot']['key'] if o['kind'] in ('media','inventory') else o['id']
                for o in objects if not files_only or o['kind'] in ('media','inventory')}

    def _existing(self,action,ids):
        for raw in self.db.execute("SELECT * FROM media_mcp_record WHERE kind='deletion_plan' AND state='executing'").mappings():
            row=self.records.decode(raw);data=row['data'];previous=self._object_keys(data['objects'],files_only=action=='collection')
            if previous & ids:
                if data['owner']==self.service.actor.id and action==data['action'] and previous==ids:return self.public(row)
                raise ValueError('deletion_resume_existing_plan')
        return None

    def _put(self,kind,objects,files=None,directories=None,retained=None,title=None):
        keys=self._object_keys(objects)
        for row in self.db.execute("SELECT data FROM media_mcp_record WHERE kind='deletion_plan' AND state='executing'").mappings():
            previous=json.loads(row['data'])
            if keys & self._object_keys(previous['objects']):
                raise ValueError('deletion_resume_existing_plan')
        data={'owner':self.service.actor.id,'action':kind,'objects':objects,'files':files or [],
              'directories':directories or [],'retained_directories':retained or [],
              'title':title,'expires_at':time.time()+900}
        row=self.records.put('deletion_plan',data,'preview')
        return self.public(row)

    @staticmethod
    def public(row):
        data=row['data']
        return {'plan_id':row['id'],'state':row['state'],'action':data['action'],
                'title':data.get('title'),'files':[f['path'] for f in data['files']],
                'directories':data['directories'],'retained_directories':sorted(set(data['retained_directories'])|set((data.get('receipt') or {}).get('retained_directories',[]))),
                'torrent_count':sum(bool(o.get('torrent')) for o in data['objects']),
                'task_count':sum(o['kind'] not in ('media','inventory') for o in data['objects']),
                'task_ids':[o['id'] for o in data['objects'] if o['kind'] not in ('media','inventory')],
                'file_count':len(data['files']),'receipt':data.get('receipt')}

    def download_preview(self,job_id):
        self.service._download_permission()
        with self.db.lock('acquire:'+job_id),media_mutation_lock(self.db,timeout=5):
            row=self.service._task(job_id,manage=True)
            if row['state']=='deleted':raise ValueError('task_already_deleted')
            existing=self._existing('download',{job_id})
            if existing:return existing
            torrent=self._torrent(row)
            return self._put('download',[{'kind':'acquisition','id':row['id'],'revision':row['revision'],
                'torrent':torrent,'task_identity':self._task_identity(row),'processing_key':row['data'].get('delivery_hash')}],title=(row['data'].get('identity') or {}).get('title'))

    def task_preview(self,job_id):
        lib=Collections(self.service);lib.manage()
        with media_mutation_lock(self.db,timeout=5):
            row=lib.owned(job_id,'library_task')
            if row['state']=='deleted':raise ValueError('task_already_deleted')
            existing=self._existing('task',{job_id})
            if existing:return existing
            return self._put('task',[{'kind':'library_task','id':job_id,'revision':row['revision'],
                                      'processing_key':row['data'].get('processing_key'),'task_identity':self._library_task_identity(row)}],title=row['data'].get('label'))

    def collection_preview(self,collection_id,selection=None,season=None):
        lib=Collections(self.service);lib.manage()
        with media_mutation_lock(self.db,timeout=5):
            roots=(download_root(),library_root())
            if any(not root.is_dir() for root in roots) or roots[0].stat().st_dev!=roots[1].stat().st_dev:
                raise ValueError('deletion_media_roots_unavailable')
            if roots[0].is_relative_to(roots[1]) or roots[1].is_relative_to(roots[0]):
                raise ValueError('deletion_media_roots_overlap')
            group,selected=lib.selection(collection_id,selection,season)
            all_files=lib.files();selected_keys={f['key'] for f in selected}
            existing=self._existing('collection',selected_keys)
            if existing:return existing
            originals={f['source_path'] for f in selected if f.get('source_path')};targets={f['target_path'] for f in selected if f.get('target_path')}
            protected={p for f in all_files if f['key'] not in selected_keys for p in (f.get('source_path'),f.get('target_path')) if p}
            for sub in self.db.execute('SELECT * FROM media_subtitle').mappings():
                if sub['matched_video_target_path'] not in targets and sub['matched_video_source_path'] not in originals:
                    protected.update((sub['source_subtitle_path'],sub['target_subtitle_path']))
            paths={};directories=set();retained=[]
            def add(path,role):
                if not path or path in protected:return
                fingerprint=file_state(path,role)
                if fingerprint:paths[path]={'path':path,'role':role,'fingerprint':fingerprint}
                if len(paths)>2000:raise ValueError('deletion_manifest_too_large')
            for f in selected:
                source=file_state(f['source_path'],'source');target=file_state(f['target_path'],'target')
                if not source and not target:raise ValueError('deletion_media_missing')
                if source and target and source[:2]!=target[:2]:raise ValueError('deletion_mapping_conflict')
                for role in ('source','target'):add(f[role+'_path'],role)
            for sub in self.db.execute('SELECT * FROM media_subtitle').mappings():
                if sub['matched_video_target_path'] in targets or sub['matched_video_source_path'] in originals:
                    for key,role in [('source_subtitle_path','source'),('target_subtitle_path','target')]:
                        path=sub[key]
                        if path and not path.startswith(('provider://','embedded://')):
                            try:add(path,role)
                            except ValueError:
                                # Existing extracted sources may live beside the library video.
                                add(path,'target')
            for file in selected:
                if file['key'].startswith('i:'):
                    raw=self.db.execute('SELECT data FROM media_inventory WHERE id=:id',{'id':int(file['key'].split(':')[1])}).scalar()
                    for path in json.loads(raw).get('subtitles',[]):
                        add(path,'source' if file.get('source_path') else 'target')
            candidates=set()
            for f in selected:
                for role,root in [('source',download_root()),('target',library_root())]:
                    if not f.get(role+'_path'):continue
                    path=contained(f[role+'_path'],root,exists=False)
                    parts=path.relative_to(root).parts
                    if role=='target' and path.parent in (root/'movie',root/'series'):continue
                    parent=root/parts[0] if role=='source' else (root.joinpath(*parts[:2]) if len(parts)>2 else path.parent)
                    if parent!=root and parent.is_dir():candidates.add((str(parent),role))
            for raw,role in sorted(candidates):
                parent=Path(raw)
                others=[f for f in all_files if f['key'] not in selected_keys and
                        any(p and Path(p).is_relative_to(parent) for p in (f.get('source_path'),f.get('target_path')))]
                children=[]
                for child in parent.rglob('*'):
                    children.append(child)
                    if len(children)>2000:raise ValueError('deletion_manifest_too_large')
                for child in children:contained(str(child),download_root() if role=='source' else library_root())
                known=originals if role=='source' else targets
                unknown_video=any(c.is_file() and is_video_file(str(c)) and str(c) not in known for c in children)
                if others or unknown_video or any(p and Path(p).is_relative_to(parent) for p in protected):
                    retained.append(raw);continue
                directories.add(raw)
                for child in children:
                    if child.is_file():add(str(child),role)
                    elif child.is_dir():directories.add(str(child))
                    else:raise ValueError('deletion_non_regular_file')
            objects=[{'kind':'media' if f.get('media_id') else 'inventory','id':f.get('media_id') or int(f['key'].split(':')[1]),'snapshot':lib.freeze(f),'classification':self._classification(f)} for f in selected]
            for raw in self.db.execute("SELECT * FROM media_mcp_record WHERE kind='acquisition' AND state!='deleted'").mappings():
                row=self.records.decode(raw);source=row['data'].get('source_path')
                if source and (source in originals or any(Path(p).is_relative_to(Path(source)) for p in originals)):
                    # Never delete a bundle task that also owns retained media.
                    if any(f.get('source_path') and Path(f['source_path']).is_relative_to(Path(source))
                           and f['key'] not in selected_keys for f in all_files):
                        raise ValueError('deletion_download_shared_with_other_media')
                    self.service._task(row['id'],manage=True)
                    objects.append({'kind':'acquisition','id':row['id'],'revision':row['revision'],
                                    'torrent':self._torrent(row),'task_identity':self._task_identity(row),'processing_key':row['data'].get('delivery_hash')})
            return self._put('collection',objects,list(paths.values()),sorted(directories),retained,lib._title(group)['title'])

    def _validate_objects(self,data):
        lib=Collections(self.service)
        current={f['key']:f for f in lib.files()} if data['action']=='collection' else {}
        selected_keys={o['snapshot']['key'] for o in data['objects'] if o['kind'] in ('media','inventory')}
        originals={o['snapshot']['source_path'] for o in data['objects'] if o['kind'] in ('media','inventory') and o['snapshot'].get('source_path')}
        paths={f['path'] for f in data['files']};targets={o['snapshot']['target_path'] for o in data['objects'] if o['kind'] in ('media','inventory') and o['snapshot'].get('target_path')}
        if any(f['key'] not in selected_keys and paths & {f.get('source_path'),f.get('target_path')} for f in current.values()):
            raise ValueError('deletion_path_shared')
        if data['action']=='collection':
            for sub in self.db.execute('SELECT * FROM media_subtitle').mappings():
                if sub['matched_video_target_path'] not in targets and sub['matched_video_source_path'] not in originals and paths & {sub['source_subtitle_path'],sub['target_subtitle_path']}:
                    raise ValueError('deletion_path_shared')
        for obj in data['objects']:
            if obj['kind'] in ('media','inventory'):
                file=current.get(obj['snapshot']['key'])
                if not file:raise ValueError('deletion_media_changed')
                # File state is validated separately, including resumable staged paths.
                frozen=lib.freeze(file);expected=obj['snapshot']
                if self._classification(file)!=obj['classification']:raise ValueError('deletion_media_changed')
                for key in ('key','source_path','target_path','title_id','season','episode'):
                    if frozen.get(key)!=expected.get(key):raise ValueError('deletion_media_changed')
                # The user classification's fingerprint may point at the staged inode.
                # Compare its persisted evidence above, not a missing-path rendering.
                if ({k:v for k,v in frozen['metadata'].items() if k!='classification'}!=
                    {k:v for k,v in expected['metadata'].items() if k!='classification'}):
                    raise ValueError('deletion_media_changed')

            else:
                row=self.service._task(obj['id'],manage=True) if obj['kind']=='acquisition' else lib.owned(obj['id'],'library_task')
                if row['state']=='deleted' or (self._task_identity(row)!=obj['task_identity'] if obj['kind']=='acquisition' else self._library_task_identity(row)!=obj['task_identity']):
                    raise ValueError('deletion_task_changed')

    def apply(self,plan_id,confirm):
        if confirm is not True:raise ValueError('deletion_confirmation_required')
        plan=self.records.get(plan_id,'deletion_plan');data=plan['data']
        if data['owner']!=self.service.actor.id:raise ValueError('permission_denied')
        if data['action']=='download':self.service._download_permission()
        else:Collections(self.service).manage()
        with ExitStack() as stack:
            for obj in sorted((o for o in data['objects'] if o['kind']=='acquisition'),key=lambda o:o['id']):
                stack.enter_context(self.db.lock('acquire:'+obj['id']))
            stack.enter_context(media_mutation_lock(self.db,timeout=5))
            plan=self.records.get(plan_id,'deletion_plan');data=plan['data']
            if plan['state']=='preview':
                require_fresh(data)
                for f in data['files']:
                    if file_state(f['path'],f['role'])!=f['fingerprint']:raise ValueError('deletion_files_changed')
            elif plan['state'] not in ('executing','applied'):raise ValueError('deletion_plan_invalid')
            if plan['state']!='applied':
                self._validate_objects(data)
                self._quiesce(data)
                if plan['state']=='preview':
                    plan=self.records.update(plan,'executing');data=plan['data']
                self._remove_torrents(data)
                self._stage_files(plan)
                self._commit(plan)
                plan=self.records.get(plan_id,'deletion_plan')
            self._cleanup(plan)
            return self.public(self.records.get(plan_id,'deletion_plan'))

    def _quiesce(self,data):
        """The write transaction fences a simultaneous worker claim."""
        keys={o['processing_key'] for o in data['objects'] if o.get('processing_key')}
        roots={o['snapshot'].get(key) for o in data['objects'] if o['kind'] in ('media','inventory') for key in ('source_path','target_path') if o['snapshot'].get(key)}
        with self.db.begin() as conn:
            # A no-op write acquires SQLite's writer fence before checking leases.
            conn.execute(text('UPDATE media_processing_job SET state=state WHERE id=-1'))
            rows=conn.execute(text("SELECT * FROM media_processing_job WHERE state IN ('queued','retry','running')")).mappings().all()
            affected=[r for r in rows if r['delivery_key'] in keys or any(
                root and (r['path']==root or Path(root).is_relative_to(Path(r['path']))) for root in roots)]
            if any(r['state']=='running' and not (data['action']=='task' and r['stage']=='library' and r['delivery_key'] in keys) for r in affected):
                raise ValueError('deletion_wait_for_worker_checkpoint')
            if roots:
                for row in conn.execute(text("SELECT data FROM media_mcp_record WHERE kind='library_task' AND state IN ('queued','running')")).mappings():
                    if any(f.get(key) in roots for f in json.loads(row['data']).get('files',[]) for key in ('source_path','target_path')):
                        raise ValueError('deletion_wait_for_worker_checkpoint')
            for row in affected:
                conn.execute(text("UPDATE media_processing_job SET state='cancelled',owner=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=:id"),{'id':row['id']})

    def _remove_torrents(self,data):
        for obj in data['objects']:
            if obj['kind']!='acquisition':continue
            row=self.records.get(obj['id'],'acquisition');current=self._torrent(row)
            if current:
                if current!=obj.get('torrent'):raise ValueError('deletion_torrent_changed')
                assert_mutation_lock()
                self.downloader.remove(current['hash'])
                if self.downloader.find(current['hash']):raise ValueError('deletion_torrent_removal_pending')

    @staticmethod
    def _staged(plan,index,f):
        return str(Path(f['path']).parent/('.media-delete-'+plan['id']+'-'+str(index)))

    def _stage_files(self,plan):
        for index,f in enumerate(plan['data']['files']):
            staged=self._staged(plan,index,f)
            actual=file_state(f['path'],f['role']);saved=file_state(staged,f['role'])
            if actual is None and saved==f['fingerprint']:continue
            if actual!=f['fingerprint'] or saved not in (None,f['fingerprint']):raise ValueError('deletion_files_changed')
            assert_mutation_lock()
            if saved is None:os.link(f['path'],staged,follow_symlinks=False)
            if file_state(staged,f['role'])!=f['fingerprint'] or file_state(f['path'],f['role'])!=f['fingerprint']:
                raise ValueError('deletion_files_changed')
            assert_mutation_lock();Path(f['path']).unlink()

    def _commit(self,plan):
        data=plan['data']
        for f in data['files']:
            if file_state(f['path'],f['role']) is not None:raise ValueError('deletion_path_reappeared')
        with self.db.begin() as conn:
            for obj in data['objects']:
                if obj['kind'] in ('media','inventory'):
                    snap=obj['snapshot'];source=snap['source_path'];target=snap['target_path']
                    conn.execute(text('DELETE FROM media_subtitle WHERE matched_video_target_path=:target OR matched_video_source_path=:source'),{'source':source,'target':target})
                    if obj['kind']=='media':conn.execute(text('DELETE FROM media_link WHERE id=:id'),{'id':obj['id']})
                    for table in ('media_library_identity','media_library_classification'):
                        conn.execute(text(f'DELETE FROM {table} WHERE path IN (:source,:target)'),{'source':source,'target':target})
                    if self.db.table_exists('media_inventory'):
                        conn.execute(text("DELETE FROM media_inventory WHERE path IN (:source,:target) OR json_extract(data,'$.video_path') IN (:source,:target)"),{'source':source,'target':target})
                    meta=snap['metadata'];kind=meta.get('media_type');kind='tv' if kind=='tv_extra' else kind;tmdb=meta.get('media_tmdb_id')
                    if kind and tmdb and not conn.execute(text("SELECT path FROM media_library_identity WHERE json_extract(data,'$.identity.title_id')=:title LIMIT 1"),{'title':f'{kind}:{tmdb}'}).first() and not conn.execute(text('SELECT id FROM media_link WHERE media_type IN (:kind,:extra) AND media_tmdb_id=:tmdb LIMIT 1'),{'kind':kind,'extra':'tv_extra' if kind=='tv' else kind,'tmdb':tmdb}).first():
                        conn.execute(text("DELETE FROM media_mcp_record WHERE kind='library_title' AND json_extract(data,'$.identity.title_id')=:title"),{'title':f'{kind}:{tmdb}'})
                else:
                    conn.execute(text("UPDATE media_mcp_record SET state='deleted',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id"),{'id':obj['id']})
            receipt={'files':len(data['files']),'objects':len(data['objects']),'completed_at':time.time(),'cleanup_complete':False}
            conn.execute(text("UPDATE media_mcp_record SET state='applied',data=:data,revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
                         {'id':plan['id'],'data':json.dumps({**data,'receipt':receipt},ensure_ascii=False)})
        self.service.accounts.event(self.service.actor,'deletion_applied','deletion_plan',plan['id'])

    def _cleanup(self,plan):
        for index,f in enumerate(plan['data']['files']):
            path=self._staged(plan,index,f);actual=file_state(path,f['role'])
            if actual is not None:
                if actual!=f['fingerprint']:raise ValueError('deletion_quarantine_changed')
                assert_mutation_lock();Path(path).unlink()
        retained=[]
        for raw in sorted(plan['data']['directories'],key=lambda p:len(Path(p).parts),reverse=True):
            root=download_root() if Path(raw).is_relative_to(download_root()) else library_root()
            directory=contained(raw,root,exists=False)
            try:directory.rmdir()
            except FileNotFoundError:pass
            except OSError:
                # A new or unrelated entry is never removed by recursive cleanup.
                retained.append(raw)
        receipt={**plan['data']['receipt'],'cleanup_complete':True,'retained_directories':retained}
        if receipt!=plan['data']['receipt']:
            self.records.update(plan,'applied',{**plan['data'],'receipt':receipt})
