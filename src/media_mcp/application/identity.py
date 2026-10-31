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


def excluded_episode(metadata):
    """Owned season packs may contain same-work episodes outside this request."""
    expected=expected_identity.get()
    if not expected or expected['identity']['kind']!='tv' or metadata.get('media_tmdb_id')!=expected['identity']['tmdb_id']:
        return False
    return metadata.get('media_type')=='tv_extra' or (
        metadata.get('media_type')=='tv' and metadata.get('season')==expected['scope']['season'] and
        metadata.get('episode') is not None and metadata['episode'] not in expected['scope']['episodes'])
