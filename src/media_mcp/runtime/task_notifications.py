"""Persistent, deduplicated terminal notification intents with retryable delivery."""
import time
from media_mcp.storage.records import Records

REASONS={
    'quota_checks_exhausted':'已达到 10 次恢复检查上限，仍无法安全继续，任务已停止。',
    'session_recovery_requires_review':'部分文件的会话仍无法安全恢复，已停止这些文件的自动替代。',
    'analysis_ai_outcome_unknown':'识别请求结果尚未确认，任务已暂停，未重复提交。',
    'automatic_subtitle_outcome_unknown':'字幕请求结果尚未确认，任务已暂停，未重复提交。',
    'token_rejected':'模型服务认证失效，任务已暂停。',
    'login_required':'模型服务需要重新登录，任务已暂停。',
}


def enqueue(records, row, reason):
    from media_mcp.application.collections import digest
    from sqlalchemy.exc import IntegrityError
    if row['kind']!='library_task':
        raise ValueError('notification_requires_root_task')
    key=digest(['library-terminal-notice',row['id'],reason])
    if not records.by_key(key):
        try:records.put('library_notice',{'task_id':row['id'],'reason':reason,
                    'label':str(row['data'].get('label') or '媒体整理任务')[:200],
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
            sent=bool(sender('Media 任务需要关注',
                f"{data.get('label') or '媒体整理任务'}：已保存 {data['completed']}/{data['total']} 项。"
                f"{REASONS.get(data['reason'],'任务已停止自动处理，请在任务页查看具体原因。')}"
                f"已有成果保留。任务 {data['task_id']}。"))
        except Exception:sent=False
        try:records.update(row,'delivered' if sent else 'pending',data)
        except RuntimeError:
            # An operator may have suppressed an intent while its HTTP delivery
            # was in flight. Never restore or overwrite that newer decision.
            continue
