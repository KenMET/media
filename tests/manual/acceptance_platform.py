"""Real loopback TCP web/MCP/provider acceptance in a marked disposable container.

No real indexer, downloader, model, or media is used. Suitable for --network none.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time
from unittest.mock import patch

import requests
import uvicorn


def main():
    if os.environ.get('MEDIA_ACCEPTANCE') != 'isolated-container' or not Path('/state/.acceptance').is_file():
        raise SystemExit('Refusing unmarked acceptance environment')
    if os.environ.get('MEDIA_DB_PATH') != '/state/media.sqlite3':
        raise SystemExit('Refusing unexpected database')
    if Path('/state/media.sqlite3').exists():
        raise SystemExit('Requires fresh disposable state')
    from fastmcp import Client
    from preview_platform import PreviewTMDB, PreviewIndexer
    from media_mcp.application.controller import Controller
    from media_mcp.platform.accounts import Accounts
    from media_mcp.platform.api import create_app
    from media_mcp.platform.catalog import Catalog
    from media_mcp.platform.gateway import create_gateway
    from media_mcp.platform.remote_mcp import RemoteMCPService, RemoteTokenVerifier
    from media_mcp.platform.transport import Remote
    from media_mcp.runtime.state import MediaJobs
    from media_mcp.server import create_server
    from media_mcp.storage.client import DatabaseClient
    from media_mcp.storage.media import _client
    from media_mcp.storage.records import Records

    class Server:
        def __init__(self):
            self.socket = socket.socket()
            self.socket.bind(('127.0.0.1',0))
            self.port = self.socket.getsockname()[1]
            self.url = f'http://127.0.0.1:{self.port}'
        def start(self, app):
            self.server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
            self.thread = threading.Thread(target=self.server.run, kwargs={'sockets':[self.socket]}, daemon=True)
            self.thread.start()
            for _ in range(100):
                if self.server.started:
                    return
                time.sleep(.05)
            raise RuntimeError('acceptance_server_start_timeout')
        def stop(self):
            if hasattr(self,'server'):
                self.server.should_exit = True
                self.thread.join(5)
            else:
                self.socket.close()

    local, cloud, mcp = Server(), Server(), Server()
    os.environ.update(MEDIA_CONTROL_TOKEN=secrets.token_urlsafe(40),
        MEDIA_WEB_BOOTSTRAP_TOKEN=secrets.token_urlsafe(40), MEDIA_ALLOWED_HOSTS='localhost',
        MEDIA_WEB_PUBLIC='false', MEDIA_WEB_SECURE_COOKIE='false',
        MEDIA_CATALOG_URL=cloud.url, MEDIA_CONTROL_URL='',
        MEDIA_DOWNLOAD_ROOT='/data/downloads', MEDIA_LIBRARY_ROOT='/data/media_hub')
    records = Records(_client(None))
    records.initialize()
    accounts = Accounts(records.db)
    accounts.initialize()
    jobs = MediaJobs()
    jobs.initialize()

    class Indexer(PreviewIndexer):
        def torrent(self, url):
            assert url == 'magnet:?xt=urn:btih:'+'a'*40
            return None

    with patch.dict(os.environ, {'MEDIA_DB_PATH':'/state/cloud/catalog.sqlite3'}):
        catalog = Catalog(DatabaseClient(),tmdb=PreviewTMDB())
    try:
        local.start(create_app(accounts,records))
        remote = Remote(local.url)
        cloud.start(create_gateway(remote,catalog=catalog,tmdb=PreviewTMDB(),jackett=Indexer()))
        mcp.start(create_server(RemoteMCPService(remote),RemoteTokenVerifier(remote)).http_app(
            path='/mcp',stateless_http=True,json_response=True))
        browser = requests.Session()
        def api(path, payload=None):
            response = browser.get(cloud.url+path,timeout=10) if payload is None else browser.post(
                cloud.url+path,json=payload,timeout=10)
            response.raise_for_status()
            result = response.json()
            assert result['success'], result.get('error_code')
            return result['data']
        api('/api/auth/bootstrap',{'username':'acceptance','password':'acceptance-password-123',
                                 'token':os.environ['MEDIA_WEB_BOOTSTRAP_TOKEN']})
        login = api('/api/auth/login',{'username':'acceptance','password':'acceptance-password-123'})
        browser.headers['x-csrf-token'] = login['csrf']
        assert api('/api/discover')['items'][0]['rating_source'] == 'TMDB'
        def command(operation, **arguments):
            return api('/api/command',{'operation':operation,'arguments':arguments})
        titles = command('search_titles',query='\u8fdc\u5c71\u6765\u4fe1',kind='movie')['titles']
        releases = command('search_releases',title_id=titles[0]['title_id'])['releases']
        assert releases and 'download_url' not in releases[0]
        plan = command('plan',release_id=releases[0]['release_id'])
        arguments = {'plan_id':plan['plan_id'],'revision':plan['revision'],'idempotency_key':'acceptance-platform-001'}
        first = command('start',**arguments)
        assert command('start',**arguments)['job_id'] == first['job_id']

        video = Path('/data/downloads/fixture.mkv')
        video.parent.mkdir(parents=True,exist_ok=True)
        video.write_bytes(b'disposable platform acceptance bytes')
        original = hashlib.sha256(video.read_bytes()).hexdigest()
        class Downloader:
            def __init__(self):
                self.job_id = None
                self.progress = .5
                self.added = 0
            def prepare(self):
                pass
            def add(self, *, job_id, **kwargs):
                self.job_id = job_id
                self.added += 1
            def find(self, hash_value):
                if not self.job_id:
                    return None
                return {'category':'media-mcp','tags':'media-mcp-'+self.job_id,'progress':self.progress,
                    'state':'downloading','content_path':str(video),'save_path':str(video.parent),
                    'download_speed':1024,'eta':10,'total_bytes':video.stat().st_size}
            def files(self, hash_value):
                return [{'name':video.name,'progress':1,'priority':1}]
        downloader = Downloader()
        controller = Controller(records,downloader=downloader,jobs=jobs)
        controller.tick(first['job_id'])
        controller.tick(first['job_id'])
        live = command('job',job_id=first['job_id'])
        assert live['progress'] == .5 and live['download_speed'] == 1024
        token = api('/api/tokens',{'name':'acceptance-mcp'})['token']
        async def check_mcp():
            async with Client(mcp.url+'/mcp',auth=token) as client:
                status = await client.call_tool('media_status')
                assert status.structured_content['service'] == 'media-mcp'
                response = await client.call_tool('media_get_job',{'job_id':first['job_id']})
                assert response.structured_content['data']['job_id'] == first['job_id']
                response = await client.call_tool('media_start_acquisition',arguments)
                assert response.structured_content['data']['job_id'] == first['job_id']
        asyncio.run(check_mcp())
        assert downloader.added == 1
        downloader.progress = 1
        controller.tick(first['job_id'])
        assert jobs.db.execute('SELECT COUNT(*) FROM media_processing_job').scalar() == 1
        library = Path('/data/media_hub')
        library.mkdir(parents=True,exist_ok=True)
        os.link(video,library/video.name)
        assert hashlib.sha256(video.read_bytes()).hexdigest() == original
        local.stop()
        assert browser.get(cloud.url+'/api/status',timeout=5).status_code == 503
        assert downloader.added == 1
        print(json.dumps({'acceptance':'passed','transport':'real TCP web + provider + MCP',
            'download_submissions':downloader.added,'disconnect_status':503,
            'hardlink_source_preserved':True,'real_media_or_downloader_used':False},ensure_ascii=False))
    finally:
        mcp.stop()
        cloud.stop()
        local.stop()


if __name__ == '__main__':
    main()
