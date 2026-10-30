"""Independent session observations and quota deadlines under one owned job lease."""
from media_mcp.application.collections import digest
from media_mcp.runtime.quota_wait import QuotaWaiting,check_quota_wait,next_quota_check,retain_quota_budget
from media_mcp.runtime.session_recovery import SessionWaiting,ResearchRequired,recover_analysis,now_text


def modern_request(data):
    request=data.get('analysis_request') or {}
    return bool(data.get('action')=='analysis' and data.get('owner')
                and data.get('analysis_thread') and data.get('analysis_turn')
                and not data.get('subtitle_inflight') and request.get('payload') and request.get('binding'))


def strong_request(data):
    return bool(data.get('ai_inflight') and modern_request(data))


def restore_wait_checkpoint(records,row,guard):
    """Cover a crash after the file failure checkpoint but before parent retry."""
    parent=row['data'];target=row
    if parent.get('action')=='auto':
        target=records.by_key(digest(['library-auto-item',row['id'],parent.get('next_work',0)]))
    if not target:return row
    data=target['data'];failure=data.get('last_model_failure') or {}
    if failure.get('code')!='rate_limited' or not modern_request(data):return row
    if data.get('owner')!=parent.get('owner'):raise ValueError('analysis_recovery_identity_mismatch')
    request=data['analysis_request'];keys={f['key'] for f in request['payload']['requested_files']}
    if not data.get('ai_inflight') and (data.get('analysis_plan_id') or keys<={v['key'] for v in data.get('analysis_decisions',[])}):return row
    resume=parent.get('quota_resume') or {}
    if resume.get('record_id')==target['id'] and resume.get('failure_key')==digest(failure):return row
    if (failure.get('thread')!=data['analysis_thread'] or failure.get('turn')!=data['analysis_turn']
        or failure.get('generation')!=data.get('analysis_generation',0)
        or failure.get('input_digest')!=request['binding'].get('input_digest')):return row
    if not failure.get('at') or failure.get('quota_next_check_at')!=next_quota_check(failure['at']):
        raise ValueError('quota_checkpoint_requires_review')
    wait={'record_id':target['id'],'checks':0,'outcome_unknown':bool(data.get('ai_inflight')),
          'next_check_at':failure['quota_next_check_at'],'observation':'rate_limited'}
    wait=retain_quota_budget(records,parent,wait)
    guard()
    return records.update(row,row['state'],{**parent,'quota_wait':wait,'quota_resume':None,
        'quota_history':parent.get('quota_history',[])+[{**wait,'observation':'quota_wait_restored_from_checkpoint'}]})


def coordinate(records,row,library,client=None,probe=None,guard=lambda:None):
    wait=row['data'].get('quota_wait')
    if not wait:
        row=restore_wait_checkpoint(records,row,guard)
        wait=row['data'].get('quota_wait')
        if not wait:return row
    wait=dict(wait);session=None
    target=records.get(wait.get('record_id') or row['id'])
    data=target['data']
    requested={f['key'] for f in (data.get('analysis_request') or {}).get('payload',{}).get('requested_files',[])}
    accepted={f['key'] for f in data.get('analysis_decisions',[])}
    already_accepted=bool(requested and requested<=accepted and not data.get('ai_inflight'))
    eligible=strong_request(data) or data.get('recovered_analysis_turn') or already_accepted
    if wait.get('outcome_unknown') and modern_request(data) and eligible:
        if data['owner']!=row['data']['owner']:
            raise ValueError('analysis_recovery_identity_mismatch')
        if row['data'].get('action')=='auto':
            expected=records.by_key(digest(['library-auto-item',row['id'],row['data'].get('next_work',0)]))
            if not expected or expected['id']!=target['id']:raise ValueError('analysis_recovery_identity_mismatch')
        elif target['id']!=row['id']:
            raise ValueError('analysis_recovery_identity_mismatch')
        request=data['analysis_request'];binding=request['binding']
        from media_mcp.application.library_analysis import manifest,LibraryAnalysis
        guard();library.validate(data['files'])
        if (digest(request['payload'])!=binding.get('input_digest') or digest(data['files'])!=binding.get('files_digest')
            or not data.get('analysis_roots') or digest(manifest(data['analysis_roots']))!=binding.get('manifest_digest')
            or request.get('generation',0)!=data.get('analysis_generation',0)
            or data.get('analysis_policy')!=binding.get('policy')):
            raise ValueError('analysis_recovery_input_changed')
        if client is None:
            from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient
            policy=data['analysis_policy'];client=LibraryAnalysisClient(timeout=30,max_retries=0,
                model=policy['model'],reasoning_effort=policy['effort'])
        before=len(data.get('analysis_decisions',[]));prior_plan=data.get('analysis_plan_id')
        completed=(data.get('recovered_analysis_turn') or {}).get('turn')
        if data.get('ai_inflight'):
            try:
                target,completed=recover_analysis(records,target,client,guard,binding,
                    [f['key'] for f in request['payload']['requested_files']])
            except SessionWaiting as error:
                session=error;completed=None;target=records.get(target['id'])
        observed_recovery=dict(target['data'].get('session_recovery') or {})
        if completed:
            kwargs={'client':client,'allow_new_research':False}
            if probe is not None:kwargs['probe']=probe
            try:LibraryAnalysis(library).process(target,guard,**kwargs)
            except ResearchRequired:pass
            target=records.get(target['id'])
        guard();row=records.get(row['id']);parent=dict(row['data']);detail=target['data']
        recovery={**(detail.get('session_recovery') or observed_recovery or {'state':'recovered'}),'record_id':target['id'],'independent_observation':True}
        if session:session.recovery=recovery
        parent['session_recovery']=recovery
        if not detail.get('ai_inflight'):
            wait['outcome_unknown']=False
            wait['original_request_state']=recovery.get('state','reconciled')
        progress=already_accepted or len(detail.get('analysis_decisions',[]))>before or bool(detail.get('analysis_plan_id') and detail.get('analysis_plan_id')!=prior_plan)
        if (completed or already_accepted) and progress and not detail.get('ai_inflight'):
            # Reconciliation is real accepted work, not an availability probe.
            parent['quota_history']=parent.get('quota_history',[])+[{**wait,'observation':'original_completed_reconciled'}]
            parent.pop('quota_wait',None);parent.pop('error_code',None);parent['quota_resume']=None
            if parent.get('model_failure'):
                parent.setdefault('model_failure_history',[]).append(parent.pop('model_failure'))
            row=records.update(row,row['state'],parent)
            return row
        parent['quota_wait']=wait
        row=records.update(row,row['state'],parent)
    if (wait.get('next_check_at') or '')>now_text():
        if session:raise session
        raise QuotaWaiting(wait,checked=False)
    try:row=check_quota_wait(records,row,client,guard)
    except QuotaWaiting as error:
        if not session:raise
        # The probe already persisted its budget and next deadline. Session
        # polling uses its own saved deadline without rewriting the quota wait.
        raise session from error
    if session:raise session
    return row
