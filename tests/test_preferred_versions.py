"""All publishers retain one preferred feature without changing source bytes."""
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import test_platform
from media_mcp.application.identity import expected_identity
from media_mcp.ingest.services.linking import apply_preferred_media
from media_mcp.storage.media import upsert_media_link


class PreferredVersionTests(TestCase):
    setUp=test_platform.PlatformTests.setUp

    def fixture(self):
        self.source=Path(os.environ['MEDIA_DOWNLOAD_ROOT']);self.source.mkdir()
        self.library=Path(os.environ['MEDIA_LIBRARY_ROOT']);self.library.mkdir()
        self.metadata={'media_type':'movie','media_tmdb_id':1,'media_name':'Example'}
        first=self.source/'first.mkv';first.write_bytes(b'original-first')
        second=self.source/'second.mkv';second.write_bytes(b'original-second')
        return first,second

    @staticmethod
    def quality(height=1080,duration=100):
        return {'height':height,'width':1920 if height==1080 else 1280,'duration':duration,'source_rank':2,'revision':0}

    def test_same_source_retitle_does_not_create_an_orphan_second_target(self):
        source,_=self.fixture();target=self.library/'old.mkv'
        self.assertTrue(apply_preferred_media(str(source),str(target),self.metadata,None)[0])
        other=self.library/'new-title.mp4'
        self.assertEqual(apply_preferred_media(str(source),str(other),self.metadata,None)[2],str(target))
        self.assertFalse(other.exists());self.assertTrue(os.path.samefile(source,target))

    def test_equal_and_different_cut_keep_existing_and_sources(self):
        first,second=self.fixture();target=self.library/'old.mkv'
        apply_preferred_media(str(first),str(target),self.metadata,None)
        for duration in (100,160):
            with patch('media_mcp.ingest.services.linking.probe_quality',side_effect=lambda path,release_path=None:self.quality(duration=duration if path==str(second) else 100)):
                result=apply_preferred_media(str(second),str(self.library/'new.mp4'),self.metadata,None)
            self.assertTrue(result[0]);self.assertEqual(result[2],'')
            self.assertTrue(os.path.samefile(first,target));self.assertFalse((self.library/'new.mp4').exists())
        self.assertEqual(first.read_bytes(),b'original-first');self.assertEqual(second.read_bytes(),b'original-second')

    def test_upgrade_uses_recovery_removes_old_target_and_preserves_sources(self):
        first,second=self.fixture();old=self.library/'old.mkv';new=self.library/'new.mp4'
        apply_preferred_media(str(first),str(old),self.metadata,None)
        with patch('media_mcp.ingest.services.linking.probe_quality',side_effect=lambda path,release_path=None:self.quality(1080 if path==str(second) else 720)):
            self.assertTrue(apply_preferred_media(str(second),str(new),self.metadata,None)[0])
        self.assertFalse(old.exists());self.assertTrue(os.path.samefile(second,new))
        self.assertEqual(first.read_bytes(),b'original-first')
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM media_link WHERE status='linked'").scalar(),1)

    def test_first_publication_failure_rolls_back_and_legacy_duplicates_need_confirmation(self):
        first,second=self.fixture();target=self.library/'first.mkv'
        with patch('media_mcp.ingest.services.linking.upsert_media_link',side_effect=RuntimeError('db_failure')):
            with self.assertRaisesRegex(RuntimeError,'db_failure'):
                apply_preferred_media(str(first),str(target),self.metadata,None)
        self.assertFalse(target.exists());self.assertTrue(first.exists())
        for source,name in ((first,'first.mkv'),(second,'second.mkv')):
            link=self.library/name;os.link(source,link)
            upsert_media_link(None,str(source),str(link),**self.metadata,status='linked')
        third=self.source/'third.mkv';third.write_bytes(b'third')
        result=apply_preferred_media(str(third),str(self.library/'third.mkv'),self.metadata,None)
        self.assertFalse(result[0]);self.assertIn('explicit cleanup',result[1])
        self.assertEqual(len(list(self.library.glob('*.mkv'))),2)

    def test_resolution_ceiling_and_multi_episode_file_fail_closed(self):
        source,_=self.fixture()
        token=expected_identity.set({'identity':{'kind':'movie','tmdb_id':1},'scope':{'resolution':720}})
        try:
            with patch('media_mcp.ingest.services.linking.probe_quality',return_value=self.quality(1080)):
                self.assertFalse(apply_preferred_media(str(source),str(self.library/'too-high.mkv'),self.metadata,None)[0])
        finally:expected_identity.reset(token)
        combined=self.source/'Show.S01E01E02.mkv';combined.write_bytes(b'combined')
        self.assertFalse(apply_preferred_media(str(combined),str(self.library/'episode.mkv'),
            {'media_type':'tv','media_tmdb_id':2,'season':1,'episode':1},None)[0])

    def test_extra_episode_in_owned_pack_is_indexed_without_publishing_or_failing(self):
        source,_=self.fixture()
        metadata={'media_type':'tv','media_tmdb_id':2,'season':1,'episode':2}
        token=expected_identity.set({'identity':{'kind':'tv','tmdb_id':2},'scope':{'season':1,'episodes':[1]}})
        try:
            result=apply_preferred_media(str(source),str(self.library/'episode-two.mkv'),metadata,None)
        finally:expected_identity.reset(token)
        self.assertTrue(result[0]);self.assertEqual(result[2],'')
        self.assertFalse((self.library/'episode-two.mkv').exists())
        self.assertEqual(self.db.execute('SELECT status FROM media_link').scalar(),'unlinked')
        self.assertEqual(source.read_bytes(),b'original-first')

    def test_failed_indexing_never_removes_an_existing_untracked_hardlink(self):
        source,_=self.fixture();target=self.library/'existing.mkv';os.link(source,target)
        with patch('media_mcp.ingest.services.linking.upsert_media_link',side_effect=RuntimeError('db_failure')):
            with self.assertRaisesRegex(RuntimeError,'db_failure'):
                apply_preferred_media(str(source),str(target),self.metadata,None)
        self.assertTrue(os.path.samefile(source,target))
        self.assertEqual(source.read_bytes(),b'original-first')

    def test_reclassifying_an_existing_source_requires_review_without_an_orphan(self):
        source,_=self.fixture();target=self.library/'original.mkv'
        apply_preferred_media(str(source),str(target),self.metadata,None)
        renamed=self.library/'different-work.mkv'
        result=apply_preferred_media(str(source),str(renamed),{**self.metadata,'media_tmdb_id':2},None)
        self.assertFalse(result[0]);self.assertTrue(os.path.samefile(source,target))
        self.assertFalse(renamed.exists())
