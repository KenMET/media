"""Real local persistence, multi-process ownership and filesystem recovery tests."""
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from media_mcp.storage.client import DatabaseClient
from media_mcp.storage.records import Records
from media_mcp.storage import media
from media_mcp.runtime.state import MediaJobs,media_mutation_lock,release_mutation_lock_for_io,assert_mutation_lock


def _claim_in_process(path,gate,queue):
    os.environ['MEDIA_DB_PATH']=path
    gate.wait(5)
    row=MediaJobs().claim('ingest')
    queue.put(row['owner'] if row else None)


def _hold_in_process(path,queue):
    os.environ['MEDIA_DB_PATH']=path
    import time
    with DatabaseClient().lock('mutations'):
        queue.put('locked')
        time.sleep(20)


class SQLiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.downloads=self.root/'downloads';self.library=self.root/'library'
        self.downloads.mkdir();self.library.mkdir()
        env=patch.dict(os.environ,{'MEDIA_DB_PATH':str(self.root/'state/media.sqlite3'),
            'MEDIA_DOWNLOAD_ROOT':str(self.downloads),'MEDIA_LIBRARY_ROOT':str(self.library)})
        env.start();self.addCleanup(env.stop)
        self.db=media._client(None);self.records=Records(self.db);self.records.initialize()
        self.jobs=MediaJobs();self.jobs.initialize()

    def test_real_upserts_persist_and_json_queries_work(self):
        source=self.downloads/'a.mkv';source.write_bytes(b'a');target=self.library/'a.mkv';os.link(source,target)
        for reason in ('first','updated'):
            media.upsert_media_link(None,str(source),str(target),media_type='movie',media_tmdb_id=1,status='linked',reason=reason)
        rows=self.db.execute('SELECT * FROM media_link').mappings().all()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['reason'],'updated')
        media.upsert_tmdb_cache(None,'movie','cache',{'title':'first'})
        media.upsert_tmdb_cache(None,'movie','cache',{'title':'second'})
        self.assertEqual(json.loads(self.db.execute('SELECT response_json FROM tmdb_cache').scalar())['title'],'second')
        media.upsert_media_subtitle(None,'source.srt','target.srt',matched_video_target_path=str(target),status='linked')
        media.upsert_media_subtitle(None,'source.srt','target.srt',matched_video_target_path=str(target),status='updated')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_subtitle').scalar(),1)
        record=self.records.put('acquisition',{'identity':{'title_id':'movie:1'},'delivery_hash':'abc'},'processing')
        self.assertEqual(self.records.active('movie:1')[0]['id'],record['id'])
        self.assertEqual(self.records.active('movie:2'),[])
        self.assertEqual(Records(DatabaseClient()).processing_context('abc')['identity']['title_id'],'movie:1')

    def test_expired_owner_cannot_renew_or_finish(self):
        self.jobs.enqueue('one','/path');first=self.jobs.claim('ingest')
        self.db.execute("UPDATE media_processing_job SET lease_until=datetime('now','-1 second')")
        second=MediaJobs().claim('ingest')
        self.assertNotEqual(first['owner'],second['owner'])
        self.assertFalse(self.jobs.renew(first))
        with self.assertRaisesRegex(RuntimeError,'lease_lost'):self.jobs.finish(first)
        self.jobs.finish(second,result='{"created":1}')
        self.assertIsNotNone(self.jobs.claim('subtitle'))

    def test_two_processes_cannot_claim_same_delivery(self):
        self.jobs.enqueue('one','/path')
        ctx=multiprocessing.get_context('spawn');gate=ctx.Event();queue=ctx.Queue()
        children=[ctx.Process(target=_claim_in_process,args=(str(self.db.path),gate,queue)) for _ in range(2)]
        try:
            for p in children:p.start()
            gate.set();result=[queue.get(timeout=10) for _ in children]
            self.assertEqual(sum(v is not None for v in result),1)
            for p in children:p.join(5);self.assertEqual(p.exitcode,0)
        finally:
            for p in children:
                if p.is_alive():p.terminate();p.join()

    def test_crashed_process_releases_file_lock(self):
        ctx=multiprocessing.get_context('spawn');queue=ctx.Queue()
        process=ctx.Process(target=_hold_in_process,args=(str(self.db.path),queue));process.start()
        try:
            self.assertEqual(queue.get(timeout=10),'locked')
            with self.assertRaisesRegex(RuntimeError,'busy'):
                with self.db.lock('mutations'):pass
        finally:
            process.terminate();process.join(5)
        with self.db.lock('mutations') as lock:lock.check()

    def test_stale_external_result_and_replaced_lock_rejected(self):
        with media_mutation_lock(self.db):
            with self.assertRaisesRegex(RuntimeError,'changed_during'):
                with release_mutation_lock_for_io(validate=lambda:False):pass
            with self.assertRaises(RuntimeError):assert_mutation_lock()
        with media_mutation_lock(self.db):
            from media_mcp.runtime.state import _active_mutation_lock
            lock,_=_active_mutation_lock.get();lock.path.unlink();lock.path.touch()
            with self.assertRaisesRegex(RuntimeError,'lock_lost'):assert_mutation_lock()

    def _version_fixture(self,fail=False):
        from media_mcp.ingest.services.linking import apply_preferred_media
        old=self.downloads/'old.mkv';new=self.downloads/'new.mkv';target=self.library/'film.mkv'
        old.write_bytes(b'old-video');new.write_bytes(b'new-video');os.link(old,target)
        subtitle=self.library/'film.zh-CN.srt';subtitle.write_text('old subtitles')
        meta={'media_type':'movie','media_tmdb_id':1}
        media.upsert_media_link(None,str(old),str(target),**meta,status='linked')
        media.upsert_media_subtitle(None,str(subtitle),str(subtitle),matched_video_source_path=str(old),matched_video_target_path=str(target),status='linked')
        from contextlib import nullcontext
        store=patch('media_mcp.ingest.services.linking.upsert_media_link',side_effect=RuntimeError('injected_database_failure')) if fail else nullcontext()
        with patch('media_mcp.ingest.services.linking.probe_quality',return_value={}),patch('media_mcp.ingest.services.linking.compare_quality',return_value=1),store:
            if fail:
                with self.assertRaisesRegex(RuntimeError,'injected'):apply_preferred_media(str(new),str(target),meta,None)
                self.assertTrue(os.path.samefile(old,target));self.assertEqual(subtitle.read_text(),'old subtitles')
            else:
                result=apply_preferred_media(str(new),str(target),meta,None)
                self.assertTrue(result[0]);self.assertTrue(os.path.samefile(new,target))
                rows=self.db.execute('SELECT status FROM media_link').scalars().all()
                self.assertCountEqual(rows,['linked','unlinked'])
                paths=self.db.execute('SELECT target_subtitle_path FROM media_subtitle').scalars().all()
                self.assertTrue(all(Path(p).is_file() for p in paths))
        self.assertEqual(old.read_bytes(),b'old-video')
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_version_change WHERE state!='done'").scalar(),0)

    def test_version_upgrade_real_sqlite_journal(self):self._version_fixture()
    def test_failed_version_publication_restores_old_files(self):self._version_fixture(fail=True)
