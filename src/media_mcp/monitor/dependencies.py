"""Read-only downloader API readiness, never create categories or submit tasks."""
import re

from media_mcp.adapters.download import Downloader


def check_downloader(factory=Downloader):
    try:
        version=factory().client.app_version()
        if not isinstance(version,str) or not re.fullmatch(r'[A-Za-z0-9.+_-]{1,40}',version):
            return {'success':False,'error_code':'invalid_downloader_response'}
        return {'success':True,'version':version}
    except Exception as error:
        name=type(error).__name__
        code='downloader_auth_failed' if name in ('LoginFailed','Unauthorized401Error','Forbidden403Error') else 'downloader_unavailable'
        return {'success':False,'error_code':code}


def main():
    result=check_downloader()
    if result['success']:
        print('Downloader API check passed: qBittorrent '+result['version'])
        return
    messages={
        'downloader_auth_failed':'Authentication failed; check QBITTORRENT_USERNAME / QBITTORRENT_PASSWORD or local authentication bypass settings',
        'invalid_downloader_response':'The service did not return a valid qBittorrent version; check the downloader address and port',
        'downloader_unavailable':'Connection failed; check QBITTORRENT_URL, downloader status and network access',
    }
    raise SystemExit('Downloader API check failed: '+messages[result['error_code']]+'.')


if __name__=='__main__':
    main()
