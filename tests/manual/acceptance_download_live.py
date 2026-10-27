"""Explicit public Sintel sample -> real qBittorrent, in marked disposable mounts only.

The sample listing is curated from WebTorrent's official free-torrents page;
it is not evidence of a private Jackett site search. All other adapters are real.
Sintel (c) Blender Foundation, durian.blender.org, CC BY 3.0, credits intact.
"""
import hashlib
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys

import requests


# Fixed, opt-in fresh test ports; arbitrary downloader targets are never accepted.
FRESH = os.environ.get('MEDIA_ACCEPTANCE_PROFILE') == 'fresh-20261026'
BASE_PORT = 18510 if FRESH else 18410
WEB = f'http://127.0.0.1:{BASE_PORT+4}'
REQUEST_KEY = 'public-sintel-live-acceptance-' + ('20261026' if FRESH else '20261025')


def bdecode(content):
    pos = 0
    def parse():
        nonlocal pos
        char = content[pos:pos+1]
        if char == b'i':
            end = content.index(b'e',pos)
            value = int(content[pos+1:end]); pos = end+1
            return value
        if char in (b'd',b'l'):
            pos += 1
            value = {} if char == b'd' else []
            while content[pos:pos+1] != b'e':
                if char == b'd':
                    key = parse(); value[key] = parse()
                else:
                    value.append(parse())
            pos += 1
            return value
        end = content.index(b':',pos)
        size = int(content[pos:end]); pos = end+1
        value = content[pos:pos+size]; pos += size
        return value
    return parse()


def verify_http(job_id, row):
    from fastmcp import Client
    base = WEB
    def login(username,password):
        client = requests.Session()
        result = client.post(base+'/api/auth/login',json={'username':username,'password':password},timeout=15).json()
        assert result['success']
        client.headers['x-csrf-token'] = result['data']['csrf']
        return client
    def call(client,name,args):
        return client.post(base+'/api/command',json={'operation':name,'arguments':args},timeout=20).json()
    admin = login('compose-check','compose-acceptance-password-123')
    assert call(admin,'job',{'job_id':job_id})['data']['stage'] == row['state']
    replay = call(admin,'start',{'plan_id':row['data']['plan_id'],
        'revision':row['data']['plan_revision'],'idempotency_key':REQUEST_KEY})
    assert replay['data']['job_id'] == job_id
    assert len(call(admin,'jobs',{})['data']['jobs']) == 1
    token = admin.post(base+'/api/tokens',json={'name':'live-download-acceptance'},timeout=15).json()['data']
    try:
        async def check_mcp():
            async with Client(f'http://127.0.0.1:{BASE_PORT}/mcp',auth=token['token']) as client:
                task = await client.call_tool('media_get_job',{'job_id':job_id})
                assert task.structured_content['data']['stage'] == row['state']
                status = await client.call_tool('media_status')
                assert status.structured_content['worker_ready'] is True
        asyncio.run(check_mcp())
    finally:
        admin.delete(base+'/api/tokens/'+token['id'],json={},timeout=15).raise_for_status()
    username, password = 'live-viewer-'+secrets.token_hex(5), secrets.token_urlsafe(24)
    result = admin.post(base+'/api/users',json={'username':username,'password':password,'role':'user'},timeout=15).json()
    user_id = result['data']['id']
    try:
        viewer = login(username,password)
        assert call(viewer,'jobs',{})['data']['jobs'] == []
        assert not call(viewer,'job',{'job_id':job_id})['success']
        grant = {'kind':'task','object_id':job_id,'user_id':user_id,'permission':'read'}
        assert admin.post(base+'/api/allocations',json=grant,timeout=15).json()['success']
        assert call(viewer,'job',{'job_id':job_id})['success']
        assert not call(viewer,'retry',{'job_id':job_id,'revision':row['revision']})['success']
        grant['permission'] = 'none'
        assert admin.post(base+'/api/allocations',json=grant,timeout=15).json()['success']
        assert not call(viewer,'job',{'job_id':job_id})['success']
    finally:
        admin.patch(base+'/api/users/'+user_id,json={'enabled':False,'role':'user'},timeout=15).raise_for_status()
    assert viewer.get(base+'/api/auth/me',timeout=15).status_code == 401
    return {'web_mcp_same_completed_task':True,'replay_keeps_one_task':True,
            'real_http_user_isolation_and_grant_revocation':True,'disabled_session_rejected':True}


def main():
    assert os.environ.get('MEDIA_ACCEPTANCE') == 'isolated-container'
    assert os.environ.get('MEDIA_DB_PATH') == '/state/media.sqlite3'
    assert os.environ.get('QBITTORRENT_URL') == f'http://127.0.0.1:{BASE_PORT+1}'
    assert Path('/state/.acceptance').is_file() and Path('/data/.acceptance').is_file()
    from media_mcp.adapters.tmdb import TMDB
    from media_mcp.adapters.torrent import infohash
    from media_mcp.adapters.download import Downloader
    from media_mcp.application.controller import Controller
    from media_mcp.platform.accounts import Accounts
    from media_mcp.platform.service import PlatformService
    from media_mcp.storage.records import Records
    from media_mcp.storage.media import _client
    records = Records(); records.initialize(); _client(None)
    manifest = Path('/state/live-download.json')
    downloader = Downloader()
    if manifest.is_file():
        saved = json.loads(manifest.read_text())
        row = records.get(saved['job_id'],'acquisition')
        report = {'job_id':row['id'],'stage':row['state'],'error_code':row['data'].get('error_code'),
                  'progress':row['data'].get('progress'),'processing':row['data'].get('processing')}
        torrent = downloader.find(saved['infohash'])
        if torrent:
            report['downloader'] = {key:torrent.get(key) for key in ('state','progress','download_speed','total_bytes')}
        if '--verify' in sys.argv:
            assert row['state'] in ('completed','completed_with_warnings'), report
            links = records.db.execute("SELECT source_path,target_path FROM media_link WHERE status='linked'").mappings().all()
            assert links
            for link in links:
                source, target = Path(link['source_path']), Path(link['target_path'])
                assert os.path.samefile(source,target)
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                assert digest == hashlib.sha256(target.read_bytes()).hexdigest()
            subtitles = records.db.execute("SELECT target_subtitle_path,status FROM media_subtitle").mappings().all()
            assert subtitles and any(Path(item['target_subtitle_path']).is_file() for item in subtitles)
            chinese_count = max(sum('\u3400' <= char <= '\u9fff' for char in
                Path(item['target_subtitle_path']).read_text(encoding='utf-8',errors='replace'))
                for item in subtitles if Path(item['target_subtitle_path']).is_file())
            assert chinese_count > 30, 'Generated Chinese subtitle must contain real Chinese text'
            # Verify the exact official torrent payload, not just progress or identical hardlinks.
            original = requests.get('https://webtorrent.io/torrents/sintel.torrent',timeout=20)
            original.raise_for_status()
            assert infohash(original.content) == saved['infohash']
            info = bdecode(original.content)[b'info']
            remaining = bytearray()
            hashes = bytearray()
            folder = Path('/data/downloads')/info[b'name'].decode()
            for member in info[b'files']:
                path = folder.joinpath(*(part.decode() for part in member[b'path']))
                assert path.resolve().is_relative_to(folder.resolve())
                with path.open('rb') as stream:
                    while chunk := stream.read(65536):
                        remaining.extend(chunk)
                        while len(remaining) >= info[b'piece length']:
                            size = info[b'piece length']
                            hashes.extend(hashlib.sha1(remaining[:size]).digest())
                            del remaining[:size]
            if remaining:
                hashes.extend(hashlib.sha1(remaining).digest())
            assert bytes(hashes) == info[b'pieces']
            report.update(acceptance='passed',hardlink_bytes_preserved=True,linked_videos=len(links))
            report.update(official_torrent_all_pieces_verified=True,subtitle_records=len(subtitles),
                          chinese_subtitle_characters=chinese_count,
                          **verify_http(saved['job_id'],row))
        print(json.dumps(report,ensure_ascii=False)); return
    assert '--submit' in sys.argv, 'No existing live test'
    assert not downloader.client.torrents_info(), 'Requires empty isolated downloader'
    if FRESH:
        initialized=requests.get(WEB+'/api/auth/setup-status',timeout=15).json()['data']['initialized']
        if not initialized:
            bootstrap=requests.post(WEB+'/api/auth/bootstrap',json={
                'username':'compose-check','password':'compose-acceptance-password-123',
                'token':Path('/state/web-bootstrap-token').read_text().strip()},timeout=15)
            assert bootstrap.status_code == 200, 'Fresh disposable admin initialization failed'
    response = requests.get('https://webtorrent.io/torrents/sintel.torrent',timeout=20,allow_redirects=False)
    assert response.status_code == 200 and len(response.content) < 2*1024*1024
    payload = response.content
    hash_value = infohash(payload)
    assert hash_value == '08ada5a7a6183aae1e09d831df6748d566095a10'
    metadata = bdecode(payload)[b'info']
    total = sum(row[b'length'] for row in metadata[b'files'])
    assert 0 < total < 200*1024*1024
    tmdb = TMDB(remote=False)
    titles = tmdb.search('Sintel','movie',2010)
    identity = next(row for row in titles if row['original_title'] == 'Sintel' and row['date'].startswith('2010'))

    class PublishedSample:
        def search(self, query, kind=None):
            return {'releases':[{'name':'Sintel.2010.Official.WebTorrent.Sample','size':total,
                'seeders':None,'resolution':None,'indexer':'WebTorrent official free sample',
                'indexer_id':'webtorrent-sintel','categories':[2000],
                'download_url':'https://webtorrent.io/torrents/sintel.torrent',
                'claimed_infohash':hash_value}],
                'diagnostics':[{'site':'webtorrent-sintel','status':'ok','raw_count':1}]}
        def torrent(self, url):
            assert url == 'https://webtorrent.io/torrents/sintel.torrent'
            return payload

    accounts = Accounts(records.db)
    session, _, actor = accounts.login('compose-check','compose-acceptance-password-123')
    sample = PublishedSample()
    service = PlatformService(actor,accounts,records,tmdb=tmdb,indexer=sample)
    found = service.search_releases(identity['title_id'])
    browser = requests.Session()
    web = WEB
    result = browser.post(web+'/api/auth/login',json={
        'username':'compose-check','password':'compose-acceptance-password-123'},timeout=15).json()
    browser.headers['x-csrf-token'] = result['data']['csrf']
    def command(name,args):
        result = browser.post(web+'/api/command',json={'operation':name,'arguments':args},timeout=30).json()
        assert result['success'], result
        return result['data']
    plan = command('plan',{'release_id':found['releases'][0]['release_id']})
    arguments = {'plan_id':plan['plan_id'],'revision':plan['revision'],
                 'idempotency_key':REQUEST_KEY}
    task = command('start',arguments)
    assert command('start',arguments)['job_id'] == task['job_id']
    controller = Controller(records,downloader,sample)
    controller.tick(task['job_id'])
    row = records.get(task['job_id'],'acquisition')
    assert row['state'] == 'downloading', row['data'].get('error_code')
    downloader.client.transfer_set_download_limit(limit=4*1024*1024)
    downloader.client.transfer_set_upload_limit(limit=128*1024)
    manifest.write_text(json.dumps({'job_id':task['job_id'],'infohash':hash_value,
        'title_id':identity['title_id'],'bytes':total,'source':'WebTorrent official free sample'}))
    accounts.logout(session)
    print(json.dumps({'submitted':True,'job_id':task['job_id'],'title':identity['title'],
                      'bytes':total,'source':'WebTorrent official free sample','real_downloader':True,
                      'private_indexer_search_verified':False},ensure_ascii=False))


if __name__ == '__main__':
    main()
