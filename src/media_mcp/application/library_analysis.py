"""Local library inspection, deterministic triage and bounded AI research previews."""
import json
import ipaddress
import math
import os
from pathlib import Path
import re
import stat
import statistics
import subprocess
import time
import uuid
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field
from sqlalchemy import text
from media_mcp.application.collections import classify,digest,file_state,library_root,video_changed
from media_mcp.config import contained,download_root
from media_mcp.platform.cloud import Evidence,Identity
from media_mcp.runtime.state import media_mutation_lock,assert_mutation_lock
from media_mcp.storage.records import require_fresh

MAX_SELECTED=500
MAX_CONTEXT_FILES=2000
MAX_CONTEXT_VIDEOS=500
VIDEO={'.mkv','.mp4','.avi','.mov','.wmv','.flv','.webm','.m4v','.ts'}


class Decision(Evidence):
    key:str=Field(pattern=r'^[mi]:[1-9][0-9]*$')
    category:Literal['main','extra','unknown']
    identity:Identity|None=None
    season:int|None=Field(default=None,ge=0,le=99)
    episode:int|None=Field(default=None,ge=1,le=999)
    confidence:float=Field(ge=0,le=1)
    runtime_seconds:float|None=Field(default=None,gt=0,le=172800)
    reason:str=Field(min_length=1,max_length=2000)
    sources:list[str]=Field(default_factory=list,max_length=12)


class AnalysisOutput(Evidence):
    decisions:list[Decision]=Field(max_length=12)


def path_role(path,allow_root=False):
    if allow_root:
        for base,role in ((Path(download_root()).resolve(),'source'),(library_root(),'target')):
            if Path(path).absolute()==base and Path(path).resolve()==base:return base,role
    try:return contained(path,download_root(),exists=False),'source'
    except ValueError:return contained(path,library_root(),exists=False),'target'


def context_roots(files,folder=False):
    roots={}
    generic={Path(download_root()).resolve(),library_root(),library_root()/'movie',library_root()/'series'}
    for file in files:
        if not file['state']['source'] and not file['state']['target']:raise ValueError('analysis_file_missing')
        role='source' if file['state']['source'] else 'target'
        raw=file.get(role+'_path')
        if not raw:raise ValueError('analysis_file_missing')
        path,role=path_role(raw)
        owner=file.get('classification',{}).get('owner') or file.get('metadata',{}).get('classification',{}).get('owner')
        root=Path(owner) if owner and Path(owner) in path.parents else path.parent
        root,role=path_role(str(root),allow_root=True)
        recursive=folder or root not in generic
        entry=roots.setdefault(str(root),{'path':str(root),'recursive':recursive})
        if not recursive:entry.setdefault('selected',[]).append(str(path))
    return [entry for path,entry in sorted(roots.items())
            if not any(other!=path and value['recursive'] and Path(other) in Path(path).parents for other,value in roots.items())]


def manifest(roots):
    entries={}
    def inspect(path):
        if path.name=='.env' or path.name.startswith('.env.') or path.is_symlink():return
        info=path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):return
        path,role=path_role(str(path))
        entries[str(path)]={'path':str(path),'state':[info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns]}
        if len(entries)>MAX_CONTEXT_FILES:raise ValueError('analysis_context_too_large')
    for root in roots:
        path,role=path_role(root['path'],allow_root=True)
        if not path.is_dir():raise ValueError('analysis_directory_missing')
        if root['recursive']:
            def unreadable(error):raise ValueError('analysis_directory_unreadable')
            for directory,dirs,files in os.walk(path,followlinks=False,onerror=unreadable):
                dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not Path(directory,d).is_symlink())
                for name in sorted(files):inspect(Path(directory,name))
        else:
            selected=[Path(value) for value in root.get('selected',[])]
            for child in sorted(path.iterdir()):
                if not selected or any(child==value or child.name.startswith(value.stem+'.') for value in selected):inspect(child)
    result=list(entries.values())
    if len(json.dumps(result))>600000:raise ValueError('analysis_context_too_large')
    return result


def probe_duration(path):
    try:
        output=subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe',
            '-show_entries','format=duration','-of','json',path],capture_output=True,text=True,timeout=10,check=True)
        duration=float(json.loads(output.stdout)['format']['duration'])
        return duration if math.isfinite(duration) and duration>0 else None
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,TypeError):return None


def tmdb_source(url):
    try:
        value=urlsplit(url)
        if value.scheme!='https' or value.hostname not in ('www.themoviedb.org','themoviedb.org') or value.username or value.password or value.port not in (None,443):return None
        match=re.match(r'^/(movie|tv)/([1-9][0-9]{0,11})(?:[-/]|$)',value.path)
        return f'{match[1]}:{match[2]}' if match else None
    except ValueError:return None


def public_source(url):
    try:
        value=urlsplit(url);host=(value.hostname or '').lower().rstrip('.')
        if value.scheme!='https' or value.username or value.password or value.port not in (None,443):return False
        try:return ipaddress.ip_address(host).is_global
        except ValueError:
            return bool('.' in host and not host.endswith(('.local','.lan','.internal')) and re.fullmatch(r'[a-z0-9.-]+',host))
    except ValueError:return False


def source_key(url):
    if not public_source(url):return None
    value=urlsplit(url)
    return value.hostname.lower(),value.path.rstrip('/')


def validate_decision(item,opened,search_count=0):
    result=item.model_dump();result['source']='ai';result['applicable']=False
    claimed={tmdb_source(url) for url in item.sources if tmdb_source(url)}
    keys={source_key(url) for url in item.sources if source_key(url)}
    result['sources']=sorted(url for url in opened if public_source(url) and (source_key(url) in keys or tmdb_source(url) in claimed))
    observed_keys={source_key(url) for url in result['sources']}
    if search_count:
        result['sources']=sorted(set(result['sources'])|{url for url in item.sources if public_source(url) and source_key(url) not in observed_keys})
    result['source_provenance']={url:'opened' if source_key(url) in observed_keys else 'search_reference' for url in result['sources']}
    result['observed_search_count']=search_count
    if item.category=='unknown' or item.confidence<.8:
        return result
    if item.category=='main' and not item.identity:return result
    if item.category=='extra' and (item.season is not None or item.episode is not None):return result
    if item.identity:
        identity=item.identity.model_dump()
        if identity.get('date') and not re.fullmatch(r'(?:18|19|20|21)\d{2}(?:-\d{2}-\d{2})?',identity['date']):return result
        poster=identity.get('poster_url')
        if poster and not re.fullmatch(r'https://image\.tmdb\.org/t/p/(?:w342|w500|original)/[A-Za-z0-9_.-]+',poster):identity['poster_url']=None
        sources=[url for url in result['sources'] if tmdb_source(url)==item.identity.title_id]
        if not sources:return result
        if item.category=='main' and item.identity.kind=='tv':
            if item.season is None or item.episode is None:return result
            if not any(re.search(r'/season/'+str(item.season)+r'(?:/|$)',urlsplit(url).path) for url in sources):return result
        if item.identity.kind=='movie' and (item.season is not None or item.episode is not None):return result
        result['identity']=identity
    elif item.category=='extra':
        # Classification without a parent identity remains explicitly labelled as such.
        if not result['sources']:return result
    result['applicable']=True
    return result


class LibraryAnalysis:
    def __init__(self,library):
        self.library=library;self.db=library.db;self.records=library.records

    def queue(self,collection_id,idempotency_key,selection=None,season=None,folder=False):
        lib=self.library;lib.manage()
        intent={'selection':sorted(selection) if selection is not None else None,'season':season,'folder':folder}
        previous=self.records.by_key(digest(['library',lib.actor.id,idempotency_key]))
        if previous:
            if previous['data']['action']!='analysis' or previous['data']['intent'].get('request')!=intent or previous['data']['collection_id']!=collection_id:
                raise ValueError('idempotency_key_reused_with_different_request')
            return lib.task(previous['id'])
        group,files=lib.selection(collection_id,selection,season)
        roots=context_roots([{**f,'state':lib.freeze(f)['state']} for f in files],folder=folder)
        if folder:
            def inside(file):
                for path in (file.get('source_path'),file.get('target_path')):
                    if path and any((Path(r['path']) in Path(path).parents if r['recursive'] else Path(path).parent==Path(r['path'])) for r in roots):return True
                return False
            files=[file for file in lib.files() if inside(file)]
        if not files or len(files)>MAX_SELECTED:raise ValueError('analysis_select_smaller_scope')
        return lib._queue('analysis',collection_id,[lib.freeze(f) for f in files],[],idempotency_key,request=intent,label=lib._title(group)['title'],analysis_roots=roots)

    def plan(self,plan_id):
        self.library.manage();row=self.library.owned(plan_id,'library_analysis')
        data=row['data']
        return {'plan_id':row['id'],'state':row['state'],'expires_at':data['expires_at'],
                'decisions':data['decisions'],'files':data['public_files'],'context_file_count':len(data['manifest']),
                'ai_used':data['ai_used'],'receipt':data.get('receipt')}

    def cache_identity(self,conn,identity):
        key=digest('library-title:'+identity['title_id'])
        previous=conn.execute(text('SELECT data FROM media_mcp_record WHERE key_hash=:key'),{'key':key}).scalar()
        metadata=json.loads(previous) if previous else {}
        metadata['identity']={**metadata.get('identity',{}),**{k:v for k,v in identity.items() if v is not None}}
        conn.execute(text('''INSERT INTO media_mcp_record(id,kind,data,state,key_hash,created_at,updated_at)
            VALUES(:id,'library_title',:data,'confirmed',:key,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            ON CONFLICT(key_hash) DO UPDATE SET data=excluded.data,state='confirmed',
            revision=media_mcp_record.revision+1,updated_at=CURRENT_TIMESTAMP'''),
            {'id':uuid.uuid4().hex,'data':json.dumps(metadata,ensure_ascii=False),'key':key})

    def apply(self,plan_id,selection,*,automatic=False,guard=None,exclude_task=None):
        lib=self.library;lib.manage()
        if automatic:
            if guard is None:raise ValueError('automatic_guard_required')
            guard()
        chosen=set(selection)
        with media_mutation_lock(self.db):
            row=lib.owned(plan_id,'library_analysis');data=row['data']
            from media_mcp.runtime.session_recovery import assert_generation
            assert_generation(self.records,data['task_id'],data.get('analysis_generation',0))
            if row['state']=='applied':
                if chosen!=set(data['receipt']['keys']):raise ValueError('analysis_selection_already_applied')
                return data['receipt']
            require_fresh(data)
            if not chosen or len(chosen)!=len(selection):raise ValueError('analysis_select_results')
            decisions={d['key']:d for d in data['decisions'] if d['applicable']}
            if not chosen<=decisions.keys():raise ValueError('analysis_result_not_applicable')
            lib.validate(data['files'])
            if digest(manifest(data['roots']))!=digest(data['manifest']):raise ValueError('analysis_directory_changed')
            if lib.active_overlap(data['files'],excluded=(exclude_task,) if automatic else ()):raise ValueError('collection_operation_busy')
            files={f['key']:f for f in data['files']}
            with self.db.begin() as conn:
                for key in sorted(chosen,key=lambda value:(decisions[value]['source']=='ai',value)):
                    assert_mutation_lock();decision=decisions[key];file=files[key]
                    identity=decision.get('identity')
                    if identity:
                        lib.write_identity(conn,file,identity,decision,confirmation='automatic' if automatic else 'user')
                        self.cache_identity(conn,identity)
                    role='source' if file['state']['source'] else 'target';path=file[role+'_path']
                    conn.execute(text('''INSERT INTO media_library_classification(path,category,fingerprint) VALUES(:path,:category,:fingerprint)
                        ON CONFLICT(path) DO UPDATE SET category=excluded.category,fingerprint=excluded.fingerprint,updated_at=CURRENT_TIMESTAMP'''),
                        {'path':path,'category':decision['category'],'fingerprint':json.dumps(file_state(path,role))})
                receipt={'updated_files':len(chosen),'keys':sorted(chosen),'automatic':automatic};data['receipt']=receipt
                assert_mutation_lock()
                conn.execute(text("UPDATE media_mcp_record SET state='applied',data=:data,updated_at=CURRENT_TIMESTAMP WHERE id=:id"),
                    {'data':json.dumps(data,ensure_ascii=False),'id':row['id']})
                conn.execute(text("UPDATE media_mcp_record SET data=json_set(data,'$.analysis_applied',:count),revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id"),{'id':data['task_id'],'count':len(chosen)})
        lib.service.accounts.event(lib.actor,'library_analysis_applied','library',plan_id)
        return receipt

    def process(self,row,guard,client=None,probe=probe_duration,*,allow_new_research=True):
        lib=self.library;data=row['data']
        from media_mcp.runtime.session_recovery import assert_generation,recover_analysis
        generation=data.get('analysis_generation',0)
        parent_guard=guard
        def guard():
            parent_guard();assert_generation(self.records,row['id'],generation)
        def save():
            nonlocal row
            guard();row=self.records.update(row,'running',data)
        guard();lib.validate(data['files'])
        current={f['key']:f for f in lib.files()}
        files=[{**current[f['key']],'state':f['state']} for f in data['files']]
        roots=data.get('analysis_roots') or context_roots(files,folder=data['intent']['request']['folder'])
        observed=manifest(roots)
        if data.get('analysis_manifest') is not None and digest(observed)!=digest(data['analysis_manifest']):
            raise ValueError('analysis_directory_changed')
        data['analysis_roots']=roots;data['analysis_manifest']=observed
        videos=[entry for entry in observed if Path(entry['path']).suffix.lower() in VIDEO]
        known_paths={entry['path'] for entry in videos}
        for file in files:
            for role in ('source','target'):
                path=file.get(role+'_path')
                if file['state'][role] and path not in known_paths:
                    videos.append({'path':path,'state':file['state'][role]});known_paths.add(path)
        if len({tuple(entry['state'][:2]) for entry in videos})>MAX_CONTEXT_VIDEOS:raise ValueError('analysis_context_too_large')
        self.db.execute('CREATE TABLE IF NOT EXISTS media_library_probe (path TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,duration REAL)')
        facts=[];physical_probes={}
        categories={f.get(role+'_path'):f['classification']['category'] for f in current.values() for role in ('source','target') if f.get(role+'_path')}
        for probe_index,entry in enumerate(videos):
            data['analysis_progress']={'phase':'probing','done':probe_index,'total':len(videos)}
            save();guard()
            cached=self.db.execute('SELECT fingerprint,duration FROM media_library_probe WHERE path=:path',entry).mappings().first()
            fingerprint=json.dumps(entry['state'])
            duration=physical_probes.get(fingerprint)
            if fingerprint not in physical_probes:
                duration=cached['duration'] if cached and cached['fingerprint']==fingerprint and cached['duration'] is not None else probe(entry['path'])
                physical_probes[fingerprint]=duration
            guard()
            path,role=path_role(entry['path'])
            if file_state(str(path),role)!=entry['state']:raise ValueError('collection_changed_rebuild_plan')
            self.db.execute('''INSERT INTO media_library_probe(path,fingerprint,duration) VALUES(:path,:fingerprint,:duration)
                ON CONFLICT(path) DO UPDATE SET fingerprint=excluded.fingerprint,duration=excluded.duration''',
                {'path':str(path),'fingerprint':fingerprint,'duration':duration})
            facts.append({'path':str(path),'duration_seconds':duration,'category_hint':categories.get(str(path),classify({role+'_path':str(path)})['category'])})
        durations={f['path']:f['duration_seconds'] for f in facts}
        selected_paths={f['source_path'] if f['state']['source'] else f['target_path'] for f in files}
        generic_roots={r['path'] for r in roots if not r['recursive']}
        peer=[f['duration_seconds'] for f in facts if f['duration_seconds'] and f['category_hint']=='main' and
              (str(Path(f['path']).parent) not in generic_roots or f['path'] in selected_paths)]
        median=statistics.median(peer) if len(peer)>=3 else None
        proposals=[];unresolved=[]
        for file in files:
            path=file['source_path'] if file['state']['source'] else file['target_path']
            duration=durations.get(path)
            outlier=file['state']['status']=='conflict' or bool(median and duration and (duration<median*.55 or duration>median*1.7))
            hint=file['classification'];identity=(file.get('identity') or {}).get('identity')
            if not identity and file.get('title_id'):
                group={'title_id':file['title_id'],'files':[file]};lib._title(group)
                identity=(lib._title_cache.get(file['title_id']) or {}).get('identity')
            expected=(file.get('identity') or {}).get('runtime_seconds')
            mismatch=bool(duration and expected and abs(duration-expected)>max(300,expected*.25))
            reason='mapping_conflict' if file['state']['status']=='conflict' else 'duration_metadata_mismatch' if mismatch else 'duration_outlier' if outlier else 'duration_unavailable' if not duration else 'rule_uncertain'
            base={'key':file['key'],'category':hint['category'],'identity':identity,'season':file.get('season'),
                  'episode':file.get('episode'),'confidence':.99,'reason':'existing_confirmed_identity',
                  'sources':[],'source':'rule','applicable':True,'runtime_seconds':expected}
            if hint['reason']=='user_classified' and hint['category']=='extra' and not outlier and (not duration or duration<=1200):
                base.update(identity=None,season=None,episode=None,reason='user_confirmed_classification');proposals.append(base)
            elif hint['category']=='extra' and duration and duration<=1200 and not outlier:
                base.update(identity=None,season=None,episode=None,reason='explicit_extra_marker_and_duration');proposals.append(base)
            elif identity and hint['category']=='main' and duration and file['state']['status']!='conflict' and not outlier and not mismatch and not video_changed(file,file['state']):
                proposals.append(base)
            else:
                if hint['category']=='extra' and duration and duration>1200:reason='extra_with_long_duration'
                unresolved.append({'key':file['key'],'source_path':file.get('source_path'),'target_path':file.get('target_path'),
                    'duration_seconds':duration,'expected_runtime_seconds':expected,'rule_hint':hint['category'],'fallback_reason':reason,
                    'filename_hints':file['guess'],'cached_identity':identity})
        # Keep accepted AI chunks durable. A restarted worker never resubmits an unknown model turn.
        accepted=data.get('analysis_decisions',[])
        done={decision['key'] for decision in accepted}
        pending=[file for file in unresolved if file['key'] not in done]
        if pending:
            from media_mcp.runtime.model_scope import assert_no_unresolved_analysis
            pending_keys={file['key'] for file in pending}
            assert_no_unresolved_analysis(self.db,[file for file in data['files'] if file['key'] in pending_keys],exclude_id=row['id'])
        for index in range(0,len(pending),12):
            chunk=pending[index:index+12]
            if 'analysis_policy' not in data:
                from media_mcp.storage.model_settings import ModelSettings
                policy=ModelSettings(self.db).get()
                if data.get('ai_inflight') and policy['revision']!=0:
                    raise ValueError('analysis_recovery_policy_unverified')
                data['analysis_policy']=policy;save()
            policy=data['analysis_policy']
            if client is None:
                from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient
                client=LibraryAnalysisClient(timeout=300,max_retries=0,model=policy['model'],reasoning_effort=policy['effort'])
            payload={'requested_files':chunk,'directory_files':[item['path'] for item in observed],
                     'video_probes':facts,'peer_median_seconds':median,'rules_succeeded':proposals}
            original_request=data.get('analysis_request') or {}
            original_keys={f['key'] for f in original_request.get('payload',{}).get('requested_files',[])}
            bound=data.get('ai_inflight') or data.get('recovered_analysis_turn') or original_request.get('pending_replacement')
            if original_request.get('payload') and (bound or original_keys=={f['key'] for f in chunk}):
                # Rule/cache enrichment may change between workers. Reuse the
                # exact submitted input, after checking its physical scope below.
                original_payload=original_request['payload']
                if {f['key'] for f in original_payload['requested_files']}!={f['key'] for f in chunk}:
                    raise ValueError('analysis_recovery_input_changed')
                payload=original_payload
            binding={'input_digest':digest(payload),'files_digest':digest(data['files']),
                     'manifest_digest':digest(observed),'policy':policy,'profile':'library-readonly-web-v1'}
            if data.get('ai_inflight'):
                row,_=recover_analysis(self.records,row,client,guard,binding,[f['key'] for f in chunk])
                data=row['data'];generation=data.get('analysis_generation',0)
            recovered=data.get('recovered_analysis_turn')
            if recovered and recovered['binding']!=binding:raise ValueError('analysis_recovery_input_changed')
            def thread(ident):data['analysis_thread']=ident;save()
            def submitting():data['ai_inflight']=True;save()
            def turn(ident):data['analysis_turn']=ident;save()
            data['analysis_progress']={'phase':'researching','done':len(accepted),'total':len(unresolved)}
            save();guard();lib.validate(data['files'])
            try:
                if recovered:
                    from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient
                    result,opened=LibraryAnalysisClient.recovered_result(recovered['turn'])
                else:
                    if not allow_new_research:
                        from media_mcp.runtime.session_recovery import ResearchRequired
                        raise ResearchRequired()
                    data.update(analysis_request={'binding':binding,'generation':generation,'payload':payload},analysis_thread=None,analysis_turn=None)
                    save()
                    result,opened=client.analyze(payload,on_thread=thread,on_submitting=submitting,on_turn=turn)
            except Exception as error:
                from media_mcp.adapters.codex import CodexError
                if isinstance(error, CodexError):
                    from media_mcp.runtime.session_recovery import now_text
                    data['last_model_failure']={'code':error.code,'phase':error.phase,
                        'outcome_unknown':error.outcome_unknown,'terminal_observed':error.terminal_observed,
                        'thread':data.get('analysis_thread'),'turn':data.get('analysis_turn'),
                        'generation':generation,'input_digest':binding['input_digest'],'at':now_text()}
                    if error.code=='rate_limited':
                        from media_mcp.runtime.quota_wait import next_quota_check
                        data['last_model_failure']['quota_next_check_at']=next_quota_check(data['last_model_failure']['at'])
                        error.quota_next_check_at=data['last_model_failure']['quota_next_check_at']
                    if not error.outcome_unknown:
                        data['ai_inflight']=False
                    if error.terminal_observed and not error.outcome_unknown and data.get('analysis_thread') and data.get('analysis_turn'):
                        from media_mcp.runtime.thread_cleanup import archive_intent
                        data.setdefault('analysis_request_history',[]).append({
                            'thread':data['analysis_thread'],'turn':data['analysis_turn'],
                            'generation':generation,'binding':binding,'status':'failed_or_interrupted',
                            'terminal_observed':True})
                        data.setdefault('thread_archive_intents',[]).append(
                            archive_intent(data,[f['key'] for f in chunk],'failed_or_interrupted'))
                    save()
                raise
            guard();lib.validate(data['files'])
            if digest(manifest(roots))!=digest(observed):raise ValueError('analysis_directory_changed')
            parsed=AnalysisOutput.model_validate(result)
            if {d.key for d in parsed.decisions}!={f['key'] for f in chunk} or len(parsed.decisions)!=len(chunk):
                raise ValueError('analysis_selection_changed')
            for item in parsed.decisions:
                decision=validate_decision(item,set(opened),getattr(opened,'search_count',0))
                selected=next(f for f in files if f['key']==item.key)
                if selected['state']['status']=='conflict':
                    decision['applicable']=False;decision['reason']='mapping_conflict_requires_review; '+decision['reason']
                accepted.append(decision)
            data['analysis_decisions']=accepted;data['ai_inflight']=False
            from media_mcp.runtime.thread_cleanup import archive_intent
            intent=archive_intent(data,[f['key'] for f in chunk])
            if intent:
                intents=data.setdefault('thread_archive_intents',[])
                if not any(v['key']==intent['key'] for v in intents):intents.append(intent)
            data.pop('recovered_analysis_turn',None);data.pop('session_recovery',None);save()
        decisions=proposals+accepted
        if {d['key'] for d in decisions}!={f['key'] for f in data['files']}:
            raise ValueError('analysis_selection_changed')
        guard();lib.validate(data['files'])
        if digest(manifest(roots))!=digest(observed):raise ValueError('analysis_directory_changed')
        plan=self.records.put('library_analysis',{'owner':lib.actor.id,'files':data['files'],'roots':roots,'manifest':observed,
            'public_files':[{'key':f['key'],'name':f['name'],'source_path':f.get('source_path'),
                'target_path':f.get('target_path'),'duration_seconds':durations.get(f['source_path'] if f['state']['source'] else f['target_path'])} for f in files],
            'task_id':row['id'],'analysis_generation':generation,'decisions':decisions,'expires_at':time.time()+86400,'ai_used':bool(unresolved)},'preview')
        guard();data['analysis_plan_id']=plan['id'];data['results']=[{'key':d['key'],'state':'completed' if d['applicable'] else 'needs_review'} for d in decisions]
        self.records.update(row,'completed' if all(d['applicable'] for d in decisions) else 'completed_with_warnings',data)
