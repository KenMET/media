"""Archive only Media research turns whose accepted result is durably checkpointed."""
import json
import time
from media_mcp.storage.records import Records
from media_mcp.application.collections import digest


def archive_intent(data, requested_keys, terminal_status='completed'):
    thread,turn=data.get('analysis_thread'),data.get('analysis_turn')
    if not thread or not turn:return None
    return {'key':digest(['media-research-archive',thread,turn]),'thread':thread,'turn':turn,
            'generation':data.get('analysis_generation',0),'requested_keys':list(requested_keys),
            'terminal_status':terminal_status}


def proven(data,intent):
    expected=intent.get('terminal_status','completed')
    if expected=='completed':
        requested=set(intent.get('requested_keys') or [])
        return bool(requested and requested<={v['key'] for v in data.get('analysis_decisions',[])})
    return expected in {'failed','interrupted','failed_or_interrupted'} and any(
        h.get('thread')==intent['thread'] and h.get('turn')==intent['turn'] and
        h.get('generation',0)==intent.get('generation',0) and h.get('status')==expected and
        (expected!='failed_or_interrupted' or h.get('terminal_observed'))
        for h in data.get('analysis_request_history',[]))


def enqueue(records, source, intent):
    from sqlalchemy.exc import IntegrityError
    data=source['data']
    if source['kind'] not in ('library_task','library_auto_item') or data.get('action')!='analysis' or not data.get('owner'):
        return False
    if not intent or intent['key']!=digest(['media-research-archive',intent['thread'],intent['turn']]):return False
    if not proven(data,intent):return False
    if data.get('ai_inflight') and data.get('analysis_thread')==intent['thread']:return False
    if any(h.get('thread')==intent['thread'] and h.get('status')=='unknown' for h in data.get('analysis_request_history',[])):return False
    if records.by_key(intent['key']):return True
    try:records.put('library_thread_gc',{**intent,'source_id':source['id'],'owner':data['owner'],
                    'attempts':0,'next_attempt_at':0},'pending',key_hash=intent['key'])
    except IntegrityError:
        if not records.by_key(intent['key']):raise
    return True


def drain(records=None,client=None,clock=time.time,limit=1):
    records=records or Records()
    # Explicit intents are committed with accepted chunks; never infer ownership
    # from a title, list position, or an arbitrary completed Codex conversation.
    missing=records.db.execute("""SELECT r.id AS source_id,i.value AS intent
        FROM media_mcp_record r,json_each(r.data,'$.thread_archive_intents') i
        LEFT JOIN media_mcp_record q ON q.key_hash=json_extract(i.value,'$.key')
        WHERE r.kind IN ('library_task','library_auto_item') AND q.id IS NULL LIMIT 5""").mappings().all()
    for value in missing:enqueue(records,records.get(value['source_id']),json.loads(value['intent']))
    pending=records.db.execute("""SELECT * FROM media_mcp_record WHERE kind='library_thread_gc'
        AND state IN ('pending','retry','archiving') AND COALESCE(json_extract(data,'$.next_attempt_at'),0)<=:now
        ORDER BY created_at LIMIT :limit""",{'now':clock(),'limit':limit}).mappings().all()
    if pending and client is None:
        from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient
        client=LibraryAnalysisClient(timeout=10,max_retries=0)
    for value in pending:
        row=records.decode(value);data=row['data'];source=records.get(data['source_id']);original=source['data']
        if (original.get('ai_inflight') and original.get('analysis_thread')==data['thread'] or
            any(h.get('thread')==data['thread'] and h.get('status')=='unknown' for h in original.get('analysis_request_history',[]))):
            records.update(row,'held',{**data,'reason':'request_outcome_unknown'});continue
        if original.get('owner')!=data['owner'] or not proven(original,data):
            records.update(row,'held',{**data,'reason':'accepted_request_identity_changed'});continue
        data={**data,'attempts':data['attempts']+1,'next_attempt_at':clock()+60}
        try:row=records.update(row,'archiving',data)
        except RuntimeError:continue
        try:
            thread=client.recover_thread(data['thread']).get('thread') or {}
            turns=thread.get('turns') or []
            expected=data.get('terminal_status','completed')
            statuses={'failed','interrupted'} if expected=='failed_or_interrupted' else {expected}
            if thread.get('id')!=data['thread'] or len(turns)!=1 or turns[0].get('id')!=data['turn'] or turns[0].get('status') not in statuses:
                records.update(row,'held',{**data,'reason':'not_the_single_completed_media_turn'});continue
            client.archive_thread(data['thread'])
        except Exception as error:
            code=getattr(error,'code','archive_unavailable')
            records.update(row,'unavailable' if code=='thread_unavailable' else 'retry',
                           {**data,'reason':code if code in {'thread_unavailable','thread_not_loaded','connection_failed','model_timeout'} else 'archive_unavailable'})
            continue
        records.update(row,'archived',{**data,'next_attempt_at':None})
