"""Durable observation and single replacement of side-effect-free library research."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta

MAX_SESSION_CHECKS = 3
SESSION_CHECK_SECONDS = 60


def now_text(offset=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset)).strftime('%Y-%m-%d %H:%M:%S')


class SessionWaiting(RuntimeError):
    code = 'model_session_waiting'
    def __init__(self, recovery):
        self.recovery = recovery
        super().__init__(self.code)


class ResearchRequired(RuntimeError):
    """Read-only reconciliation reached a boundary requiring a new model call."""


def recover_analysis(records, row, client, guard, binding, requested_keys=None):
    """Caller validates frozen files/manifest before entry and before accepting output.

    Keep the old unknown request as an immutable history entry. CAS and the worker
    lease fence every write; an execution generation also fences future plan use.
    A missing rollout permits one replacement, never a still-running request.
    """
    from media_mcp.adapters.codex import CodexError
    data = deepcopy(row['data'])
    active = data.get('analysis_request')
    if active and active['binding'] != binding:
        raise ValueError('analysis_recovery_input_changed')
    recovery = dict(data.get('session_recovery') or {})
    identity={'thread':data.get('analysis_thread'),'turn':data.get('analysis_turn'),
              'generation':data.get('analysis_generation',0)}
    previous_identity=recovery.get('identity')
    if (previous_identity is not None and previous_identity!=identity or
        previous_identity is None and recovery.get('state') in ('recovered','replaced')):
        data.setdefault('session_recovery_history',[]).append(recovery)
        recovery={}
    recovery['identity']=identity
    if (recovery.get('next_check_at') or '') > now_text():
        raise SessionWaiting(recovery)
    thread, turn = data.get('analysis_thread'), data.get('analysis_turn')
    if not thread or not turn or data.get('subtitle_inflight'):
        raise ValueError('analysis_ai_outcome_unknown')
    guard()
    recovery.setdefault('checks',0)
    recovery.update(observations=recovery.get('observations',0)+1,record_id=row['id'])
    result = None
    try:
        result = client.recover_thread(thread)
        guard()
        observed = result.get('thread') or {}
        if observed.get('id') != thread:
            raise ValueError('analysis_recovery_identity_mismatch')
        match = next((t for t in observed.get('turns', []) if t.get('id') == turn), None)
        if not match:
            raise ValueError('analysis_recovery_turn_missing')
        status = match.get('status')
        if status not in ('completed', 'failed', 'interrupted', 'inProgress'):
            raise ValueError('analysis_recovery_status_unknown')
        recovery['observation'] = 'original_turn_' + status
    except CodexError as error:
        if error.code not in {'thread_unavailable', 'thread_not_loaded', 'connection_failed',
                              'app_server_unreachable', 'model_timeout', 'model_upstream_unavailable'}:
            raise
        status = 'unavailable'
        recovery['checks']+=1
        recovery['observation'] = error.code
    history = list(data.get('analysis_request_history', []))
    generation = data.get('analysis_generation', 0)
    def stop(reason):
        recovery.update(state='needs_review',next_check_at=None)
        data['session_recovery']=recovery
        guard();records.update(row,row['state'],data)
        raise ValueError(reason)
    if status in ('completed', 'failed', 'interrupted'):
        history.append({'thread': thread, 'turn': turn, 'status': status,
                        'generation': generation, 'binding': binding, 'requested_keys':requested_keys,'at': now_text()})
        data.update(ai_inflight=False, analysis_request_history=history)
        if status == 'completed':
            data['recovered_analysis_turn'] = {'binding': binding, 'turn': match}
        else:
            from media_mcp.runtime.thread_cleanup import archive_intent
            intent=archive_intent(data,requested_keys or [],status)
            if intent:data.setdefault('thread_archive_intents',[]).append(intent)
        recovery.update(next_check_at=None, state='recovered')
        data['session_recovery'] = recovery
        guard()
        row = records.update(row, row['state'], data)
        return row, match if status == 'completed' else None
    if status == 'inProgress':
        recovery.setdefault('running_since', now_text())
        elapsed = (datetime.now(timezone.utc) - datetime.strptime(recovery['running_since'], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)).total_seconds()
        if elapsed >= 600:
            stop('analysis_original_turn_still_running')
    elif recovery['checks'] >= MAX_SESSION_CHECKS:
        # Only a confirmed missing persisted history permits replacing read-only
        # research. Network failures never establish that condition.
        if recovery['observation'] != 'thread_unavailable':
            stop('analysis_session_recovery_exhausted')
        chunk = binding['input_digest']
        replacements = dict(data.get('analysis_replacements', {}))
        if replacements.get(chunk, 0) >= 1:
            stop('analysis_replacement_exhausted')
        history.append({'thread': thread, 'turn': turn, 'status': 'unknown',
                        'superseded': True, 'generation': generation, 'binding': binding,
                        'requested_keys':requested_keys,
                        'legacy_input_binding': active is None, 'at': now_text(),
                        'possible_duplicate_model_usage': True})
        replacements[chunk] = 1
        pending_request={**active,'generation':generation+1,'pending_replacement':True} if active and active.get('payload') else None
        data.update(analysis_request_history=history, analysis_replacements=replacements,
                    analysis_generation=generation + 1, ai_inflight=False,
                    analysis_thread=None, analysis_turn=None, analysis_request=pending_request)
        recovery.update(next_check_at=None, state='replaced')
        data['session_recovery'] = recovery
        guard()
        return records.update(row, row['state'], data), None
    recovery.update(next_check_at=now_text(SESSION_CHECK_SECONDS), state='observing')
    data['session_recovery'] = recovery
    guard()
    records.update(row, row['state'], data)
    raise SessionWaiting(recovery)


def assert_generation(records, ident, generation):
    if records.get(ident)['data'].get('analysis_generation', 0) != generation:
        raise RuntimeError('analysis_execution_superseded')
