"""Cloud web/provider gateway; account and task authority remains on the local host."""
import base64
import json
import os
import re
from urllib.parse import urlsplit
import requests

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

from media_mcp.adapters.jackett import Jackett
from media_mcp.adapters.tmdb import TMDB
from media_mcp.platform.api import Command, Input, read_input
from media_mcp.platform.catalog import Catalog
from media_mcp.platform.transport import Remote, require_service, service_token, client_address, control_url
from media_mcp.platform.limits import Budget
from media_mcp.platform.network import browser_peer, validate_public_origin, proxy_mode, LoopbackProxyMiddleware, SameOriginMiddleware
from media_mcp.storage.client import DatabaseClient


# Only API routes belonging to this application may be forwarded.
PROXY_ROUTES = (
    r'auth/(?:bootstrap|login|me|logout|password|setup-status)', r'users(?:/[a-f0-9]{32})?',
    r'command', r'allocations', r'events', r'status', r'tokens(?:/[a-f0-9]{32})?',
)


class Empty(Input):
    pass


def provider_call(command, tmdb, jackett):
    args = command.arguments
    if command.operation == 'tmdb':
        path, params = args.get('path', ''), args.get('params', {})
        if (set(args) != {'path','params'} or not isinstance(path, str) or not re.fullmatch(
            r'(?:search/(?:movie|tv)|(?:movie|tv)/[1-9][0-9]{0,11}|tv/[1-9][0-9]{0,11}/season/[0-9]{1,2}|trending/(?:movie|tv)/(?:day|week))', path)
            or not isinstance(params, dict) or set(params) - {'query','year','first_air_date_year','include_adult','language'}):
            raise ValueError('invalid_provider_request')
        for key, value in params.items():
            if key == 'query' and (not isinstance(value, str) or not 1 <= len(value) <= 200):
                raise ValueError('invalid_provider_request')
            if key in ('year','first_air_date_year') and (type(value) is not int or not 1880 <= value <= 2200):
                raise ValueError('invalid_provider_request')
            if key == 'include_adult' and value != 'false':
                raise ValueError('invalid_provider_request')
            if key == 'language' and value not in ('zh-CN','en-US'):
                raise ValueError('invalid_provider_request')
        return tmdb.get(path, **params)
    if command.operation == 'jackett_search':
        if (set(args) != {'query','kind'} or not isinstance(args.get('query'), str)
                or not 1 <= len(args['query']) <= 300 or args.get('kind') not in ('movie','tv',None)):
            raise ValueError('invalid_provider_request')
        return jackett.search(args['query'], args['kind'])
    if command.operation == 'jackett_torrent':
        if set(args) != {'url'} or not isinstance(args.get('url'), str) or len(args['url']) > 16384:
            raise ValueError('invalid_provider_request')
        result = jackett.torrent(args['url'])
        return {'kind':'bytes', 'data':base64.b64encode(result).decode()} if isinstance(result, bytes) else {
            'kind':'magnet' if result else 'direct', 'data':result}
    raise ValueError('unknown_provider_operation')


def create_gateway(remote=None, catalog=None, tmdb=None, jackett=None, http_request=None):
    remote = remote or Remote(control_url())
    if not service_token():
        raise ValueError('control_token_not_configured')
    tmdb, jackett = tmdb or TMDB(remote=False), jackett or Jackett(remote=False)
    catalog = catalog or Catalog(DatabaseClient(), tmdb=tmdb)
    budget = Budget(DatabaseClient())
    from media_mcp.platform.cloud import CloudCommands
    def cloud_call(request, payload):
        result = relay(request, '/internal/cloud', json.dumps(payload).encode())
        envelope = json.loads(result.body)
        if not envelope.get('success'):
            raise ValueError(envelope.get('error_code', 'remote_service_unavailable'))
        return envelope['data']
    http_request = http_request or requests.request
    hosts = [host.strip() for host in os.environ.get('MEDIA_ALLOWED_HOSTS', '').split(',') if host.strip()]
    public = os.environ.get('MEDIA_WEB_PUBLIC', 'false') == 'true'
    proxied=proxy_mode()
    secure=public or (proxied and os.environ.get('MEDIA_WEB_SECURE_COOKIE','true')=='true')
    if public and not proxied and (not hosts or any('*' in host or '/' in host for host in hosts)):
        raise ValueError('gateway_requires_exact_allowed_hosts')
    if public and not proxied:
        validate_public_origin(hosts)
    hosts = list(set(hosts+['127.0.0.1','localhost']))

    def endpoint(fn):
        async def handle(request):
            origin = request.headers.get('origin')
            if origin and origin not in ('http://'+request.headers.get('host', ''),
                                         'https://'+request.headers.get('host', '')):
                return JSONResponse({'success':False,'error_code':'cross_origin_request_denied'}, status_code=403)
            try:
                response = await fn(request)
                if not isinstance(response, (JSONResponse, FileResponse)):
                    response = JSONResponse({'success':True,'data':response})
            except ValueError as exc:
                code = str(exc)
                if not code.replace('_','').isalnum() or len(code)>120:
                    code = 'invalid_request'
                response = JSONResponse({'success':False,'error_code':code}, status_code=(
                    403 if code in ('permission_denied','download_permission_required','csrf_failed') else 401 if code == 'authentication_required' else
                    429 if code in ('account_rate_limited','account_concurrency_limited') else 400))
            except Exception:
                response = JSONResponse({'success':False,'error_code':'local_service_unavailable'}, status_code=503)
            response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                'Referrer-Policy':'same-origin','X-Frame-Options':'DENY',
                'Content-Security-Policy':"default-src 'self'; img-src 'self' https: data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"})
            return response
        return handle

    def relay(request, path, body=None):
        headers = {'x-media-service-token':service_token()}
        if path == '/api/auth/login':
            # Overwrite rather than relay any client-supplied identity headers.
            headers['x-media-client-ip'] = client_address(browser_peer(request))
        cookie = request.cookies.get('media_session')
        if cookie:
            # Requests builds the Cookie header; arbitrary client cookies are not forwarded.
            cookies = {'media_session':cookie}
        else:
            cookies = {}
        if request.headers.get('x-csrf-token'):
            headers['x-csrf-token'] = request.headers['x-csrf-token']
        if body is not None:
            headers['content-type'] = 'application/json'
        params = {key:request.query_params[key] for key in ('after','limit') if key in request.query_params}
        with http_request(request.method, remote.base+path, data=body, headers=headers,
                    cookies=cookies, params=params, stream=True, allow_redirects=False, timeout=45) as upstream:
                chunks, size = [], 0
                for chunk in upstream.iter_content(65536):
                    size += len(chunk)
                    if size > 2*1024*1024:
                        raise RuntimeError('remote_response_too_large')
                    chunks.append(chunk)
                payload = json.loads(b''.join(chunks))
                if not isinstance(payload, dict) or 'success' not in payload:
                    raise RuntimeError('remote_invalid_response')
                if path == '/api/status' and payload.get('success'):
                    payload['data']['public'] = secure
                    payload['data']['service'] = 'media-cloud-web'
                    payload['data']['tmdb_configured'] = bool(os.environ.get('TMDB_API_KEY'))
                    payload['data']['indexer_configured'] = bool(jackett.configured)
                response = JSONResponse(payload, status_code=upstream.status_code)
                cookie_header = upstream.headers.get('set-cookie')
                if cookie_header:
                    if secure and '; secure' not in cookie_header.lower():
                        cookie_header += '; Secure'
                    response.headers['set-cookie'] = cookie_header
                return response

    async def proxy(request):
        path = request.path_params['path']
        if not any(re.fullmatch(pattern, path) for pattern in PROXY_ROUTES):
            raise ValueError('unknown_api_route')
        body = None
        if request.method in ('POST','PATCH','DELETE'):
            # Validate bounded JSON here; the local API performs endpoint-specific validation.
            model = await read_input(request, dict_input)
            body = json.dumps(model.payload).encode()
            if path == 'command':
                command = Command.model_validate(model.payload)
                if command.operation=='collection_identify':
                    from media_mcp.platform.api import CollectionIdentify
                    from media_mcp.application.collections import prepare_identity
                    args=CollectionIdentify.model_validate(command.arguments).model_dump()
                    def identify():
                        def call(payload):
                            response=relay(request,'/internal/collection',json.dumps(payload).encode())
                            envelope=json.loads(response.body)
                            if not envelope.get('success'):
                                raise ValueError(envelope.get('error_code','local_service_unavailable'))
                            return envelope['data']
                        context=call({'action':'context',**{key:args[key] for key in ('collection_id','selection','season')}})
                        with budget.operation(context['user_id'],'search'):
                            snapshot=prepare_identity(tmdb,context,args['title_id'],args['season_override'],args['assignments'])
                        return call({'action':'plan','context_id':context['context_id'],'snapshot':snapshot})
                    return await run_in_threadpool(identify)
                if command.operation in CloudCommands.operations:
                    commands = CloudCommands(lambda payload:cloud_call(request,payload), budget.db, tmdb, jackett)
                    return await run_in_threadpool(commands.invoke, command.operation, command.arguments)
        return await run_in_threadpool(relay, request, '/api/'+path, body)

    async def authenticate(request):
        # Account disable/revocation is checked at the source of truth on every request.
        result = await run_in_threadpool(relay, request, '/api/auth/me')
        payload = json.loads(result.body)
        if result.status_code != 200 or not payload.get('success'):
            raise ValueError('authentication_required')
        return payload['data']['user']

    async def discover(request):
        user = await authenticate(request)
        return await run_in_threadpool(budget.call,user['id'],'search',catalog.discover, request.query_params.get('source','tmdb'),
            request.query_params.get('kind','movie'), request.query_params.get('window','week'))

    async def detail(request):
        user = await authenticate(request)
        return await run_in_threadpool(budget.call,user['id'],'search',catalog.detail, request.query_params.get('title_id',''))

    async def provider(request):
        require_service(request)
        command = await read_input(request, Command)
        return await run_in_threadpool(provider_call, command, tmdb, jackett)

    async def health(request):
        return {'service':'media-cloud-web','status':'ok'}

    from pathlib import Path
    static = Path(__file__).parent/'static'
    async def asset(request):
        name = request.path_params.get('name','index.html')
        if name not in ('index.html','app.js','app.css','i18n.js','ux.js','library.js'):
            raise ValueError('page_not_found')
        return FileResponse(static/name)

    routes = [Route(path,endpoint(fn),methods=methods) for path,fn,methods in (
        ('/healthz',health,['GET']), ('/api/discover',discover,['GET']),('/api/detail',detail,['GET']),
        ('/api/{path:path}',proxy,['GET','POST','PATCH','DELETE']), ('/internal/provider',provider,['POST']),
        ('/',asset,['GET']),('/assets/{name}',asset,['GET']),
    )]
    from media_mcp.lan import lan_middleware
    middleware = ([Middleware(LoopbackProxyMiddleware,allow_authenticated_web=True),Middleware(SameOriginMiddleware)] if proxied else
                  [Middleware(TrustedHostMiddleware,allowed_hosts=hosts)] if public else lan_middleware())
    return Starlette(routes=routes, middleware=middleware)


# RootModel accepts only JSON objects, preserving the original endpoint payload.
from pydantic import RootModel
class dict_input(RootModel[dict]):
    @property
    def payload(self):
        return self.root


def main():
    import uvicorn
    from media_mcp.config import env_value
    uvicorn.run(create_gateway(), host=env_value('MEDIA_CLOUD_WEB_BIND', 'MEDIA_GATEWAY_BIND', default='0.0.0.0'),
                port=int(env_value('MEDIA_CLOUD_WEB_PORT', 'MEDIA_GATEWAY_PORT', 'MEDIA_WEB_PORT', default='18214')), proxy_headers=False)


if __name__ == '__main__':
    main()
