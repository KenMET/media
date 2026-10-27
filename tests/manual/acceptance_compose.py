"""Smoke test the disposable setup.sh local/cloud groups, with no submitted torrents."""
import asyncio
import json
from pathlib import Path

import requests
from fastmcp import Client


if __name__ == '__main__':
    private = Path('/acceptance-private')
    if not (private/'.acceptance').is_file():
        raise SystemExit('Refusing unmarked compose state')
    web = 'http://127.0.0.1:18414'
    browser = requests.Session()
    bootstrap = browser.post(web+'/api/auth/bootstrap',json={
        'username':'compose-check','password':'compose-acceptance-password-123',
        'token':(private/'web-bootstrap-token').read_text().strip()},timeout=15)
    assert bootstrap.status_code == 200 or bootstrap.json().get('error_code') == 'bootstrap_closed'
    login = browser.post(web+'/api/auth/login',json={
        'username':'compose-check','password':'compose-acceptance-password-123'},timeout=15)
    assert login.status_code == 200
    browser.headers['x-csrf-token'] = login.json()['data']['csrf']
    status = browser.get(web+'/api/status',timeout=15).json()['data']
    assert status['service'] == 'media-gateway'
    assert status['tmdb_configured'] is False
    assert requests.get('http://127.0.0.1:18412/UI/Dashboard',timeout=10).status_code == 200
    torrents = requests.get('http://127.0.0.1:18411/api/v2/torrents/info',timeout=10)
    assert torrents.status_code == 200 and torrents.json() == []
    provider = requests.post(web+'/internal/provider',headers={
        'x-media-service-token':(private/'control-token').read_text().strip()},json={
        'operation':'jackett_search','arguments':{'query':'acceptance-no-sites','kind':'movie'}},timeout=15)
    assert provider.status_code == 200 and provider.json()['data']['diagnostics'][0]['status'] == 'no_configured_sites'
    token = browser.post(web+'/api/tokens',json={'name':'compose-acceptance'},timeout=15).json()['data']['token']
    async def check():
        async with Client('http://127.0.0.1:18410/mcp',auth=token) as client:
            jobs = await client.call_tool('media_list_jobs')
            assert jobs.structured_content['data']['jobs'] == []
            status = await client.call_tool('media_status')
            assert status.structured_content['tmdb_configured'] is False
    asyncio.run(check())
    print(json.dumps({'acceptance':'passed','setup_groups':['local','cloud'],
        'web_login':True,'mcp_authenticated':True,'qBittorrent_reachable':True,'Jackett_reachable':True,
        'torrent_count':0,'model_and_sites':'intentionally_unconfigured','real_media_used':False}))
