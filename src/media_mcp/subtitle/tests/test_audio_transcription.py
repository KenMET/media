#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

from media_mcp.subtitle.domain.audio_transcription import (
    build_asr_sidecar_path,
    normalize_asr_language,
    render_srt,
)
from media_mcp.subtitle.domain.translation import SubtitleEvent


class AudioTranscriptionTest(unittest.TestCase):
    def test_render_srt(self):
        content = render_srt(
            [
                SubtitleEvent(1, 1.234, 3.456, ' Hello   world '),
                SubtitleEvent(2, 4.0, 5.0, '\u7b2c\u4e8c\u53e5'),
            ]
        )

        self.assertIn('00:00:01,234 --> 00:00:03,456', content)
        self.assertIn('Hello world', content)
        self.assertIn('\u7b2c\u4e8c\u53e5', content)

    def test_build_asr_sidecar_path(self):
        self.assertEqual(
            '/media/movie.asr.en.srt',
            build_asr_sidecar_path('/media/movie.mkv', 'en'),
        )
        self.assertEqual(
            '/media/movie.asr.zh-CN.srt',
            build_asr_sidecar_path('/media/movie.mkv', 'zh-CN'),
        )

    def test_normalize_asr_language(self):
        self.assertEqual('zh-CN', normalize_asr_language('zh'))
        self.assertEqual('en', normalize_asr_language('en'))
        self.assertIsNone(normalize_asr_language(None))


if __name__ == '__main__':
    unittest.main()
