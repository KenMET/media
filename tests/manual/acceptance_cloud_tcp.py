"""Read-only live discovery over fixed disposable TCP ports; no downloads submitted."""
import asyncio
import json
import os
from pathlib import Path

import requests
from fastmcp import Client


def main():
    if os.environ.get('MEDIA_ACCEPTANCE') != 'isolated-container' or not Path('/acceptance-private/.acceptance').is_file():
        raise SystemExit('Refusing unmarked acceptance state')
    web='http://127.0.0.1:18614'
    browser=requests.Session();browser.trust_env=False
    response=browser.post(web+'/api/auth/login',json={
        'username':'cloud-check','password':'isolated-cloud-password-123'},timeout=15)
    assert response.status_code==200,response.status_code
    browser.headers['x-csrf-token']=response.json()['data']['csrf']
    def command(name,arguments):
        result=browser.post(web+'/api/command',json={'operation':name,'arguments':arguments},timeout=90).json()
        assert result.get('success'),result.get('error_code')
        return result['data']
    title_ids=[]
    for query in ('Sintel','辛特尔'):
        titles=command('search_titles',{'query':query,'kind':'movie'})['titles']
        assert titles
        title_ids.append(titles[0]['title_id'])
    detail=browser.get(web+'/api/detail',params={'title_id':title_ids[0]},timeout=45).json()
    assert detail.get('success') and detail['data']['title_id']==title_ids[0]
    discover=browser.get(web+'/api/discover',params={'source':'simkl','kind':'movie','window':'day'},timeout=45).json()
    assert discover.get('success') and discover['data']['status']=='ready'
    release=command('search_releases',{'title_id':title_ids[0]})
    assert release['diagnostics']
    sites=[{'site':site['site'],'status':site['status']} for item in release['diagnostics'] for site in item['sites']]
    assert any(site['status']=='ok' for site in sites),sites
    # The same session is authoritative on NAS, where discovery is disabled.
    local=requests.Session();local.trust_env=False
    local.cookies.update(browser.cookies)
    local.headers['x-csrf-token']=browser.headers['x-csrf-token']
    forbidden=local.post('http://127.0.0.1:18613/api/command',json={
        'operation':'search_titles','arguments':{'query':'Sintel','kind':'movie'}},timeout=15).json()
    assert not forbidden.get('success') and forbidden.get('error_code')=='cloud_search_only'
    issued=browser.post(web+'/api/tokens',json={'name':'cloud-tcp-acceptance'},timeout=15).json()
    assert issued.get('success')
    token=issued['data']['token']
    async def mcp_check():
        async with Client('http://127.0.0.1:18610/mcp',auth=token) as client:
            result=await client.call_tool('media_search_titles',{'query':'Sintel','kind':'movie'})
            assert result.structured_content['success'] and result.structured_content['data']['titles']
            jobs=await client.call_tool('media_list_jobs')
            assert jobs.structured_content['success']
    asyncio.run(mcp_check())
    sealed=local.get('http://127.0.0.1:18613/internal/pairing',timeout=15).json()
    assert not sealed.get('success') and sealed.get('error_code')=='pairing_closed'
    print(json.dumps({'acceptance':'passed','transport':'real TCP HTTP and MCP',
        'control_port':18613,'cloud_url_configured':False,'local_execution_only':True,
        'automatic_pairing_sealed':True,'real_title_search':['English','Chinese'],
        'real_discover':'SIMKL day','real_detail':'TMDB','public_indexer_statuses':sites,
        'downloads_submitted':0,'production_media_used':False},ensure_ascii=False))


if __name__=='__main__':
    main()
