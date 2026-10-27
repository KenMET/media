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
        print('下载器 API 检查通过：qBittorrent '+result['version'])
        return
    messages={
        'downloader_auth_failed':'认证失败，请核对 QBITTORRENT_USERNAME / QBITTORRENT_PASSWORD 或本机免认证设置',
        'invalid_downloader_response':'服务响应不是有效的 qBittorrent 版本，请检查下载器地址和端口',
        'downloader_unavailable':'连接失败，请检查 QBITTORRENT_URL、下载器状态及网络',
    }
    raise SystemExit('下载器 API 检查未通过：'+messages[result['error_code']]+'。')


if __name__=='__main__':
    main()
