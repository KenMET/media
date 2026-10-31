"""Explicit legacy cleanup preserves source bytes and refuses stale evidence."""
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import test_platform
from media_mcp.application.duplicates import Duplicates
from media_mcp.platform.service import PlatformService
from media_mcp.storage.media import upsert_media_link
from media_mcp.runtime.state import MediaJobs


class DuplicateTests(TestCase):
    setUp=test_platform.PlatformTests.setUp

    def fixture(self):
        source=Path(os.environ['MEDIA_DOWNLOAD_ROOT']);source.mkdir()
        library=Path(os.environ['MEDIA_LIBRARY_ROOT']);library.mkdir()
        self.sources=[];self.targets=[]
        for n in range(2):
            src=source/f'version-{n}.mkv';src.write_bytes(f'original-{n}'.encode())
            target=library/f'movie-{n}.mkv';os.link(src,target)
            upsert_media_link(None,str(src),str(target),media_type='movie',media_tmdb_id=1,
                media_name='Movie',status='linked')
            self.sources.append(src);self.targets.append(target)
        return Duplicates(PlatformService(self.admin,self.accounts,self.records))

    def test_preview_is_read_only_confirmation_is_idempotent_and_sources_survive(self):
        duplicates=self.fixture();before=[(p.read_bytes(),p.stat().st_ino) for p in self.sources]
        group=duplicates.list()['groups'][0]
        plan=duplicates.preview(group['versions'][0]['id'])
        self.assertTrue(all(p.exists() for p in self.targets))
        with self.assertRaisesRegex(ValueError,'explicit_confirmation'):
            duplicates.apply(plan['plan_id'],False)
        receipt=duplicates.apply(plan['plan_id'],True)
        self.assertEqual(receipt['retired_versions'],1)
        self.assertEqual(duplicates.apply(plan['plan_id'],True),receipt)
        self.assertTrue(self.targets[0].exists());self.assertFalse(self.targets[1].exists())
        self.assertEqual([(p.read_bytes(),p.stat().st_ino) for p in self.sources],before)
        self.assertEqual(duplicates.list()['groups'],[])

    def test_changed_target_and_active_delivery_are_rejected(self):
        duplicates=self.fixture();group=duplicates.list()['groups'][0]
        plan=duplicates.preview(group['versions'][0]['id'])
        self.targets[1].unlink();self.targets[1].write_bytes(b'replacement')
        with self.assertRaisesRegex(ValueError,'identity|changed'):
            duplicates.apply(plan['plan_id'],True)
        self.assertEqual(self.targets[1].read_bytes(),b'replacement')
        self.targets[1].unlink();os.link(self.sources[1],self.targets[1])
        jobs=MediaJobs();jobs.initialize();jobs.enqueue('busy',str(self.sources[0].parent))
        with self.assertRaisesRegex(ValueError,'busy'):
            duplicates.preview(group['versions'][0]['id'])

    def test_source_missing_or_wrong_owner_cannot_cleanup(self):
        duplicates=self.fixture();group=duplicates.list()['groups'][0]
        plan=duplicates.preview(group['versions'][0]['id'])
        other=Duplicates(PlatformService(self.alice,self.accounts,self.records))
        with self.assertRaises(ValueError):other.apply(plan['plan_id'],True)
        self.sources[1].unlink()
        with self.assertRaisesRegex(ValueError,'identity'):
            duplicates.apply(plan['plan_id'],True)
        self.assertTrue(all(p.exists() for p in self.targets))

    def test_failed_cleanup_preserves_keeper_and_restores_all_links_and_subtitles(self):
        duplicates=self.fixture();group=duplicates.list()['groups'][0]
        subtitle=self.targets[1].with_suffix('.srt');subtitle.write_text('Original subtitles')
        plan=duplicates.preview(group['versions'][0]['id'])
        with patch('media_mcp.application.duplicates.os.replace',side_effect=OSError('Archive unavailable')):
            with self.assertRaisesRegex(OSError,'Archive unavailable'):
                duplicates.apply(plan['plan_id'],True)
        self.assertTrue(all(p.exists() for p in self.targets))
        self.assertTrue(all(os.path.samefile(s,t) for s,t in zip(self.sources,self.targets)))
        self.assertEqual(subtitle.read_text(),'Original subtitles')
        self.assertEqual(len(duplicates.list()['groups']),1)
        self.assertEqual(duplicates.apply(plan['plan_id'],True)['retired_versions'],1)
        self.assertTrue(self.targets[0].exists())
        self.assertFalse(subtitle.exists())
        self.assertEqual(len(list(self.sources[1].parent.glob('.phantom-subtitles/*/*'))),1)

    def test_shared_stem_subtitle_stays_with_keeper(self):
        duplicates=self.fixture()
        second=self.targets[0].with_suffix('.mp4')
        self.targets[1].rename(second);self.targets[1]=second
        upsert_media_link(None,str(self.sources[1]),str(second),media_type='movie',media_tmdb_id=1,
            media_name='Movie',status='linked')
        subtitle=self.targets[0].with_suffix('.srt');subtitle.write_text('Shared keeper subtitles')
        group=duplicates.list()['groups'][0]
        plan=duplicates.preview(group['versions'][0]['id'])
        duplicates.apply(plan['plan_id'],True)
        self.assertTrue(self.targets[0].exists());self.assertFalse(second.exists())
        self.assertEqual(subtitle.read_text(),'Shared keeper subtitles')
