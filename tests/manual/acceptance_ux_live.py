"""Capability acceptance on the existing marked LOCAL test stack, no downloads."""
import json
import os
from pathlib import Path

import requests


def main():
    assert os.environ.get('MEDIA_ACCEPTANCE') == 'isolated-container'
    private = Path('/acceptance-private')
    assert (private/'.acceptance').is_file()
    manifest = json.loads((private/'live-download.json').read_text())
    base = 'http://127.0.0.1:18414'
    password = 'ux-acceptance-password-123'
    def login(username, password):
        client = requests.Session()
        response = client.post(base+'/api/auth/login',json={'username':username,'password':password},timeout=15)
        response.raise_for_status()
        data = response.json()['data']
        client.headers['x-csrf-token'] = data['csrf']
        return client, data['user']
    def command(client,operation,arguments):
        return client.post(base+'/api/command',json={'operation':operation,'arguments':arguments},timeout=20)
    admin,_ = login('compose-check','compose-acceptance-password-123')
    assert admin.get(base+'/api/auth/setup-status',timeout=15).json()['data'] == {'initialized':True}
    original = command(admin,'jobs',{}).json()['data']['jobs']
    assert len(original) == 1 and original[0]['job_id'] == manifest['job_id']
    users = admin.get(base+'/api/users',timeout=15).json()['data']['users']
    sessions = []
    for username,download,manage in (('ux-viewer',False,False),('ux-download',True,False),('ux-manager',False,True)):
        saved = next((row for row in users if row['username'] == username),None)
        values = {'role':'user','can_download':download,'can_manage_media':manage}
        if saved:
            result = admin.patch(base+'/api/users/'+saved['id'],json={**values,'enabled':True},timeout=15)
        else:
            result = admin.post(base+'/api/users',json={**values,'username':username,'password':password},timeout=15)
        assert result.status_code == 200, result.status_code
        client,actor = login(username,password)
        sessions.append(client)
        assert actor['can_download'] is download and actor['can_manage_media'] is manage
        assert client.get(base+'/api/users',timeout=15).status_code == 403
        assert command(client,'jobs',{}).json()['data']['jobs'] == []
        assert command(client,'job',{'job_id':manifest['job_id']}).json()['success'] is False
        visible = command(client,'media',{}).json()['data']['media']
        assert bool(visible) is manage
        if not download:
            for operation,arguments in (
                ('search_releases',{'title_id':manifest['title_id']}),
                ('plan',{'release_id':'a'*32}),
                ('start',{'plan_id':'a'*32,'revision':1,'idempotency_key':'ux-must-not-submit'}),
            ):
                rejected = command(client,operation,arguments)
                assert rejected.status_code == 403 and rejected.json()['error_code'] == 'download_permission_required'
        assert client.post(base+'/api/users',json={'username':'must-not-create','password':password},timeout=15).status_code == 403
    users = admin.get(base+'/api/users',timeout=15).json()['data']['users']
    download_user = next(row for row in users if row['username'] == 'ux-download')
    update = admin.patch(base+'/api/users/'+download_user['id'],json={
        'role':'user','enabled':True,'can_download':False,'can_manage_media':False},timeout=15)
    assert update.status_code == 200
    assert sessions[1].get(base+'/api/auth/me',timeout=15).status_code == 401
    assert admin.patch(base+'/api/users/'+download_user['id'],json={
        'role':'user','enabled':True,'can_download':True,'can_manage_media':False},timeout=15).status_code == 200
    assert len(command(admin,'jobs',{}).json()['data']['jobs']) == 1
    for client in (sessions[0],sessions[2],admin):
        client.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()
    print(json.dumps({'acceptance':'passed','capabilities_independent':True,
        'viewer_cannot_download_or_configure':True,'manager_can_read_library_not_private_jobs':True,
        'permission_change_revokes_session':True,'download_count_unchanged':1}))


if __name__ == '__main__':
    main()
