"""Durable two-hour quota checks; unknown submissions are observation-only."""
from datetime import datetime, timezone, timedelta

QUOTA_CHECK_SECONDS = 2 * 60 * 60
MAX_QUOTA_CHECKS = 10


class QuotaWaiting(RuntimeError):
    code = 'model_quota_waiting'
    def __init__(self, wait, *, checked=True):
        self.wait = wait
        self.checked = checked
        super().__init__(self.code)


def next_quota_check(at=None):
    base=datetime.strptime(at,'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc) if at else datetime.now(timezone.utc)
    return (base + timedelta(seconds=QUOTA_CHECK_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')


def retain_quota_budget(records, data, wait):
    """Carry the same work's budget until it produces accepted progress."""
    resume = data.get('quota_resume') or {}
    if (resume.get('record_id') == wait.get('record_id')
            and resume.get('completed') == len(data.get('results', []))):
        target = records.get(wait['record_id'])
        if len(target['data'].get('analysis_decisions', [])) <= resume.get('accepted_count', 0):
            return {**resume['wait'], **wait, 'checks': resume['wait'].get('checks', 0)}
    return wait


def check_quota_wait(records, row, client=None, guard=lambda: None):
    wait = row['data'].get('quota_wait')
    if not wait:
        return row
    guard()
    if client is None:
        from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient
        from media_mcp.storage.model_settings import ModelSettings
        target=records.get(wait.get('record_id') or row['id'])
        policy=target['data'].get('analysis_policy') or ModelSettings(records.db).get()
        client = LibraryAnalysisClient(timeout=30, max_retries=0,model=policy['model'],reasoning_effort=policy['effort'])
    wait = dict(wait)
    if wait.get('checks',0)>=MAX_QUOTA_CHECKS:
        raise QuotaWaiting(wait,checked=False)
    wait['checks'] = wait.get('checks', 0) + 1
    # Quota availability and an earlier request's outcome are independent.
    # Never clear unknown flags here; LibraryAnalysis reconciles that request
    # under its file snapshot, generation and worker lease before any new turn.
    if wait.get('observation') in {'original_turn_unavailable', 'original_turn_not_terminal',
                                  'submission_identity_unavailable', 'completed_requires_reconciliation'}:
        wait.setdefault('legacy_observation_checks', wait.get('checks', 1) - 1)
    # Reserve the finite budget and next deadline before external I/O. A crash
    # cannot erase an attempted check or cause an immediate duplicate probe.
    from media_mcp.runtime.session_recovery import now_text
    wait.update(probe_attempts=wait.get('probe_attempts',0)+1,probe_inflight=True,
                probe_reserved_at=now_text(),next_check_at=next_quota_check(),observation='probe_started')
    guard();row=records.update(row,row['state'],{**row['data'],'quota_wait':wait})
    try:
        guard()
        client.check_connection()
        guard()
    except Exception as error:
        if str(error)=='media_job_lease_lost':raise
        from media_mcp.adapters.codex import error_code
        wait['probe_inflight']=False
        wait['actual_probe_checks']=wait.get('actual_probe_checks',0)+1
        wait['probe_error_code'] = error_code(error)
        wait['observation'] = 'rate_limited' if getattr(error, 'code', '') == 'rate_limited' else 'probe_unavailable'
        guard();records.update(row,row['state'],{**row['data'],'quota_wait':wait})
        from media_mcp.runtime.model_retry import PERMANENT_MODEL_ERRORS
        if getattr(error, 'code', '') in PERMANENT_MODEL_ERRORS:raise
        raise QuotaWaiting(wait) from error
    guard()
    data = dict(row['data'])
    wait['probe_inflight']=False
    wait['actual_probe_checks']=wait.get('actual_probe_checks',0)+1
    wait.pop('probe_error_code',None)
    wait['observation']='quota_available'
    data['quota_history'] = data.get('quota_history', []) + [dict(wait)]
    target=records.get(wait.get('record_id') or row['id'])
    data['quota_resume']={'wait':wait,'record_id':target['id'],
        'completed':len(data.get('results',[])),
        'accepted_count':len(target['data'].get('analysis_decisions',[])),
        'input_digest':(target['data'].get('analysis_request') or {}).get('binding',{}).get('input_digest')}
    from media_mcp.application.collections import digest
    data['quota_resume']['failure_key']=digest(target['data'].get('last_model_failure') or {})
    data.pop('quota_wait', None)
    data.pop('error_code', None)
    return records.update(row, 'queued', data)


def schedule_existing_quota_task(records, task_id, actor):
    """Enroll a stopped quota task without clearing its unknown submission fence."""
    import json
    from sqlalchemy import text
    from media_mcp.application.collections import digest
    row = records.get(task_id, 'library_task')
    data = row['data']
    if not actor.can_manage_media or data['owner'] != actor.id:
        raise ValueError('media_management_permission_required')
    if row['state'] != 'needs_review':
        raise ValueError('quota_task_not_stopped')
    target = row
    if data.get('action') == 'auto':
        target = records.by_key(digest(['library-auto-item', row['id'], data.get('next_work', 0)]))
    failure = (target or {}).get('data', {}).get('last_model_failure', {})
    if failure.get('code') != 'rate_limited':
        raise ValueError('quota_failure_not_verified')
    wait = {'record_id': target['id'], 'outcome_unknown':bool(failure.get('outcome_unknown')),
            'checks':0, 'next_check_at':next_quota_check()}
    updated = {**data, 'quota_wait':wait, 'error_code':'model_quota_waiting',
               'analysis_progress':{**data.get('analysis_progress', {}), 'phase':'waiting_quota'}}
    with records.db.begin() as conn:
        job = conn.execute(text("SELECT id,state FROM media_processing_job WHERE delivery_key=:key AND stage='library'"), {'key':data['processing_key']}).mappings().one()
        if job['state'] != 'needs_review':
            raise ValueError('quota_task_not_stopped')
        count = conn.execute(text("UPDATE media_mcp_record SET data=:data,state='queued',revision=revision+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id AND revision=:revision AND state='needs_review'"),
                             {'data':json.dumps(updated,ensure_ascii=False),'id':row['id'],'revision':row['revision']}).rowcount
        if count != 1:
            raise RuntimeError('stale_job_revision')
        conn.execute(text("UPDATE media_processing_job SET state='retry',next_attempt_at=datetime('now','+7200 seconds'),updated_at=CURRENT_TIMESTAMP WHERE id=:id AND state='needs_review'"), {'id':job['id']})
    return records.get(task_id)
