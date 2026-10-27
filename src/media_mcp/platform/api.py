"""Web/control HTTP API. All mutations use the existing application and fencing."""
from dataclasses import asdict
import json
import os
import secrets
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from media_mcp.lan import lan_middleware
from media_mcp.platform.accounts import Accounts
from media_mcp.platform.catalog import Catalog
from media_mcp.platform.service import PlatformService
from media_mcp.platform.transport import require_service, client_address
from media_mcp.platform.limits import Budget
from media_mcp.platform.network import browser_peer, validate_public_origin
from media_mcp.storage.records import Records


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Login(Input):
    username: str = Field(min_length=1, max_length=48)
    password: str = Field(min_length=1, max_length=256)


class Bootstrap(Login):
    token: str = Field(min_length=32, max_length=256)


class NewUser(Login):
    role: Literal['admin', 'user'] = 'user'
    can_download: bool = True
    can_manage_media: bool = False


class UserUpdate(Input):
    enabled: bool
    role: Literal['admin', 'user']
    can_download: bool | None = None
    can_manage_media: bool | None = None


class Password(Input):
    old_password: str = Field(max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class Command(Input):
    operation: str = Field(max_length=40)
    arguments: dict = Field(default_factory=dict)


class Search(Input):
    query: str = Field(min_length=1, max_length=200)
    kind: Literal['movie', 'tv']
    year: int | None = Field(default=None, ge=1880, le=2200)


class Title(Input):
    title_id: str = Field(pattern=r'^(movie|tv):[1-9][0-9]{0,11}$')


class Releases(Title):
    season: int | None = Field(default=None, ge=0, le=99)
    episodes: list[int] | None = Field(default=None, max_length=200)
    resolution: Literal[480, 720, 1080, 2160] | None = None


class Plan(Input):
    release_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class Start(Input):
    plan_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


class Job(Input):
    job_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class Retry(Job):
    revision: int = Field(ge=1)


class Jobs(Input):
    after: str = Field(default='', max_length=32)
    limit: int = Field(default=30, ge=1, le=100)


class Media(Input):
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=30, ge=1, le=100)


class Subtitles(Input):
    media_id: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=128)


class Allocation(Input):
    kind: Literal['task', 'media']
    object_id: str = Field(min_length=1, max_length=32)
    user_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    permission: Literal['read', 'manage', 'none']


class TokenName(Input):
    name: str = Field(min_length=1, max_length=80)


COMMANDS = {
    'search_titles':Search, 'library':Title, 'search_releases':Releases, 'plan':Plan,
    'start':Start, 'job':Job, 'jobs':Jobs, 'retry':Retry, 'subtitles':Subtitles, 'media':Media,
}
READ_COMMANDS = {'search_titles', 'library', 'job', 'jobs', 'media'}


async def read_input(request, model, limit=65536):
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
        raise ValueError('json_content_type_required')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise ValueError('request_too_large')
    try:
        return model.model_validate_json(bytes(body))
    except (ValidationError, ValueError):
        raise ValueError('invalid_request') from None


def create_app(accounts=None, records=None, service_factory=None):
    accounts = accounts or Accounts()
    accounts.initialize()
    records = records or Records(accounts.db)
    records.initialize()
    factory = service_factory or (lambda actor:PlatformService(actor, accounts, records))
    catalog = Catalog(accounts.db)
    budget = Budget(accounts.db, accounts.clock)
    public = os.environ.get('MEDIA_WEB_PUBLIC', 'false') == 'true'
    secure = public or os.environ.get('MEDIA_WEB_SECURE_COOKIE', 'false') == 'true'

    def actor(request, mutation=False):
        return accounts.authenticate(request.cookies.get('media_session', ''),
                                     request.headers.get('x-csrf-token', '') if mutation else None)

    def endpoint(fn):
        async def handle(request):
            # Do not trust forwarded identity or origin headers; reverse proxy preserves Host.
            origin = request.headers.get('origin')
            if origin and origin not in ('http://'+request.headers.get('host', ''),
                                         'https://'+request.headers.get('host', '')):
                return JSONResponse({'success':False, 'error_code':'cross_origin_request_denied'}, status_code=403)
            try:
                result = await fn(request)
                if isinstance(result, (JSONResponse, FileResponse)):
                    response = result
                else:
                    response = JSONResponse({'success':True, 'data':result})
            except ValueError as exc:
                code = str(exc)
                if not code.replace('_', '').isalnum() or len(code) > 120:
                    code = 'invalid_request'
                status = 401 if code in ('authentication_required', 'invalid_credentials') else (
                    403 if code in ('permission_denied','download_permission_required','media_management_permission_required','csrf_failed','bootstrap_denied') else (
                    429 if code in ('login_rate_limited','account_rate_limited','account_concurrency_limited',
                                    'account_queue_full','account_token_limit') else 400))
                response = JSONResponse({'success':False, 'error_code':code}, status_code=status)
            except Exception:
                response = JSONResponse({'success':False, 'error_code':'dependency_unavailable'}, status_code=503)
            response.headers.update({
                'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff',
                'Referrer-Policy':'same-origin', 'X-Frame-Options':'DENY',
                'Content-Security-Policy':"default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            })
            return response
        return handle

    async def setup_status(request):
        initialized = await run_in_threadpool(lambda:bool(accounts.db.execute(
            'SELECT EXISTS(SELECT 1 FROM platform_user)').scalar()))
        return {'initialized':initialized}

    async def bootstrap(request):
        data = await read_input(request, Bootstrap)
        def expected_token():
            configured = os.environ.get('MEDIA_WEB_BOOTSTRAP_TOKEN', '')
            if configured:
                return configured
            path = Path(os.environ.get('MEDIA_WEB_BOOTSTRAP_TOKEN_FILE') or
                        str(Path(os.environ.get('MEDIA_STATE_DIR', '/state'))/'web-bootstrap-token'))
            try:
                return path.read_text().strip()
            except OSError:
                return ''
        result = await run_in_threadpool(accounts.bootstrap, data.username, data.password, data.token,
                                        await run_in_threadpool(expected_token))
        return asdict(result)

    async def login(request):
        data = await read_input(request, Login)
        peer = request.client.host if request.client else 'unknown'
        forwarded = request.headers.getlist('x-media-client-ip')
        if forwarded:
            # Only an authenticated gateway may assert its socket client's identity.
            require_service(request)
            if len(forwarded) != 1:
                raise ValueError('invalid_client_address')
            peer = 'gateway:' + client_address(forwarded[0])
        else:
            peer = browser_peer(request)
        token, csrf, user = await run_in_threadpool(accounts.login, data.username, data.password,
                                                   peer)
        response = JSONResponse({'success':True, 'data':{'user':asdict(user), 'csrf':csrf}})
        response.set_cookie('media_session', token, httponly=True, secure=secure,
                            samesite='strict', max_age=43200, path='/')
        return response

    async def me(request):
        user = await run_in_threadpool(actor, request)
        # Return CSRF only at login; restored tabs reauthenticate instead of exposing session tokens.
        return {'user':asdict(user)}

    async def logout(request):
        await run_in_threadpool(actor, request, True)
        await run_in_threadpool(accounts.logout, request.cookies.get('media_session', ''))
        response = JSONResponse({'success':True, 'data':{}})
        response.delete_cookie('media_session', path='/', secure=secure, httponly=True, samesite='strict')
        return response

    async def password(request):
        user = await run_in_threadpool(actor, request, True)
        data = await read_input(request, Password)
        await run_in_threadpool(accounts.change_password, user, data.old_password, data.new_password)
        return {'login_required':True}

    async def users(request):
        user = await run_in_threadpool(actor, request, request.method != 'GET')
        if request.method == 'GET':
            return {'users':await run_in_threadpool(accounts.users, user)}
        data = await read_input(request, NewUser)
        return await run_in_threadpool(accounts.create_user, user, **data.model_dump())

    async def user_update(request):
        user = await run_in_threadpool(actor, request, True)
        data = await read_input(request, UserUpdate)
        await run_in_threadpool(accounts.update_user, user, request.path_params['user_id'], **data.model_dump())
        return {}

    async def command(request):
        user = await run_in_threadpool(actor, request, True)
        data = await read_input(request, Command)
        schema = COMMANDS.get(data.operation)
        if schema is None:
            raise ValueError('unknown_operation')
        try:
            arguments = schema.model_validate(data.arguments).model_dump()
        except ValidationError:
            raise ValueError('invalid_request') from None
        return await run_in_threadpool(getattr(factory(user), data.operation), **arguments)

    async def internal_command(request):
        require_service(request)
        user, _ = await run_in_threadpool(accounts.verify_api_token,
                                          request.headers.get('x-media-user-token', ''))
        data = await read_input(request, Command)
        schema = COMMANDS.get(data.operation)
        if schema is None:
            raise ValueError('unknown_operation')
        try:
            arguments = schema.model_validate(data.arguments).model_dump()
        except ValidationError:
            raise ValueError('invalid_request') from None
        service = PlatformService(user, accounts, records, entry='mcp')
        return await run_in_threadpool(getattr(service, data.operation), **arguments)

    async def token_info(request):
        require_service(request)
        user, expiry = await run_in_threadpool(accounts.verify_api_token,
                                               request.headers.get('x-media-user-token', ''))
        return {'user':asdict(user), 'expires_at':expiry}

    async def cloud_command(request):
        require_service(request)
        token = request.headers.get('x-media-user-token', '')
        if token:
            user, _ = await run_in_threadpool(accounts.verify_api_token, token)
            entry = 'mcp'
        else:
            user = await run_in_threadpool(actor, request, True)
            entry = 'web'
        from media_mcp.platform.cloud import CloudRequest, accept_cloud
        data = await read_input(request, CloudRequest, limit=12*1024*1024)
        service = PlatformService(user, accounts, records, entry=entry)
        return await run_in_threadpool(accept_cloud, data, service)

    async def pair(request):
        from media_mcp.platform.pairing import pairing_response
        return await run_in_threadpool(pairing_response,request,accounts.db.path.parent)

    async def internal_status(request):
        require_service(request)
        await run_in_threadpool(accounts.verify_api_token, request.headers.get('x-media-user-token', ''))
        from media_mcp.monitor.health import healthy
        return {'service':'media-control', 'worker_ready':await run_in_threadpool(healthy),
                'auth_mode':'platform', 'indexer_configured':bool(os.environ.get('JACKETT_URL') or
                    os.environ.get('MEDIA_CATALOG_URL')),
                'tmdb_configured':bool(os.environ.get('TMDB_API_KEY') or os.environ.get('MEDIA_CATALOG_URL'))}

    async def allocation(request):
        user = await run_in_threadpool(actor, request, True)
        data = await read_input(request, Allocation)
        await run_in_threadpool(accounts.grant, user, **data.model_dump())
        return {}

    async def events(request):
        user = await run_in_threadpool(actor, request)
        return {'events':await run_in_threadpool(accounts.events, user,
                    int(request.query_params.get('after', 0)), int(request.query_params.get('limit', 50)))}

    async def tokens(request):
        user = await run_in_threadpool(actor, request, request.method != 'GET')
        if request.method == 'GET':
            return {'tokens':await run_in_threadpool(accounts.api_tokens, user)}
        data = await read_input(request, TokenName)
        return await run_in_threadpool(accounts.create_api_token, user, data.name)

    async def revoke_token(request):
        user = await run_in_threadpool(actor, request, True)
        await run_in_threadpool(accounts.revoke_api_token, user, request.path_params['token_id'])
        return {}

    async def status(request):
        await run_in_threadpool(actor, request)
        from media_mcp.monitor.health import healthy
        return {'service':'media-web', 'worker_ready':await run_in_threadpool(healthy),
                'tmdb_configured':bool(os.environ.get('TMDB_API_KEY') or os.environ.get('MEDIA_CATALOG_URL')), 'public':public}

    async def health(request):
        return {'service':'media-web', 'status':'ok'}

    async def discover(request):
        user = await run_in_threadpool(actor, request)
        if os.environ.get('MEDIA_EXECUTION_ONLY') == 'true':
            raise ValueError('cloud_search_only')
        return await run_in_threadpool(budget.call, user.id, 'search', catalog.discover,
            request.query_params.get('source', 'tmdb'), request.query_params.get('kind', 'movie'),
            request.query_params.get('window', 'week'))

    async def detail(request):
        user = await run_in_threadpool(actor, request)
        if os.environ.get('MEDIA_EXECUTION_ONLY') == 'true':
            raise ValueError('cloud_search_only')
        return await run_in_threadpool(budget.call,user.id,'search',catalog.detail, request.query_params.get('title_id', ''))

    static = Path(__file__).parent/'static'
    async def asset(request):
        name = request.path_params.get('name', 'index.html')
        if name not in ('index.html','app.js','app.css','i18n.js','ux.js') or not (static/name).is_file():
            raise ValueError('page_not_found')
        return FileResponse(static/name)

    routes = [Route(path, endpoint(fn), methods=methods) for path,fn,methods in (
        ('/api/auth/bootstrap',bootstrap,['POST']), ('/api/auth/login',login,['POST']),
        ('/api/auth/me',me,['GET']), ('/api/auth/logout',logout,['POST']),
        ('/api/auth/password',password,['POST']), ('/api/users',users,['GET','POST']),
        ('/api/users/{user_id}',user_update,['PATCH']), ('/api/command',command,['POST']),
        ('/internal/command',internal_command,['POST']), ('/internal/token-info',token_info,['POST']),
        ('/internal/status',internal_status,['POST']),
        ('/internal/cloud',cloud_command,['POST']),
        ('/internal/pairing',pair,['GET','POST']),
        ('/api/allocations',allocation,['POST']), ('/api/events',events,['GET']),
        ('/api/auth/setup-status',setup_status,['GET']),
        ('/api/tokens',tokens,['GET','POST']), ('/api/tokens/{token_id}',revoke_token,['DELETE']),
        ('/api/status',status,['GET']), ('/healthz',health,['GET']),
        ('/api/discover',discover,['GET']), ('/api/detail',detail,['GET']),
        ('/',asset,['GET']), ('/assets/{name}',asset,['GET']),
    )]
    if public:
        hosts = [h.strip() for h in os.environ.get('MEDIA_ALLOWED_HOSTS', '').split(',') if h.strip()]
        if not hosts or any('*' in host or '/' in host for host in hosts):
            raise ValueError('public_web_requires_exact_allowed_hosts')
        validate_public_origin(hosts)
        middleware = [Middleware(TrustedHostMiddleware, allowed_hosts=list(set(hosts+['127.0.0.1','localhost'])))]
    else:
        middleware = lan_middleware()
    return Starlette(routes=routes, middleware=middleware)


def main():
    import uvicorn
    from media_mcp.storage.media import _client
    _client(None)
    if not os.environ.get('MEDIA_WEB_BOOTSTRAP_TOKEN'):
        token_path = Path(os.environ.get('MEDIA_WEB_BOOTSTRAP_TOKEN_FILE') or
                          str(Path(os.environ.get('MEDIA_STATE_DIR', '/state'))/'web-bootstrap-token'))
        token_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, 'w') as handle:
                handle.write(secrets.token_urlsafe(40))
    app = create_app()
    uvicorn.run(app, host=os.environ.get('MEDIA_WEB_BIND_HOST', '127.0.0.1'),
                port=int(os.environ.get('MEDIA_WEB_PORT', '18213')), proxy_headers=False)


if __name__ == '__main__':
    main()
