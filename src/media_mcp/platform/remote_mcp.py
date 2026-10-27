"""Cloud MCP forwards to local task authority with the user's revocable API token."""
from fastmcp.server.auth.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token

from media_mcp.platform.mcp import PlatformMCPService


class RemoteTokenVerifier(TokenVerifier):
    def __init__(self, remote):
        super().__init__(required_scopes=['media:access'])
        self.remote = remote

    async def verify_token(self, token):
        from starlette.concurrency import run_in_threadpool
        try:
            result = await run_in_threadpool(self.remote.call, '/internal/token-info', {}, user_token=token)
        except Exception:
            return None
        return AccessToken(token=token, client_id=result['user']['id'], subject=result['user']['id'],
                           scopes=['media:access'], expires_at=result['expires_at'])


class RemoteMCPService:
    def __init__(self, remote):
        self.remote = remote

    def status(self):
        token = get_access_token()
        if not token:
            raise ValueError('authentication_required')
        result = self.remote.call('/internal/status', {}, user_token=token.token)
        import os
        from media_mcp.adapters.jackett import Jackett
        result['tmdb_configured'] = bool(os.environ.get('TMDB_API_KEY'))
        result['indexer_configured'] = Jackett(remote=False).configured
        result['service'] = 'media-mcp'
        return result

    def __getattr__(self, name):
        if name not in PlatformMCPService.methods:
            raise AttributeError(name)
        from media_mcp.platform.api import COMMANDS
        def invoke(*args, **kwargs):
            token = get_access_token()
            if not token:
                raise ValueError('authentication_required')
            fields = list(COMMANDS[name].model_fields)
            arguments = {**dict(zip(fields, args)), **kwargs}
            from media_mcp.platform.cloud import CloudCommands
            if name in CloudCommands.operations:
                from media_mcp.storage.client import DatabaseClient
                from media_mcp.adapters.tmdb import TMDB
                from media_mcp.adapters.jackett import Jackett
                commands = CloudCommands(lambda payload:self.remote.call('/internal/cloud',payload,user_token=token.token),
                                         DatabaseClient(), TMDB(remote=False), Jackett(remote=False))
                return commands.invoke(name, arguments)
            return self.remote.call('/internal/command', {'operation':name,'arguments':arguments}, user_token=token.token)
        return invoke
