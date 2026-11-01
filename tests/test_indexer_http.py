"""Fresh administrator/CSRF authority across local and cloud indexer settings."""
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

import test_gateway
from media_mcp.platform.api import create_app
from media_mcp.platform.gateway import create_gateway


class IndexerHTTPTests(unittest.TestCase):
    setUp=test_gateway.GatewayTests.setUp

    def test_admin_only_list_and_mutations_recheck_source_authority_and_csrf(self):
        manager=Mock();manager.invoke.return_value={'indexers':[],'revision':0}
        with patch('media_mcp.adapters.jackett_admin.JackettAdmin',return_value=manager),patch.dict('os.environ',{'MEDIA_EXECUTION_ONLY':'false','MEDIA_CATALOG_URL':''}):
            apps=[create_app(self.accounts,self.records),create_gateway(self.remote,catalog=Mock(),http_request=self.transport.request)]
            for app in apps:
                with self.subTest(app=app),TestClient(app,base_url='http://media.test',client=('127.0.0.1',1234)) as client:
                    manager.reset_mock()
                    denied=client.get('/api/settings/jackett');self.assertEqual(denied.status_code,401)
                    client.post('/api/auth/login',json={'username':'alice','password':'alice-password-123'})
                    self.assertEqual(client.get('/api/settings/jackett').status_code,403)
                    manager.invoke.assert_not_called()
                    login=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'}).json()['data']
                    self.assertEqual(client.get('/api/settings/jackett').status_code,200)
                    manager.reset_mock()
                    payload={'action':'test','site':'public'}
                    self.assertEqual(client.post('/api/settings/jackett',json=payload).status_code,403)
                    manager.invoke.assert_not_called()
                    client.headers['x-csrf-token']=login['csrf']
                    self.assertEqual(client.post('/api/settings/jackett',json=payload).status_code,200)
                    self.assertEqual(manager.invoke.call_args.kwargs['action'],'test')
                    self.assertEqual(client.post('/api/settings/jackett',json={'action':'remove','site':'public','revision':'a'*64}).status_code,400)
                    self.assertEqual(client.post('/api/settings/jackett',json={'action':'test','site':'../private'}).status_code,400)
                    self.assertEqual(client.get('/assets/jackett.js').status_code,200)
