import base64
import copy
import os
import time
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

import test_gateway
from media_mcp.application.controller import Controller
from media_mcp.platform.cloud import CloudCommands, CloudRecords, decode_payload
from media_mcp.platform.gateway import create_gateway
from media_mcp.storage.records import Records


TORRENT = b'd4:infod4:name4:test6:lengthi1eee'


class CloudExecutionTests(unittest.TestCase):
    setUp = test_gateway.GatewayTests.setUp

    def providers(self):
        tmdb, indexer = Mock(), Mock()
        identity = {'title_id':'movie:1', 'kind':'movie', 'tmdb_id':1,
                    'title':'测试电影', 'original_title':'Example', 'date':'2026-01-01'}
        tmdb.detail.return_value = identity
        tmdb.search.return_value = [identity]
        indexer.search.return_value = {'releases':[{'name':'Example.2026.1080p',
            'download_url':'http://cloud-jackett/private-token', 'indexer':'public',
            'categories':[2000], 'resolution':1080}],
            'diagnostics':[{'site':'public','status':'ok','raw_count':1}]}
        indexer.torrent.return_value = TORRENT
        return tmdb, indexer

    def commands(self, actor=None):
        actor = actor or self.admin
        token = self.accounts.create_api_token(actor,'split-test')['token']
        tmdb,indexer = self.providers()
        def call(payload):
            with patch.dict(os.environ, {'MEDIA_EXECUTION_ONLY':'true'}):
                return self.remote.call('/internal/cloud',payload,user_token=token)
        return CloudCommands(call,self.accounts.db,tmdb,indexer), token

    def test_web_search_and_download_use_cloud_providers_and_local_fencing(self):
        tmdb,indexer = self.providers()
        app = create_gateway(self.remote,tmdb=tmdb,jackett=indexer,catalog=Mock(),http_request=self.transport.request)
        with TestClient(app,base_url='http://media.test',client=('127.0.0.1',9000)) as client:
            login=client.post('/api/auth/login',json={'username':'alice','password':'alice-password-123'})
            client.headers['x-csrf-token']=login.json()['data']['csrf']
            def invoke(name,arguments):
                response=client.post('/api/command',json={'operation':name,'arguments':arguments})
                self.assertEqual(response.status_code,200,response.text)
                return response.json()['data']
            for query in ('测试电影','Example'):
                self.assertEqual(invoke('search_titles',{'query':query,'kind':'movie'})['titles'][0]['title_id'],'movie:1')
            releases=invoke('search_releases',{'title_id':'movie:1','resolution':1080})
            release_id=releases['releases'][0]['release_id']
            plan=invoke('plan',{'release_id':release_id})
            args={'plan_id':plan['plan_id'],'revision':plan['revision'],'idempotency_key':'split-web-123'}
            first=invoke('start',args)
            self.assertEqual(invoke('start',args)['job_id'],first['job_id'])
        indexer.torrent.assert_called_once_with('http://cloud-jackett/private-token')
        row=self.records.get(first['job_id'],'acquisition')
        self.assertEqual(row['data']['_platform_owner'],self.alice['id'])
        self.assertEqual(row['data']['release']['download_url'],'cloud-prepared')
        downloader=Mock();downloader.find.return_value=None
        no_indexer=Mock();no_indexer.torrent.side_effect=AssertionError('NAS must not fetch a torrent')
        with patch.dict(os.environ,{'MEDIA_EXECUTION_ONLY':'true'}):
            Controller(self.records,downloader,no_indexer,Mock()).tick(row['id'])
        self.assertEqual(downloader.add.call_args.kwargs['torrent'],TORRENT)
        no_indexer.torrent.assert_not_called()
        self.assertEqual(self.records.get(row['id'])['state'],'downloading')

    def test_mcp_search_and_plan_recheck_token_revocation(self):
        commands,token=self.commands()
        result=commands.invoke('search_releases',{'title_id':'movie:1'})
        release_id=result['releases'][0]['release_id']
        plan=commands.invoke('plan',{'release_id':release_id})
        self.assertEqual(plan['identity']['title_id'],'movie:1')
        self.accounts.change_password(self.admin,'owner-password-123','changed-password-123')
        with self.assertRaisesRegex(ValueError,'authentication_required'):
            commands.invoke('plan',{'release_id':release_id})

    def test_other_user_cannot_use_release_and_disabled_download_cannot_search_releases(self):
        commands,_=self.commands()
        release_id=commands.invoke('search_releases',{'title_id':'movie:1'})['releases'][0]['release_id']
        # The cloud does not let an administrator's records leak into another account.
        alice=self.accounts.actor_by_id(self.alice['id'])
        other,_=self.commands(alice)
        with self.assertRaisesRegex(ValueError,'record_not_found'):
            other.invoke('plan',{'release_id':release_id})
        self.accounts.update_user(self.admin,alice.id,enabled=True,role='user',can_download=False,can_manage_media=False)
        with self.assertRaisesRegex(ValueError,'authentication_required'):
            other.invoke('search_releases',{'title_id':'movie:1'})
        other,_=self.commands(self.accounts.actor_by_id(alice.id))
        with self.assertRaisesRegex(ValueError,'download_permission_required'):
            other.invoke('search_releases',{'title_id':'movie:1'})

    def test_real_mcp_tools_execute_search_and_plan_in_cloud(self):
        from media_mcp.server import create_server
        from media_mcp.platform.remote_mcp import RemoteMCPService, RemoteTokenVerifier
        tmdb,indexer=self.providers()
        token=self.accounts.create_api_token(self.admin,'cloud-mcp')['token']
        app=create_server(RemoteMCPService(self.remote),RemoteTokenVerifier(self.remote)).http_app(
            path='/mcp',stateless_http=True,json_response=True)
        with patch('media_mcp.adapters.tmdb.TMDB',return_value=tmdb),patch('media_mcp.adapters.jackett.Jackett',return_value=indexer),TestClient(app,base_url='http://127.0.0.1') as client:
            def tool(name,args):
                response=client.post('/mcp',headers={'authorization':'Bearer '+token,
                    'accept':'application/json, text/event-stream'},json={'jsonrpc':'2.0','id':1,
                    'method':'tools/call','params':{'name':name,'arguments':args}})
                self.assertEqual(response.status_code,200,response.text)
                result=response.json()['result']['structuredContent']
                self.assertTrue(result.get('success'),result)
                return result['data']
            self.assertEqual(tool('media_search_titles',{'query':'测试电影','kind':'movie'})['titles'][0]['title_id'],'movie:1')
            releases=tool('media_search_releases',{'title_id':'movie:1'})
            plan=tool('media_plan_acquisition',{'release_id':releases['releases'][0]['release_id']})
            job=tool('media_start_acquisition',{'plan_id':plan['plan_id'],'revision':plan['revision'],
                'idempotency_key':'cloud-real-mcp-123'})
            self.assertEqual(self.records.get(job['job_id'])['data']['_platform_entry'],'mcp')
            indexer.torrent.assert_called_once()

    def test_cloud_plan_rejects_oversize_or_inconsistent_evidence_and_missing_service_auth(self):
        commands,token=self.commands()
        release_id=commands.invoke('search_releases',{'title_id':'movie:1'})['releases'][0]['release_id']
        row=CloudRecords(self.accounts.db,self.admin.id).get(release_id,'release')
        snapshot={k:row['data'][k] for k in ('identity','scope','release','expires_at')}
        payload={'action':'plan','operation':'plan','release_id':release_id,'snapshot':snapshot,
                 'payload':{'kind':'bytes','data':base64.b64encode(TORRENT).decode()}}
        headers={'x-media-user-token':token,'x-media-service-token':os.environ['MEDIA_CONTROL_TOKEN']}
        with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',9000)) as client:
            self.assertEqual(client.post('/internal/cloud',json=payload).status_code,403)
            for bad in ('identity','scope','extra','expired','future','hash','torrent'):
                changed=copy.deepcopy(payload)
                if bad=='identity':changed['snapshot']['identity']['tmdb_id']=2
                if bad=='scope':changed['snapshot']['scope']['episodes']=[1]
                if bad=='extra':changed['snapshot']['source_path']='/data/private'
                if bad=='expired':changed['snapshot']['expires_at']=time.time()-1
                if bad=='future':changed['snapshot']['expires_at']=time.time()+3600
                if bad=='hash':changed['snapshot']['release']['claimed_infohash']='a'*40
                if bad=='torrent':changed['payload']['data']='!!!'
                response=client.post('/internal/cloud',json=changed,headers=headers)
                self.assertEqual(response.status_code,400,(bad,response.text))
            response=client.post('/internal/cloud',content=b' '* (12*1024*1024+1),
                                 headers={**headers,'content-type':'application/json'})
            self.assertEqual(response.status_code,400)

    def test_local_execution_disallows_all_provider_network_calls(self):
        from media_mcp.adapters.tmdb import TMDB
        from media_mcp.adapters.jackett import Jackett
        from media_mcp.platform.transport import provider_remote
        with patch.dict(os.environ,{'MEDIA_EXECUTION_ONLY':'true','MEDIA_CATALOG_URL':'https://old.invalid'}):
            self.assertIsNone(provider_remote())
            for function,args in ((TMDB().get,('movie/1',)),(Jackett().search,('Example',)),
                                  (Jackett().torrent,('http://cloud-jackett/token',))):
                with self.assertRaisesRegex(ValueError,'cloud_search_only'):
                    function(*args)

    def test_cloud_payload_unknown_submission_never_fetches_or_adds_twice(self):
        commands,token=self.commands()
        release_id=commands.invoke('search_releases',{'title_id':'movie:1'})['releases'][0]['release_id']
        plan=commands.invoke('plan',{'release_id':release_id})
        job=self.remote.call('/internal/command',{'operation':'start','arguments':{
            'plan_id':plan['plan_id'],'revision':plan['revision'],'idempotency_key':'unknown-cloud-123'}},user_token=token)
        downloader=Mock();downloader.find.return_value=None;downloader.add.side_effect=TimeoutError()
        indexer=Mock();indexer.torrent.side_effect=AssertionError('no local network')
        controller=Controller(self.records,downloader,indexer,Mock())
        controller.tick(job['job_id']);controller.tick(job['job_id'])
        self.assertEqual(self.records.get(job['job_id'])['state'],'submission_unknown')
        self.assertEqual(downloader.add.call_count,1)
        indexer.torrent.assert_not_called()

    def test_preparation_failure_retains_cloud_payload_for_safe_retry(self):
        commands,token=self.commands()
        release_id=commands.invoke('search_releases',{'title_id':'movie:1'})['releases'][0]['release_id']
        plan=commands.invoke('plan',{'release_id':release_id})
        job=self.remote.call('/internal/command',{'operation':'start','arguments':{
            'plan_id':plan['plan_id'],'revision':plan['revision'],'idempotency_key':'cloud-prepare-retry-123'}},user_token=token)
        downloader=Mock();downloader.find.return_value=None;downloader.prepare.side_effect=TimeoutError()
        indexer=Mock();indexer.torrent.side_effect=AssertionError('no local network')
        controller=Controller(self.records,downloader,indexer,Mock())
        controller.tick(job['job_id'])
        row=self.records.get(job['job_id'])
        self.assertEqual(row['state'],'queued')
        self.assertIn('cloud_payload',row['data'])
        downloader.prepare.side_effect=None
        row['data']['retry_at']=0
        self.records.update(row,'queued',row['data'])
        controller.tick(job['job_id'])
        self.assertEqual(self.records.get(job['job_id'])['state'],'downloading')
        self.assertEqual(downloader.add.call_count,1)
        indexer.torrent.assert_not_called()

    def test_magnet_payload_cannot_smuggle_a_second_download(self):
        magnet='magnet:?xt=urn:btih:'+'a'*40
        self.assertEqual(decode_payload({'kind':'magnet','data':magnet}),(None,magnet))
        for suffix in ('\nhttp://unrelated.invalid/file','\rmagnet:?xt=urn:btih:'+'b'*40,'\x00','\x7f'):
            with self.assertRaisesRegex(ValueError,'invalid_magnet_payload'):
                decode_payload({'kind':'magnet','data':magnet+suffix})

    def test_tv_metadata_and_magnet_are_frozen_without_local_indexer_access(self):
        commands,token=self.commands()
        commands.tmdb.detail.return_value={'title_id':'tv:1','kind':'tv','tmdb_id':1,
            'title':'测试剧集','original_title':'Example','date':'2026-01-01'}
        commands.tmdb.get.return_value={'episodes':[{'episode_number':1,'name':'第一集'}]}
        magnet='magnet:?xt=urn:btih:'+'a'*40
        commands.indexer.search.return_value={'releases':[{'name':'Example.S02E01.1080p',
            'download_url':magnet,'resolution':1080,'categories':[5000]}],
            'diagnostics':[{'site':'public','status':'ok','raw_count':1}]}
        commands.indexer.torrent.return_value=None
        found=commands.invoke('search_releases',{'title_id':'tv:1','season':2})
        plan=commands.invoke('plan',{'release_id':found['releases'][0]['release_id']})
        self.assertEqual(plan['scope']['episodes'],[1])
        self.assertEqual(plan['scope']['episode_metadata'],[{'episode':1,'title':'第一集'}])
        job=self.remote.call('/internal/command',{'operation':'start','arguments':{
            'plan_id':plan['plan_id'],'revision':plan['revision'],'idempotency_key':'cloud-tv-magnet-123'}},user_token=token)
        downloader=Mock();downloader.find.return_value=None
        indexer=Mock();indexer.torrent.side_effect=AssertionError('no local network')
        Controller(self.records,downloader,indexer,Mock()).tick(job['job_id'])
        self.assertEqual(downloader.add.call_args.kwargs['magnet'],magnet)
        self.assertIsNone(downloader.add.call_args.kwargs['torrent'])
        indexer.torrent.assert_not_called()

    def test_small_host_clock_difference_does_not_reject_fresh_cloud_snapshot(self):
        commands,_=self.commands()
        release_id=commands.invoke('search_releases',{'title_id':'movie:1'})['releases'][0]['release_id']
        records=CloudRecords(self.accounts.db,self.admin.id)
        row=records.get(release_id,'release')
        row['data']['expires_at']=time.time()+1810
        records.update(row,'ready',row['data'])
        self.assertEqual(commands.invoke('plan',{'release_id':release_id})['identity']['title_id'],'movie:1')
