import unittest

from media_mcp.subtitle.domain.translation import (
    SubtitleTranslationError, parse_text_subtitle_content,
)


class AssDialogueTests(unittest.TestCase):
    def parse(self, *lines):
        content = '[Events]\n' + '\n'.join(
            f'Dialogue: 0,0:00:{i:02}.00,0:00:{i:02}.90,Default,,0,0,0,,{text}'
            for i, text in enumerate(lines)
        )
        return parse_text_subtitle_content(content, '.ass')

    def test_drawings_excluded_and_event_numbers_contiguous(self):
        events = self.parse(r'{\p1}m 0 0 l 100 100', 'Hello', r'{\p4}m 1 2', '123')
        self.assertEqual([(e.index, e.source_text) for e in events], [(1, 'Hello'), (2, '123')])

    def test_inline_drawing_and_explicit_reset(self):
        self.assertEqual(self.parse(r'Before {\p1}m 0 0 l 1 1{\p0}after')[0].source_text, 'Before after')
        self.assertEqual(self.parse(r'{\p1}m 0 0{\rDefault}Hello')[0].source_text, 'Hello')

    def test_position_and_baseline_are_not_drawing_switches(self):
        self.assertEqual(self.parse(r'{\pos(1,2)\pbo10}Hello')[0].source_text, 'Hello')

    def test_drawing_only_is_not_translation_source(self):
        with self.assertRaisesRegex(SubtitleTranslationError, 'no parseable dialogue'):
            self.parse(r'{\p1}m 0 0 l 1 1{\p0}')


if __name__ == '__main__':
    unittest.main()
