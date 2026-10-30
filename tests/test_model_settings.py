"""Admin-owned model settings persist across processes and hot-reload per call."""
import unittest
from unittest.mock import Mock, patch
from starlette.testclient import TestClient
from tests import test_platform, test_gateway
from media_mcp.platform.api import create_app
from media_mcp.platform.gateway import create_gateway
from media_mcp.storage.model_settings import ModelSettings
from media_mcp.ingest.clients.codex import CodexMediaClient
from media_mcp.subtitle.clients.codex import CodexSubtitleClient
from media_mcp.ingest.clients.library_analysis import LibraryAnalysisClient
from media_mcp.adapters.codex import CodexClient

CHOICES = [{'model':'gpt-6.1-terra','efforts':['low','medium']},
           {'model':'fixture-model','efforts':['low']}]


class ModelSettingsTests(unittest.TestCase):
    setUp = test_platform.PlatformTests.setUp

    def client(self, name='owner', password='owner-password-123'):
        client=TestClient(create_app(self.accounts,self.records),base_url='http://127.0.0.1',client=('127.0.0.1',1234))
        result=client.post('/api/auth/login',json={'username':name,'password':password}).json()['data']
        client.headers['x-csrf-token']=result['csrf']
        self.addCleanup(client.close)
        return client

    def test_admin_save_persists_and_stale_edits_cannot_overwrite(self):
        client=self.client()
        policy=client.get('/api/settings/model').json()['data']
        self.assertEqual(('gpt-6.1-terra','low',0),(policy['model'],policy['effort'],policy['revision']))
        with patch('media_mcp.storage.model_settings.available_models',return_value=CHOICES):
            response=client.post('/api/settings/model',json={**{k:policy[k] for k in ('model','effort','revision')},'effort':'medium'})
            self.assertEqual(200,response.status_code)
            self.assertEqual('medium',ModelSettings().get()['effort'])
            stale=client.post('/api/settings/model',json={'model':policy['model'],'effort':'low','revision':0})
            self.assertEqual('model_settings_changed',stale.json()['error_code'])
        self.assertEqual(1,ModelSettings().get()['revision'])
        self.assertEqual(1,self.db.execute("SELECT COUNT(*) FROM platform_event WHERE action='model_settings_updated'").scalar())

    def test_auth_csrf_and_input_validation_leave_saved_policy_unchanged(self):
        client=self.client('alice','alice-password-123')
        for path in ('/api/settings/model','/api/settings/model/options'):
            self.assertEqual(403,client.get(path).status_code)
        self.assertEqual(403,client.post('/api/settings/model',json={'model':'gpt-6.1-terra','effort':'low','revision':0}).status_code)
        client=self.client()
        with patch('media_mcp.storage.model_settings.available_models',return_value=CHOICES):
            for body in ({'model':'unknown-model','effort':'low','revision':0},
                         {'model':'fixture-model','effort':'medium','revision':0},
                         {'model':'gpt-6.1-terra','effort':'high','revision':0},
                         {'model':'../escape','effort':'low','revision':0},
                         {'model':'gpt-6.1-terra','effort':'low','revision':True}):
                self.assertEqual(400,client.post('/api/settings/model',json=body).status_code)
        client.headers['x-csrf-token']='invalid'
        self.assertEqual(403,client.post('/api/settings/model',json={'model':'gpt-6.1-terra','effort':'low','revision':0}).status_code)
        self.assertEqual(0,ModelSettings().get()['revision'])

    def test_saved_changes_reach_existing_clients_without_rebuild_or_new_instance(self):
        clients=[kind(bearer_token='fixture',max_retries=0) for kind in
                 (CodexMediaClient,CodexSubtitleClient,LibraryAnalysisClient,CodexClient)]
        requests=[]
        def connect(deadline):
            session=Mock()
            def rpc(method,params):
                if method=='thread/start':
                    requests.append([params['model'],None])
                    return {'thread':{'id':'thread'}}
                if method=='turn/start':
                    requests[-1][1]=params['effort']
                    return {'turn':{'id':'turn'}}
                return {'data':[]}
            session.rpc.side_effect=rpc
            session.wait_turn.return_value='{}'
            return session
        for client in clients:
            client._connect=connect
            client.run_json('fixture',{})
        self.assertEqual([['gpt-6.1-terra','low']]*4,requests)
        ModelSettings().save(model='fixture-model',effort='low',revision=0,actor=self.admin,accounts=self.accounts)
        for client in clients:client.run_json('fixture',{})
        self.assertEqual([['fixture-model','low']]*4,requests[4:])
        ModelSettings().save(model='gpt-6.1-terra',effort='medium',revision=1,actor=self.admin,accounts=self.accounts)
        for client in clients:client.run_json('fixture',{})
        self.assertEqual([['gpt-6.1-terra','medium']]*4,requests[8:])

    def test_setting_change_during_call_does_not_change_that_calls_snapshot(self):
        client=CodexClient(bearer_token='fixture',max_retries=0)
        session=Mock();seen=[]
        def rpc(method,params):
            if method=='thread/start':
                seen.append(params['model'])
                ModelSettings().save(model='fixture-model',effort='medium',revision=0,actor=self.admin,accounts=self.accounts)
                return {'thread':{'id':'thread'}}
            if method=='turn/start':
                seen.append(params['effort'])
                return {'turn':{'id':'turn'}}
            return {'data':[]}
        session.rpc.side_effect=rpc;session.wait_turn.return_value='{}'
        with patch.object(client,'_connect',return_value=session):client.run_json('fixture',{})
        self.assertEqual(['gpt-6.1-terra','low'],seen)
        self.assertEqual('medium',ModelSettings().get()['effort'])


class ModelGatewayTests(unittest.TestCase):
    setUp = test_gateway.GatewayTests.setUp

    def test_cloud_forwards_admin_policy_and_preserves_csrf(self):
        app=create_gateway(self.remote,catalog=Mock(),http_request=self.transport.request)
        with TestClient(app,base_url='http://media.test',client=('127.0.0.1',1234)) as client:
            login=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'}).json()['data']
            policy=client.get('/api/settings/model')
            self.assertEqual(200,policy.status_code)
            body={'model':'gpt-6.1-terra','effort':'medium','revision':0}
            with patch('media_mcp.storage.model_settings.available_models',return_value=CHOICES):
                self.assertEqual(200,client.get('/api/settings/model/options').status_code)
                self.assertEqual(403,client.post('/api/settings/model',json=body).status_code)
                result=client.post('/api/settings/model',json=body,headers={'x-csrf-token':login['csrf']})
                self.assertEqual(200,result.status_code)
                self.assertEqual('medium',ModelSettings().get()['effort'])


if __name__=='__main__':unittest.main()
