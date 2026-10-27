"""Bounded authenticated server-to-server transport; no automatic mutation retries."""
import hashlib
import hmac
import json
import os
import ipaddress
from pathlib import Path
from urllib.parse import urlsplit

import requests


def control_url():
    """New split deployments use the existing FRP listener on this host."""
    port = os.environ.get('MEDIA_CONTROL_PORT', '')
    if port:
        if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise ValueError('invalid_media_control_port')
        return 'http://127.0.0.1:'+str(int(port))
    return os.environ.get('MEDIA_CONTROL_URL', '')


def service_token():
    token = os.environ.get('MEDIA_CONTROL_TOKEN', '')
    if not token:
        path = os.environ.get('MEDIA_CONTROL_TOKEN_FILE', '')
        if path:
            try:
                token = Path(path).read_text().strip()
            except OSError:
                pass
    return token if len(token) >= 32 else ''


def require_service(request):
    expected = service_token()
    supplied = request.headers.get('x-media-service-token', '')
    if not expected or not hmac.compare_digest(hashlib.sha256(expected.encode()).digest(),
                                              hashlib.sha256(supplied.encode()).digest()):
        raise ValueError('permission_denied')


def client_address(value):
    """A bounded canonical address, never a chain of untrusted forwarded values."""
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise ValueError('invalid_client_address') from None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


class Remote:
    def __init__(self, base, session=None):
        parsed = urlsplit(base)
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('invalid_media_remote_url')
        if parsed.scheme == 'http':
            import ipaddress
            try:
                address = ipaddress.ip_address(parsed.hostname)
                private = address.is_loopback or address in ipaddress.ip_network('10.0.0.0/8') or (
                    address.version == 4 and (address in ipaddress.ip_network('172.16.0.0/12') or
                                              address in ipaddress.ip_network('192.168.0.0/16')))
            except ValueError:
                private = parsed.hostname == 'localhost'
            if not private:
                raise ValueError('remote_http_requires_private_address')
        self.base, self.session = base.rstrip('/'), session or requests.Session()

    def call(self, path, payload, *, user_token=None):
        token = service_token()
        if not token:
            raise ValueError('control_token_not_configured')
        headers = {'x-media-service-token':token}
        if user_token:
            headers['x-media-user-token'] = user_token
        try:
            with self.session.post(self.base+path, json=payload, headers=headers, timeout=45,
                                   stream=True, allow_redirects=False) as response:
                if response.status_code >= 500:
                    raise RuntimeError('remote_service_unavailable')
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 12*1024*1024:
                        raise RuntimeError('remote_response_too_large')
                    chunks.append(chunk)
                data = json.loads(b''.join(chunks))
        except (requests.RequestException, ValueError):
            raise RuntimeError('remote_service_unavailable') from None
        if not isinstance(data, dict) or not data.get('success'):
            code = data.get('error_code', '') if isinstance(data, dict) else ''
            if not code.replace('_', '').isalnum() or len(code) > 120:
                code = 'remote_service_unavailable'
            raise ValueError(code)
        return data.get('data')


def provider_remote():
    if os.environ.get('MEDIA_EXECUTION_ONLY') == 'true':
        return None
    url = os.environ.get('MEDIA_CATALOG_URL', '')
    return Remote(url) if url else None
