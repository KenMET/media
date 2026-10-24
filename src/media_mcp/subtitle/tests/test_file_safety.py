import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import Mock, patch
from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
from media_mcp.subtitle.services import dependencies
from media_mcp.subtitle.domain.embedded_subtitle import set_mkv_default_subtitle, extract_embedded_subtitle


class SubtitleSafetyTests(unittest.TestCase):
    def agent(self):return SubtitleAgent(provider_registry=Mock())

    def test_cleanup_preserves_active_output_and_user_source(self):
        with tempfile.TemporaryDirectory() as root:
            files=[Path(root,name) for name in ('video.ass','video.zh-CN-bilingual.ass','video.en.srt')]
            for file in files:file.write_text('keep')
            self.agent()._cleanup_legacy_translation_sources({'target_path':str(Path(root,'video.mkv'))})
            self.assertTrue(all(file.exists() for file in files))

    def test_shared_video_is_never_edited_even_if_feature_enabled(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root,'source.mkv');source.write_bytes(b'video');target=Path(root,'target.mkv');os.link(source,target)
            with patch('media_mcp.subtitle.domain.embedded_subtitle.subprocess.run') as run:
                self.assertEqual(set_mkv_default_subtitle(str(target),Mock()),(False,'shared_inode_must_not_be_modified'))
                run.assert_not_called()
            self.assertEqual(source.read_bytes(),b'video')

    def test_failed_extraction_never_publishes_partial_or_overwrites_existing_subtitle(self):
        with tempfile.TemporaryDirectory() as root:
            target=Path(root,'video.srt');target.write_text('original')
            def fail(command,**_):
                Path(command[-1]).write_text('partial')
                raise subprocess.TimeoutExpired(command,120)
            with patch('media_mcp.subtitle.domain.embedded_subtitle.subprocess.run',side_effect=fail):
                ok,_=extract_embedded_subtitle('/fake/video.mkv',Mock(stream_index=1),str(target))
            self.assertFalse(ok);self.assertEqual(target.read_text(),'original')
            self.assertEqual(list(Path(root).iterdir()),[target])

    def test_preview_does_not_remove_mislinked_subtitle(self):
        agent=self.agent()
        agent._target_sidecar_candidates=Mock(return_value=[])
        agent._translated_target_path=Mock(return_value='/fake/video.ass')
        agent._legacy_translated_target_path=Mock(return_value='/fake/video.ass')
        agent._remove_mislinked_generated_subtitle=Mock()
        agent._parse_subtitle_candidate=Mock(return_value=Mock(generated_by_agent=True))
        with patch.object(dependencies.os.path,'exists',return_value=True):
            self.assertEqual(agent._process_media_link({'source_path':'/fake/source.mkv','target_path':'/fake/video.mkv'},[],test_mode=True),'exists')
        agent._remove_mislinked_generated_subtitle.assert_not_called()

    def test_quota_error_defers_without_sleep(self):
        agent=SubtitleAgent(provider_registry=Mock(),defer_ai_usage=True)
        with patch.object(dependencies.time,'sleep') as sleep:
            with self.assertRaises(RuntimeError):agent._call_ai_with_usage_retry(Mock(side_effect=RuntimeError('rate limit')),media_label='movie',operation='translate')
            sleep.assert_not_called()
