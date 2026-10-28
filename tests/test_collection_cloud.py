import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

from starlette.testclient import TestClient
from media_mcp.platform.gateway import create_gateway
from media_mcp.storage.media import upsert_media_link
import test_gateway
from test_collections import Provider


class CollectionCloudTests(unittest.TestCase):
    setUp=test_gateway.GatewayTests.setUp

    def test_identification_uses_cloud_provider_and_requires_management_not_download(self):
        source=Path(os.environ['MEDIA_DOWNLOAD_ROOT']);source.mkdir()
        library=Path(os.environ['MEDIA_LIBRARY_ROOT']);(library/'series/Test/第01季').mkdir(parents=True)
        src=source/'Test.S01E01.mkv';src.write_bytes(b'fixture')
        target=library/'series/Test/第01季/Test - S01E01 - 2024.mkv';os.link(src,target)
        upsert_media_link(None,str(src),str(target),status='linked')
        alice=self.accounts.actor_by_id(self.alice['id'])
        self.accounts.update_user(self.admin,alice.id,enabled=True,role='user',can_download=False,can_manage_media=True)
        provider=Provider()
        app=create_gateway(self.remote,tmdb=provider,jackett=Mock(),catalog=Mock(),http_request=self.transport.request)
        with TestClient(app,base_url='http://media.test',client=('127.0.0.1',9000)) as client:
            login=client.post('/api/auth/login',json={'username':'alice','password':'alice-password-123'}).json()['data']
            client.headers['x-csrf-token']=login['csrf']
            def command(operation,args):
                response=client.post('/api/command',json={'operation':operation,'arguments':args})
                self.assertEqual(response.status_code,200,response.text)
                return response.json()['data']
            collection=command('collections',{})['collections'][0]['collection_id']
            with patch.dict(os.environ,MEDIA_EXECUTION_ONLY='true'),patch('media_mcp.adapters.tmdb.TMDB.get',side_effect=AssertionError('NAS provider call')):
                plan=command('collection_identify',{'collection_id':collection,'title_id':'tv:123'})
            self.assertEqual(plan['identity']['title_id'],'tv:123')
            identified=command('collection_identity_apply',{'plan_id':plan['plan_id']})
            detail=command('collection',{'collection_id':identified['collection_id']})
            self.assertEqual(detail['poster_url'],'https://image.tmdb.org/t/p/w342/test.jpg')
            self.assertTrue(detail['identified'])

    def test_internal_evidence_endpoint_is_not_public(self):
        with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',9000)) as client:
            response=client.post('/internal/collection',json={'action':'context','collection_id':'a'*32})
            self.assertEqual(response.status_code,403)

if __name__=='__main__':unittest.main()
