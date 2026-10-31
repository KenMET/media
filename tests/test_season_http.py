"""Cloud discovery and NAS-owned explicit consent over the authenticated HTTP bridge."""
import os
import unittest
from unittest.mock import Mock,patch
from starlette.testclient import TestClient
import test_gateway
from media_mcp.platform.gateway import create_gateway


class SeasonHTTPTests(unittest.TestCase):
    setUp=test_gateway.GatewayTests.setUp

    def test_cloud_one_shot_subscription_and_internal_service_boundary(self):
        tmdb,indexer=Mock(),Mock()
        tmdb.detail.return_value={'title_id':'tv:1','kind':'tv','tmdb_id':1,'title':'Show','original_title':'Show'}
        tmdb.get.return_value={'episodes':[{'episode_number':1,'air_date':'2020-01-01'}]}
        indexer.search.return_value={'releases':[{'name':'Show S01 1080p','resolution':1080,'seeders':2,
            'download_url':'magnet:?xt=urn:btih:'+'a'*40}], 'diagnostics':[{'site':'fixture','status':'ok','raw_count':1}]}
        indexer.torrent.side_effect=lambda url:url
        app=create_gateway(self.remote,catalog=Mock(),tmdb=tmdb,jackett=indexer,http_request=self.transport.request)
        with TestClient(app,base_url='http://media.test',client=('127.0.0.1',1234)) as client:
            login=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'}).json()['data']
            args={'title_id':'tv:1','season':1,'resolution':1080,'idempotency_key':'http-season-request'}
            response=client.post('/api/command',json={'operation':'season_acquire','arguments':args})
            self.assertEqual(response.status_code,403)
            headers={'x-csrf-token':login['csrf']}
            response=client.post('/api/command',json={'operation':'season_acquire','arguments':args},headers=headers)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()['data']['job_ids']),1)
            created=client.post('/api/command',json={'operation':'subscription_create','arguments':args},headers=headers)
            self.assertEqual(created.status_code,200,created.text)
            row=created.json()['data']
            changed=client.post('/api/command',json={'operation':'subscription_change','arguments':{
                'request_id':row['request_id'],'revision':row['revision'],'state':'paused'}},headers=headers)
            self.assertEqual(changed.status_code,200,changed.text)
            result=client.post('/api/command',json={'operation':'subscriptions','arguments':{}},headers=headers).json()['data']
            self.assertEqual(result['subscriptions'][0]['state'],'paused')
        with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
            self.assertEqual(client.post('/internal/season-due',json={}).status_code,403)
            response=client.post('/internal/season-due',json={},headers={'x-media-service-token':os.environ['MEDIA_CONTROL_TOKEN']})
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['data']['claims'],[])
