"""Bounded task-level model recovery. Never replay an unobserved model outcome."""
RETRYABLE_MODEL_ERRORS = frozenset({
    'connection_failed', 'app_server_unreachable', 'model_upstream_unavailable',
    'model_connection_lost', 'model_timeout', 'rate_limited', 'maintenance', 'model_at_capacity',
})
PERMANENT_MODEL_ERRORS=frozenset({'token_missing','token_rejected','login_required',
    'model_request_rejected','model_unavailable','runtime_unexpected_mcp',
    'runtime_instruction_sources','interactive_request_rejected','unexpected_tool_call'})
MAX_MODEL_RETRIES = 3


def retryable_model_error(error):
    return (not getattr(error, 'outcome_unknown', False)
            and getattr(error, 'code', str(error)) in RETRYABLE_MODEL_ERRORS)


class ModelServiceDeferred(RuntimeError):
    code = 'model_service_waiting'
    def __init__(self, cause):
        self.cause = cause
        super().__init__(self.code)
