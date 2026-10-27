"""Prepare bundled service configuration; never read the parent repository."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets


def initialize_services(service='all'):
    if service not in ('all', 'qbittorrent', 'jackett'):
        raise ValueError('invalid_bootstrap_service')
    prepare_qb = service in ('all', 'qbittorrent')
    prepare_jackett = service in ('all', 'jackett')
    qb=Path(os.environ.get('QBITTORRENT_CONFIG_DIR','/services/qbittorrent'))/'qBittorrent/qBittorrent.conf'
    jackett=Path(os.environ.get('JACKETT_CONFIG_FILE','/services/jackett/Jackett/ServerConfig.json'))
    uid, gid = int(os.environ.get('PUID','0')), int(os.environ.get('PGID','0'))
    # The init container runs as root; service configs must be writable by PUID.
    # Only these managed directories and newly created files are touched.
    directories = ((qb.parent.parent, qb.parent) if prepare_qb else ()) + (
        (jackett.parent.parent, jackett.parent) if prepare_jackett else ())
    for directory in directories:
        directory.mkdir(parents=True,exist_ok=True)
        os.chown(directory, uid, gid)
    if prepare_qb and not qb.exists():
        salt=secrets.token_bytes(16)
        password=secrets.token_bytes(32)
        digest=hashlib.pbkdf2_hmac('sha512',password,salt,100000,64)
        hashed=base64.b64encode(salt).decode()+':'+base64.b64encode(digest).decode()
        port=int(os.environ.get('MEDIA_TORRENT_PORT','48181'))
        qb.write_text('''[LegalNotice]
Accepted=true

[BitTorrent]
Session\\DefaultSavePath=/data/downloads
Session\\TempPathEnabled=false
Session\\Port=TORRENT_PORT
Session\\AddTorrentStopped=false

[Preferences]
Downloads\\SavePath=/data/downloads
Downloads\\TempPathEnabled=false
Connection\\PortRangeMin=TORRENT_PORT
Connection\\UPnP=false
WebUI\\Address=*
WebUI\\Port=8080
WebUI\\LocalHostAuth=false
WebUI\\AuthSubnetWhitelistEnabled=true
WebUI\\AuthSubnetWhitelist=127.0.0.1/32, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, ::1/128, fc00::/7
WebUI\\HostHeaderValidation=false
WebUI\\Username=media
WebUI\\Password_PBKDF2="@ByteArray(PASSWORD_HASH)"
'''.replace('TORRENT_PORT',str(port)).replace('PASSWORD_HASH',hashed))
        qb.chmod(0o600)
        os.chown(qb, uid, gid)
    if prepare_jackett and not jackett.exists():
        jackett.write_text(json.dumps({'Port':9117,'AllowExternal':True,'LocalBindAddress':'127.0.0.1',
            'APIKey':secrets.token_hex(16),'AdminPassword':None,'UpdateDisabled':True,
            'CacheEnabled':True,'CacheTtl':2100,'CacheMaxResultsPerIndexer':1000},indent=2)+'\n')
        jackett.chmod(0o600)
        os.chown(jackett, uid, gid)
    # Only touch the two directory owners, never recursively change existing data.
    data_root=Path(os.environ.get('MEDIA_DATA_ROOT','/data'))
    for name in (('downloads','media_hub') if prepare_qb else ()):
        path=data_root/name;path.mkdir(parents=True,exist_ok=True)
        os.chown(path,int(os.environ.get('PUID','0')),int(os.environ.get('PGID','0')))
    print('Selected bundled service configuration ready; internal credentials are managed automatically.')


if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('service', choices=('all', 'qbittorrent', 'jackett'), nargs='?', default='all')
    initialize_services(parser.parse_args().service)
