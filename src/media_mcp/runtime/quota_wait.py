"""Durable two-hour quota checks; unknown submissions are observation-only."""
from datetime import datetime, timezone, timedelta

QUOTA_CHECK_SECONDS = 2 * 60 * 60
MAX_QUOTA_CHECKS = 10


class QuotaWaiting(RuntimeError):
    code = 'model_quota_waiting'
    def __init__(self, wait):
        self.wait = wait
        super().__init__(self.code)


def next_quota_check():
    return (datetime.now(timezone.utc) + timedelta(seconds=QUOTA_CHECK_SECONDS)).strftime('%Y-%m-%d %H:%M:%S')


def check_quota_wait(records, row, client=None, guard=lambda: None):
    wait = row['data'].get('quota_wait')
    if not wait:
        return row
    guard()
    if client is None:
        from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient
        client = LibraryAnalysisClient(timeout=30, max_retries=0)
    wait = dict(wait)
    wait['checks'] = wait.get('checks', 0) + 1
    if wait.get('outcome_unknown'):
        # A successful probe cannot prove the outcome of an earlier submission.
        target = records.get(wait.get('record_id') or row['id'])
        data = target['data']
        thread, turn = data.get('analysis_thread'), data.get('analysis_turn')
        if not thread or not turn or data.get('subtitle_inflight'):
            wait['observation'] = 'submission_identity_unavailable'
            raise QuotaWaiting(wait)
        try:
            result = client.read_thread(thread)
            guard()
        except Exception as error:
            if str(error)=='media_job_lease_lost':raise
            wait['observation'] = 'original_turn_unavailable'
            raise QuotaWaiting(wait) from error
        observed = result.get('thread') or {}
        match = next((t for t in observed.get('turns', []) if t.get('id') == turn), None)
        if observed.get('id') != thread or not match or match.get('status') not in ('failed', 'interrupted'):
            wait['observation'] = 'completed_requires_reconciliation' if match and match.get('status') == 'completed' else 'original_turn_not_terminal'
            raise QuotaWaiting(wait)
        # Only a matching failed/interrupted research turn establishes safe replay.
        proof={'thread': thread, 'turn': turn, 'status': match['status']}
        if not data.get('ai_inflight') and data.get('quota_terminal_observation') != proof:
            wait['observation'] = 'submission_state_changed'
            raise QuotaWaiting(wait)
        guard()
        if data.get('ai_inflight'):
            target = records.update(target, target['state'], {**data, 'ai_inflight': False,
                'quota_terminal_observation': proof})
        if target['id'] == row['id']:
            row = target
        wait['outcome_unknown'] = False
    try:
        guard()
        client.check_connection()
        guard()
    except Exception as error:
        if str(error)=='media_job_lease_lost':raise
        from media_mcp.runtime.model_retry import PERMANENT_MODEL_ERRORS
        if getattr(error, 'code', '') in PERMANENT_MODEL_ERRORS:
            raise
        wait['observation'] = 'probe_not_ready'
        raise QuotaWaiting(wait) from error
    guard()
    data = dict(row['data'])
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
