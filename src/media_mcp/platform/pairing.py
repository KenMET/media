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


def local_pairing_peer(request):
    """Only a local socket may enroll: loopback, or the explicitly bound LAN IP itself."""
    try:
        bind=ipaddress.ip_address(os.environ.get('MEDIA_WEB_BIND_HOST','127.0.0.1'))
        if bind.is_loopback:
            return loopback_peer(request.scope)
        ranges=('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','fc00::/7')
        if not any(bind in ipaddress.ip_network(network) for network in ranges):
            return False
        peer=ipaddress.ip_address(request.scope['client'][0])
        server=ipaddress.ip_address(request.scope['server'][0])
        return peer==bind and server==bind
    except (ValueError,TypeError,KeyError,IndexError):
        return False


def pairing_response(request, directory):
    token=service_token()
    if (os.environ.get('MEDIA_SERVICE_PAIRING')!='true'
            or not local_pairing_peer(request) or not token):
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


def pairing_error_message(error):
    """Explain bounded failure categories without echoing URLs or response bodies."""
    if isinstance(error,requests.Timeout):
        reason='Control connection timed out; check the cloud FRP port and the FRPC connection to the local control API'
    elif isinstance(error,requests.ConnectionError):
        reason='Cannot connect to control; check cloud MEDIA_CONTROL_PORT and point local FRPC localIP to 127.0.0.1 and localPort to MEDIA_LOCAL_CONTROL_PORT'
    elif isinstance(error,requests.HTTPError):
        status=getattr(error.response,'status_code',None)
        if status==403:
            reason='Control rejected pairing (HTTP 403); check whether initial pairing is enabled and the request comes from local FRPC'
        elif status==400:
            reason='Control rejected the request (HTTP 400); if initial pairing is disabled and cloud credentials are lost, run sh setup.sh local pair on the NAS'
        else:
            reason='Unexpected control HTTP response; confirm the FRP mapping points to the Media control API'
    elif isinstance(error,OSError):
        reason='Cannot read or write cloud internal credentials; check the host state directory and permissions'
    else:
        reason='Control response or credential validation failed; check the mapped service and private credentials without deleting or overwriting existing keys'
    return 'Automatic connection incomplete: '+reason+'. Existing keys will not be overwritten.'


def main():
    try:
        from media_mcp.platform.transport import control_url
        connect(control_url(),sys.argv[1])
    except Exception as error:
        # Never echo response bodies, headers, credentials or connection objects.
        raise SystemExit(pairing_error_message(error)) from None
    print('Internal authentication was configured automatically; no manual control token is needed.')


if __name__=='__main__':
    main()
