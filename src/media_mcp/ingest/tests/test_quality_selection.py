import os
from pathlib import Path
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from media_mcp.ingest.domain.quality import compare_quality
from media_mcp.ingest.services import linking


class QualityTests(unittest.TestCase):
    def profile(self, **overrides):
        return {'height':1080,'duration':100,'source_rank':2,'revision':0,**overrides}

    def test_existing_or_new_nonconflicting_link_does_not_probe_video(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory,'source.mkv');source.write_bytes(b'video');target=Path(directory,'target.mkv')
            db=MagicMock();conn=MagicMock();conn.execute.return_value.mappings.return_value.all.return_value=[]
            @contextmanager
            def lock(_, **kwargs):yield conn
            with patch.object(linking,'_client',return_value=db),patch.object(linking,'media_mutation_lock',lock),patch.object(linking.version_changes,'initialize'),patch.object(linking.version_changes,'recover_pending'),patch.object(linking,'upsert_media_link'),patch.object(linking,'probe_quality') as probe:
                self.assertTrue(linking.apply_preferred_media(str(source),str(target),{'media_type':'movie'},'test')[0])
                self.assertTrue(linking.apply_preferred_media(str(source),str(target),{'media_type':'movie'},'test')[0])
                probe.assert_not_called()
            self.assertTrue(os.path.samefile(source,target))

    def test_resolution_before_release_labels(self):
        self.assertEqual(compare_quality(self.profile(height=2160,source_rank=1),self.profile()),1)
        self.assertEqual(compare_quality(self.profile(height=720,source_rank=4),self.profile()),-1)

    def test_unknown_and_different_cuts_do_not_replace(self):
        self.assertIsNone(compare_quality(self.profile(duration=None),self.profile()))
        self.assertIsNone(compare_quality(self.profile(duration=120,height=2160),self.profile()))
        self.assertEqual(compare_quality(self.profile(),self.profile()),0)

    def run_link(self, directory, *, fail_db=False, better=True):
        root=Path(directory);old=root/'old.mkv';new=root/'new.mkv';target=root/'library'/'video.mkv'
        target.parent.mkdir();old.write_bytes(b'old');new.write_bytes(b'new');os.link(old,target)
        sidecar=target.with_suffix('.ass');sidecar.write_text('old subtitle')
        row={'id':7,'source_path':str(old),'target_path':str(target)}
        db=MagicMock();conn=MagicMock();conn.execute.return_value.mappings.return_value.all.return_value=[row]
        @contextmanager
        def lock(_, **kwargs):yield conn
        def profile(path,*_):return self.profile(height=2160 if path==str(new) and better else 1080)
        with patch.object(linking.version_changes,'initialize'),patch.object(linking.version_changes,'recover_pending'),patch.object(linking,'_client',return_value=db),patch.object(linking,'media_mutation_lock',lock),patch.object(linking,'probe_quality',side_effect=profile),patch.object(linking,'upsert_media_link',side_effect=RuntimeError('db_failed') if fail_db else None):
            if fail_db:
                with self.assertRaises(RuntimeError):linking.apply_preferred_media(str(new),str(target),{'media_type':'movie'},'test')
            else:
                result=linking.apply_preferred_media(str(new),str(target),{'media_type':'movie'},'test')
                self.assertTrue(result[0])
        self.assertTrue(old.exists());self.assertTrue(new.exists())
        if fail_db or not better:
            self.assertTrue(os.path.samefile(old,target));self.assertTrue(sidecar.exists())
        else:
            self.assertTrue(os.path.samefile(new,target));self.assertFalse(sidecar.exists())
            self.assertTrue(list((root/'.phantom-subtitles'/'7').glob('*.ass')))

    def test_upgrade_preserves_old_source_and_archives_old_subtitle(self):
        with tempfile.TemporaryDirectory() as directory:self.run_link(directory)

    def test_equal_quality_leaves_source_unlinked(self):
        with tempfile.TemporaryDirectory() as directory:self.run_link(directory,better=False)

    def test_database_failure_restores_old_link_and_subtitle(self):
        with tempfile.TemporaryDirectory() as directory:self.run_link(directory,fail_db=True)

class SourceGenerationTests(unittest.TestCase):
    def test_deleted_path_accepts_a_new_source_generation(self):
        import json
        from media_mcp.ingest import run
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'video.mkv');source.write_bytes(b'first')
            stat=source.stat()
            record={'status':'deleted','source_inode':stat.st_ino,'source_size':stat.st_size,
                'agent_result_json':json.dumps({'_source_fingerprint':[stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns]})}
            with patch.object(run,'g_logger',MagicMock()),patch.object(run,'get_media_link_by_source',return_value=record):
                self.assertEqual(run.restore_link_from_db(str(source)),(True,'unlinked'))
                source.write_bytes(b'other')
                os.utime(source,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000))
                self.assertEqual(run.restore_link_from_db(str(source)),(False,'not_found'))

    def test_automatic_retry_holds_review_but_retries_transport_errors(self):
        from media_mcp.ingest import run
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'video.mkv');source.write_bytes(b'video')
            stat=source.stat();record={'status':'needs_review','source_inode':stat.st_ino,'source_size':stat.st_size,'reason':'low confidence: 0.5'}
            with patch.object(run,'g_logger',MagicMock()),patch.object(run,'get_media_link_by_source',return_value=record):
                self.assertEqual(run.restore_link_from_db(str(source),recheck_review=False),(True,'needs_review'))
                self.assertEqual(run.restore_link_from_db(str(source),recheck_review=True),(False,'not_found'))
                record['reason']='codex_request_failed: model_timeout'
                self.assertEqual(run.restore_link_from_db(str(source),recheck_review=False),(False,'not_found'))

    def test_explicit_retry_rechecks_unchanged_unlinked_source(self):
        from media_mcp.ingest import run
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'video.mkv');source.write_bytes(b'video')
            stat=source.stat();record={'status':'unlinked','source_inode':stat.st_ino,'source_size':stat.st_size}
            with patch.object(run,'g_logger',MagicMock()),patch.object(run,'get_media_link_by_source',return_value=record):
                self.assertEqual(run.restore_link_from_db(str(source)),(True,'unlinked'))
                self.assertEqual(run.restore_link_from_db(str(source),recheck_unlinked=True),(False,'not_found'))

class MaintenanceSafetyTests(unittest.TestCase):
    def test_purge_rejects_paths_outside_library_before_mutation(self):
        from media_mcp.ingest import run
        with tempfile.TemporaryDirectory() as root:
            outside=Path(root,'outside.mkv');outside.write_bytes(b'keep')
            with patch.object(run,'g_logger',MagicMock()),patch.object(run,'list_media_links_by_keyword',return_value=[{'id':1,'target_path':str(outside)}]),patch.object(run,'delete_media_links_by_ids') as delete:
                with self.assertRaisesRegex(RuntimeError,'outside_media_root'):
                    run._purge_hardlinks_by_keyword('movie')
                delete.assert_not_called()
            self.assertEqual(outside.read_bytes(),b'keep')

    def test_failed_purge_keeps_database_mapping(self):
        from media_mcp.ingest import run
        with tempfile.TemporaryDirectory() as root:
            target=Path(root,'movie.mkv');target.write_bytes(b'keep')
            with patch.object(run,'MEDIA_ROOT',root),patch.object(run,'g_logger',MagicMock()),patch.object(run,'list_media_links_by_keyword',return_value=[{'id':1,'target_path':str(target)}]),patch.object(run.os,'remove',side_effect=PermissionError()),patch.object(run,'delete_media_links_by_ids') as delete:
                with self.assertRaisesRegex(RuntimeError,'records_preserved'):
                    run._purge_hardlinks_by_keyword('movie')
                delete.assert_not_called()
            self.assertTrue(target.exists())
