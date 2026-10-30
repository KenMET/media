"""Durable collection maintenance, with the existing lease and mutation fences."""
import hashlib
import json
import os
import re
from pathlib import Path
import threading
import time
from sqlalchemy import text

from media_mcp.application.collections import Collections, mapping_state
from media_mcp.runtime.state import MediaJobs,media_mutation_lock,assert_mutation_lock,media_job_guard
from media_mcp.runtime.worker import heartbeat
from media_mcp.storage.records import Records
from media_mcp.runtime.model_retry import ModelServiceDeferred, retryable_model_error, MAX_MODEL_RETRIES, PERMANENT_MODEL_ERRORS


def repair_mapping(library,jobs,conn,file,operation):
    from media_mcp.runtime import version_changes
    from media_mcp.storage.media import upsert_media_link
    from media_mcp.config import contained
    from media_mcp.application.collections import library_root,file_state
    target=operation['target_path'];source=file['source_path']
    contained(target,library_root(),exists=False)
    if operation['action']=='refresh_record':
        current=next((f for f in library.files() if f['key']==file['key']),None)
        if current and current.get('status')=='unlinked':
            raise ValueError('version_selection_required')
        observed=library.freeze(current) if current else None
        expected=json.loads(json.dumps(file))
        if observed:
            for key in ('status','reason','fail_stage'):
                observed['metadata'].pop(key,None)
                expected['metadata'].pop(key,None)
        if observed!=expected:
            raise ValueError('collection_changed_rebuild_plan')
        if mapping_state(file)['status']!='linked':
            raise ValueError('collection_changed_rebuild_plan')
        assert_mutation_lock()
        conn.execute(text("""UPDATE media_link SET status='linked',source_exists=1,target_exists=1,
            fail_stage=NULL,reason='library_mapping_checked',updated_at=CURRENT_TIMESTAMP WHERE id=:id"""),{'id':file['media_id']})
        conn.commit()
        return {'key':file['key'],'state':'completed','record_refreshed':True}
    version_changes.initialize(jobs.db)
    assert_mutation_lock()
    version_changes.recover_pending(conn)
    if os.path.lexists(target):
        existing=jobs.db.execute('SELECT * FROM media_link WHERE source_path=:source AND target_path=:target',{'source':source,'target':target}).mappings().first()
        expected_title=file['title_id']
        if (not existing or existing['status']!='linked' or (file['media_id'] and existing['id']!=file['media_id']) or
            f"{existing['media_type']}:{existing['media_tmdb_id']}"!=expected_title or
            existing['season']!=file['season'] or existing['episode']!=file['episode'] or
            file_state(source,'source')!=file['state']['source'] or
            file_state(target,'target')[:2]!=file['state']['source'][:2]):
            raise ValueError('collection_target_changed')
        return {'key':file['key'],'state':'completed','recovered':True}
    library.validate([file])
    if jobs.db.execute('SELECT id FROM media_link WHERE target_path=:target AND id!=:id',{'target':target,'id':file['media_id'] or -1}).first():
        raise ValueError('collection_target_owned')
    current=next(f for f in library.files() if f['key']==file['key'])
    Path(target).parent.mkdir(parents=True,exist_ok=True)
    contained(target,library_root(),exists=False)
    change,payload=version_changes.prepare(conn,source,target,[])
    try:
        assert_mutation_lock()
        os.link(source,target)
        metadata={key:current.get(key) for key in ('media_type','media_tmdb_id','media_name','base_title','alt_name','year','season','episode')}
        annotation=current.get('identity')
        if annotation:
            identity=annotation['identity']
            metadata.update(media_type=identity['kind'],media_tmdb_id=identity['tmdb_id'],media_name=identity['title'],
                base_title=identity['title'],alt_name=identity.get('original_title'),original_language=identity.get('original_language'),
                year=int(identity['date'][:4]) if identity.get('date') else None)
        assert_mutation_lock()
        if file['media_id']:
            fingerprint=file_state(source,'source')
            conn.execute(text('''UPDATE media_link SET target_path=:target,target_path_hash=:hash,
                source_exists=1,target_exists=1,source_size=:size,target_size=:size,
                source_inode=:inode,target_inode=:inode,status='linked',reason='library_mapping_repair',
                updated_at=CURRENT_TIMESTAMP WHERE id=:id'''),
                {'target':target,'hash':hashlib.sha256(target.encode()).hexdigest(),'size':fingerprint[2],
                 'inode':fingerprint[1],'id':file['media_id']})
        else:
            upsert_media_link(None,source,target,**metadata,status='linked',reason='library_mapping_repair',_connection=conn)
        conn.execute(text("UPDATE media_version_change SET state='committed',updated_at=CURRENT_TIMESTAMP WHERE id=:id"),{'id':change})
        conn.commit()
    except BaseException:
        conn.rollback()
        assert_mutation_lock()
        version_changes.recover_one(conn,change,payload,False)
        raise
    version_changes.recover_one(conn,change,payload,True)
    return {'key':file['key'],'state':'completed'}


def process_subtitle(library,jobs,file,subtitle_agent=None,*,task_id=None):
    library.validate([file])
    from media_mcp.runtime.model_scope import assert_no_unresolved_subtitle
    assert_no_unresolved_subtitle(jobs.db,file,exclude_id=task_id)
    if subtitle_agent is None:
        from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
        subtitle_agent=SubtitleAgent(defer_ai_usage=True)
    path=file['source_path'] if file['state']['source'] else file['target_path']
    rows=jobs.db.execute("""SELECT id FROM media_link WHERE (source_path=:path OR target_path=:path)
        AND status IN ('linked','source_missing','target_missing')""",{'path':path}).mappings().all()
    if {row['id'] for row in rows}!={file['media_id']}:
        raise ValueError('collection_mapping_ambiguous')
    # Already hold the mutation lock; the agent releases/revalidates it for external I/O.
    summary=subtitle_agent._run_path_summary_locked(path,send_notify=False)
    counts={key:summary[key] for key in ('handled','media_count','sidecar_count','skipped','failed','missing','review') if type(summary.get(key)) is int}
    incomplete=summary.get('media_count')!=1 or not summary.get('handled') or summary.get('failed') or summary.get('missing') or summary.get('review')
    failure=getattr(subtitle_agent,'_last_model_error',None)
    if incomplete and failure is not None:raise failure
    return {'key':file['key'],'state':'needs_review' if incomplete else 'completed','summary':counts}


def process_task(jobs,job,subtitle_agent=None,analysis_client=None,analysis_probe=None):
    from media_mcp.platform.accounts import Accounts
    from media_mcp.platform.service import PlatformService
    from media_mcp.runtime import version_changes
    from media_mcp.storage.media import upsert_media_link
    records=Records(jobs.db)
    row=jobs.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_task' AND json_extract(data,'$.processing_key')=:key",{'key':job['delivery_key']}).mappings().first()
    if not row:
        raise ValueError('library_task_not_found')
    row=records.decode(row)
    if row['state'] in ('completed','completed_with_warnings','needs_review','failed'):
        return
    accounts=Accounts(jobs.db);actor=accounts.actor_by_id(row['data']['owner'])
    if not actor.can_manage_media:
        raise ValueError('media_management_permission_required')
    library=Collections(PlatformService(actor,accounts,records))
    def lease():
        if not jobs.db.execute("SELECT id FROM media_processing_job WHERE id=:id AND owner=:owner AND state='running' AND lease_until>CURRENT_TIMESTAMP",job).first():
            raise RuntimeError('media_job_lease_lost')
    lease()
    from media_mcp.runtime.recovery_coordinator import coordinate
    def recovery_guard():
        lease()
        if not accounts.actor_by_id(row['data']['owner']).can_manage_media:
            raise ValueError('media_management_permission_required')
    row=coordinate(records,row,library,analysis_client,analysis_probe,guard=recovery_guard)
    if row['state'] in ('completed','completed_with_warnings','needs_review','failed'):return
    lease()
    starting_data=dict(row['data'])
    if row['state']=='queued':starting_data.pop('error_code',None)
    row=records.update(row,'running',starting_data)
    data=row['data'];completed={item['key'] for item in data['results']}
    if data['action']=='auto':
        from media_mcp.application.library_auto import LibraryAuto
        LibraryAuto(library).process(jobs,row,recovery_guard,analysis_client,analysis_probe,subtitle_agent)
        return
    if data['action']=='analysis':
        from media_mcp.application.library_analysis import LibraryAnalysis
        kwargs={'client':analysis_client}
        if analysis_probe is not None:kwargs['probe']=analysis_probe
        LibraryAnalysis(library).process(row,recovery_guard,**kwargs)
        return
    if data['action']=='subtitles' and data.get('subtitle_inflight'):
        raise ValueError('automatic_subtitle_outcome_unknown')
    for file in data['files']:
        if file['key'] in completed:
            continue
        lease()
        if data['action']=='subtitles':
            data['subtitle_inflight']=file['key'];row=records.update(row,'running',data)
        try:
            with media_job_guard(lease),media_mutation_lock(jobs.db) as conn:
                # Permission changes and file changes after queueing both fail closed.
                fresh=accounts.actor_by_id(data['owner'])
                if not fresh.can_manage_media:
                    raise ValueError('media_management_permission_required')
                if data['action']=='mapping':
                    operation=next(op for op in data['operations'] if op['key']==file['key'])
                    result=repair_mapping(library,jobs,conn,file,operation)
                else:
                    if subtitle_agent is None:
                        from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
                        subtitle_agent=SubtitleAgent(defer_ai_usage=True)
                    result=process_subtitle(library,jobs,file,subtitle_agent,task_id=row['id'])
                assert_mutation_lock()
        except Exception as error:
            if str(error) in ('media_job_lease_lost','media_mutation_lock_lost','media_mutation_scope_invalidated'):
                raise
            from media_mcp.adapters.codex import CodexError
            if isinstance(error,CodexError):
                if not error.outcome_unknown:
                    data.pop('subtitle_inflight',None);row=records.update(row,'running',data)
                if retryable_model_error(error):raise ModelServiceDeferred(error.code) from error
                if error.outcome_unknown or error.code in PERMANENT_MODEL_ERRORS:raise
            code=getattr(error,'code',str(error) if isinstance(error,ValueError) else type(error).__name__)
            result={'key':file['key'],'state':'needs_review','error_code':code if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,100}',code) else type(error).__name__}
        lease()
        data.pop('subtitle_inflight',None)
        data['results'].append(result)
        row=records.update(row,'running',data)
    lease()
    state='completed_with_warnings' if data.get('blocked') or any(item['state']!='completed' for item in data['results']) else 'completed'
    records.update(row,state,data)


def record_failure(jobs, job, exc):
    from media_mcp.runtime.quota_wait import QuotaWaiting,next_quota_check,MAX_QUOTA_CHECKS,retain_quota_budget
    from media_mcp.runtime.session_recovery import SessionWaiting,now_text,SESSION_CHECK_SECONDS
    records=Records(jobs.db)
    value=jobs.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_task' AND json_extract(data,'$.processing_key')=:key",{'key':job['delivery_key']}).mappings().first()
    row=records.decode(value) if value else None
    previous=row['data'] if row else {}
    session=exc.recovery if isinstance(exc,SessionWaiting) else None
    if session is None and getattr(exc,'outcome_unknown',False) and getattr(exc,'code',None)!='rate_limited':
        ident=getattr(exc,'recovery_record_id',None)
        if ident:
            target=records.get(ident)['data']
            if target.get('ai_inflight') and target.get('analysis_thread') and target.get('analysis_turn') and not target.get('subtitle_inflight'):
                session={'record_id':ident,'checks':0,'state':'observing','observation':'original_turn_unknown','next_check_at':now_text(SESSION_CHECK_SECONDS)}
    underlying=exc.__cause__ if isinstance(exc,ModelServiceDeferred) else exc
    quota=isinstance(exc,QuotaWaiting) or getattr(underlying,'code',None)=='rate_limited' or getattr(exc,'cause',None)=='rate_limited'
    transport=isinstance(exc,ModelServiceDeferred) or retryable_model_error(exc)
    transport=bool(transport and not quota and session is None)
    retries=previous.get('transport_retry_count')
    if retries is None:
        # Old queue claim totals included quota/session observations. Only a
        # known prior transport failure can contribute to its conservative cap.
        from media_mcp.runtime.model_retry import RETRYABLE_MODEL_ERRORS
        failure=previous.get('model_failure') or {}
        retries=min(previous.get('model_retry_count',0),MAX_MODEL_RETRIES) if failure.get('code') in RETRYABLE_MODEL_ERRORS-{'rate_limited'} else 0
    retries+=int(transport)
    retry_model=quota or transport and retries<=MAX_MODEL_RETRIES
    candidate=getattr(exc,'cause',None) or getattr(exc,'code',str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
    if getattr(exc,'outcome_unknown',False):candidate='analysis_ai_outcome_unknown'
    wait=None
    if quota:
        wait=dict(exc.wait) if isinstance(exc,QuotaWaiting) else {'outcome_unknown':bool(getattr(underlying,'outcome_unknown',False)),
            'record_id':getattr(exc,'recovery_record_id',None) or (row['id'] if row else None),'checks':0,
            'next_check_at':getattr(underlying,'quota_next_check_at',None) or next_quota_check()}
        if not isinstance(exc,QuotaWaiting):
            wait=retain_quota_budget(records,previous,{**wait,'observation':'rate_limited'})
    exhausted=quota and wait.get('checks',0)>=MAX_QUOTA_CHECKS
    if quota:candidate='quota_checks_exhausted' if exhausted else 'model_quota_waiting'
    if exhausted:retry_model=False
    if session is not None:
        candidate='model_session_waiting';retry_model=True
    error=candidate if re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,100}',candidate) else type(exc).__name__
    if jobs.renew(job):
        if row:
            if error=='analysis_ai_outcome_unknown' and (row['data'].get('action')=='subtitles' or row['data'].get('analysis_progress',{}).get('phase')=='subtitles'):
                error='automatic_subtitle_outcome_unknown'
            quota_data={}
            if not retry_model:
                quota_data['terminal_notice_event']={'reason':error,'at':now_text()}
            if session is not None:quota_data['session_recovery']=session
            if quota:
                if exhausted:wait['next_check_at']=None
                elif not wait.get('next_check_at') or isinstance(exc,QuotaWaiting) and exc.checked and not wait.get('probe_reserved_at'):
                    wait['next_check_at']=next_quota_check()
                quota_data['quota_wait']=wait
                quota_data['quota_resume']=None
                if not isinstance(exc,QuotaWaiting) and wait.get('outcome_unknown'):
                    from media_mcp.runtime.recovery_coordinator import strong_request
                    detail=records.get(wait['record_id'])['data']
                    if strong_request(detail):
                        quota_data['session_recovery']={'record_id':wait['record_id'],'checks':0,
                            'state':'observing','next_check_at':now_text(SESSION_CHECK_SECONDS),
                            'independent_observation':True}
            unknown=bool(session is not None or (quota_data.get('quota_wait') or {}).get('outcome_unknown')
                or getattr(exc,'outcome_unknown',False) or error in {'analysis_ai_outcome_unknown','automatic_subtitle_outcome_unknown'})
            if not unknown:
                context=quota_data.get('quota_wait') or row['data'].get('quota_wait') or row['data'].get('session_recovery') or {}
                ident=getattr(exc,'recovery_record_id',None) or context.get('record_id') or row['id']
                try:
                    active=records.get(ident)['data']
                    unknown=bool(active.get('ai_inflight') or active.get('subtitle_inflight'))
                except ValueError:pass
            updated=records.update(row,'failed' if exhausted else ('queued' if retry_model else 'needs_review'),{**row['data'],**quota_data,'error_code':error,
                'model_retry_count':retries,'transport_retry_count':retries,
                'model_failure':{'code':error,'phase':getattr(exc.__cause__ if isinstance(exc,ModelServiceDeferred) else exc,'phase',None),
                    'outcome_unknown':unknown,
                    'terminal_observed':bool(getattr(exc.__cause__ if isinstance(exc,ModelServiceDeferred) else exc,'terminal_observed',False))},
                'analysis_progress':{**row['data'].get('analysis_progress',{}),'phase':'failed' if exhausted else ('waiting_session' if session is not None else ('waiting_quota' if quota else ('waiting_model' if retry_model else 'paused')))}})
            if not retry_model:
                from media_mcp.runtime.task_notifications import enqueue
                enqueue(records,updated,error)
    return error, retry_model


def retry_delay(jobs,job,error):
    """Use persisted independent deadlines, never total queue claims as retries."""
    if error is None:return None
    from datetime import datetime,timezone
    import math
    value=jobs.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_task' AND json_extract(data,'$.processing_key')=:key",{'key':job['delivery_key']}).mappings().first()
    if not value:return None
    data=Records.decode(value)['data'];deadlines=[]
    wait=data.get('quota_wait') or {};session=data.get('session_recovery') or {}
    if error in {'model_quota_waiting','model_session_waiting'}:
        if wait.get('next_check_at'):deadlines.append(wait['next_check_at'])
        independent=session.get('independent_observation') and session.get('record_id')==wait.get('record_id')
        if independent:
            source=Records(jobs.db).get(session['record_id'])
            independent=bool(source['data'].get('ai_inflight'))
        if (error=='model_session_waiting' or independent) and session.get('state','observing')=='observing' and session.get('next_check_at'):
            deadlines.append(session['next_check_at'])
        if deadlines:
            due=min(datetime.strptime(v,'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc) for v in deadlines)
            return max(0,math.ceil((due-datetime.now(timezone.utc)).total_seconds()))
        return 60 if error=='model_session_waiting' else 7200
    from media_mcp.runtime.model_retry import RETRYABLE_MODEL_ERRORS
    if error in RETRYABLE_MODEL_ERRORS:
        return min(3600,30*2**min(data.get('transport_retry_count',1),7))
    return None


def run_library_worker():
    jobs=MediaJobs();jobs.reset_after_fork();jobs.initialize()
    while True:
        heartbeat('library')
        job=jobs.claim('library')
        if not job:
            time.sleep(2);continue
        done=threading.Event()
        def renew():
            while not done.wait(20):
                try:
                    if not jobs.renew(job):os._exit(1)
                    heartbeat('library')
                except Exception:os._exit(1)
        thread=threading.Thread(target=renew,daemon=True);thread.start()
        error=None
        retry_model=False
        try:
            process_task(jobs,job)
        except Exception as exc:
            error,retry_model=record_failure(jobs,job,exc)
        finally:
            done.set();thread.join(timeout=2)
        jobs.finish(job,error=error,review_required=bool(error) and not retry_model,result=json.dumps({'error':error}),
            retry_delay_seconds=retry_delay(jobs,job,error) if retry_model else None)
        heartbeat('library')
