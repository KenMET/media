"""Compatibility for migrated internal calls; no dependency on Phantom MCP."""
from dataclasses import asdict
import base64


def mcp_direct_call_ns(name, _request_timeout_seconds=None, **kwargs):
    if name == 'notify.send_notification':
        from .notify import send_notification
        return send_notification(**kwargs)
    if name.startswith('subtitle.'):
        from media_mcp.subtitle.providers.base import SubtitleSearchRequest
        from media_mcp.subtitle.providers.registry import provider_factory
        provider = provider_factory(kwargs.pop('provider'))
        if name == 'subtitle.search':
            request = SubtitleSearchRequest(media_type=kwargs.get('media_type', 'movie'),
                title=kwargs.get('query', ''), languages=(kwargs['language'],),
                tmdb_id=kwargs.get('tmdb_id'), year=kwargs.get('year'),
                season=kwargs.get('season'), episode=kwargs.get('episode'))
            return {'candidates': [asdict(item) for item in provider.search(request)]}
        if name == 'subtitle.download':
            from media_mcp.subtitle.providers.cloud_mcp import _candidate_from_payload
            item = provider.download(_candidate_from_payload(provider.name, kwargs.get('candidate', kwargs)))
            return {**asdict(item), 'content_base64': base64.b64encode(item.content).decode()}
    raise ValueError('unsupported_internal_operation')
