import os
from pathlib import Path
import unittest
from unittest.mock import patch
import test_collections as fixtures
from test_library_auto import AutoAI
from media_mcp.runtime.state import MediaJobs
from media_mcp.runtime.library_worker import process_task
from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent


def ass(chinese=True):
    text='[Script Info]\nTitle: AI translated bilingual subtitle\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    for index in range(10):
        words='这是中文对白内容。\\NEnglish dialogue.' if chinese else 'Only English dialogue.'
        text+=f'Dialogue: 0,0:00:{index:02d}.00,0:00:{index:02d}.90,Default,,0,0,0,,{words}\n'
    return text


class ExistingGeneratedSubtitleTests(unittest.TestCase):
    setUp=fixtures.CollectionsTests.setUp
    fixture=fixtures.CollectionsTests.fixture

    def run_fixture(self,legacy=False,chinese=True):
        self.fixture(1);source,target=self.paths[0];agent=SubtitleAgent(defer_ai_usage=True)
        row=dict(self.db.execute('SELECT * FROM media_link').mappings().one())
        path=Path(agent._legacy_translated_target_path(row) if legacy else agent._translated_target_path(row))
        path.write_text(ass(chinese));before=path.read_bytes();inode=path.stat().st_ino;source_before=source.read_bytes()
        request=self.service.library_auto('existing-generated-001')
        jobs=MediaJobs();jobs.initialize();claimed=jobs.claim('library')
        with patch('media_mcp.subtitle.services.dependencies.restyle_bilingual_ass',return_value=False),patch.object(agent,'_process_online_subtitle',side_effect=AssertionError('must not download again')):
            process_task(jobs,claimed,subtitle_agent=agent,analysis_client=AutoAI(),analysis_probe=lambda path:1400)
        jobs.finish(claimed)
        final=Path(agent._translated_target_path(dict(self.db.execute('SELECT * FROM media_link').mappings().one())))
        self.assertEqual(source.read_bytes(),source_before)
        self.assertEqual(final.read_bytes(),before);self.assertEqual(final.stat().st_ino,inode)
        return self.service.collection_task(request['job_id']),final

    def test_existing_generated_ass_is_registered_and_automatic_task_finishes(self):
        task,path=self.run_fixture()
        self.assertEqual(task['state'],'completed',task)
        self.assertEqual(task['summary']['subtitles'],1)
        row=self.db.execute('SELECT * FROM media_subtitle').mappings().one()
        self.assertEqual(row['target_subtitle_path'],str(path));self.assertEqual(row['status'],'exists')
        self.assertEqual(row['reason'],'existing_generated_subtitle_content_validated')
        self.assertEqual(self.service.library_auto('existing-generated-002')['total'],0)

    def test_legacy_generated_ass_is_registered_after_existing_migration(self):
        task,path=self.run_fixture(legacy=True)
        self.assertEqual(task['state'],'completed',task)
        self.assertEqual(self.db.execute('SELECT target_subtitle_path FROM media_subtitle').scalar(),str(path))

    def test_marker_without_chinese_dialogue_does_not_report_ready(self):
        task,path=self.run_fixture(chinese=False)
        self.assertEqual(task['state'],'completed_with_warnings')
        row=self.db.execute('SELECT status,reason FROM media_subtitle').mappings().one()
        self.assertEqual(row['status'],'needs_review')
        self.assertEqual(row['reason'],'existing_subtitle_chinese_content_unverified')

    def test_dry_run_does_not_write_a_subtitle_record(self):
        self.fixture(1);agent=SubtitleAgent(defer_ai_usage=True)
        row=dict(self.db.execute('SELECT * FROM media_link').mappings().one());path=Path(agent._translated_target_path(row));path.write_text(ass())
        self.assertEqual(agent._process_media_link(row,[],test_mode=True),'exists')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM media_subtitle').scalar(),0)

if __name__=='__main__':unittest.main()
