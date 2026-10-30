"""One durable, worker-owned run for automatic library identification and maintenance."""
import json
import re
import uuid
from pathlib import Path
from sqlalchemy import text
from media_mcp.application.collections import digest,file_state,library_root,mapping_state,video_changed
from media_mcp.application.library_analysis import LibraryAnalysis,context_roots
from media_mcp.config import contained
from media_mcp.runtime.model_retry import retryable_model_error, ModelServiceDeferred, PERMANENT_MODEL_ERRORS
from media_mcp.runtime.state import media_mutation_lock,media_job_guard,assert_mutation_lock


def ready_subtitle(file):
    for path in file.get('_ready_subtitle_paths',[]):
        try:
            if contained(path,library_root(),exists=False).is_file():return True
        except ValueError:pass
    return False


def code(error):
    if str(error) in ('media_job_lease_lost','media_mutation_lock_lost','media_mutation_scope_invalidated'):raise error
    value=getattr(error,'code',str(error) if isinstance(error,ValueError) else type(error).__name__)
    if value in ('media_job_lease_lost','media_mutation_lock_lost','media_mutation_scope_invalidated'):raise error
    return value if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,100}',value) else type(error).__name__


AI_UNAVAILABLE={'token_missing','token_rejected','login_required','rate_limited','maintenance','model_at_capacity','connection_failed'}


class UnavailableAI:
    def analyze(self,*args,**kwargs):raise ValueError('automatic_ai_unavailable')


class LibraryAuto:
    def __init__(self,library):
        self.lib=library;self.records=library.records;self.db=library.db

    def pending(self,file,state):
        if video_changed(file,state):return True
        if file['classification']['category']=='extra' and (file['classification']['reason']=='user_classified' or file['title_id']):return False
        if not file['title_id']:return True
        if state['status'] in ('missing','target_missing','unorganized','conflict'):return True
        if not file.get('media_id') and state['status']=='library_only':return False
        if file.get('status') not in ('linked','source_missing'):return True
        return not ready_subtitle(file)

    def queue(self,idempotency_key,collection_id=None,scope='pending'):
        lib=self.lib;lib.manage()
        from media_mcp.runtime.state import MediaJobs
        MediaJobs().initialize()
        intent={'collection_id':collection_id,'scope':scope}
        request_key=digest(['library-auto',lib.actor.id,idempotency_key])
        with media_mutation_lock(self.db):
            previous=self.records.by_key(request_key)
            if previous:
                if previous['data']['owner']!=lib.actor.id or previous['data']['intent']!=intent:raise ValueError('idempotency_key_reused_with_different_request')
                return lib.task(previous['data']['job_id'])
            active=self.db.execute("""SELECT * FROM media_mcp_record WHERE kind='library_task'
                AND json_extract(data,'$.action')='auto' AND state IN ('queued','running') ORDER BY rowid LIMIT 1""").mappings().first()
            if active:
                active=self.records.decode(active)
                if active['data']['owner']!=lib.actor.id or active['data']['intent']!=intent:raise ValueError('library_auto_already_running')
                self.records.put('library_auto_request',{'owner':lib.actor.id,'intent':intent,'job_id':active['id']},key_hash=request_key)
                return lib.task(active['id'])
            groups=lib.groups()
            if collection_id:
                if collection_id not in groups:raise ValueError('collection_not_found')
                groups={collection_id:groups[collection_id]}
            files=[];work=[];results=[]
            for group in groups.values():
                selected=[]
                for file in group['files']:
                    try:
                        state=mapping_state(file)
                        if scope=='pending' and not self.pending(file,state):continue
                        if not state['source'] and not state['target']:raise ValueError('analysis_file_missing')
                        frozen=lib.freeze(file);files.append(frozen);selected.append(file['key'])
                    except (ValueError,OSError) as error:
                        results.append({'key':file['key'],'name':file['name'],'state':'needs_review','error_code':code(error)})
                for offset in range(0,len(selected),500):
                    work.append({'keys':selected[offset:offset+500],'label':lib._title(group)['title'],'collection_id':group['collection_id']})
            if len(files)>20000:raise ValueError('library_auto_scope_too_large')
            if files:
                from media_mcp.platform.limits import Budget
                Budget(self.db,lib.service.accounts.clock).admit_job(lib.actor.id)
            ident=uuid.uuid4().hex
            data={'owner':lib.actor.id,'action':'auto','automatic':True,'collection_id':collection_id,'label':lib._title(next(iter(groups.values())))['title'] if collection_id else '自动整理媒体库',
                'intent':intent,'files':files,'work':work,'next_work':0,'results':results,'operations':[],
                'total':len(files)+len(results),'processing_key':digest('library:'+ident),'blocked':[],
                'summary':{'identified':0,'linked':0,'extras':0,'subtitles':0},'analysis_progress':{'phase':'automatic','done':len(results),'total':len(files)+len(results)}}
            state='queued' if work else 'completed_with_warnings' if results else 'completed'
            with self.db.begin() as conn:
                conn.execute(text("""INSERT INTO media_mcp_record(id,kind,data,state,created_at,updated_at)
                    VALUES(:id,'library_task',:data,:state,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""),{'id':ident,'data':json.dumps(data,ensure_ascii=False),'state':state})
                conn.execute(text("""INSERT INTO media_mcp_record(id,kind,data,state,key_hash,created_at,updated_at)
                    VALUES(:request,'library_auto_request',:data,'ready',:key,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""),
                    {'request':uuid.uuid4().hex,'data':json.dumps({'owner':lib.actor.id,'intent':intent,'job_id':ident}),'key':request_key})
                if work:
                    conn.execute(text("""INSERT INTO media_processing_job(delivery_key,stage,path,state,next_attempt_at,created_at,updated_at)
                        VALUES(:key,'library',:path,'queued',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"""),{'key':data['processing_key'],'path':collection_id or 'library'})
            lib.service.accounts.event(lib.actor,'library_auto_requested','library',ident)
            return lib.task(ident)

    def alias(self,original,files,guard):
        paths={f.get(role+'_path') for f in files for role in ('source','target') if f.get(role+'_path')}
        matches=[group['collection_id'] for group in self.lib.groups().values() if any(
            f.get('source_path') in paths or f.get('target_path') in paths for f in group['files'])]
        if len(matches)!=1:return None
        target=matches[0]
        if target!=original:
            guard()
            key=digest(['library-alias',self.lib.actor.id,original])
            self.db.execute("""INSERT INTO media_mcp_record(id,kind,data,state,key_hash,created_at,updated_at)
                VALUES(:id,'library_alias',:data,'ready',:key,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
                ON CONFLICT(key_hash) DO UPDATE SET data=excluded.data,updated_at=CURRENT_TIMESTAMP""",
                {'id':uuid.uuid4().hex,'data':json.dumps({'target':target}),'key':key})
        return target

    def process(self,jobs,row,guard,client=None,probe=None,subtitle_agent=None):
        lib=self.lib;data=row['data'];frozen={file['key']:file for file in data['files']}
        def save():
            nonlocal row
            guard();row=self.records.update(row,'running',data)
        def phase(name,label):
            data['analysis_progress']={'phase':name,'label':label,'done':len(data['results']),'total':data['total']};save()
        for index in range(data.get('next_work',0),len(data['work'])):
            item=data['work'][index];expected=[frozen[key] for key in item['keys']]
            phase('identifying',item['label'])
            child_key=digest(['library-auto-item',row['id'],index]);child=self.records.by_key(child_key)
            try:
                if not child:
                    guard();lib.validate(expected)
                    if lib.active_overlap(expected,excluded=(row['id'],)):raise ValueError('collection_operation_busy')
                    child=self.records.put('library_auto_item',{'owner':lib.actor.id,'action':'analysis','collection_id':item['collection_id'],
                        'files':expected,'results':[],'intent':{'request':{'folder':False}},'analysis_roots':context_roots(expected)},'running',key_hash=child_key)
                if not child['data'].get('analysis_plan_id'):
                    kwargs={'client':UnavailableAI() if data.get('ai_error') else client}
                    if probe is not None:kwargs['probe']=probe
                    LibraryAnalysis(lib).process(child,guard,**kwargs)
                    child=self.records.get(child['id'])
                plan=self.records.get(child['data']['analysis_plan_id'],'library_analysis')
                eligible=[d['key'] for d in plan['data']['decisions'] if d['applicable'] and (d['source']=='rule' or d['confidence']>=.9)]
                phase('saving',item['label'])
                if eligible:
                    with media_job_guard(guard):
                        LibraryAnalysis(lib).apply(plan['id'],eligible,automatic=True,guard=guard,exclude_task=row['id'])
                target=self.alias(item['collection_id'],expected,guard)
                if data['collection_id'] and target:data['result_collection_id']=target
                child=self.records.get(child['id'])
                child=self.maintain(jobs,child,eligible,guard,phase,subtitle_agent,data.get('ai_error'))
                if child['data'].get('ai_error'):data['ai_error']=child['data']['ai_error']
                outcomes={result['key']:result for result in child['data'].get('auto_results',[])}
                for decision in plan['data']['decisions']:
                    original=frozen[decision['key']]
                    result=outcomes.get(decision['key'],{'key':decision['key'],'state':'needs_review',
                        'error_code':'automatic_match_uncertain','analysis_plan_id':plan['id']})
                    result={**result,'name':Path(original.get('source_path') or original.get('target_path')).name,'category':decision['category']}
                    data['results'].append(result)
                    if decision['key'] in eligible:
                        data['summary']['identified']+=1
                        data['summary']['extras']+=int(decision['category']=='extra')
                    data['summary']['linked']+=int(result.get('mapping_created',False))
                    data['summary']['subtitles']+=int(result.get('subtitles')=='ready')
            except Exception as error:
                if child:error.recovery_record_id=child['id']
                if isinstance(error, ModelServiceDeferred) or getattr(error, 'outcome_unknown', False):raise
                error_code=code(error)
                if retryable_model_error(error):
                    raise ModelServiceDeferred(error_code) from error
                if error_code in AI_UNAVAILABLE or error_code in PERMANENT_MODEL_ERRORS:raise
                if child:
                    guard();child=self.records.get(child['id'])
                    self.records.update(child,'needs_review',{**child['data'],'error_code':error_code})
                for file in expected:
                    data['results'].append({'key':file['key'],'name':Path(file.get('source_path') or file.get('target_path')).name,
                        'state':'needs_review','error_code':error_code})
            data['next_work']=index+1;data['analysis_progress']['done']=len(data['results']);save()
        guard()
        state='completed_with_warnings' if any(result['state']!='completed' for result in data['results']) else 'completed'
        data['analysis_progress']={'phase':'finished','done':len(data['results']),'total':data['total']}
        self.records.update(row,state,data)

    def maintain(self,jobs,child,eligible,guard,phase,subtitle_agent,ai_error=None):
        from media_mcp.runtime.library_worker import repair_mapping,process_subtitle
        lib=self.lib;data=child['data'];selected=set(eligible)
        if ai_error:data['ai_error']=ai_error
        decisions={d['key']:d for d in self.records.get(data['analysis_plan_id'])['data']['decisions']}
        def save():
            nonlocal child
            guard();child=self.records.update(child,'running',data)
        # Persist mapping previews before touching the filesystem, so a committed link is recoverable.
        if 'auto_plans' not in data:
            plans=[]
            for group in lib.groups().values():
                keys=[file['key'] for file in group['files'] if file['key'] in selected and file['classification']['category']=='main']
                if keys:plans.append(lib.mapping_preview(group['collection_id'],selection=keys)['plan_id'])
            data['auto_plans']=plans;data['auto_mappings']={};data['auto_results']=[];save()
        phase('mapping','')
        for ident in data['auto_plans']:
            plan=self.records.get(ident,'library_mapping')['data'];files={file['key']:file for file in plan['files']}
            for operation in plan['operations']:
                key=operation['key']
                if key in data['auto_mappings']:continue
                try:
                    guard()
                    if operation['action']=='review':raise ValueError(operation['reason'] or 'automatic_mapping_review')
                    if operation['action'] in ('create_link','refresh_record'):
                        with media_job_guard(guard),media_mutation_lock(self.db) as conn:
                            value=repair_mapping(lib,jobs,conn,files[key],operation)
                        data['auto_mappings'][key]={'state':value['state'],'created':operation['action']=='create_link'}
                    else:
                        lib.validate([files[key]])
                        data['auto_mappings'][key]={'state':'completed','created':False}
                except Exception as error:
                    data['auto_mappings'][key]={'state':'needs_review','error_code':code(error)}
                save()
        originals={file['key']:file for file in data['files']}
        completed={result['key'] for result in data['auto_results']}
        for key in eligible:
            if key in completed:continue
            guard();original=originals[key]
            if decisions[key]['category']=='extra':
                data['auto_results'].append({'key':key,'state':'completed','subtitles':'not_applicable'});save();continue
            mapping=data['auto_mappings'].get(key,{'state':'needs_review','error_code':'automatic_mapping_review'})
            result={'key':key,'state':mapping['state'],'mapping_created':mapping.get('created',False),'error_code':mapping.get('error_code')}
            if mapping['state']=='completed':
                phase('subtitles','')
                try:
                    current=next((file for file in lib.files() if (file.get('source_path') and file.get('source_path')==original.get('source_path')) or
                                  (not original.get('source_path') and file.get('target_path')==original.get('target_path'))),None)
                    if not current:raise ValueError('collection_changed_rebuild_plan')
                    if video_changed(current,mapping_state(current)):raise ValueError('source_identity_changed')
                    if not current.get('media_id'):
                        result['subtitles']='not_applicable'
                    elif ready_subtitle(current):result['subtitles']='ready'
                    else:
                        if data.get('ai_error'):raise ValueError('automatic_ai_unavailable')
                        if data.get('subtitle_inflight')==key:raise ValueError('automatic_subtitle_outcome_unknown')
                        if subtitle_agent is None:
                            from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
                            subtitle_agent=SubtitleAgent(defer_ai_usage=True)
                        data['subtitle_inflight']=key;save()
                        with media_job_guard(guard),media_mutation_lock(self.db):
                            value=process_subtitle(lib,jobs,lib.freeze(current),subtitle_agent,task_id=child['id'])
                        fresh=next((file for file in lib.files() if file['key']==current['key']),None)
                        if value['state']!='completed' or not fresh or not ready_subtitle(fresh):raise ValueError('automatic_subtitle_review')
                        result['subtitles']='ready'
                        data['subtitle_inflight']=None
                except Exception as error:
                    error_code=code(error)
                    if retryable_model_error(error):
                        data['subtitle_inflight']=None
                        save()
                        raise ModelServiceDeferred(error_code) from error
                    if error_code in AI_UNAVAILABLE or error_code in PERMANENT_MODEL_ERRORS:raise
                    if error_code=='prior_subtitle_outcome_unknown':
                        data['subtitle_inflight']=None;save()
                    result.update(state='needs_review',error_code=error_code)
            data['auto_results'].append(result);save()
        guard()
        return self.records.update(child,'completed',data)
