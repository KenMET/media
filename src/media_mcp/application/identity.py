"""Per-processing-job identity fence before filesystem publication."""
from contextvars import ContextVar
expected_identity = ContextVar('media_expected_identity', default=None)


def validate_identity(metadata):
    expected = expected_identity.get()
    if expected is None:
        return
    identity, scope = expected['identity'], expected['scope']
    if (metadata.get('media_type') != identity['kind'] or
        metadata.get('media_tmdb_id') != identity['tmdb_id'] or
        (identity['kind'] == 'tv' and (metadata.get('season') != scope['season'] or
                                     metadata.get('episode') not in scope['episodes']))):
        raise ValueError('acquisition_identity_mismatch_needs_review')
