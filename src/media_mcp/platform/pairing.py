"""One-time enrollment through the owner's loopback-only FRP control mapping.

No secret is printed. Public gateway routes never relay this endpoint.
"""
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

import requests

from media_mcp.platform.network import loopback_peer
from media_mcp.platform.transport import service_token, require_service


def loopback_url(base):
    parsed=urlsplit(base)
    try:
        local=parsed.hostname=='localhost' or ipaddress.ip_address(parsed.hostname).is_loopback
        _=parsed.port
    except (ValueError,TypeError):
        local=False
    if (not local or parsed.scheme!='http' or parsed.username or parsed.password
            or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        raise ValueError('pairing_requires_loopback_frp_url')
    return base.rstrip('/')


def pairing_response(request, directory):
    try:
        bind=ipaddress.ip_address(os.environ.get('MEDIA_WEB_BIND_HOST','127.0.0.1')).is_loopback
    except ValueError:
        bind=False
    token=service_token()
    if (os.environ.get('MEDIA_SERVICE_PAIRING')!='true' or not bind
            or not loopback_peer(request.scope) or not token):
        raise ValueError('permission_denied')
    marker=Path(directory)/'control-pairing.sealed'
    identity=hashlib.sha256(token.encode()).hexdigest()
    if request.method=='POST':
        require_service(request)
        descriptor=os.open(marker,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'w') as handle:
            handle.write(identity)
            handle.flush()
            os.fsync(handle.fileno())
        return {'paired':True}
    if marker.is_file() and marker.read_text()==identity:
        raise ValueError('pairing_closed')
    return {'token':token}


def connect(base, destination, session=None):
    base=loopback_url(base)
    path=Path(destination)
    client=session or requests.Session()
    client.trust_env=False
    if not path.is_file():
        with client.get(base+'/internal/pairing',timeout=15,stream=True,allow_redirects=False) as response:
            response.raise_for_status()
            body=bytearray()
            for chunk in response.iter_content(4096):
                body.extend(chunk)
                if len(body)>4096:
                    raise ValueError('pairing_invalid_response')
            result=json.loads(body)
            token=result.get('data',{}).get('token','') if result.get('success') else ''
        if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_.~+/=-]{32,256}',token):
            raise ValueError('pairing_invalid_response')
        path.parent.mkdir(parents=True,exist_ok=True)
        try:
            descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor,'w') as handle:
                handle.write(token)
                handle.flush()
                os.fsync(handle.fileno())
    if path.is_symlink():
        raise ValueError('pairing_invalid_destination')
    token=path.read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9_.~+/=-]{32,256}',token):
        raise ValueError('pairing_invalid_destination')
    os.chmod(path,0o600)
    response=client.post(base+'/internal/pairing',json={},headers={'x-media-service-token':token},
                         timeout=15,allow_redirects=False)
    response.raise_for_status()
    if not response.json().get('data',{}).get('paired'):
        raise ValueError('pairing_not_completed')


def main():
    try:
        from media_mcp.platform.transport import control_url
        connect(control_url(),sys.argv[1])
    except Exception:
        # Never echo response bodies, headers, credentials or connection objects.
        raise SystemExit('自动连接未完成：请先启动 local，并确认 FRP 映射仅在云端本机可达；已有密钥不会被覆盖。') from None
    print('内部认证已自动配置，无需手工填写 control token。')


if __name__=='__main__':
    main()
