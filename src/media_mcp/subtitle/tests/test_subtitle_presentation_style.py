#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

from media_mcp.subtitle.domain.online_subtitle import apply_srt_presentation_style
from media_mcp.subtitle.domain.translation import (
    SubtitleEvent,
    render_bilingual_ass,
    render_chinese_ass,
    strip_trailing_punctuation,
)


class StripTrailingPunctuationTest(unittest.TestCase):
    def test_strips_chinese_tail_punctuation(self):
        self.assertEqual(
            strip_trailing_punctuation('它覆盖了地球表面一半以上。'),
            '它覆盖了地球表面一半以上',
        )

    def test_strips_english_tail_punctuation(self):
        self.assertEqual(
            strip_trailing_punctuation('It covers over half the surface,'),
            'It covers over half the surface',
        )

    def test_keeps_question_exclamation_and_ellipsis(self):
        self.assertEqual(strip_trailing_punctuation('这是谁？'), '这是谁？')
        self.assertEqual(strip_trailing_punctuation('快跑！'), '快跑！')
        self.assertEqual(strip_trailing_punctuation('海洋里的动物……'), '海洋里的动物……')

    def test_strips_repeated_punctuation(self):
        self.assertEqual(strip_trailing_punctuation('结束了。】' .replace('】', '，')), '结束了')

    def test_preserves_an8_tag(self):
        self.assertEqual(
            strip_trailing_punctuation(r'{\an8}顶部字幕。'),
            r'{\an8}顶部字幕',
        )

    def test_lone_punctuation_line_untouched(self):
        self.assertEqual(strip_trailing_punctuation('……'), '……')

    def test_empty_lines_pass_through(self):
        self.assertEqual(strip_trailing_punctuation('第一行。\n\n第三行，'), '第一行\n\n第三行')


class ApplySrtPresentationStyleTest(unittest.TestCase):
    def test_rewrites_text_lines_only(self):
        srt = (
            '1\n00:00:01,000 --> 00:00:02,000\n'
            '海洋里的动物。\n\n'
            '2\n00:00:03,000 --> 00:00:04,000\n'
            '比任何地方都多。\n'
        ).encode('utf-8')
        result = apply_srt_presentation_style(srt).decode('utf-8')
        self.assertIn('00:00:01,000 --> 00:00:02,000', result)
        self.assertIn('海洋里的动物', result)
        self.assertNotIn('动物。', result)
        self.assertNotIn('都多。', result)

    def test_structure_survives(self):
        srt = (
            '1\n00:00:01,000 --> 00:00:02,000\n'
            '甲，乙。\n\n'
            '2\n00:00:03,000 --> 00:00:04,000\n'
            '丙；丁。\n'
        ).encode('utf-8')
        result = apply_srt_presentation_style(srt).decode('utf-8')
        self.assertEqual(result.count(' --> '), 2)
        self.assertTrue(result.startswith('1\n'))


class RenderAssStripTest(unittest.TestCase):
    @staticmethod
    def _events():
        return [
            SubtitleEvent(index=1, start_seconds=1.0, end_seconds=2.0, source_text='Line one,'),
        ]

    def test_bilingual_ass_strips_both_lines(self):
        content = render_bilingual_ass(
            self._events(),
            ['中文台词。'],
        )
        self.assertIn('中文台词', content)
        self.assertIn('Line one', content)
        self.assertNotIn('台词。', content.replace('中文台词', ''))
        self.assertNotIn('one,', content)

    def test_chinese_ass_strips_chinese_line(self):
        content = render_chinese_ass(self._events(), ['中文台词。'])
        self.assertIn(',,中文台词\n', content)
        self.assertNotIn('台词。', content)

    def test_strip_disabled_keeps_punctuation(self):
        content = render_bilingual_ass(
            self._events(),
            ['中文台词。'],
            strip_tail_punctuation=False,
        )
        self.assertIn('中文台词。', content)
        self.assertIn('Line one,', content)


if __name__ == '__main__':
    unittest.main()
