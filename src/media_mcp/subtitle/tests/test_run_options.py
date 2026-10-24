#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest
from contextlib import nullcontext
import os
import json
import tempfile
from unittest.mock import Mock, patch, mock_open

from media_mcp.subtitle.run import build_parser
from media_mcp.subtitle.domain.embedded_subtitle import EmbeddedSubtitleStream
from media_mcp.subtitle.domain.online_subtitle import ValidatedOnlineSubtitle
from media_mcp.subtitle.domain.subtitle_file import SubtitleCandidate
from media_mcp.subtitle.domain.subtitle_sync import SubtitleSyncResult
from media_mcp.subtitle.providers.base import DownloadedSubtitle, OnlineSubtitleCandidate
from media_mcp.subtitle.providers.base import ProviderTemporarilyUnavailable
from media_mcp.adapters.subtitle.opensubtitles import OpenSubtitlesProvider
from media_mcp.subtitle.services.subtitle_agent import SubtitleAgent


class SubtitleRunOptionsTest(unittest.TestCase):
    def setUp(self):
        # These tests exercise orchestration with a fake store. Cross-process
        # locking is verified separately against isolated MySQL.
        lock = patch('media_mcp.runtime.state.media_mutation_lock', return_value=nullcontext())
        lock.start()
        self.addCleanup(lock.stop)

    def test_disable_opensubtitle_cli_option(self):
        args = build_parser().parse_args(['--disable-opensubtitle'])

        self.assertTrue(args.disable_opensubtitle)
        self.assertFalse(args.disable_agent)

    def test_opensubtitles_requires_api_key_environment(self):
        with patch.dict(
            'os.environ',
            {
                'OPENSUBTITLES_API_KEY': '',
                'OPENSUBTITLES_USER_AGENT': 'phantom_slayer test',
            },
            clear=False,
        ):
            provider = OpenSubtitlesProvider()

        self.assertFalse(provider.configured)

    def test_opensubtitles_uses_api_key_environment(self):
        with patch.dict(
            'os.environ',
            {
                'OPENSUBTITLES_API_KEY': 'test-key',
                'OPENSUBTITLES_USER_AGENT': 'phantom_slayer test',
            },
            clear=False,
        ):
            provider = OpenSubtitlesProvider()

        self.assertTrue(provider.configured)

    def test_translation_does_not_overwrite_non_generated_plain_ass(self):
        agent = SubtitleAgent(
            provider_registry=Mock(providers=[]),
            disable_opensubtitle=True,
        )
        with tempfile.TemporaryDirectory() as directory:
            video_path = os.path.join(directory, 'movie.mkv')
            plain_ass = os.path.join(directory, 'movie.ass')
            with open(plain_ass, 'w', encoding='utf-8') as handle:
                handle.write(
                    '[Script Info]\n'
                    '[Events]\n'
                    'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
                    'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello\n'
                )

            target = agent._translated_target_path({'target_path': video_path})

        self.assertTrue(target.endswith('movie.zh-CN-bilingual.ass'))

    def test_translation_source_prefers_media_original_language_sidecar(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/Anime.S01E01.mkv',
            'target_path': '/library/Anime.S01E01.mkv',
            'media_type': 'tv',
            'season': 1,
            'episode': 1,
            'original_language': 'ja',
        }
        english = SubtitleCandidate(
            path='/downloads/Anime.S01E01.en.srt',
            extension='.srt',
            language='en',
            subtitle_type='normal',
            season=1,
            episode=1,
            release_group=None,
            sample=[],
        )
        japanese = SubtitleCandidate(
            path='/downloads/Anime.S01E01.ja.srt',
            extension='.srt',
            language='ja',
            subtitle_type='normal',
            season=1,
            episode=1,
            release_group=None,
            sample=[],
        )

        selected = agent._select_sidecar_translation_source(media_link, [english, japanese])

        self.assertEqual(japanese.path, selected.path)

    def test_translation_source_reads_original_language_from_agent_json(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/Anime.S01E01.mkv',
            'target_path': '/library/Anime.S01E01.mkv',
            'media_type': 'tv',
            'season': 1,
            'episode': 1,
            'agent_result_json': json.dumps(
                {'normalized_result': {'original_language': 'jpn', 'origin_country': 'JP'}},
                ensure_ascii=False,
            ),
        }

        self.assertEqual('ja', agent._media_original_language(media_link))
        self.assertEqual('JP', agent._translation_media_context(media_link)['origin_country'])

    def test_embedded_translation_source_prefers_media_original_language(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {'original_language': 'ja'}
        english = EmbeddedSubtitleStream(
            stream_index=2,
            subtitle_ordinal=1,
            codec='subrip',
            language='en',
            raw_language='eng',
            title='English',
            subtitle_type='normal',
            disposition_default=True,
            disposition_forced=False,
        )
        japanese = EmbeddedSubtitleStream(
            stream_index=3,
            subtitle_ordinal=2,
            codec='subrip',
            language='ja',
            raw_language='jpn',
            title='Japanese',
            subtitle_type='normal',
            disposition_default=False,
            disposition_forced=False,
        )

        selected = agent._select_embedded_translation_source_for_media(media_link, [english, japanese])

        self.assertEqual(japanese.stream_index, selected.stream_index)

    def test_embedded_translation_source_skips_signs_and_songs_track(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {'original_language': 'en'}
        signs = EmbeddedSubtitleStream(
            stream_index=2,
            subtitle_ordinal=1,
            codec='ass',
            language='en',
            raw_language='eng',
            title='English Signs/Songs',
            subtitle_type='forced',
            disposition_default=True,
            disposition_forced=False,
        )
        full = EmbeddedSubtitleStream(
            stream_index=3,
            subtitle_ordinal=2,
            codec='ass',
            language='en',
            raw_language='eng',
            title='English Full Subtitles',
            subtitle_type='normal',
            disposition_default=False,
            disposition_forced=False,
        )

        selected = agent._select_embedded_translation_source_for_media(media_link, [signs, full])

        self.assertEqual(full.stream_index, selected.stream_index)

    def test_embedded_ocr_translation_source_selects_pgs_origin_language(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {'origin_country': 'US'}
        english_pgs = EmbeddedSubtitleStream(
            stream_index=5,
            subtitle_ordinal=1,
            codec='hdmv_pgs_subtitle',
            language='en',
            raw_language='eng',
            title='English PGS',
            subtitle_type='normal',
            disposition_default=True,
            disposition_forced=False,
        )
        spanish_pgs = EmbeddedSubtitleStream(
            stream_index=6,
            subtitle_ordinal=2,
            codec='hdmv_pgs_subtitle',
            language='es',
            raw_language='spa',
            title='Spanish PGS',
            subtitle_type='normal',
            disposition_default=False,
            disposition_forced=False,
        )

        selected = agent._select_embedded_ocr_translation_source_for_media(
            media_link,
            [spanish_pgs, english_pgs],
            language_preferences=('en',),
        )

        self.assertEqual(english_pgs.stream_index, selected.stream_index)

    def test_translation_source_prefers_origin_country_over_original_language(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'origin_country': 'JP',
            'original_language': 'fr',
        }

        self.assertEqual(('ja', 'en'), agent._translation_source_language_preferences(media_link))

    def test_process_media_link_tries_online_chinese_before_translation(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/movie.mkv',
            'target_path': '/library/movie.mkv',
            'media_type': 'movie',
            'origin_country': 'JP',
        }

        with (
            patch.object(agent, '_target_sidecar_candidates', return_value=[]),
            patch.object(agent, '_translated_target_path', return_value='/library/movie.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/library/movie.zh-CN-bilingual.ass'),
            patch.object(agent, '_process_embedded', return_value='no_preferred_embedded_subtitle'),
            patch.object(agent, '_process_text_translation') as translation,
            patch.object(agent, '_select_sidecar', return_value=(None, None)) as select_sidecar,
            patch.object(agent, '_process_online_subtitle', return_value='downloaded') as online,
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_media_link(media_link, [])

        self.assertEqual('downloaded', action)
        select_sidecar.assert_called_once()
        online.assert_called_once_with(media_link, test_mode=False)
        translation.assert_not_called()

    def test_process_media_link_translation_order_after_online_chinese_miss(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/movie.mkv',
            'target_path': '/library/movie.mkv',
            'media_type': 'movie',
            'origin_country': 'US',
        }

        with (
            patch.object(agent, '_target_sidecar_candidates', return_value=[]),
            patch.object(agent, '_translated_target_path', return_value='/library/movie.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/library/movie.zh-CN-bilingual.ass'),
            patch.object(agent, '_process_embedded', return_value='no_preferred_embedded_subtitle'),
            patch.object(agent, '_select_sidecar', return_value=(None, None)),
            patch.object(agent, '_process_online_subtitle', return_value=None),
            patch.object(agent, '_process_text_translation', return_value='translated') as translation,
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_media_link(media_link, [])

        self.assertEqual('translated', action)
        translation.assert_called_once_with(
            media_link,
            [],
            test_mode=False,
            source_kinds=('embedded', 'sidecar', 'online'),
            reuse_existing_output=False,
        )

    def test_rejected_english_target_is_preserved_before_chinese_fallback(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, 'movie.mkv')
            subtitle = os.path.join(directory, 'movie.ass')
            content = ('[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
                + ''.join(f'Dialogue: 0,0:00:{i:02d}.00,0:00:{i:02d}.90,Default,,0,0,0,,English dialogue {i}\n' for i in range(10)))
            with open(subtitle, 'w') as handle: handle.write(content)
            candidate = SubtitleCandidate(path=subtitle, extension='.ass', language='zh-CN',
                subtitle_type='normal', season=None, episode=None, release_group=None, sample=[])
            media = {'source_path': target, 'target_path': target, 'media_type': 'movie'}
            with (
                patch.object(agent, '_target_sidecar_candidates', return_value=[candidate]),
                patch.object(agent, '_translated_target_path', return_value=target+'.generated.ass'),
                patch.object(agent, '_legacy_translated_target_path', return_value=target+'.legacy.ass'),
                patch.object(agent, '_replace_file', side_effect=os.replace),
                patch.object(agent, '_invalidate_path_cache'),
                patch.object(agent, '_cleanup_redundant_language_sidecars'),
                patch.object(agent, '_process_sidecar') as reuse,
                patch.object(agent, '_process_embedded', return_value='embedded_extracted'),
            ):
                self.assertEqual(agent._process_media_link(media, []), 'embedded_extracted')
            reuse.assert_not_called()
            backups = [name for name in os.listdir(directory) if name.endswith('.rejected-language')]
            self.assertEqual(len(backups), 1)
            with open(os.path.join(directory, backups[0])) as handle: self.assertEqual(handle.read(), content)
            self.assertFalse(os.path.exists(subtitle))

    def test_existing_target_sidecar_skips_embedded_translation(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/movie.mkv',
            'target_path': '/library/movie.mkv',
            'media_type': 'movie',
            'origin_country': 'US',
        }
        sidecar = SubtitleCandidate(
            path='/library/movie.zh-CN.srt',
            extension='.srt',
            language='zh-CN',
            subtitle_type='normal',
            season=None,
            episode=None,
            release_group=None,
            sample=[],
        )

        with (
            patch.object(agent, '_target_sidecar_candidates', return_value=[sidecar]),
            patch('builtins.open', mock_open(read_data=b'validated content')),
            patch('media_mcp.subtitle.services.dependencies.validate_online_subtitle'),
            patch.object(agent, '_translated_target_path', return_value='/library/movie.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/library/movie.zh-CN-bilingual.ass'),
            patch.object(agent, '_process_sidecar', return_value='exists') as process_sidecar,
            patch.object(agent, '_process_embedded') as embedded,
            patch.object(agent, '_process_text_translation') as translation,
            patch.object(agent, '_cleanup_redundant_language_sidecars'),
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_media_link(media_link, [])

        self.assertEqual('exists', action)
        process_sidecar.assert_called_once_with(media_link, sidecar, test_mode=False)
        embedded.assert_not_called()
        translation.assert_not_called()

    def test_online_translation_searches_origin_english_then_any_foreign(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/movie.mkv',
            'target_path': '/library/movie.mkv',
            'media_type': 'movie',
            'origin_country': 'JP',
        }
        any_source = {
            'source_path': None,
            'source_id': 'provider://subdl/ko-1',
            'source_language': 'ko',
            'source_type': 'provider_translation',
            'source_detail': 'online subdl:ko-1',
            'temporary_source': False,
        }

        with (
            patch.object(agent, '_translated_target_path', return_value='/library/movie.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/library/movie.zh-CN-bilingual.ass'),
            patch.object(agent, '_download_online_translation_source', side_effect=[None, None, any_source]) as download,
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_text_translation(
                media_link,
                [],
                test_mode=True,
                source_kinds=('online',),
            )

        self.assertEqual('translated', action)
        self.assertEqual(('ja',), download.call_args_list[0].kwargs['language_preferences'])
        self.assertEqual(('en',), download.call_args_list[1].kwargs['language_preferences'])
        fallback_languages = download.call_args_list[2].kwargs['language_preferences']
        self.assertEqual('ko', fallback_languages[0])
        self.assertNotIn('ja', fallback_languages)
        self.assertNotIn('en', fallback_languages)

    def test_translation_source_order_is_language_first_then_source(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/movie.mkv',
            'target_path': '/library/movie.mkv',
            'media_type': 'movie',
            'origin_country': 'JP',
        }
        english_source = {
            'source_path': None,
            'source_id': 'provider://subdl/en-1',
            'source_language': 'en',
            'source_type': 'provider_translation',
            'source_detail': 'online subdl:en-1',
            'temporary_source': False,
        }

        with (
            patch.object(agent, '_translated_target_path', return_value='/library/movie.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/library/movie.zh-CN-bilingual.ass'),
            patch.object(agent, '_select_embedded_translation_source_for_media', return_value=None) as embedded,
            patch.object(agent, '_select_sidecar_translation_source', return_value=None) as sidecar,
            patch.object(agent, '_download_online_translation_source', side_effect=[None, english_source]) as online,
            patch('media_mcp.subtitle.services.dependencies.ffprobe_subtitle_streams', return_value=[]),
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_text_translation(
                media_link,
                [],
                test_mode=True,
                source_kinds=('embedded', 'sidecar', 'online'),
            )

        self.assertEqual('translated', action)
        self.assertEqual(('ja',), embedded.call_args_list[0].kwargs['language_preferences'])
        self.assertEqual(('ja',), sidecar.call_args_list[0].kwargs['language_preferences'])
        self.assertEqual(('ja',), online.call_args_list[0].kwargs['language_preferences'])
        self.assertEqual(('en',), embedded.call_args_list[1].kwargs['language_preferences'])
        self.assertEqual(('en',), sidecar.call_args_list[1].kwargs['language_preferences'])
        self.assertEqual(('en',), online.call_args_list[1].kwargs['language_preferences'])

    def test_translation_uses_embedded_pgs_ocr_before_sidecar_online(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/downloads/movie.mkv',
            'target_path': '/library/movie.mkv',
            'media_type': 'movie',
            'origin_country': 'US',
        }
        english_pgs = EmbeddedSubtitleStream(
            stream_index=5,
            subtitle_ordinal=1,
            codec='hdmv_pgs_subtitle',
            language='en',
            raw_language='eng',
            title='English PGS',
            subtitle_type='normal',
            disposition_default=True,
            disposition_forced=False,
        )

        with (
            patch.object(agent, '_translated_target_path', return_value='/library/movie.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/library/movie.zh-CN-bilingual.ass'),
            patch('media_mcp.subtitle.services.dependencies.ffprobe_subtitle_streams', return_value=[english_pgs]),
            patch.object(agent, '_select_sidecar_translation_source') as sidecar,
            patch.object(agent, '_download_online_translation_source') as online,
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_text_translation(
                media_link,
                [],
                test_mode=True,
                source_kinds=('embedded', 'sidecar', 'online'),
            )

        self.assertEqual('translated', action)
        self.assertEqual('translated:embedded_ocr:en', agent._last_action_detail)
        sidecar.assert_not_called()
        online.assert_not_called()

    def test_ai_usage_error_waits_and_retries(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]), defer_ai_usage=False)
        call = Mock(side_effect=[RuntimeError('429 insufficient quota'), {'success': True}])

        with patch('media_mcp.subtitle.services.dependencies.time.sleep') as sleep:
            result = agent._call_ai_with_usage_retry(
                call,
                media_label='movie',
                operation='subtitle_translate',
            )

        self.assertEqual({'success': True}, result)
        self.assertEqual(2, call.call_count)
        sleep.assert_called_once()

    def test_ai_usage_failure_response_waits_and_retries(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]), defer_ai_usage=False)
        call = Mock(side_effect=[
            {'success': False, 'error': 'billing hard limit reached'},
            {'success': True},
        ])

        with patch('media_mcp.subtitle.services.dependencies.time.sleep') as sleep:
            result = agent._call_ai_with_usage_retry(
                call,
                media_label='movie',
                operation='subtitle_translate',
            )

        self.assertEqual({'success': True}, result)
        self.assertEqual(2, call.call_count)
        sleep.assert_called_once()

    def test_non_usage_ai_error_is_not_retried_forever(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        call = Mock(side_effect=RuntimeError('invalid JSON response'))

        with patch('media_mcp.subtitle.services.dependencies.time.sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'invalid JSON'):
                agent._call_ai_with_usage_retry(
                    call,
                    media_label='movie',
                    operation='subtitle_translate',
                )

        self.assertEqual(1, call.call_count)
        sleep.assert_not_called()

    def test_ai_usage_retry_stops_after_max_wait(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]), defer_ai_usage=False)
        call = Mock(side_effect=RuntimeError('429 insufficient quota'))

        with (
            patch('media_mcp.subtitle.services.dependencies.AI_RETRY_WAIT_SECONDS', 10),
            patch('media_mcp.subtitle.services.dependencies.AI_RETRY_MAX_WAIT_SECONDS', 20),
            patch('media_mcp.subtitle.services.dependencies.time.sleep') as sleep,
        ):
            with self.assertRaisesRegex(RuntimeError, 'exceeded max wait'):
                agent._call_ai_with_usage_retry(
                    call,
                    media_label='movie',
                    operation='subtitle_translate',
                )

        self.assertEqual(3, call.call_count)
        self.assertEqual(2, sleep.call_count)

    def test_disable_opensubtitle_also_disables_agent(self):
        agent = SubtitleAgent(
            provider_registry=Mock(providers=[]),
            disable_opensubtitle=True,
        )

        self.assertTrue(agent.disable_opensubtitle)
        self.assertTrue(agent.disable_agent)

    def test_disable_opensubtitle_stops_after_local_processing(self):
        agent = SubtitleAgent(
            provider_registry=Mock(providers=[]),
            disable_opensubtitle=True,
        )
        media_link = {
            'source_path': '/media/movie.mkv',
            'target_path': '/library/movie.mkv',
            'media_type': 'movie',
        }

        with (
            patch.object(agent, '_cleanup_redundant_language_sidecars'),
            patch.object(agent, '_translated_target_path', return_value='/library/movie.zh-CN-bilingual.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/library/movie.bilingual.ass'),
            patch.object(agent, '_process_embedded', return_value=None),
            patch.object(agent, '_select_sidecar', return_value=(None, None)),
            patch.object(agent, '_process_online_subtitle') as online,
            patch.object(agent, '_process_text_translation') as translation,
            patch.object(agent, '_mark_missing', return_value='missing') as mark_missing,
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_media_link(media_link, [])

        self.assertEqual(action, 'missing')
        online.assert_not_called()
        translation.assert_not_called()
        mark_missing.assert_called_once_with(
            media_link,
            'opensubtitle_disabled_no_local_chinese_subtitle',
            test_mode=False,
        )

    def test_generic_chinese_tracks_are_analyzed_even_when_one_is_default(self):
        agent = SubtitleAgent(
            provider_registry=Mock(providers=[]),
            disable_opensubtitle=True,
        )
        simplified_or_traditional = [
            EmbeddedSubtitleStream(
                stream_index=5,
                subtitle_ordinal=1,
                codec='ass',
                language='zh',
                raw_language='chi',
                title=None,
                subtitle_type='normal',
                disposition_default=True,
                disposition_forced=False,
            ),
            EmbeddedSubtitleStream(
                stream_index=6,
                subtitle_ordinal=2,
                codec='ass',
                language='zh',
                raw_language='chi',
                title=None,
                subtitle_type='normal',
                disposition_default=False,
                disposition_forced=False,
            ),
        ]

        ambiguous = agent._ambiguous_embedded_selection(
            simplified_or_traditional,
            simplified_or_traditional[0],
        )

        self.assertEqual([5, 6], [stream.stream_index for stream in ambiguous])

    def test_subtitle_run_path_sends_completion_notification(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/data/downloads/movie.mkv',
            'target_path': '/data/media_hub/movie.mkv',
            'media_type': 'movie',
            'media_name': '电影名',
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'movie.mkv')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('')

            with (
                patch.object(agent, '_media_links_for_path', return_value=[media_link]),
                patch.object(agent, '_process_media_link', return_value='translated'),
                patch('media_mcp.subtitle.services.dependencies.discover_subtitle_files', return_value=[]),
                patch('media_mcp.subtitle.services.dependencies.mcp_direct_call_ns', return_value=True) as notify,
            ):
                result = agent.run_path(path)

        self.assertEqual((1, 0, 0, 0), result)
        notify.assert_called_once()
        _, kwargs = notify.call_args
        self.assertEqual('notify.send_notification', notify.call_args.args[0])
        self.assertEqual('Media字幕通知', kwargs['title'])
        self.assertIn('电影 电影名 字幕按AI翻译处理完成', kwargs['content'])

    def test_subtitle_dry_run_does_not_send_notification(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/data/downloads/movie.mkv',
            'target_path': '/data/media_hub/movie.mkv',
            'media_type': 'movie',
            'media_name': '电影名',
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'movie.mkv')
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write('')

            with (
                patch.object(agent, '_media_links_for_path', return_value=[media_link]),
                patch.object(agent, '_process_media_link', return_value='downloaded'),
                patch('media_mcp.subtitle.services.dependencies.discover_subtitle_files', return_value=[]),
                patch('media_mcp.subtitle.services.dependencies.mcp_direct_call_ns') as notify,
            ):
                result = agent.run_path(path, test_mode=True)

        self.assertEqual((1, 0, 0, 0), result)
        notify.assert_not_called()

    def test_subtitle_batch_continues_after_single_media_exception(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        first = {
            'source_path': '/data/downloads/show/S01E01.mkv',
            'target_path': '/data/media_hub/show/S01E01.mkv',
            'media_type': 'tv',
            'media_name': '剧名',
            'season': 1,
            'episode': 1,
        }
        second = {
            'source_path': '/data/downloads/show/S01E02.mkv',
            'target_path': '/data/media_hub/show/S01E02.mkv',
            'media_type': 'tv',
            'media_name': '剧名',
            'season': 1,
            'episode': 2,
        }
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(agent, '_media_links_for_path', return_value=[first, second]),
                patch.object(agent, '_process_media_link', side_effect=[RuntimeError('boom'), 'downloaded']) as process,
                patch.object(agent, '_record_failed') as record_failed,
                patch('media_mcp.subtitle.services.dependencies.discover_subtitle_files', return_value=[]),
            ):
                summary = agent.run_path_summary(directory, send_notify=False)

        self.assertEqual(2, process.call_count)
        record_failed.assert_called_once()
        self.assertEqual(1, summary['handled'])
        self.assertEqual(1, summary['failed'])
        self.assertEqual({'failed': 1, 'downloaded': 1}, summary['action_counts'])
        self.assertEqual({'failed:batch_exception': 1, 'downloaded': 1}, summary['detailed_action_counts'])

    def test_subtitle_summary_counts_detailed_translation_sources(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        first = {
            'source_path': '/data/downloads/show/S01E01.mkv',
            'target_path': '/data/media_hub/show/S01E01.mkv',
            'media_type': 'tv',
            'media_name': 'Show',
            'season': 1,
            'episode': 1,
        }
        second = {
            'source_path': '/data/downloads/show/S01E02.mkv',
            'target_path': '/data/media_hub/show/S01E02.mkv',
            'media_type': 'tv',
            'media_name': 'Show',
            'season': 1,
            'episode': 2,
        }
        third = {
            'source_path': '/data/downloads/show/S01E03.mkv',
            'target_path': '/data/media_hub/show/S01E03.mkv',
            'media_type': 'tv',
            'media_name': 'Show',
            'season': 1,
            'episode': 3,
        }

        def process(media_link, _sidecars, test_mode=False):
            if media_link['episode'] == 1:
                agent._set_action_detail('translated:embedded:en')
                return 'translated'
            if media_link['episode'] == 2:
                agent._set_action_detail('translated:online:ja')
                return 'translated'
            agent._set_action_detail('failed:translation')
            return 'failed'

        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(agent, '_media_links_for_path', return_value=[first, second, third]),
                patch.object(agent, '_process_media_link', side_effect=process),
                patch('media_mcp.subtitle.services.dependencies.discover_subtitle_files', return_value=[]),
            ):
                summary = agent.run_path_summary(directory, send_notify=False)

        self.assertEqual({'translated': 2, 'failed': 1}, summary['action_counts'])
        self.assertEqual(
            {'translated:embedded:en': 1, 'translated:online:ja': 1, 'failed:translation': 1},
            summary['detailed_action_counts'],
        )

    def test_online_download_falls_back_to_next_provider_after_quota(self):
        class ProviderStub:
            def __init__(self, name, registry):
                self.name = name
                self.registry = registry

            def search(self, request):
                return [
                    candidate
                    for candidate in self.registry.candidates
                    if candidate.provider == self.name
                ]

            def download(self, candidate):
                self.registry.downloaded.append(candidate.provider)
                if candidate.provider == 'opensubtitles':
                    raise ProviderTemporarilyUnavailable('opensubtitles', 'quota exhausted')
                return DownloadedSubtitle(b'normalized subtitle', candidate.file_name)

        class RegistryStub:
            def __init__(self, candidates):
                self.candidates = candidates
                self.downloaded = []
                self.providers = [ProviderStub('opensubtitles', self), ProviderStub('subdl', self)]

        candidates = [
            OnlineSubtitleCandidate(
                provider='opensubtitles',
                candidate_id='os-1',
                file_id='1',
                file_name='open.srt',
                language='zh-CN',
                subtitle_type='normal',
                format='srt',
                media_type='movie',
                tmdb_id=27205,
                download_count=10000,
            ),
            OnlineSubtitleCandidate(
                provider='subdl',
                candidate_id='subdl-1',
                file_id='/subtitle/1-2.zip',
                file_name='subdl.zip',
                language='zh-CN',
                subtitle_type='normal',
                format='srt',
                media_type='movie',
                tmdb_id=27205,
                download_count=1,
            ),
        ]
        registry = RegistryStub(candidates)
        agent = SubtitleAgent(provider_registry=registry)

        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, 'movie.mkv')
            media_link = {
                'source_path': target,
                'target_path': target,
                'media_type': 'movie',
                'media_tmdb_id': 27205,
                'media_name': 'Inception',
            }
            validated = ValidatedOnlineSubtitle(
                content=b'1\n00:00:01,000 --> 00:00:02,000\nChinese\n',
                extension='.srt',
                encoding='utf-8',
                profile={'chinese_chars': 20, 'dialogue_lines': 6},
            )
            with (
                patch('media_mcp.subtitle.services.dependencies.validate_online_subtitle', return_value=validated),
                patch('media_mcp.subtitle.services.dependencies.SUBTITLE_SYNC_MODE', 'disabled'),
                patch('media_mcp.subtitle.services.dependencies.upsert_media_subtitle') as upsert,
            ):
                status = agent._process_online_subtitle(media_link)

            output = os.path.join(directory, 'movie.srt')
            output_exists = os.path.exists(output)

        self.assertEqual('downloaded', status)
        self.assertEqual(['opensubtitles', 'subdl'], registry.downloaded)
        self.assertTrue(upsert.called)
        self.assertTrue(output_exists)

    def test_online_search_falls_back_to_filename_title_before_translation(self):
        class ProviderStub:
            name = 'subtitlecat'

            def __init__(self):
                self.search_titles = []

            def search(self, request):
                self.search_titles.append(request.title)
                if request.title != "Persona 3 the Movie #2 Midsummer Knight's Dream":
                    return []
                return [
                    OnlineSubtitleCandidate(
                        provider='subtitlecat',
                        candidate_id='cat-1',
                        file_id='cat-1',
                        file_name='persona.srt',
                        language='zh-Hant',
                        subtitle_type='normal',
                        format='srt',
                        media_type='movie',
                        tmdb_id=297189,
                        machine_translated=True,
                    )
                ]

            def download(self, candidate):
                raise AssertionError('dry-run should not download')

        provider = ProviderStub()
        agent = SubtitleAgent(provider_registry=Mock(providers=[provider], provider_statuses=None))

        media_link = {
            'source_path': "/tmp/Persona 3 the Movie #2 Midsummer Knight's Dream.mkv",
            'target_path': '/tmp/target.mkv',
            'filename': "Persona 3 the Movie #2 Midsummer Knight's Dream.mkv",
            'media_type': 'movie',
            'media_tmdb_id': 297189,
            'media_name': '女神异闻录3 剧场版 第二章 仲夏骑士之梦',
            'base_title': "女神异闻录3 剧场版 第二章 仲夏骑士之梦(劇場版「ペルソナ3」第2章 Midsummer Knight's Dream)",
            'alt_name': "劇場版「ペルソナ3」第2章 Midsummer Knight's Dream",
            'year': 2014,
        }

        result = agent._process_online_subtitle(media_link, test_mode=True)

        self.assertEqual('downloaded', result)
        self.assertIn("Persona 3 the Movie #2 Midsummer Knight's Dream", provider.search_titles)

    def test_online_candidate_score_rejects_explicit_episode_mismatch(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/tmp/Light Shop 1 - Strangers.mkv',
            'target_path': '/tmp/Light Shop.S01E01.mkv',
            'media_type': 'tv',
            'media_tmdb_id': 226529,
            'season': 1,
            'episode': 1,
        }
        candidate = OnlineSubtitleCandidate(
            provider='assrt',
            candidate_id='666590:8',
            file_id='666590:8',
            file_name='Light.Shop.S01E08.1080p.DSNP.WEB-DL.DDP5.1.Atmos.H.264-ARiC.srt',
            language='zh-CN',
            subtitle_type='normal',
            format='srt',
            media_type='tv',
            parent_tmdb_id=226529,
            season=1,
            episode=1,
        )

        score, reason = agent._online_candidate_score(media_link, candidate)

        self.assertEqual(0.0, score)
        self.assertEqual('explicit episode mismatch in file_name', reason)

    def test_online_candidate_score_rejects_parent_tmdb_mismatch_even_with_explicit_episode(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/tmp/Light Shop 1 - Strangers.mkv',
            'target_path': '/tmp/Light Shop.S01E01.mkv',
            'media_type': 'tv',
            'media_tmdb_id': 226529,
            'base_title': 'Light Shop',
            'season': 1,
            'episode': 1,
        }
        candidate = OnlineSubtitleCandidate(
            provider='opensubtitles',
            candidate_id='wrong-show',
            file_id='wrong-show',
            file_name='Light.Shop.S01E01.WEB-DL.srt',
            language='zh-CN',
            subtitle_type='normal',
            format='srt',
            media_type='tv',
            parent_tmdb_id=999999,
            season=1,
            episode=1,
            title='Light Shop S01E01',
            release='Light Shop S01E01',
        )

        score, reason = agent._online_candidate_score(media_link, candidate)

        self.assertEqual(0.0, score)
        self.assertEqual('parent TMDB mismatch', reason)

    def test_online_candidate_score_rejects_wrong_show_same_episode(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/tmp/Light Shop 6 - Three-Day Funeral.mkv',
            'target_path': '/tmp/Light Shop.S01E06.mkv',
            'filename': 'Light Shop 6 - Three-Day Funeral.mkv',
            'media_type': 'tv',
            'media_tmdb_id': 226529,
            'base_title': 'Light Shop',
            'season': 1,
            'episode': 6,
        }
        candidate = OnlineSubtitleCandidate(
            provider='subtitlecat',
            candidate_id='cat-niko',
            file_id='https://www.subtitlecat.com/subs/169/Niko.and.the.Sword.of.Light.S01.E06.WEBRip-en.srt',
            file_name='Niko.and.the.Sword.of.Light.S01.E06.WEBRip-en-zh-CN.srt',
            language='zh-CN',
            subtitle_type='normal',
            format='srt',
            media_type='tv',
            parent_tmdb_id=226529,
            season=1,
            episode=6,
            title='Niko and the Sword of Light S01E06',
            release='Niko and the Sword of Light S01E06',
            machine_translated=True,
        )

        score, reason = agent._online_candidate_score(media_link, candidate)

        self.assertEqual(0.0, score)
        self.assertEqual('title mismatch', reason)

    def test_online_download_rejects_wrong_archive_member_filename(self):
        class ProviderStub:
            name = 'assrt'

            def __init__(self, candidate):
                self.candidate = candidate
                self.search_calls = 0
                self.download_calls = 0

            def search(self, request):
                self.search_calls += 1
                return [self.candidate] if self.search_calls == 1 else []

            def download(self, candidate):
                self.download_calls += 1
                return DownloadedSubtitle(
                    b'1\n00:00:01,000 --> 00:00:02,000\nChinese\n',
                    'Light.Shop.S01E08.1080p.DSNP.WEB-DL.srt',
                )

        candidate = OnlineSubtitleCandidate(
            provider='assrt',
            candidate_id='666590',
            file_id='666590',
            file_name='Light.Shop.S01.1080p.DSNP.WEB-DL.zip',
            language='zh-CN',
            subtitle_type='normal',
            format='srt',
            media_type='tv',
            parent_tmdb_id=226529,
            season=1,
            episode=1,
        )
        provider = ProviderStub(candidate)
        agent = SubtitleAgent(provider_registry=Mock(providers=[provider], provider_statuses=None))

        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, 'Light.Shop.S01E01.mkv')
            media_link = {
                'source_path': target,
                'target_path': target,
                'media_type': 'tv',
                'media_tmdb_id': 226529,
                'base_title': 'Light Shop',
                'season': 1,
                'episode': 1,
            }
            with (
                patch('media_mcp.subtitle.services.dependencies.validate_online_subtitle') as validate,
                patch('media_mcp.subtitle.services.dependencies.SUBTITLE_SYNC_MODE', 'disabled'),
                patch('media_mcp.subtitle.services.dependencies.upsert_media_subtitle') as upsert,
            ):
                status = agent._process_online_subtitle(media_link)
            output = os.path.join(directory, 'Light.Shop.S01E01.srt')
            output_exists = os.path.exists(output)

        self.assertIsNone(status)
        self.assertEqual(1, provider.download_calls)
        validate.assert_not_called()
        upsert.assert_not_called()
        self.assertFalse(output_exists)

    def test_online_download_rejects_subtitle_timing_overrun(self):
        class ProviderStub:
            name = 'subdl'

            def __init__(self, candidate):
                self.candidate = candidate
                self.search_calls = 0

            def search(self, request):
                self.search_calls += 1
                return [self.candidate] if self.search_calls == 1 else []

            def download(self, candidate):
                return DownloadedSubtitle(b'unsynced subtitle', candidate.file_name)

        candidate = OnlineSubtitleCandidate(
            provider='subdl',
            candidate_id='subdl-1',
            file_id='subdl-1',
            file_name='movie.srt',
            language='zh-CN',
            subtitle_type='normal',
            format='srt',
            media_type='movie',
            tmdb_id=27205,
        )
        provider = ProviderStub(candidate)
        agent = SubtitleAgent(provider_registry=Mock(providers=[provider], provider_statuses=None))
        content = (
            '1\n00:00:01,000 --> 00:00:02,000\n中文字幕第一行\n\n'
            '2\n00:09:50,000 --> 00:10:00,000\n中文字幕第二行\n'
        ).encode('utf-8')
        validated = ValidatedOnlineSubtitle(
            content=content,
            extension='.srt',
            encoding='utf-8',
            profile={'chinese_chars': 20, 'dialogue_lines': 6},
        )

        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, 'movie.mkv')
            media_link = {
                'source_path': target,
                'target_path': target,
                'media_type': 'movie',
                'media_tmdb_id': 27205,
                'base_title': 'Movie',
            }
            with (
                patch('media_mcp.subtitle.services.dependencies.validate_online_subtitle', return_value=validated),
                patch('media_mcp.subtitle.services.dependencies.SUBTITLE_SYNC_MODE', 'disabled'),
                patch.object(agent, '_video_duration_seconds', return_value=120.0),
                patch('media_mcp.subtitle.services.dependencies.upsert_media_subtitle') as upsert,
            ):
                status = agent._process_online_subtitle(media_link)
            output = os.path.join(directory, 'movie.srt')
            output_exists = os.path.exists(output)

        self.assertIsNone(status)
        upsert.assert_not_called()
        self.assertFalse(output_exists)

    def test_online_download_syncs_subtitle_when_ffsubsync_available(self):
        class ProviderStub:
            name = 'subdl'

            def __init__(self, candidates):
                self.candidates = candidates

            def search(self, request):
                return self.candidates

            def download(self, candidate):
                return DownloadedSubtitle(b'unsynced subtitle', candidate.file_name)

        candidate = OnlineSubtitleCandidate(
            provider='subdl',
            candidate_id='subdl-1',
            file_id='sub-1',
            file_name='sub.srt',
            language='zh-CN',
            subtitle_type='normal',
            format='srt',
            media_type='movie',
            tmdb_id=27205,
            download_count=1,
        )
        provider = ProviderStub([candidate])
        agent = SubtitleAgent(provider_registry=Mock(providers=[provider], provider_statuses=None))

        def fake_sync(video_path, subtitle_path, output_path, **kwargs):
            with open(output_path, 'wb') as handle:
                handle.write(b'1\n00:00:02,000 --> 00:00:03,000\nSynced\n')
            return SubtitleSyncResult(True, output_path, 'ffsubsync')

        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, 'movie.mkv')
            with open(target, 'wb') as handle:
                handle.write(b'video')
            media_link = {
                'source_path': target,
                'target_path': target,
                'media_type': 'movie',
                'media_tmdb_id': 27205,
                'media_name': 'Inception',
            }
            validated = ValidatedOnlineSubtitle(
                content=b'1\n00:00:01,000 --> 00:00:02,000\nChinese\n',
                extension='.srt',
                encoding='utf-8',
                profile={'chinese_chars': 20, 'dialogue_lines': 6},
            )
            with (
                patch('media_mcp.subtitle.services.dependencies.validate_online_subtitle', return_value=validated) as validate,
                patch('media_mcp.subtitle.services.dependencies.sync_subtitle_to_audio', side_effect=fake_sync),
                patch('media_mcp.subtitle.services.dependencies.upsert_media_subtitle') as upsert,
            ):
                status = agent._process_online_subtitle(media_link)

            output = os.path.join(directory, 'movie.srt')
            with open(output, 'rb') as handle:
                synced_content = handle.read()

        self.assertEqual('downloaded', status)
        self.assertEqual('downloaded:online_synced', agent._last_action_detail)
        self.assertEqual(3, validate.call_count)
        self.assertIn(b'Synced', synced_content)
        reason = upsert.call_args.kwargs['reason']
        self.assertIn('subtitle_sync=ffsubsync', reason)

    def test_online_translation_source_is_synced_before_translation(self):
        class ProviderStub:
            name = 'subdl'

            def __init__(self, candidates):
                self.candidates = candidates

            def search(self, request):
                return self.candidates

            def download(self, candidate):
                return DownloadedSubtitle(b'unsynced source', candidate.file_name)

        candidate = OnlineSubtitleCandidate(
            provider='subdl',
            candidate_id='subdl-en-1',
            file_id='en-1',
            file_name='source.srt',
            language='en',
            subtitle_type='normal',
            format='srt',
            media_type='movie',
            tmdb_id=27205,
            download_count=1,
        )
        provider = ProviderStub([candidate])
        agent = SubtitleAgent(provider_registry=Mock(providers=[provider], provider_statuses=None))

        def fake_sync(video_path, subtitle_path, output_path, **kwargs):
            with open(output_path, 'wb') as handle:
                handle.write(b'1\n00:00:02,000 --> 00:00:03,000\nSynced English\n')
            return SubtitleSyncResult(True, output_path, 'ffsubsync')

        with tempfile.TemporaryDirectory() as directory:
            target = os.path.join(directory, 'movie.mkv')
            with open(target, 'wb') as handle:
                handle.write(b'video')
            media_link = {
                'source_path': target,
                'target_path': target,
                'media_type': 'movie',
                'media_tmdb_id': 27205,
                'media_name': 'Inception',
            }
            validated = ValidatedOnlineSubtitle(
                content=b'1\n00:00:01,000 --> 00:00:02,000\nEnglish\n',
                extension='.srt',
                encoding='utf-8',
                profile={'dialogue_lines': 6},
            )
            with (
                patch('media_mcp.subtitle.services.dependencies.validate_online_translation_source', return_value=validated) as validate,
                patch('media_mcp.subtitle.services.dependencies.sync_subtitle_to_audio', side_effect=fake_sync),
            ):
                source = agent._download_online_translation_source(
                    media_link,
                    os.path.join(directory, 'movie.ass'),
                    language_preferences=('en',),
                )

            with open(source['source_path'], 'rb') as handle:
                synced_content = handle.read()

        self.assertEqual('subtitle_sync=ffsubsync', source['source_sync_reason'])
        self.assertEqual(3, validate.call_count)
        self.assertIn(b'Synced English', synced_content)

    def test_audio_transcription_runs_after_other_subtitle_sources_fail(self):
        agent = SubtitleAgent(provider_registry=Mock(providers=[]))
        media_link = {
            'source_path': '/data/downloads/movie.mkv',
            'target_path': '/data/media_hub/movie.mkv',
            'media_type': 'movie',
        }

        with (
            patch.object(agent, '_cleanup_redundant_language_sidecars'),
            patch.object(agent, '_translated_target_path', return_value='/data/media_hub/movie.ass'),
            patch.object(agent, '_legacy_translated_target_path', return_value='/data/media_hub/movie.zh-CN-bilingual.ass'),
            patch.object(agent, '_process_embedded', return_value=None),
            patch.object(agent, '_select_sidecar', return_value=(None, None)),
            patch.object(agent, '_process_online_subtitle', return_value=None),
            patch.object(agent, '_process_text_translation', return_value=None),
            patch.object(agent, '_process_audio_transcription', return_value='audio_transcribed') as audio,
            patch('media_mcp.subtitle.services.dependencies.os.path.exists', return_value=False),
        ):
            action = agent._process_media_link(media_link, [])

        self.assertEqual('audio_transcribed', action)
        audio.assert_called_once_with(media_link, test_mode=False)


if __name__ == '__main__':
    unittest.main()
