"""Optional multi-user MCP identity; the default private LAN MCP stays unchanged."""
from fastmcp.server.auth.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from media_mcp.platform.service import PlatformService


class PlatformTokenVerifier(TokenVerifier):
    def __init__(self, accounts):
        super().__init__(required_scopes=['media:access'])
        self.accounts = accounts

    async def verify_token(self, token):
        from starlette.concurrency import run_in_threadpool
        try:
            actor, expiry = await run_in_threadpool(self.accounts.verify_api_token, token)
        except ValueError:
            return None
        return AccessToken(token=token, client_id=actor.id, subject=actor.id,
                           scopes=['media:access'], expires_at=expiry)


class PlatformMCPService:
    methods = frozenset(('search_titles','library','search_releases','plan','start','job','jobs','retry','subtitles'))

    def __init__(self, accounts, records):
        self.accounts, self.records = accounts, records

    def __getattr__(self, name):
        if name not in self.methods:
            raise AttributeError(name)
        def invoke(*args, **kwargs):
            token = get_access_token()
            if not token or not token.subject:
                raise ValueError('authentication_required')
            actor = self.accounts.actor_by_id(token.subject)
            service = PlatformService(actor, self.accounts, self.records, entry='mcp')
            return getattr(service, name)(*args, **kwargs)
        return invoke
