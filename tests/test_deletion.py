import os
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

from media_mcp.application.collections import Collections
from media_mcp.application.deletion import Deletions
from media_mcp.platform.service import PlatformService
from media_mcp.runtime.state import MediaJobs
from media_mcp.storage.media import upsert_media_link,upsert_media_subtitle
import test_platform


class DeletionTests(unittest.TestCase):
    def setUp(self):
        test_platform.PlatformTests.setUp(self)
        self.service=PlatformService(self.admin,self.accounts,self.records)
        self.downloader=Mock();self.downloader.find.return_value=None
        self.delete=Deletions(self.service,self.downloader)
        self.jobs=MediaJobs();self.jobs.initialize()

    def media(self,name='Show',episode=1,source_folder=None):
        source=Path(os.environ['MEDIA_DOWNLOAD_ROOT'])/(source_folder or name)/f'E{episode}.mkv'
        target=Path(os.environ['MEDIA_LIBRARY_ROOT'])/'series'/name/'\u7b2c01\u5b63'/f'E{episode}.mkv'
        source.parent.mkdir(parents=True,exist_ok=True);target.parent.mkdir(parents=True,exist_ok=True)
        source.write_bytes(b'original video');os.link(source,target)
        upsert_media_link(None,str(source),str(target),media_type='tv',media_tmdb_id=123 if name=='Show' else 456,
                          media_name=name,season=1,episode=episode,status='linked')
        sub=target.with_suffix('.zh.srt');sub.write_text('Chinese subtitle')
        upsert_media_subtitle(None,str(sub),str(sub),matched_video_source_path=str(source),matched_video_target_path=str(target),status='verified')
        lib=Collections(self.service);group=next(g for g in lib.groups().values() if any(f['source_path']==str(source) for f in g['files']))
        return group['collection_id'],source,target,sub

    def download(self,state='downloading'):
        return self.records.put('acquisition',{'_platform_owner':self.admin.id,'infohash':'a'*40,
            'identity':{'title':'Owned'},'release':{},'delivery_hash':'delivery'},state)

    def torrent(self,row,**changes):
        return {'hash':'a'*40,'category':'media-mcp','tags':'media-mcp-'+row['id'],
                'save_path':os.environ['MEDIA_DOWNLOAD_ROOT'],'content_path':os.environ['MEDIA_DOWNLOAD_ROOT']+'/Owned',
                'added_on':123,**changes}

    def test_collection_removes_sources_links_subtitles_and_owned_folders(self):
        ident,source,target,sub=self.media()
        poster=target.parent.parent/'poster.jpg';poster.write_bytes(b'artwork')
        plan=self.delete.collection_preview(ident)
        self.assertEqual(plan['file_count'],4)
        self.assertTrue(source.exists());self.assertTrue(target.exists())
        result=self.delete.apply(plan['plan_id'],True)
        self.assertEqual(result['state'],'applied')
        for p in (source,target,sub,poster,source.parent,target.parent.parent):self.assertFalse(p.exists(),p)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_link').scalar(),0)
        self.assertEqual(self.service.collections()['total'],0)
        self.assertEqual(self.delete.apply(plan['plan_id'],True)['state'],'applied')

    def test_shared_delivery_preserves_other_work_and_directory(self):
        ident,source,target,sub=self.media(source_folder='Bundle')
        _,other,other_target,_=self.media('Other',episode=2,source_folder='Bundle')
        plan=self.delete.collection_preview(ident)
        self.assertIn(str(source.parent),plan['retained_directories'])
        self.delete.apply(plan['plan_id'],True)
        self.assertEqual(other.read_bytes(),b'original video');self.assertTrue(other_target.exists())

    def test_unknown_video_is_preserved(self):
        ident,source,_,_=self.media();unknown=source.parent/'unindexed.mkv';unknown.write_bytes(b'unrelated')
        plan=self.delete.collection_preview(ident);self.delete.apply(plan['plan_id'],True)
        self.assertEqual(unknown.read_bytes(),b'unrelated')

    def test_symlink_in_tree_rejects_preview(self):
        ident,source,_,_=self.media();(source.parent/'alias').symlink_to(source)
        with self.assertRaisesRegex(ValueError,'symlink_or_path_alias'):self.delete.collection_preview(ident)
        self.assertTrue(source.exists())

    def test_change_after_preview_rejects_without_removing_bytes(self):
        ident,source,target,_=self.media();plan=self.delete.collection_preview(ident)
        source.write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError,'deletion_files_changed'):self.delete.apply(plan['plan_id'],True)
        self.assertEqual(target.read_bytes(),b'changed source')

    def test_confirmation_and_other_owner_are_rejected(self):
        ident,source,_,_=self.media();plan=self.delete.collection_preview(ident)
        with self.assertRaisesRegex(ValueError,'deletion_confirmation_required'):self.delete.apply(plan['plan_id'],False)
        other=Deletions(PlatformService(self.bob,self.accounts,self.records),self.downloader)
        with self.assertRaisesRegex(ValueError,'permission_denied'):other.apply(plan['plan_id'],True)
        self.assertTrue(source.exists())

    def test_in_progress_worker_preserves_files(self):
        ident,source,_,_=self.media();plan=self.delete.collection_preview(ident)
        self.jobs.enqueue('delivery',str(source.parent));job=self.jobs.claim('ingest');self.assertIsNotNone(job)
        with self.assertRaisesRegex(ValueError,'deletion_wait_for_worker_checkpoint'):self.delete.apply(plan['plan_id'],True)
        self.assertTrue(source.exists());self.assertTrue(self.jobs.renew(job))

    def test_staging_interruption_resumes_same_plan(self):
        ident,source,target,_=self.media();plan=self.delete.collection_preview(ident)
        with patch.object(self.delete,'_commit',side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError,'interrupted'):self.delete.apply(plan['plan_id'],True)
        self.assertEqual(self.records.get(plan['plan_id'])['state'],'executing')
        self.assertFalse(source.exists());self.assertFalse(target.exists())
        self.assertEqual(self.delete.apply(plan['plan_id'],True)['state'],'applied')
        self.assertFalse(list(Path(os.environ['MEDIA_LIBRARY_ROOT']).rglob('.media-delete-*')))

    def test_replacement_of_staged_source_is_preserved(self):
        ident,source,_,_=self.media();plan=self.delete.collection_preview(ident)
        with patch.object(self.delete,'_commit',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):self.delete.apply(plan['plan_id'],True)
        source.write_bytes(b'new file')
        with self.assertRaisesRegex(ValueError,'deletion_files_changed'):self.delete.apply(plan['plan_id'],True)
        self.assertEqual(source.read_bytes(),b'new file')

    def test_download_removes_exact_torrent_and_hides_record_without_payload_deletion(self):
        row=self.download();torrent=self.torrent(row);self.downloader.find.return_value=torrent
        plan=self.delete.download_preview(row['id'])
        self.downloader.find.side_effect=[torrent,None]
        result=self.delete.apply(plan['plan_id'],True)
        self.downloader.remove.assert_called_once_with('a'*40)
        self.assertEqual(result['file_count'],0);self.assertEqual(self.records.get(row['id'])['state'],'deleted')
        self.assertEqual(self.service.jobs()['jobs'],[])
        self.assertEqual(self.records.active(),[])

    def test_unrelated_torrent_and_unknown_missing_submission_are_fenced(self):
        row=self.download();self.downloader.find.return_value=self.torrent(row,tags='other-workflow')
        with self.assertRaisesRegex(ValueError,'torrent_owner_mismatch'):self.delete.download_preview(row['id'])
        unknown=self.download('submission_unknown');self.downloader.find.return_value=None
        with self.assertRaisesRegex(ValueError,'download_submission_outcome_unknown'):self.delete.download_preview(unknown['id'])
        self.downloader.remove.assert_not_called()

    def test_torrent_replaced_after_preview_is_not_removed(self):
        row=self.download();self.downloader.find.return_value=self.torrent(row)
        plan=self.delete.download_preview(row['id']);self.downloader.find.return_value=self.torrent(row,added_on=456)
        with self.assertRaisesRegex(ValueError,'deletion_torrent_changed'):self.delete.apply(plan['plan_id'],True)
        self.downloader.remove.assert_not_called()

    def test_collection_with_owned_download_resumes_without_new_plan(self):
        ident,source,target,_=self.media();row=self.download()
        self.records.update(row,'completed',{**row['data'],'source_path':str(source.parent)})
        torrent=self.torrent(row,content_path=str(source.parent));self.downloader.find.return_value=torrent
        plan=self.delete.collection_preview(ident)
        self.downloader.find.side_effect=[torrent,None]
        with patch.object(self.delete,'_commit',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):self.delete.apply(plan['plan_id'],True)
        self.downloader.find.side_effect=None;self.downloader.find.return_value=None
        self.assertEqual(self.delete.collection_preview(ident)['plan_id'],plan['plan_id'])
        self.assertEqual(self.delete.apply(plan['plan_id'],True)['state'],'applied')
        self.assertFalse(source.exists());self.assertFalse(target.exists())
        self.assertEqual(self.records.get(row['id'])['state'],'deleted')

    def test_conflicting_mapping_does_not_delete_independent_target(self):
        ident,source,target,_=self.media();target.unlink();target.write_bytes(b'unrelated bytes')
        with self.assertRaisesRegex(ValueError,'deletion_mapping_conflict'):self.delete.collection_preview(ident)
        self.assertEqual(source.read_bytes(),b'original video');self.assertEqual(target.read_bytes(),b'unrelated bytes')

    def test_inventory_only_media_and_discovered_sidecar_can_be_deleted(self):
        from media_mcp.storage.inventory import Inventory
        source=Path(os.environ['MEDIA_DOWNLOAD_ROOT']);source.mkdir()
        root=Path(os.environ['MEDIA_LIBRARY_ROOT']);root.mkdir()
        video=root/'Only.mkv';video.write_bytes(b'library only')
        sub=video.with_suffix('.zh.srt');sub.write_text('1\n00:00:01,000 --> 00:00:02,000\n\u6d4b\u8bd5\u5b57\u5e55\n')
        inventory=Inventory(self.records);scan=inventory.scan(self.admin.id);inventory.adopt(scan['scan_id'],self.admin.id)
        group=next(iter(Collections(self.service).groups().values()))
        self.assertIsNone(group['files'][0]['media_id'])
        plan=self.delete.collection_preview(group['collection_id'])
        self.delete.apply(plan['plan_id'],True)
        self.assertFalse(video.exists());self.assertFalse(sub.exists())
        self.assertEqual(self.service.collections()['total'],0)

    def test_user_classification_survives_staging_for_resume_validation(self):
        ident,source,_,_=self.media()
        self.service.collection_classify(ident,'extra')
        group=next(iter(Collections(self.service).groups().values()))
        plan=self.delete.collection_preview(group['collection_id'])
        with patch.object(self.delete,'_commit',side_effect=RuntimeError('interrupted')):
            with self.assertRaises(RuntimeError):self.delete.apply(plan['plan_id'],True)
        self.assertEqual(self.delete.apply(plan['plan_id'],True)['state'],'applied')
        self.assertFalse(source.exists())

    def test_new_file_during_deletion_is_preserved_and_reported(self):
        ident,source,_,_=self.media();plan=self.delete.collection_preview(ident)
        commit=self.delete._commit
        extra=source.parent/'new-file.txt'
        def add_after_commit(plan):
            commit(plan);extra.write_bytes(b'new data')
        with patch.object(self.delete,'_commit',side_effect=add_after_commit):
            result=self.delete.apply(plan['plan_id'],True)
        self.assertEqual(extra.read_bytes(),b'new data')
        self.assertIn(str(source.parent),result['retained_directories'])
        self.assertTrue(result['receipt']['cleanup_complete'])

    def test_http_preview_and_apply_require_csrf_and_explicit_confirmation(self):
        from starlette.testclient import TestClient
        from media_mcp.platform.api import create_app
        ident,source,_,_=self.media()
        with TestClient(create_app(self.accounts,self.records),base_url='http://127.0.0.1',client=('127.0.0.1',1234)) as client:
            login=client.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'}).json()
            headers={'x-csrf-token':login['data']['csrf']}
            preview={'operation':'collection_delete_preview','arguments':{'collection_id':ident}}
            self.assertEqual(client.post('/api/command',json=preview).status_code,403)
            plan=client.post('/api/command',json=preview,headers=headers).json()['data']
            apply={'operation':'deletion_apply','arguments':{'plan_id':plan['plan_id'],'confirm':False}}
            self.assertEqual(client.post('/api/command',json=apply,headers=headers).status_code,400)
            self.assertTrue(source.exists());apply['arguments']['confirm']=True
            result=client.post('/api/command',json=apply,headers=headers)
            self.assertEqual(result.status_code,200,result.text);self.assertFalse(source.exists())

    def test_shared_subtitle_path_is_preserved_for_other_media(self):
        ident,_,_,sub=self.media();_,other,other_target,other_sub=self.media('Other',episode=2)
        upsert_media_subtitle(None,str(sub),str(other_sub),matched_video_source_path=str(other),matched_video_target_path=str(other_target),status='verified')
        plan=self.delete.collection_preview(ident)
        self.assertNotIn(str(sub),plan['files']);self.delete.apply(plan['plan_id'],True)
        self.assertTrue(sub.exists());self.assertTrue(other_target.exists())

    def test_active_download_progress_does_not_invalidate_deletion(self):
        row=self.download();torrent=self.torrent(row);self.downloader.find.return_value=torrent
        plan=self.delete.download_preview(row['id'])
        self.records.update(row,'downloading',{**row['data'],'progress':.5,'sampled_at':12345})
        self.downloader.find.side_effect=[torrent,None]
        self.assertEqual(self.delete.apply(plan['plan_id'],True)['state'],'applied')

    def test_timeout_after_torrent_removal_resumes_without_replaying_add(self):
        row=self.download();self.downloader.find.return_value=self.torrent(row)
        plan=self.delete.download_preview(row['id'])
        self.downloader.remove.side_effect=TimeoutError('unknown removal response')
        with self.assertRaises(TimeoutError):self.delete.apply(plan['plan_id'],True)
        self.downloader.find.return_value=None
        self.assertEqual(self.delete.download_preview(row['id'])['plan_id'],plan['plan_id'])
        self.assertEqual(self.delete.apply(plan['plan_id'],True)['state'],'applied')
        self.downloader.remove.assert_called_once()

    def test_expired_preview_preserves_files(self):
        ident,source,_,_=self.media();plan=self.delete.collection_preview(ident)
        row=self.records.get(plan['plan_id']);self.records.update(row,'preview',{**row['data'],'expires_at':0})
        with self.assertRaisesRegex(ValueError,'snapshot_expired'):self.delete.apply(plan['plan_id'],True)
        self.assertTrue(source.exists())

    def test_pending_library_task_can_be_removed_without_touching_media(self):
        ident,source,target,_=self.media()
        task=self.service.library_auto('delete-queued-library',ident,scope='all')
        plan=self.delete.task_preview(task['job_id']);self.delete.apply(plan['plan_id'],True)
        self.assertEqual(self.records.get(task['job_id'])['state'],'deleted')
        self.assertIsNone(self.jobs.claim('library'))
        self.assertFalse(self.service.library_tasks()['tasks'])
        self.assertTrue(source.exists());self.assertTrue(target.exists())

    def test_running_library_task_cancellation_fences_late_results_and_keeps_unknown(self):
        from media_mcp.runtime.library_worker import process_task,record_failure
        ident,source,_,_=self.media();task=self.service.library_auto('cancel-running-library',ident,scope='all')
        job=self.jobs.claim('library');row=self.records.get(task['job_id'])
        row=self.records.update(row,'running');child=self.records.put('library_auto_item',{
            'owner':self.admin.id,'action':'analysis','ai_inflight':True,'files':row['data']['files']},'running')
        plan=self.delete.task_preview(row['id'])
        self.records.update(row,'running',{**row['data'],'analysis_progress':{'phase':'researching'}})
        self.delete.apply(plan['plan_id'],True)
        self.assertFalse(self.jobs.renew(job))
        process_task(self.jobs,job,analysis_client=Mock())
        self.assertEqual(record_failure(self.jobs,job,RuntimeError('late failure')),('media_job_cancelled',False))
        self.assertEqual(self.records.get(row['id'])['state'],'deleted')
        self.assertEqual(self.records.get(child['id'])['data'],child['data'])
        self.assertTrue(source.exists());self.assertIsNone(self.jobs.claim('library'))

    def test_download_pagination_prioritizes_old_active_over_new_completed(self):
        complete=self.download('completed');active=self.download('downloading')
        self.db.execute("UPDATE media_mcp_record SET created_at='2020-01-01' WHERE id=:id",{'id':active['id']})
        first=self.service.jobs(limit=1)
        self.assertEqual(first['jobs'][0]['job_id'],active['id'])
        second=self.service.jobs(after=first['next_cursor'],limit=1)
        self.assertEqual(second['jobs'][0]['job_id'],complete['id'])

    def test_qbittorrent_http_removal_preserves_payload_and_unrelated_task(self):
        import json
        import threading
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        from urllib.parse import parse_qs,urlsplit
        import qbittorrentapi
        from media_mcp.adapters.download import Downloader
        row=self.download();torrent={**self.torrent(row),'progress':.5,'state':'downloading'}
        calls=[];present={'a'*40:True,'b'*40:True}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                parsed=urlsplit(self.path)
                if parsed.path.endswith('/app/version'):payload=b'v5.1.0'
                elif parsed.path.endswith('/app/webapiVersion'):payload=b'2.11.3'
                elif parsed.path.endswith('/torrents/info'):
                    hashes=parse_qs(parsed.query).get('hashes',[''])[0]
                    calls.append(('info',hashes));payload=json.dumps([torrent] if present.get(hashes) else []).encode()
                else:payload=b'{}'
                self.send_response(200);self.end_headers();self.wfile.write(payload)
            def do_POST(self):
                body=parse_qs(self.rfile.read(int(self.headers.get('Content-Length',0))).decode())
                if self.path.endswith('/torrents/info'):
                    hashes=body.get('hashes',[''])[0];calls.append(('info',hashes))
                    payload=json.dumps([torrent] if present.get(hashes) else []).encode()
                else:
                    calls.append(('delete',body));payload=b''
                    for value in body.get('hashes',[''])[0].split('|'):present[value]=False
                self.send_response(200);self.end_headers();self.wfile.write(payload)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        source=Path(os.environ['MEDIA_DOWNLOAD_ROOT'])/'Owned'/'file.mkv';source.parent.mkdir(parents=True);source.write_bytes(b'keep payload')
        try:
            client=qbittorrentapi.Client(host='http://127.0.0.1:'+str(server.server_port))
            delete=Deletions(self.service,Downloader(client))
            with patch.dict(os.environ,{'QBITTORRENT_USERNAME':'','QBITTORRENT_PASSWORD':''}):
                plan=delete.download_preview(row['id']);delete.apply(plan['plan_id'],True)
            removals=[body for operation,body in calls if operation=='delete']
            self.assertEqual(len(removals),1)
            self.assertEqual(removals[0]['hashes'],['a'*40])
            self.assertEqual([value.lower() for value in removals[0]['deleteFiles']],['false'])
            self.assertEqual(source.read_bytes(),b'keep payload');self.assertTrue(present['b'*40])
            self.assertTrue(all(value=='a'*40 for operation,value in calls if operation=='info'))
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_downloader_removal_never_deletes_payload(self):
        from media_mcp.adapters.download import Downloader
        client=Mock();Downloader(client).remove('a'*40)
        client.torrents_delete.assert_called_once_with(torrent_hashes='a'*40,delete_files=False)


if __name__=='__main__':unittest.main()
