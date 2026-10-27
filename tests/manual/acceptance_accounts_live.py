"""Disposable account lifecycle and real cloud MCP token revocation."""
import json
import os
from pathlib import Path
import secrets

import requests


def main():
    assert os.environ.get('MEDIA_ACCEPTANCE')=='isolated-container'
    assert (Path('/acceptance-private')/'.acceptance').is_file()
    base='http://127.0.0.1:18514'
    def login(name,password):
        client=requests.Session()
        response=client.post(base+'/api/auth/login',json={'username':name,'password':password},timeout=15)
        response.raise_for_status()
        client.headers['x-csrf-token']=response.json()['data']['csrf']
        return client
    admin=login('compose-check','compose-acceptance-password-123')
    name='qa-account-'+secrets.token_hex(4)
    old='disposable-account-password-123'
    new='disposable-account-password-456'
    response=admin.post(base+'/api/users',json={'username':name,'password':old,
        'can_download':False,'can_manage_media':False},timeout=15)
    response.raise_for_status()
    ident=response.json()['data']['id']
    try:
        user=login(name,old)
        assert user.get(base+'/api/users',timeout=15).status_code==403
        assert user.patch(base+'/api/users/'+ident,json={'role':'admin','enabled':True},timeout=15).status_code==403
        user.post(base+'/api/auth/password',json={'old_password':old,'new_password':new},timeout=15).raise_for_status()
        assert user.get(base+'/api/auth/me',timeout=15).status_code==401
        changed=login(name,new)
        changed.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()
        assert changed.get(base+'/api/auth/me',timeout=15).status_code==401
        response=admin.post(base+'/api/tokens',json={'name':'disposable-functional-mcp'},timeout=15)
        response.raise_for_status()
        token=response.json()['data']
        try:
            url='http://127.0.0.1:18510/mcp'
            headers={'authorization':'Bearer '+token['token'],'accept':'application/json, text/event-stream'}
            payload={'jsonrpc':'2.0','id':1,'method':'tools/call',
                'params':{'name':'media_list_jobs','arguments':{}}}
            before=requests.post(url,headers=headers,json=payload,timeout=20)
            assert before.status_code==200
            assert before.json()['result']['structuredContent']['success']
            assert requests.post(url,json=payload,timeout=15).status_code==401
        finally:
            admin.delete(base+'/api/tokens/'+token['id'],json={},timeout=15).raise_for_status()
        assert requests.post(url,headers=headers,json=payload,timeout=15).status_code==401
        print(json.dumps({'acceptance':'passed','ordinary_user_cannot_edit_users_or_promote_self':True,
            'password_change_revokes_session':True,'new_password_login_and_logout':True,
            'real_mcp_without_token':401,'real_mcp_after_token_revoke':401}))
    finally:
        admin.patch(base+'/api/users/'+ident,json={'role':'user','enabled':False,
            'can_download':False,'can_manage_media':False},timeout=15).raise_for_status()
        admin.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()


if __name__=='__main__':
    main()
