import copy
import hashlib
import time
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch
from media_mcp.application.acquire import MediaService
from media_mcp.application.controller import Controller


class MemoryRecords:
    def __init__(self):self.rows={};self.counter=0;self.db=Mock()
    def put(self,kind,data,state='ready',key_hash=None,ident=None):
        self.counter+=1;ident=ident or f'{self.counter:032x}'
        self.rows[ident]={'id':ident,'kind':kind,'data':copy.deepcopy(data),'state':state,'revision':1,'key_hash':key_hash}
        return self.get(ident)
    def get(self,ident,kind=None):
        row=self.rows[ident]
        if kind and row['kind']!=kind:raise ValueError('record_kind_mismatch')
        return copy.deepcopy(row)
    def update(self,row,state,data=None):
        if self.rows[row['id']]['revision']!=row['revision']:raise RuntimeError('stale_job_revision')
        row={**row,'state':state,'revision':row['revision']+1,'data':data or row['data']}
        self.rows[row['id']]=copy.deepcopy(row);return self.get(row['id'])
    def by_key(self,key):return next((copy.deepcopy(r) for r in self.rows.values() if r['key_hash']==key),None)
    def active(self,title_id=None):return [copy.deepcopy(r) for r in self.rows.values() if r['kind']=='acquisition' and (title_id is None or r['data']['identity']['title_id']==title_id)]


def data():
    return {'identity':{'title_id':'movie:1','kind':'movie','tmdb_id':1,'title':'Example'},
            'scope':{'season':None,'episodes':[],'resolution':1080},
            'release':{'name':'Example.1080p','download_url':'magnet:?xt=urn:btih:'+'a'*40},
            'expires_at':time.time()+900}


class AcquireTests(unittest.TestCase):
    def test_enqueue_idempotence_and_changed_key_rejected(self):
        records=MemoryRecords();service=MediaService(records,Mock(),Mock())
        service.library=lambda _: {'media':[],'active_jobs':[]}
        plan=records.put('plan',data())
        with patch('media_mcp.application.acquire.media_mutation_lock',lambda _:nullcontext()):
            first=service.start(plan['id'],1,'request-123')
            second=service.start(plan['id'],1,'request-123')
            self.assertEqual(first['job_id'],second['job_id'])
            with self.assertRaises(ValueError):service.start(plan['id'],2,'request-123')
            with self.assertRaises(ValueError):service.start(plan['id'],1,'another-request')

    def test_expired_snapshot_and_new_library_conflict(self):
        records=MemoryRecords();service=MediaService(records,Mock(),Mock())
        expired=records.put('release',{**data(),'expires_at':0})
        with self.assertRaises(ValueError):service.plan(expired['id'])
        plan=records.put('plan',data())
        service.library=lambda _: {'media':[{'status':'linked'}],'active_jobs':[]}
        with patch('media_mcp.application.acquire.media_mutation_lock',lambda _:nullcontext()):
            with self.assertRaises(ValueError):service.start(plan['id'],1,'request-123')

    def test_unknown_submission_is_observed_without_resubmission(self):
        records=MemoryRecords();downloader=Mock();indexer=Mock()
        indexer.torrent.return_value=None
        downloader.find.return_value=None
        downloader.add.side_effect=TimeoutError()
        row=records.put('acquisition',data(),'queued')
        controller=Controller(records,downloader,indexer,Mock())
        controller._tick(row)
        row=records.get(row['id']);self.assertEqual(row['state'],'submission_unknown')
        controller._tick(row)
        self.assertEqual(downloader.add.call_count,1)
        row=records.get(row['id']);self.assertEqual(row['state'],'submission_unknown')
        downloader.find.return_value={'category':'media-mcp','tags':'media-mcp-'+row['id'],
                                     'progress':0.2,'state':'downloading'}
        controller._tick(row)
        self.assertEqual(records.get(row['id'])['state'],'downloading')
        self.assertEqual(downloader.add.call_count,1)

    def test_existing_torrent_is_not_adopted_and_foreign_tag_is_rejected(self):
        records=MemoryRecords();downloader=Mock();indexer=Mock();indexer.torrent.return_value=None
        downloader.find.return_value={'category':'media-mcp','tags':'other','progress':1}
        row=records.put('acquisition',data(),'queued')
        controller=Controller(records,downloader,indexer,Mock());controller._tick(row)
        self.assertEqual(records.get(row['id'])['data']['error_code'],'torrent_already_exists')
        downloader.add.assert_not_called()
        row=records.put('acquisition',{**data(),'infohash':'a'*40},'downloading')
        controller._tick(row)
        self.assertEqual(records.get(row['id'])['data']['error_code'],'torrent_owner_mismatch')

    def test_tv_requires_scope_and_preserves_unknown_release_metadata(self):
        records=MemoryRecords();tmdb=Mock();indexer=Mock()
        tmdb.detail.return_value={'title_id':'tv:1','tmdb_id':1,'title':'Example','kind':'tv'}
        tmdb.get.return_value={'episodes':[{'episode_number':1,'name':'Pilot'}]}
        indexer.search.return_value={'releases':[{'name':'Example','download_url':'private','resolution':None,'size':None}], 'diagnostics':[{'site':'fixture','status':'ok','raw_count':1}]}
        service=MediaService(records,tmdb,indexer)
        with self.assertRaises(ValueError):service.search_releases('tv:1')
        result=service.search_releases('tv:1',2)
        self.assertEqual(result['scope']['episodes'],[1])
        self.assertIsNone(result['releases'][0]['resolution'])
        self.assertNotIn('private',str(result))
        self.assertFalse(result['releases'][0]['identity_verified'])

    def test_tick_accepts_persisted_null_retry_timestamp(self):
        from contextlib import contextmanager
        records=MemoryRecords()
        row=records.put('acquisition',{**data(),'infohash':'a'*40,'retry_at':None},'downloading')
        connection=Mock();connection.execute.return_value.scalar.return_value=1
        @contextmanager
        def isolated():yield connection
        records.db.lock=lambda *args,**kwargs:isolated()
        downloader=Mock();downloader.find.return_value=None
        Controller(records,downloader,Mock(),Mock()).tick(row['id'])
        self.assertEqual(records.get(row['id'])['state'],'needs_review')

    def test_downloader_prepares_only_its_missing_category(self):
        from media_mcp.adapters.download import Downloader
        from pathlib import Path
        client=Mock();client.torrents_categories.return_value={'existing':{}}
        adapter=Downloader(client)
        adapter.prepare()
        client.torrents_create_category.assert_called_once()
        self.assertEqual(client.torrents_create_category.call_args.kwargs['name'],'media-mcp')
        client.torrents_create_category.reset_mock()
        client.torrents_categories.return_value={'media-mcp':{'savePath':'/existing'}}
        adapter.prepare()
        client.torrents_create_category.assert_not_called()
