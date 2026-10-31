import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from media_mcp.platform.accounts import Accounts
from media_mcp.platform.api import create_app
from media_mcp.platform.gateway import create_gateway, provider_call
from media_mcp.platform.transport import Remote
from media_mcp.storage.media import _client
from media_mcp.storage.records import Records


class Response:
    def __init__(self, response):
        self.status_code, self.headers, self.content = response.status_code, response.headers, response.content
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        yield self.content


class InProcessHTTP:
    def __init__(self, app):
        self.app = app
    def request(self, method, url, **kwargs):
        kwargs.pop('stream', None)
        kwargs.pop('allow_redirects', None)
        with TestClient(self.app, base_url='http://127.0.0.1', client=('127.0.0.1', 1234)) as client:
            return Response(client.request(method, url, **kwargs))
    def post(self, url, **kwargs):
        return self.request('POST', url, **kwargs)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        env = patch.dict(os.environ, {
            'MEDIA_DB_PATH':str(root/'state/media.sqlite3'), 'MEDIA_WEB_PUBLIC':'false',
            'MEDIA_WEB_SECURE_COOKIE':'false', 'MEDIA_ALLOWED_HOSTS':'media.test',
            'MEDIA_WEB_PUBLIC_URL':'https://media.test', 'MEDIA_WEB_TRUSTED_PROXIES':'',
            'MEDIA_DOWNLOAD_ROOT':str(root/'downloads'), 'MEDIA_LIBRARY_ROOT':str(root/'library'),
            'MEDIA_CONTROL_TOKEN':'test-control-token-32-characters-long',
            'TMDB_API_KEY':'',
        })
        env.start()
        self.addCleanup(env.stop)
        self.accounts = Accounts(_client(None))
        self.accounts.initialize()
        self.admin = self.accounts.bootstrap('owner','owner-password-123','x'*32,'x'*32)
        self.alice = self.accounts.create_user(self.admin,'alice','alice-password-123')
        self.records = Records(self.accounts.db)
        self.records.initialize()
        self.local_app = create_app(self.accounts, self.records)
        self.transport = InProcessHTTP(self.local_app)
        self.remote = Remote('http://127.0.0.1:18213', session=self.transport)

    def test_login_limits_separate_gateway_clients_and_ignore_forged_headers(self):
        with patch.dict(os.environ, {'MEDIA_WEB_PUBLIC':'true'}):
            app = create_gateway(self.remote,catalog=Mock(),http_request=self.transport.request)
        with TestClient(app,base_url='https://media.test',client=('198.51.100.1',1000)) as attacker:
            for index in range(10):
                response=attacker.post('/api/auth/login',json={
                    'username':'missing'+str(index),'password':'wrong-password-123'},headers={
                    'x-media-client-ip':'203.0.113.'+str(index+1),
                    'x-forwarded-for':'203.0.113.'+str(index+1)})
                self.assertEqual(response.status_code,401,response.text)
            self.assertEqual(attacker.post('/api/auth/login',json={
                'username':'owner','password':'owner-password-123'}).status_code,429)
        with TestClient(app,base_url='https://media.test',client=('203.0.113.2',1001)) as legitimate:
            self.assertEqual(legitimate.post('/api/auth/login',json={
                'username':'owner','password':'owner-password-123'}).status_code,200)

    def test_local_login_rejects_untrusted_gateway_identity(self):
        with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',1000)) as client:
            payload={'username':'owner','password':'owner-password-123'}
            self.assertEqual(client.post('/api/auth/login',json=payload,headers={
                'x-media-client-ip':'203.0.113.2'}).status_code,403)
            headers={'x-media-service-token':os.environ['MEDIA_CONTROL_TOKEN'],
                     'x-media-client-ip':'203.0.113.2,198.51.100.1'}
            self.assertEqual(client.post('/api/auth/login',json=payload,headers=headers).status_code,400)
            headers['x-media-client-ip']='203.0.113.2'
            self.assertEqual(client.post('/api/auth/login',json=payload,headers=headers).status_code,200)

    def test_task_progress_and_paginated_results_cross_cloud_without_mutations(self):
        row=self.records.put('library_task',{'owner':self.admin.id,'action':'auto','automatic':True,
            'collection_id':None,'files':[],'total':0,'results':[],'summary':{},'work':[]},'completed')
        app=create_gateway(self.remote,catalog=Mock(),http_request=self.transport.request)
        with TestClient(app,base_url='http://media.test',client=('127.0.0.1',1234)) as client:
            login=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'}).json()['data']
            headers={'x-csrf-token':login['csrf']}
            before=self.records.db.execute('SELECT COUNT(*) FROM media_mcp_record').scalar()
            for operation,args in [('library_tasks',{}),('library_task_status',{'job_id':row['id']}),
                                   ('library_task_details',{'job_id':row['id'],'limit':25}),
                                   ('library_auto_status',{'idempotency_key':'never-submitted-001'}),
                                   ('download_submission_status',{'idempotency_key':'never-submitted-001'})]:
                response=client.post('/api/command',json={'operation':operation,'arguments':args},headers=headers)
                self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.post('/api/command',json={'operation':'library_task_details',
                'arguments':{'job_id':row['id'],'limit':51}},headers=headers).status_code,400)
            self.assertEqual(self.records.db.execute('SELECT COUNT(*) FROM media_mcp_record').scalar(),before)
            self.assertEqual(client.get('/assets/tasks.js').status_code,200)

    def test_cloud_login_cookie_csrf_and_user_isolation(self):
        with patch.dict(os.environ, {'MEDIA_WEB_PUBLIC':'true'}):
            app = create_gateway(self.remote, catalog=Mock(), http_request=self.transport.request)
        with TestClient(app,base_url='https://media.test',client=('192.0.2.1',1234)) as alice, TestClient(app,base_url='https://media.test',client=('192.0.2.2',1234)) as stranger:
            result = alice.post('/api/auth/login',json={'username':'alice','password':'alice-password-123'})
            self.assertEqual(result.status_code,200,result.text)
            self.assertIn('Secure',result.headers['set-cookie'])
            csrf = result.json()['data']['csrf']
            self.assertEqual(alice.get('/api/auth/me').json()['data']['user']['username'],'alice')
            with patch.dict(os.environ, {'TMDB_API_KEY':''}):
                self.assertFalse(alice.get('/api/status').json()['data']['tmdb_configured'])
            self.assertEqual(stranger.get('/api/auth/me').status_code,401)
            self.assertEqual(alice.get('/api/users').status_code,403)
            self.assertEqual(alice.post('/api/command',json={'operation':'jobs'}).status_code,403)
            self.assertEqual(alice.post('/api/command',json={'operation':'jobs'},headers={'x-csrf-token':csrf}).status_code,200)
            self.assertEqual(alice.get('/api/not-a-proxy').status_code,400)
            self.assertEqual(alice.post('/api/command',json={'operation':'jobs'},headers={
                'x-csrf-token':csrf,'origin':'https://attacker.invalid'}).status_code,403)

    def test_control_requires_both_service_identity_and_revocable_user_identity(self):
        token = self.accounts.create_api_token(self.admin,'test-client')['token']
        payload = {'operation':'jobs','arguments':{}}
        with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
            self.assertEqual(client.post('/internal/command',json=payload).status_code,403)
            headers = {'x-media-service-token':os.environ['MEDIA_CONTROL_TOKEN']}
            self.assertEqual(client.post('/internal/command',json=payload,headers=headers).status_code,401)
            headers['x-media-user-token'] = token
            self.assertEqual(client.post('/internal/command',json=payload,headers=headers).status_code,200)
            info = self.remote.call('/internal/token-info',{},user_token=token)
            self.assertEqual(info['user']['id'],self.admin.id)
            self.accounts.change_password(self.admin,'owner-password-123','another-password-123')
            self.assertEqual(client.post('/internal/command',json=payload,headers=headers).status_code,401)

    def test_cloud_provider_is_not_a_general_url_fetcher(self):
        tmdb, jackett = Mock(), Mock()
        app = create_gateway(self.remote,catalog=Mock(),tmdb=tmdb,jackett=jackett,
                             http_request=self.transport.request)
        with TestClient(app,base_url='http://media.test',client=('127.0.0.1',1234)) as client:
            command = {'operation':'tmdb','arguments':{'path':'../secrets','params':{}}}
            self.assertEqual(client.post('/internal/provider',json=command).status_code,403)
            headers = {'x-media-service-token':os.environ['MEDIA_CONTROL_TOKEN']}
            self.assertEqual(client.post('/internal/provider',json=command,headers=headers).status_code,400)
            tmdb.get.assert_not_called()
            tmdb.get.return_value = {'results':[]}
            command['arguments']['path'] = 'trending/movie/week'
            command['arguments']['params'] = {'page':2}
            self.assertEqual(client.post('/internal/provider',json=command,headers=headers).status_code,200)
            tmdb.get.assert_called_once_with('trending/movie/week', page=2)
            command['arguments']['params'] = {'page':True}
            self.assertEqual(client.post('/internal/provider',json=command,headers=headers).status_code,400)

    def test_mutation_transport_does_not_retry_on_lost_response(self):
        session = Mock()
        import requests
        session.post.side_effect = requests.Timeout()
        remote = Remote('https://media.test',session=session)
        with self.assertRaisesRegex(RuntimeError,'remote_service_unavailable'):
            remote.call('/internal/command',{'operation':'start'},user_token='test-user-token')
        self.assertEqual(session.post.call_count,1)

    def test_cloud_mcp_uses_local_user_authority_and_rechecks_revocation(self):
        from media_mcp.server import create_server
        from media_mcp.platform.accounts import Actor
        from media_mcp.platform.service import PlatformService
        from media_mcp.platform.remote_mcp import RemoteMCPService, RemoteTokenVerifier
        actor = Actor(self.alice['id'],'alice','user')
        owned = PlatformService(actor,self.accounts,self.records).service.records.put(
            'acquisition',{'identity':{'title_id':'movie:1'}},'queued')
        self.records.put('acquisition',{},'queued')
        token = self.accounts.create_api_token(actor,'test-mcp')['token']
        direct = self.remote.call('/internal/command',{'operation':'jobs','arguments':{}},user_token=token)
        self.assertEqual([job['job_id'] for job in direct['jobs']],[owned['id']])
        app = create_server(RemoteMCPService(self.remote),RemoteTokenVerifier(self.remote)).http_app(
            path='/mcp',stateless_http=True,json_response=True)
        with TestClient(app,base_url='http://127.0.0.1') as client:
            headers = {'authorization':'Bearer '+token, 'accept':'application/json, text/event-stream'}
            response = client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,
                'method':'tools/call','params':{'name':'media_list_jobs','arguments':{}}})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['result']['structuredContent'].get('success'),
                            response.json()['result']['structuredContent'])
            jobs = response.json()['result']['structuredContent']['data']['jobs']
            self.assertEqual([job['job_id'] for job in jobs],[owned['id']])
            status = client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,
                'method':'tools/call','params':{'name':'media_status','arguments':{}}})
            self.assertEqual(status.json()['result']['structuredContent']['service'],'media-mcp')
            self.assertIn('worker_ready',status.json()['result']['structuredContent'])
            self.accounts.update_user(self.admin,actor.id,enabled=False,role='user')
            self.assertEqual(client.post('/mcp',headers=headers,json={}).status_code,401)
