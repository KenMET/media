"""Unauthenticated personal-LAN access, based on the actual peer socket address."""
import ipaddress
import os
from urllib.parse import urlsplit
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

DEFAULT_CIDRS='127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,::1/128,fc00::/7,fe80::/10'


class LANOnlyMiddleware:
    def __init__(self,app,cidrs=None,allowed_hosts=None):
        self.app=app
        self.networks=[ipaddress.ip_network(c.strip()) for c in (cidrs or DEFAULT_CIDRS).split(',') if c.strip()]
        self.allowed_hosts = {h.strip().lower() for h in (allowed_hosts or '').split(',') if h.strip()}

    def trusted_host(self, authority):
        try:
            if any(ord(c) <= 32 or ord(c) == 127 for c in authority):
                return False
            parsed = urlsplit('//'+authority)
            if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                return False
            host = (parsed.hostname or '').lower()
            _ = parsed.port
            if host == 'localhost' or host in self.allowed_hosts:
                return True
            address = ipaddress.ip_address(host)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            return any(address in ipaddress.ip_network(c) for c in DEFAULT_CIDRS.split(','))
        except ValueError:
            return False

    async def __call__(self,scope,receive,send):
        if scope['type'] not in ('http','websocket'):
            return await self.app(scope,receive,send)
        try:
            address=ipaddress.ip_address(scope['client'][0].split('%')[0])
            if isinstance(address,ipaddress.IPv6Address) and address.ipv4_mapped:address=address.ipv4_mapped
            allowed=any(address in network for network in self.networks)
        except (ValueError,TypeError,KeyError):allowed=False
        error = None if allowed else 'lan_access_only'
        headers = scope.get('headers', [])
        hosts = [v.decode('latin1') for k,v in headers if k.lower() == b'host']
        origins = [v.decode('latin1') for k,v in headers if k.lower() == b'origin']
        if not error and (len(hosts) != 1 or not self.trusted_host(hosts[0])):
            error = 'untrusted_host'
        if not error and origins:
            try:
                origin = urlsplit(origins[0])
                if (len(origins) != 1 or origin.scheme not in ('http','https') or origin.username or origin.password
                        or origin.path not in ('','/') or origin.query or origin.fragment
                        or origin.netloc.lower() != hosts[0].lower()):
                    error = 'cross_origin_request_denied'
            except ValueError:
                error = 'cross_origin_request_denied'
        if error:
            if scope['type']=='websocket':return await send({'type':'websocket.close','code':1008})
            return await JSONResponse({'error':error},status_code=403)(scope,receive,send)
        return await self.app(scope,receive,send)


def lan_middleware():
    return [Middleware(LANOnlyMiddleware,cidrs=os.environ.get('MEDIA_LAN_CIDRS') or DEFAULT_CIDRS,
                       allowed_hosts=os.environ.get('MEDIA_ALLOWED_HOSTS',''))]
