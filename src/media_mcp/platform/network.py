"""Origin checks for the explicitly authenticated cloud MCP profile."""
from urllib.parse import urlsplit
import os
import ipaddress
from starlette.responses import JSONResponse


def proxy_mode():
    return os.environ.get('MEDIA_WEB_MODE','') == 'proxy'


def loopback_peer(scope):
    try:
        address=ipaddress.ip_address(scope['client'][0])
        if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped:
            address=address.ipv4_mapped
        return address.is_loopback
    except (ValueError,TypeError,KeyError):
        return False


def proxy_addresses():
    # Exact IPs only, never a blanket private-network trust rule.
    try:
        return {ipaddress.ip_address(item.strip()) for item in
                os.environ.get('MEDIA_PROXY_IPS','').split(',') if item.strip()}
    except ValueError:
        raise ValueError('proxy_requires_exact_ip_addresses') from None


class LoopbackProxyMiddleware:
    """Only loopback or exact operator-selected proxy container IPs may connect."""
    def __init__(self,app):
        self.app=app
        self.addresses=proxy_addresses()

    async def __call__(self,scope,receive,send):
        allowed=loopback_peer(scope)
        if not allowed:
            try:
                allowed=ipaddress.ip_address(scope['client'][0]) in self.addresses
            except (ValueError,TypeError,KeyError):
                pass
        if scope['type'] in ('http','websocket') and not allowed:
            if scope['type']=='websocket':
                return await send({'type':'websocket.close','code':1008})
            return await JSONResponse({'error':'local_proxy_only'},status_code=403)(scope,receive,send)
        return await self.app(scope,receive,send)


def validate_public_origin(hosts):
    """Public mode requires an explicit TLS entry, not merely a Secure cookie."""
    try:
        origin = urlsplit(os.environ.get('MEDIA_WEB_PUBLIC_URL',''))
        if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
                or origin.path not in ('','/') or origin.query or origin.fragment
                or origin.hostname.lower() not in {host.lower() for host in hosts}):
            raise ValueError()
        _ = origin.port
    except ValueError:
        raise ValueError('public_web_requires_https_origin') from None


def browser_peer(request):
    """Only explicitly trusted reverse proxies can provide a single X-Real-IP."""
    peer = request.client.host if request.client else 'unknown'
    configured = os.environ.get('MEDIA_WEB_TRUSTED_PROXIES','')
    if proxy_mode() and not configured:
        configured=','.join(['127.0.0.0/8','::1/128']+[str(address) for address in proxy_addresses()])
    if not configured:
        return peer
    try:
        networks = [ipaddress.ip_network(item.strip()) for item in configured.split(',') if item.strip()]
        address = ipaddress.ip_address(peer)
    except ValueError:
        raise ValueError('invalid_trusted_proxy_configuration') from None
    if any(address in network for network in networks):
        if proxy_mode():
            forwarded=request.headers.getlist('x-forwarded-for')
            if forwarded:
                if len(forwarded)!=1 or len(forwarded[0])>1024:
                    raise ValueError('invalid_client_address')
                # The closest trusted proxy appends its actual socket peer last.
                # Do not select the attacker's first forwarded value.
                from media_mcp.platform.transport import client_address
                return client_address(forwarded[0].split(',')[-1].strip())
        values = request.headers.getlist('x-real-ip')
        if not values and proxy_mode():
            # Native localhost clients need no proxy header. A proxy must overwrite
            # X-Real-IP to preserve per-client login buckets.
            return peer
        if len(values) != 1:
            raise ValueError('invalid_client_address')
        from media_mcp.platform.transport import client_address
        return client_address(values[0])
    return peer


class SameOriginMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = scope.get('headers', [])
        hosts = [v.decode('latin1') for k,v in headers if k.lower() == b'host']
        origins = [v.decode('latin1') for k,v in headers if k.lower() == b'origin']
        allowed = len(hosts) == 1
        if origins:
            try:
                origin = urlsplit(origins[0])
                allowed = (allowed and len(origins) == 1 and origin.scheme in ('http','https')
                    and not origin.username and not origin.password and origin.path in ('','/')
                    and not origin.query and not origin.fragment and origin.netloc.lower() == hosts[0].lower())
            except ValueError:
                allowed = False
        if not allowed:
            return await JSONResponse({'error':'cross_origin_request_denied'}, status_code=403)(scope,receive,send)
        return await self.app(scope,receive,send)
