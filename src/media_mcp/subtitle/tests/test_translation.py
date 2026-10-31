#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import io
import tempfile
import unittest
import zipfile

from media_mcp.subtitle.domain.online_subtitle import validate_online_subtitle
from media_mcp.subtitle.domain.subtitle_file import detect_language, detect_subtitle_type, parse_subtitle_candidate
from media_mcp.subtitle.domain.translation import (
    SubtitleEvent,
    SubtitleTranslationError,
    parse_text_subtitle,
    render_bilingual_ass,
    restyle_bilingual_ass,
    translate_events,
    validate_translation_events,
)


class SubtitleTranslationTest(unittest.TestCase):
    def _temporary_subtitle(self, suffix: str, content: str) -> str:
        handle = tempfile.NamedTemporaryFile(
            mode='w',
            suffix=suffix,
            encoding='utf-8',
            delete=False,
        )
        self.addCleanup(lambda: os.path.exists(handle.name) and os.remove(handle.name))
        with handle:
            handle.write(content)
        return handle.name

    def test_parse_srt_and_render_bilingual_ass(self):
        path = self._temporary_subtitle(
            '.srt',
            '1\n00:00:01,000 --> 00:00:03,500\nHello, John.\n\n'
            '2\n00:00:04,000 --> 00:00:06,000\nWhere are you?\n',
        )

        events = parse_text_subtitle(path)
        rendered = render_bilingual_ass(
            events,
            ['\u4f60\u597d，\u7ea6\u7ff0。', '\u4f60\u5728\u54ea\u91cc？'],
            chinese_font_size=54,
            source_font_size=40,
        )

        self.assertEqual(2, len(events))
        self.assertIn('Style: Chinese,Arial,54', rendered)
        self.assertIn('Style: Source,Arial,40', rendered)
        self.assertIn('Dialogue: 0,0:00:01.00,0:00:03.50,Chinese', rendered)
        self.assertIn('\u4f60\u597d，\u7ea6\u7ff0。', rendered)
        self.assertIn(r'\N{\rSource}Hello, John.', rendered)
        self.assertIn('Hello, John.', rendered)

    def test_parse_ass_dialogue(self):
        path = self._temporary_subtitle(
            '.ass',
            '[Events]\n'
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
            r'Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\i1}Hello\Nworld'
            '\n',
        )

        events = parse_text_subtitle(path)

        self.assertEqual(1, len(events))
        self.assertEqual('Hello\nworld', events[0].source_text)

    def test_parse_ass_filters_effects_and_overlapping_duplicates(self):
        path = self._temporary_subtitle(
            '.ass',
            '[Events]\n'
            'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
            'Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello\n'
            'Dialogue: 1,0:00:01.10,0:00:03.00,Default,,0,0,0,,Hello\n'
            'Dialogue: 0,0:00:04.00,0:00:06.00,Signs,,0,0,0,,Street sign\n'
            'Dialogue: 0,0:00:07.00,0:00:09.00,OP Romaji,,0,0,0,,Song lyric\n',
        )

        events = parse_text_subtitle(path)

        self.assertEqual(1, len(events))
        self.assertEqual('Hello', events[0].source_text)

    def test_translation_batches_keep_previous_context(self):
        path = self._temporary_subtitle(
            '.srt',
            '1\n00:00:01,000 --> 00:00:02,000\nHello.\n\n'
            '2\n00:00:03,000 --> 00:00:04,000\nJohn!\n',
        )
        events = parse_text_subtitle(path)
        payloads = []

        def fake_translate(payload):
            payloads.append(payload)
            return {
                'success': True,
                'translations': [
                    {'id': item['id'], 'zh': f'\u8bd1\u6587{item["id"]}'}
                    for item in payload['batch']['entries']
                ],
            }

        translations = translate_events(
            events,
            fake_translate,
            {'title': 'Example'},
            'en',
            max_events=1,
            max_characters=100,
        )

        self.assertEqual(['\u8bd1\u65871', '\u8bd1\u65872'], translations)
        self.assertEqual([], payloads[0]['previous_context'])
        self.assertEqual(
            [{'source': 'Hello.', 'zh': '\u8bd1\u65871'}],
            payloads[1]['previous_context'],
        )

    def test_translation_batches_can_use_token_budget(self):
        events = [
            SubtitleEvent(
                index=index,
                start_seconds=float(index),
                end_seconds=float(index) + 1.0,
                source_text='A' * 100,
            )
            for index in range(1, 5)
        ]
        payloads = []

        def fake_translate(payload):
            payloads.append(payload)
            return {
                'success': True,
                'translations': [
                    {'id': item['id'], 'zh': f'\u8bd1\u6587{item["id"]}'}
                    for item in payload['batch']['entries']
                ],
            }

        translate_events(
            events,
            fake_translate,
            {'title': 'Example'},
            'en',
            max_events=10,
            max_characters=10000,
            max_tokens=80,
        )

        self.assertEqual([2, 2], [len(payload['batch']['entries']) for payload in payloads])

    def test_translation_retries_missing_ids(self):
        path = self._temporary_subtitle(
            '.srt',
            '1\n00:00:01,000 --> 00:00:02,000\nHello.\n',
        )
        events = parse_text_subtitle(path)

        calls = []

        def fake_translate(payload):
            calls.append(payload)
            if len(calls) == 1:
                return {'success': True, 'translations': []}
            return {'success': True, 'translations': [{'id': 1, 'zh': '\u4f60\u597d'}]}

        translations = translate_events(
            events,
            fake_translate,
            {'title': 'Example'},
            'en',
        )

        self.assertEqual(['\u4f60\u597d'], translations)
        self.assertEqual([1], [item['id'] for item in calls[1]['batch']['entries']])

    def test_missing_id_retry_bounds_context_and_cannot_overwrite_accepted_lines(self):
        events=[SubtitleEvent(index=i,start_seconds=float(i),end_seconds=i+0.8,
                              source_text='Line '+str(i)) for i in range(1,31)]
        calls=[]
        def translator(payload):
            calls.append(payload)
            if len(calls)==1:
                return {'success':True,'translations':[{'id':i,'zh':'\u5df2\u8bd1'+str(i)} for i in range(3,31)]}
            return {'success':True,'translations':[{'id':3,'zh':'\u9519\u8bef\u8986\u76d6'},
                {'id':1,'zh':'\u7b2c\u4e00\u53e5'},{'id':2,'zh':'\u7b2c\u4e8c\u53e5'}]}
        translated=translate_events(events,translator,{'title':'fixture'},'en')
        self.assertEqual(2,len(calls))
        self.assertEqual([1,2],[entry['id'] for entry in calls[1]['batch']['entries']])
        self.assertLessEqual(len(calls[1]['recovered_context']),5)
        self.assertEqual(['\u7b2c\u4e00\u53e5','\u7b2c\u4e8c\u53e5','\u5df2\u8bd13'],translated[:3])
        self.assertEqual(30,len(translated))

    def test_translation_rejects_ids_missing_after_retries(self):
        events = [
            SubtitleEvent(
                index=1,
                start_seconds=1.0,
                end_seconds=2.0,
                source_text='Hello.',
            )
        ]

        with self.assertRaisesRegex(SubtitleTranslationError, 'after 2 retries'):
            translate_events(
                events,
                lambda payload: {'success': True, 'translations': []},
                {'title': 'Example'},
                'en',
            )

    def test_foreign_language_detection(self):
        self.assertEqual('en', detect_language('movie.en.srt', ['Hello there.'] * 5))
        self.assertEqual('ja', detect_language('movie.srt', ['こんにちは']))
        self.assertEqual('ko', detect_language('movie.srt', ['안녕하세요']))

    def test_signs_and_songs_subtitle_type_is_partial(self):
        self.assertEqual('forced', detect_subtitle_type('English Signs/Songs', 'en'))

    def test_restyle_generated_bilingual_ass(self):
        path = self._temporary_subtitle(
            '.ass',
            'Title: AI translated bilingual subtitle\n'
            'Style: Chinese,Arial,54,old\n'
            'Style: Source,Arial,40,old\n',
        )

        changed = restyle_bilingual_ass(
            path,
            chinese_font_size=68,
            source_font_size=46,
            bottom_margin=18,
        )

        self.assertTrue(changed)
        with open(path, 'r', encoding='utf-8') as handle:
            content = handle.read()
        self.assertIn('Style: Chinese,Arial,68', content)
        self.assertIn('Style: Source,Arial,46', content)
        self.assertIn(',70,70,18,1', content)

    def test_generated_bilingual_ass_is_marked_as_agent_output(self):
        path = self._temporary_subtitle(
            '.ass',
            '[Script Info]\n'
            'Title: AI translated bilingual subtitle\n'
            'ScriptType: v4.00+\n',
        )

        candidate = parse_subtitle_candidate(path)

        self.assertTrue(candidate.generated_by_agent)

    def test_translation_rejects_implausible_event_count(self):
        events = [
            SubtitleEvent(
                index=index,
                start_seconds=float(index),
                end_seconds=float(index) + 0.5,
                source_text='dialogue',
            )
            for index in range(1, 151)
        ]

        with self.assertRaisesRegex(SubtitleTranslationError, 'implausible event count'):
            validate_translation_events(events, max_events=50)

    def test_translation_allows_long_movie_above_count_warning(self):
        events = [
            SubtitleEvent(
                index=index,
                start_seconds=(index - 1) * (5528.52 / 7428),
                end_seconds=(index - 1) * (5528.52 / 7428) + 0.5,
                source_text=f'dialogue {index}',
            )
            for index in range(1, 7429)
        ]

        profile = validate_translation_events(events)

        self.assertEqual(7428, profile['events'])
        self.assertGreater(profile['events_per_minute'], 65.0)
        self.assertLess(profile['events_per_minute'], 120.0)
        self.assertGreater(profile['avg_chars_per_event'], 0)
        self.assertIn('short_event_ratio', profile)
        self.assertTrue(profile['count_warning'])
        self.assertTrue(profile['density_warning'])

    def test_translation_allows_dense_anime_ass_source_with_warning(self):
        events = [
            SubtitleEvent(
                index=index,
                start_seconds=(index - 1) * (1459.9 / 1308),
                end_seconds=(index - 1) * (1459.9 / 1308) + 0.8,
                source_text=f'dialogue {index}',
            )
            for index in range(1, 1309)
        ]

        profile = validate_translation_events(events)

        self.assertGreater(profile['events_per_minute'], 45.0)
        self.assertFalse(profile['count_warning'])
        self.assertFalse(profile['density_warning'])

    def test_translation_allows_over_warning_density_until_hard_limit(self):
        events = [
            SubtitleEvent(
                index=index,
                start_seconds=(index - 1) * 0.87,
                end_seconds=(index - 1) * 0.87 + 0.5,
                source_text=f'dialogue {index}',
            )
            for index in range(1, 101)
        ]

        profile = validate_translation_events(events)

        self.assertGreater(profile['events_per_minute'], 65.0)
        self.assertLess(profile['events_per_minute'], 120.0)
        self.assertTrue(profile['density_warning'])

    def test_translation_rejects_implausible_event_density(self):
        events = [
            SubtitleEvent(
                index=index,
                start_seconds=(index - 1) * 0.3,
                end_seconds=(index - 1) * 0.3 + 0.2,
                source_text=f'dialogue {index}',
            )
            for index in range(1, 151)
        ]

        with self.assertRaisesRegex(SubtitleTranslationError, 'implausible event density'):
            validate_translation_events(events)

    def test_online_archive_prefers_chinese_subtitle_member(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr(
                'movie.en.srt',
                '1\n00:00:01,000 --> 00:00:02,000\n' + ('English dialogue ' * 100),
            )
            archive.writestr(
                'movie.zh-TW.srt',
                '1\n00:00:01,000 --> 00:00:02,000\n\u9019\u662f\u4e00\u6bb5\u7e41\u9ad4\u4e2d\u6587\u5b57\u5e55\u5167\u5bb9。\n\n'
                '2\n00:00:03,000 --> 00:00:04,000\n\u89d2\u8272\u6b63\u5728\u9032\u884c\u5c0d\u8a71。\n\n'
                '3\n00:00:05,000 --> 00:00:06,000\n\u5b57\u5e55\u61c9\u8a72\u88ab\u6b63\u78ba\u9078\u4e2d。\n\n'
                '4\n00:00:07,000 --> 00:00:08,000\n\u9019\u4e0d\u662f\u82f1\u6587\u5b57\u5e55。\n\n'
                '5\n00:00:09,000 --> 00:00:10,000\n\u6700\u5f8c\u4e00\u884c\u4e2d\u6587\u5b57\u5e55。\n',
            )

        validated = validate_online_subtitle(buffer.getvalue(), 'subtitle.zip')

        self.assertEqual('.srt', validated.extension)
        self.assertIn('\u7e41\u9ad4\u4e2d\u6587\u5b57\u5e55', validated.content.decode('utf-8'))

    def test_online_subtitle_accepts_utf16_chinese(self):
        text = (
            '1\n00:00:01,000 --> 00:00:02,000\n\u9019\u662f\u7b2c\u4e00\u884c\u4e2d\u6587\u5b57\u5e55。\n\n'
            '2\n00:00:03,000 --> 00:00:04,000\n\u9019\u662f\u7b2c\u4e8c\u884c\u4e2d\u6587\u5b57\u5e55。\n\n'
            '3\n00:00:05,000 --> 00:00:06,000\n\u9019\u662f\u7b2c\u4e09\u884c\u4e2d\u6587\u5b57\u5e55。\n\n'
            '4\n00:00:07,000 --> 00:00:08,000\n\u9019\u662f\u7b2c\u56db\u884c\u4e2d\u6587\u5b57\u5e55。\n\n'
            '5\n00:00:09,000 --> 00:00:10,000\n\u9019\u662f\u7b2c\u4e94\u884c\u4e2d\u6587\u5b57\u5e55。\n'
        )

        validated = validate_online_subtitle(text.encode('utf-16'), 'movie.srt')

        self.assertEqual('utf-16', validated.encoding)
        self.assertIn('\u4e2d\u6587\u5b57\u5e55', validated.content.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
