"""Exercise media-only permission and real subtitle maintenance on fresh sample."""
import hashlib
import json
import os
from pathlib import Path
import sys

import requests


def main():
    assert os.environ.get('MEDIA_ACCEPTANCE')=='isolated-container'
    assert os.environ.get('QBITTORRENT_URL')=='http://127.0.0.1:18511'
    assert Path('/state/.acceptance').is_file() and Path('/data/.acceptance').is_file()
    base='http://127.0.0.1:18514'
    original=json.loads(Path('/state/live-download.json').read_text())
    from media_mcp.storage.records import Records
    records=Records()
    def login(name,password):
        client=requests.Session()
        response=client.post(base+'/api/auth/login',json={'username':name,'password':password},timeout=15)
        response.raise_for_status()
        client.headers['x-csrf-token']=response.json()['data']['csrf']
        return client
    def command(client,name,args):
        response=client.post(base+'/api/command',json={'operation':name,'arguments':args},timeout=20)
        assert response.status_code < 500, 'Service unavailable during command'
        return response.json()
    admin=login('compose-check','compose-acceptance-password-123')
    private=Path('/state/live-media-management.json')
    key='fresh-subtitle-maintenance-20261026'
    if not private.is_file():
        assert '--submit' in sys.argv
        assert records.get(original['job_id'],'acquisition')['state']=='completed'
        assert len(command(admin,'jobs',{})['data']['jobs'])==1
        row=records.db.execute("SELECT * FROM media_link WHERE status='linked'").mappings().one()
        source=Path(row['source_path'])
        target=Path(row['target_path'])
        assert source.resolve().is_relative_to(Path('/data/downloads'))
        assert os.path.samefile(source,target)
        existing=next((user for user in admin.get(base+'/api/users',timeout=15).json()['data']['users']
            if user['username']=='media-manager-test'),None)
        if existing:
            user_id=existing['id']
            admin.patch(base+'/api/users/'+user_id,json={'role':'user','enabled':True,
                'can_download':False,'can_manage_media':True},timeout=15).raise_for_status()
        else:
            response=admin.post(base+'/api/users',json={'username':'media-manager-test',
                'password':'media-manager-test-password-123','can_download':False,'can_manage_media':True},timeout=15)
            response.raise_for_status()
            user_id=response.json()['data']['id']
        manager=login('media-manager-test','media-manager-test-password-123')
        assert len(command(manager,'media',{})['data']['media'])==1
        assert not command(manager,'job',{'job_id':original['job_id']})['success']
        assert manager.post(base+'/api/command',json={'operation':'search_releases',
            'arguments':{'title_id':original['title_id']}},timeout=15).status_code==403
        args={'media_id':row['id'],'idempotency_key':key}
        first=command(manager,'subtitles',args)['data']
        second=command(manager,'subtitles',args)['data']
        assert first['job_id']==second['job_id']
        saved={'job_id':first['job_id'],'user_id':user_id,'media_id':row['id'],
            'source':str(source),'target':str(target),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        private.write_text(json.dumps(saved));private.chmod(0o600)
        print(json.dumps({'submitted':True,'media_only_account':True,'same_key_single_subtitle_job':True,
            'job_id':first['job_id'],'download_permission_denied':True}))
    else:
        saved=json.loads(private.read_text())
        row=records.get(saved['job_id'],'acquisition')
        result={'job_id':row['id'],'stage':row['state'],'error_code':row['data'].get('error_code')}
        if '--verify' in sys.argv:
            assert row['state']=='completed',result
            manager=login('media-manager-test','media-manager-test-password-123')
            assert command(manager,'job',{'job_id':saved['job_id']})['success']
            assert not command(manager,'job',{'job_id':original['job_id']})['success']
            replay=command(manager,'subtitles',{'media_id':saved['media_id'],'idempotency_key':key})
            assert replay['data']['job_id']==saved['job_id']
            assert len(command(admin,'jobs',{})['data']['jobs'])==2
            assert os.path.samefile(saved['source'],saved['target'])
            assert hashlib.sha256(Path(saved['source']).read_bytes()).hexdigest()==saved['sha256']
            torrents=requests.get('http://127.0.0.1:18511/api/v2/torrents/info',timeout=15).json()
            assert len(torrents)==1 and torrents[0]['hash']==original['infohash']
            admin.patch(base+'/api/users/'+saved['user_id'],json={'role':'user','enabled':False,
                'can_download':False,'can_manage_media':True},timeout=15).raise_for_status()
            result.update(acceptance='passed',media_only_maintenance_completed=True,
                private_download_still_hidden=True,subtitle_replay_single_job=True,
                source_bytes_and_hardlink_preserved=True,torrent_count=len(torrents))
        print(json.dumps(result))
    admin.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()


if __name__=='__main__':
    main()
