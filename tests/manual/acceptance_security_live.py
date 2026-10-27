"""Real TCP security checks against the fresh disposable local stack only."""
import json
import os
from pathlib import Path
import secrets

import requests
from requests.adapters import HTTPAdapter


class SourceAddress(HTTPAdapter):
    def __init__(self, address):
        self.address=address
        super().__init__()

    def init_poolmanager(self,*args,**kwargs):
        kwargs['source_address']=(self.address,0)
        return super().init_poolmanager(*args,**kwargs)


def main():
    assert os.environ.get('MEDIA_ACCEPTANCE')=='isolated-container'
    private=Path('/acceptance-private')
    assert (private/'.acceptance').is_file()
    manifest=json.loads((private/'live-download.json').read_text())
    base='http://127.0.0.1:18514'
    def session(address=None):
        client=requests.Session()
        client.trust_env=False
        if address:
            client.mount('http://',SourceAddress(address))
        return client
    def login(client,name,password):
        result=client.post(base+'/api/auth/login',json={'username':name,'password':password},timeout=15)
        result.raise_for_status()
        data=result.json()['data']
        client.headers['x-csrf-token']=data['csrf']
    def command(client,name,args):
        return client.post(base+'/api/command',json={'operation':name,'arguments':args},timeout=15)
    admin=session()
    login(admin,'compose-check','compose-acceptance-password-123')
    before=command(admin,'jobs',{}).json()['data']['jobs']
    assert len(before)==1 and before[0]['job_id']==manifest['job_id']
    suffix=secrets.token_hex(4)
    password='disposable-functional-test-password-123'
    users=[]
    clients=[]
    try:
        for purpose in ('budget','control'):
            name='qa-'+purpose+'-'+suffix
            response=admin.post(base+'/api/users',json={'username':name,'password':password,
                'can_download':False,'can_manage_media':False},timeout=15)
            response.raise_for_status()
            users.append((response.json()['data']['id'],name))
            client=session()
            login(client,name,password)
            clients.append(client)
        # A valid schema with whitespace is rejected before any provider network I/O,
        # but still consumes the account request budget. No quota burning of real users.
        for _ in range(30):
            result=command(clients[0],'search_titles',{'query':' ','kind':'movie'})
            assert result.status_code==400
        rejected=command(clients[0],'search_titles',{'query':' ','kind':'movie'})
        assert rejected.status_code==429 and rejected.json()['error_code']=='account_rate_limited'
        assert command(clients[1],'search_titles',{'query':' ','kind':'movie'}).status_code==400
        tokens=[]
        try:
            for _ in range(5):
                response=clients[0].post(base+'/api/tokens',json={'name':'disposable-test'},timeout=15)
                response.raise_for_status()
                tokens.append(response.json()['data']['id'])
            assert clients[0].post(base+'/api/tokens',json={'name':'over-limit'},timeout=15).status_code==429
        finally:
            for ident in tokens:
                clients[0].delete(base+'/api/tokens/'+ident,json={},timeout=15).raise_for_status()
        # Actual different loopback source sockets, not pretend forwarded IPs.
        segment=secrets.randbelow(200)+20
        attacker=session(f'127.77.{segment}.2')
        legitimate=session(f'127.77.{segment}.3')
        for index in range(10):
            response=attacker.post(base+'/api/auth/login',json={'username':f'missing-{suffix}-{index}',
                'password':password},headers={'x-media-client-ip':f'192.0.2.{index+1}',
                'x-forwarded-for':f'192.0.2.{index+1}','x-real-ip':f'192.0.2.{index+1}'},timeout=15)
            assert response.status_code==401
        assert attacker.post(base+'/api/auth/login',json={
            'username':users[1][1],'password':password},timeout=15).status_code==429
        login(legitimate,users[1][1],password)
        legitimate.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()
        forged=requests.post('http://127.0.0.1:18513/api/auth/login',json={
            'username':users[1][1],'password':password},headers={'x-media-client-ip':'192.0.2.1'},timeout=15)
        assert forged.status_code==403
        after=command(admin,'jobs',{}).json()['data']['jobs']
        assert [job['job_id'] for job in after]==[manifest['job_id']]
        print(json.dumps({'acceptance':'passed','real_tcp_source_isolation':True,
            'forged_headers_do_not_bypass_limits':True,'direct_forged_gateway_identity_rejected':403,
            'account_search_rate_limit':429,'other_account_unaffected':True,'token_creation_limit':429,
            'temporary_tokens_revoked':len(tokens),'acquisition_count':len(after)}))
    finally:
        for ident,_ in users:
            admin.patch(base+'/api/users/'+ident,json={'role':'user','enabled':False,
                'can_download':False,'can_manage_media':False},timeout=15).raise_for_status()
        admin.post(base+'/api/auth/logout',json={},timeout=15).raise_for_status()


if __name__=='__main__':
    main()
