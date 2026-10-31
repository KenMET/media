"""Persistent, deduplicated terminal notification intents with retryable delivery."""
import time
from media_mcp.storage.records import Records

REASONS={
    'quota_checks_exhausted':'The limit of 10 recovery checks was reached. The task stopped because it cannot safely continue.',
    'session_recovery_requires_review':'Some file sessions cannot be safely recovered. Automatic replacement for these files has stopped.',
    'analysis_ai_outcome_unknown':'The identification outcome is unknown. The task is paused without resubmission.',
    'automatic_subtitle_outcome_unknown':'The subtitle request outcome is unknown. The task is paused without resubmission.',
    'token_rejected':'Model service authentication is invalid. The task is paused.',
    'login_required':'The model service requires login. The task is paused.',
}


def enqueue(records, row, reason):
    from media_mcp.application.collections import digest
    from sqlalchemy.exc import IntegrityError
    if row['kind']!='library_task':
        raise ValueError('notification_requires_root_task')
    key=digest(['library-terminal-notice',row['id'],reason])
    if not records.by_key(key):
        try:records.put('library_notice',{'task_id':row['id'],'reason':reason,
                    'label':str(row['data'].get('label') or 'Media organization task')[:200],
                    'completed':len(row['data'].get('results',[])),
                    'total':row['data'].get('total',len(row['data'].get('files',[]))),
                    'attempts':0,'next_attempt_at':0},'pending',key_hash=key)
        except IntegrityError:
            if not records.by_key(key):raise
    if row['data'].get('terminal_notice')!=key:
        try:records.update(row,row['state'],{**row['data'],'terminal_notice':key})
        except RuntimeError:pass


def deliver(records=None, sender=None, clock=time.time):
    from media_mcp.adapters.notify import send_notification
    records=records or Records();sender=sender or send_notification
    # Reconcile a crash after recording the terminal task but before enqueuing
    # its notification. The marker is written only after the intent exists.
    stopped=records.db.execute("""SELECT * FROM media_mcp_record
        WHERE kind='library_task' AND state IN ('failed','needs_review','completed_with_warnings')
          AND json_extract(data,'$.terminal_notice_event.reason') IS NOT NULL
          AND json_extract(data,'$.terminal_notice') IS NULL LIMIT 20""").mappings().all()
    for value in stopped:
        row=records.decode(value);enqueue(records,row,row['data']['terminal_notice_event']['reason'])
    rows=records.db.execute("SELECT * FROM media_mcp_record WHERE kind='library_notice' AND state IN ('pending','sending') ORDER BY created_at LIMIT 20").mappings().all()
    for value in rows:
        row=records.decode(value);data=row['data']
        if data.get('next_attempt_at',0)>clock():continue
        data={**data,'attempts':data.get('attempts',0)+1,'next_attempt_at':clock()+60}
        try:row=records.update(row,'sending',data)
        except RuntimeError:continue
        try:
            sent=bool(sender('Media task needs attention',
                f"{data.get('label') or 'Media organization task'}: saved {data['completed']}/{data['total']} items. "
                f"{REASONS.get(data['reason'],'Automatic processing stopped. See the task page for details.')}"
                f" Existing results are preserved. Task {data['task_id']}."))
        except Exception:sent=False
        try:records.update(row,'delivered' if sent else 'pending',data)
        except RuntimeError:
            # An operator may have suppressed an intent while its HTTP delivery
            # was in flight. Never restore or overwrite that newer decision.
            continue
