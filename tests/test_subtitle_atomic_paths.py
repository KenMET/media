"""Subtitle writes must work with valid, long UTF-8 media basenames."""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from media_mcp.subtitle.domain.embedded_subtitle import EmbeddedSubtitleStream, extract_embedded_subtitle
from media_mcp.subtitle.domain.translation import SubtitleTranslationError, write_text_atomic


class SubtitleAtomicPathTests(unittest.TestCase):
    def test_english_cross_device_error_keeps_explicit_copy_fallback_working(self):
        import errno
        from media_mcp.ingest.domain.file_utils import create_hardlink
        from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent
        from media_mcp.subtitle.services import dependencies
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder, 'source.srt'); source.write_bytes(b'subtitle bytes')
            target = Path(folder, 'library', 'movie.srt')
            with patch('media_mcp.ingest.domain.file_utils.os.link', side_effect=OSError(errno.EXDEV, 'Cross-device link')):
                linked, reason = create_hardlink(str(source), str(target))
            self.assertFalse(linked)
            candidate = SimpleNamespace(path=str(source), extension='.srt', language='en', subtitle_type='normal')
            agent = SubtitleAgent.__new__(SubtitleAgent)
            with (
                patch.object(agent, '_canonicalize_numbered_sidecar', return_value=candidate),
                patch.object(agent, '_is_existing_target_sidecar', return_value=False),
                patch.object(dependencies, 'build_sidecar_path', return_value=str(target)),
                patch.object(dependencies, 'create_hardlink', return_value=(False, reason)),
                patch.object(dependencies, 'ALLOW_COPY_FALLBACK', True),
                patch.object(dependencies, 'assert_mutation_lock'),
                patch.object(dependencies, 'upsert_media_subtitle'),
            ):
                self.assertEqual(agent._process_sidecar({'target_path':str(Path(folder, 'movie.mkv'))}, candidate), 'copied')
            self.assertEqual(source.read_bytes(), b'subtitle bytes')
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertNotEqual(source.stat().st_ino, target.stat().st_ino)
            self.assertEqual(list(target.parent.iterdir()), [target])

    def target(self, folder, extension='.srt'):
        return Path(folder, '\u5b57' * 78 + extension)

    def test_extraction_supports_long_utf8_name_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            target=self.target(folder)
            def extract(command,**_):
                Path(command[-1]).write_text('extracted Chinese subtitle')
            with patch('media_mcp.subtitle.domain.embedded_subtitle.subprocess.run',side_effect=extract):
                self.assertEqual(extract_embedded_subtitle('/fake/video.mkv',Mock(stream_index=1),str(target)),(True,'embedded_extracted'))
            self.assertEqual(target.read_text(),'extracted Chinese subtitle')
            self.assertEqual(list(Path(folder).iterdir()),[target])

    def test_existing_target_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            target=self.target(folder);target.write_text('original')
            def extract(command,**_):Path(command[-1]).write_text('new')
            with patch('media_mcp.subtitle.domain.embedded_subtitle.subprocess.run',side_effect=extract):
                self.assertFalse(extract_embedded_subtitle('/fake/video.mkv',Mock(stream_index=1),str(target))[0])
            self.assertEqual(target.read_text(),'original')
            self.assertEqual(list(Path(folder).iterdir()),[target])

    def test_failed_extraction_cleans_partial_output(self):
        with tempfile.TemporaryDirectory() as folder:
            target=self.target(folder)
            def extract(command,**_):
                Path(command[-1]).write_text('partial')
                raise subprocess.TimeoutExpired(command,120)
            with patch('media_mcp.subtitle.domain.embedded_subtitle.subprocess.run',side_effect=extract):
                self.assertFalse(extract_embedded_subtitle('/fake/video.mkv',Mock(stream_index=1),str(target))[0])
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_lost_mutation_lock_prevents_publication_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            target=self.target(folder)
            def extract(command,**_):Path(command[-1]).write_text('complete output')
            with patch('media_mcp.subtitle.domain.embedded_subtitle.subprocess.run',side_effect=extract),patch(
                'media_mcp.runtime.state.assert_mutation_lock',side_effect=RuntimeError('media_mutation_lock_lost')):
                with self.assertRaisesRegex(RuntimeError,'media_mutation_lock_lost'):
                    extract_embedded_subtitle('/fake/video.mkv',Mock(stream_index=1),str(target))
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_translated_output_preserves_hardlinked_source_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder,'source.ass');source.write_text('source bytes')
            target=self.target(folder,'.ass');os.link(source,target)
            write_text_atomic(str(target),'\u65b0\u7684\u4e2d\u6587\u5b57\u5e55\n')
            self.assertEqual(source.read_text(),'source bytes')
            self.assertEqual(target.read_text(),'\u65b0\u7684\u4e2d\u6587\u5b57\u5e55\n')
            self.assertFalse(os.path.samefile(source,target))
            self.assertEqual(set(Path(folder).iterdir()),{source,target})

    def test_failed_translation_publish_preserves_target_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as folder:
            target=self.target(folder,'.ass');target.write_text('original')
            with patch('media_mcp.subtitle.domain.translation.os.replace',side_effect=OSError('publish failed')):
                with self.assertRaises(SubtitleTranslationError):write_text_atomic(str(target),'new')
            self.assertEqual(target.read_text(),'original')
            self.assertEqual(list(Path(folder).iterdir()),[target])

    def test_online_download_supports_long_utf8_name(self):
        from media_mcp.subtitle.services.online_subtitles import _process_online_subtitle
        from media_mcp.subtitle.services import dependencies
        with tempfile.TemporaryDirectory() as folder:
            video=self.target(folder,'.mkv');video.write_bytes(b'original video')
            candidate=SimpleNamespace(provider='fixture',candidate_id='fixture-candidate',file_id='fixture-1',language='zh-CN',subtitle_type='normal',format='srt')
            validated=SimpleNamespace(content=b'validated subtitle',extension='.srt',profile={'language':'zh-CN'})
            agent=Mock()
            agent.provider_registry.providers=[SimpleNamespace(name='fixture')]
            agent.provider_registry.provider_statuses=[{'provider':'fixture','configured':True}]
            agent._optional_int.return_value=None
            agent._online_search_titles.return_value=['Fixture']
            agent._media_display_name.return_value='Fixture'
            agent._provider_blocked_retry_at.return_value=None
            agent._search_provider_candidates.return_value=[candidate]
            agent._rank_online_candidates.return_value=[(200,candidate,'matched')]
            agent._redact_sensitive_text.side_effect=str
            agent._download_provider_candidate.return_value=SimpleNamespace(content=validated.content,file_name='fixture.srt')
            agent._online_candidate_explicit_episode_mismatch.return_value=None
            agent._replace_file.side_effect=os.replace
            agent._sync_downloaded_subtitle.return_value=(True,'validated')
            agent._validate_online_subtitle_timing.return_value=(True,'validated')
            agent._subtitle_metadata.return_value={}
            with patch.object(dependencies,'validate_online_subtitle',return_value=validated),patch.object(dependencies,'upsert_media_subtitle'):
                self.assertEqual(_process_online_subtitle(agent,{'target_path':str(video)}),'downloaded')
            target=Path(agent._replace_file.call_args.args[1])
            self.assertEqual(target.read_bytes(),validated.content)
            self.assertEqual(video.read_bytes(),b'original video')
            self.assertEqual(set(Path(folder).iterdir()),{video,target})

    @unittest.skipUnless(shutil.which('ffmpeg'),'ffmpeg required for real extraction')
    def test_real_ffmpeg_extracts_to_long_name_without_changing_video(self):
        with tempfile.TemporaryDirectory() as folder:
            subtitle=Path(folder,'input.srt');subtitle.write_text('1\n00:00:00,000 --> 00:00:00,900\n\u8fd9\u662f\u4e2d\u6587\u5b57\u5e55\n')
            video=Path(folder,'input.mkv')
            subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=16x16:d=1:r=1',
                '-i',str(subtitle),'-map','0:v','-map','1:0','-c:v','ffv1','-c:s','srt','-threads','1','-t','1',str(video)],check=True,capture_output=True,timeout=30)
            before=hashlib.sha256(video.read_bytes()).hexdigest();target=self.target(folder)
            stream=EmbeddedSubtitleStream(1,1,'subrip','zh-CN','chi','Chinese','normal',False,False)
            self.assertEqual(extract_embedded_subtitle(str(video),stream,str(target)),(True,'embedded_extracted'))
            self.assertIn('\u8fd9\u662f\u4e2d\u6587\u5b57\u5e55',target.read_text())
            self.assertEqual(hashlib.sha256(video.read_bytes()).hexdigest(),before)
            self.assertEqual(set(Path(folder).iterdir()),{subtitle,video,target})
