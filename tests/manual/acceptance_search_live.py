"""Real TMDB + local gateway + Jackett public-site bilingual search, no download."""
import json
import os
from pathlib import Path
import requests
import sys


def main():
    assert os.environ.get('MEDIA_ACCEPTANCE') == 'isolated-container'
    private = Path('/acceptance-private')
    assert (private/'.acceptance').is_file()
    expected_job = json.loads((private/'live-download.json').read_text())['job_id']
    base = 'http://127.0.0.1:18414'
    ordinary = '--ordinary' in sys.argv
    client = requests.Session()
    login = client.post(base+'/api/auth/login',json={
        'username':'ux-download' if ordinary else 'compose-check',
        'password':'ux-acceptance-password-123' if ordinary else 'compose-acceptance-password-123'},timeout=15).json()
    assert login['success']
    client.headers['x-csrf-token'] = login['data']['csrf']
    def command(operation,arguments):
        result = client.post(base+'/api/command',json={'operation':operation,'arguments':arguments},timeout=60).json()
        assert result['success'], result.get('error_code')
        return result['data']
    before = command('jobs',{})['jobs']
    if ordinary:
        assert before == [] and login['data']['user']['can_download'] is True
        assert login['data']['user']['role'] == 'user'
    else:
        assert len(before) == 1 and before[0]['job_id'] == expected_job
    identities = []
    for query in ('Frieren','葬送的芙莉莲'):
        rows = command('search_titles',{'query':query,'kind':'tv'})['titles']
        title = next(row for row in rows if row['original_title'] == '葬送のフリーレン')
        identities.append(title['title_id'])
    assert identities[0] == identities[1]
    report = command('search_releases',{'title_id':identities[0],'season':1,'episodes':[1]})
    assert report['releases'], report['diagnostics']
    assert any(site['site'] == 'nyaasi' and site['status'] == 'ok'
               for query in report['diagnostics'] for site in query['sites'])
    plan = command('plan',{'release_id':report['releases'][0]['release_id']})
    assert plan['identity']['title_id'] == identities[0]
    assert plan['scope']['season'] == 1 and plan['scope']['episodes'] == [1]
    assert command('jobs',{})['jobs'] == before
    print(json.dumps({'acceptance':'passed','same_title_from_chinese_and_english':identities[0],
        'actor_role':'ordinary_download_user' if ordinary else 'admin',
        'public_site':'nyaasi','accepted_releases':len(report['releases']),
        'queries':[item['query'] for item in report['diagnostics']],
        'sample_names':[row['name'] for row in report['releases'][:2]],
        'plan_identity_and_scope_verified':True,'download_submitted':False},ensure_ascii=False))
    client.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()


if __name__ == '__main__':
    main()
