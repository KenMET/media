"""Read-only cross-run fencing for unresolved research over identical video bytes."""
import json


def assert_no_unresolved_analysis(database, files, *, exclude_id, owner=None, client=None, guard=lambda:None, partial=False):
    current={tuple(f['state'].get('source') or f['state'].get('target') or ()) for f in files}
    current.discard(())
    rows=database.execute("""SELECT * FROM media_mcp_record
        WHERE kind IN ('library_task','library_auto_item') AND id<>:exclude
          AND (json_extract(data,'$.ai_inflight')=1 OR
               EXISTS (SELECT 1 FROM json_each(data,'$.analysis_request_history') history
                       WHERE json_extract(history.value,'$.status')='unknown'))
          LIMIT 129""",{'exclude':exclude_id}).mappings().all()
    if len(rows)>128:
        raise ValueError('analysis_ai_outcome_unknown')
    blocked=set()
    for row in rows:
        data=json.loads(row['data'])
        if not data.get('ai_inflight') and not any(h.get('status')=='unknown' for h in data.get('analysis_request_history',[])):
            continue
        request=data.get('analysis_request') or {}
        payload=request.get('payload') or {}
        from media_mcp.application.collections import digest
        bound=bool(payload and digest(payload)==request.get('binding',{}).get('input_digest'))
        active_keys={f['key'] for f in payload.get('requested_files',[])} if bound else None
        scope=set(active_keys or []) if data.get('ai_inflight') else set()
        exact=not data.get('ai_inflight') or active_keys is not None
        for history in data.get('analysis_request_history',[]):
            if history.get('status')!='unknown':continue
            keys=history.get('requested_keys')
            if keys is None and bound and history.get('binding',{}).get('input_digest')==request.get('binding',{}).get('input_digest'):
                keys=active_keys
            if keys is None:exact=False
            else:scope.update(keys)
        accepted={item['key'] for item in data.get('analysis_decisions',[])}
        affected=set()
        for file in data.get('files',[]):
            if file['key'] in accepted:continue
            if exact and file['key'] not in scope:continue
            state=file.get('state',{})
            fingerprint=tuple(state.get('source') or state.get('target') or ())
            if fingerprint and fingerprint in current:
                affected.update(f['key'] for f in files if tuple(f['state'].get('source') or f['state'].get('target') or ())==fingerprint)
        if affected and not observe_terminal(database,row,data,owner,client,guard):blocked.update(affected)
    if blocked and not partial:raise ValueError('analysis_ai_outcome_unknown')
    return blocked


def observe_terminal(database,row,data,owner,client,guard):
    """Reconcile a stale cross-run marker only from its exact terminal turn."""
    if (not callable(getattr(client,'recover_thread',None)) or not owner or data.get('action')!='analysis' or data.get('owner')!=owner
        or row['state'] in ('running','queued') or data.get('subtitle_inflight')
        or any(h.get('status')=='unknown' for h in data.get('analysis_request_history',[]))):return False
    thread,turn=data.get('analysis_thread'),data.get('analysis_turn')
    if not thread or not turn:return False
    from media_mcp.adapters.codex import CodexError
    from media_mcp.storage.records import Records
    from media_mcp.runtime.session_recovery import now_text
    guard()
    try:observed=client.recover_thread(thread).get('thread') or {}
    except CodexError:return False
    guard();turns=observed.get('turns') or []
    if (observed.get('id')!=thread or len(turns)!=1 or turns[0].get('id')!=turn
        or turns[0].get('status') not in ('completed','failed','interrupted')):return False
    data={**data,'ai_inflight':False,'analysis_request_history':data.get('analysis_request_history',[])+[
        {'thread':thread,'turn':turn,'status':turns[0]['status'],'at':now_text(),
         'generation':data.get('analysis_generation',0),'observation':'cross_run_terminal_confirmed'}]}
    Records(database).update(Records.decode(row),row['state'],data)
    return True


def assert_no_unresolved_subtitle(database, file, *, exclude_id):
    state=file.get('state',{})
    current=tuple(state.get('source') or state.get('target') or ())
    if not current:return
    rows=database.execute("""SELECT id,state,data FROM media_mcp_record
        WHERE kind IN ('library_task','library_auto_item') AND id<>:exclude
          AND json_extract(data,'$.subtitle_inflight') IS NOT NULL LIMIT 129""",
          {'exclude':exclude_id or ''}).mappings().all()
    if len(rows)>128:raise ValueError('prior_subtitle_outcome_unknown')
    for row in rows:
        data=json.loads(row['data']);key=data.get('subtitle_inflight')
        # This code is emitted only after process_subtitle returned. Older
        # workers forgot to clear the marker before recording that review.
        if row['state']=='completed' and any(result.get('key')==key and result.get('error_code')=='automatic_subtitle_review'
               for result in data.get('auto_results',[])):continue
        for previous in data.get('files',[]):
            if previous['key']!=key:continue
            prior=previous.get('state',{})
            if tuple(prior.get('source') or prior.get('target') or ())==current:
                raise ValueError('prior_subtitle_outcome_unknown')
