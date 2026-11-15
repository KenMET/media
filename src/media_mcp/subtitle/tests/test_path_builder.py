import os
import unittest

from media_mcp.ingest.domain.file_utils import MAX_FILENAME_BYTES
from media_mcp.subtitle.domain.path_builder import build_sidecar_path, shorten_sidecar_path


class SubtitlePathBuilderTest(unittest.TestCase):
    def test_translation_source_sidecar_preserves_suffix_with_long_media_name(self):
        video_path = os.path.join(
            '/data/media_hub/series/\u9f50\u6728\u6960\u96c4\u7684\u707e\u96be(\u6589\u6728\u6960\u96c4のΨ\u96e3)/\u7b2c02\u5b63',
            '\u9f50\u6728\u6960\u96c4\u7684\u707e\u96be(\u6589\u6728\u6960\u96c4のΨ\u96e3) - S02E21 - '
            '\u518d\u6765\u8bbf！\u5916\u516c\u5916\u5a46\u6d41\u6d6a\u8bb0 ／ \u507f\u8fd8\u4eba\u60c5！\u9e1f\u675f\u7684\u7edd\u98df\u4fee\u884c ／ '
            '\u9519\u5f00\u7684\u7537\u5973\u4ea4\u9645（\u524d\u7bc7） ／ \u9519\u5f00\u7684\u7537\u5973\u4ea4\u9645（\u540e\u7bc7） ／ '
            '\u520a\u767b\u7279\u522b\u62a5\u9053\u5427！ - 2016.mkv',
        )

        sidecar = shorten_sidecar_path(video_path, '.subtitle-translation-source-21.srt')

        self.assertLessEqual(len(os.path.basename(sidecar).encode('utf-8')), MAX_FILENAME_BYTES)
        self.assertTrue(sidecar.endswith('.subtitle-translation-source-21.srt'))
        self.assertIn('S02E21', os.path.basename(sidecar))
        self.assertIn('2016', os.path.basename(sidecar))

    def test_build_sidecar_path_limits_tagged_subtitle_name(self):
        video_path = os.path.join('/library', f'{"\u957f\u6807\u9898" * 80} - S01E01 - 2024.mkv')

        sidecar = build_sidecar_path(video_path, '.ass', 'zh-CN-bilingual', 'normal', prefer_plain=False)

        self.assertLessEqual(len(os.path.basename(sidecar).encode('utf-8')), MAX_FILENAME_BYTES)
        self.assertTrue(sidecar.endswith('.zh-CN-bilingual.ass'))

    def test_hidden_flag_dot_prefixes_translation_source(self):
        video_path = '/data/media_hub/movie/Joker (2019) - 2019.mkv'

        visible = shorten_sidecar_path(video_path, '.subtitle-translation-source.subdl.en.srt')
        hidden = shorten_sidecar_path(video_path, '.subtitle-translation-source.subdl.en.srt', hidden=True)

        self.assertFalse(os.path.basename(visible).startswith('.'))
        self.assertTrue(os.path.basename(hidden).startswith('.'))
        self.assertEqual('.' + os.path.basename(visible), os.path.basename(hidden))
        self.assertEqual(os.path.dirname(visible), os.path.dirname(hidden))

    def test_hidden_flag_survives_long_name_truncation(self):
        video_path = os.path.join('/library', f'{"\u957f\u6807\u9898" * 80} - S01E01 - 2024.mkv')

        hidden = shorten_sidecar_path(
            video_path, '.subtitle-translation-source.opensubtitles.en.srt', hidden=True
        )

        name = os.path.basename(hidden)
        self.assertTrue(name.startswith('.'))
        self.assertTrue(name.endswith('.subtitle-translation-source.opensubtitles.en.srt'))

    def test_hidden_flag_is_idempotent(self):
        video_path = '/library/Movie - 2020.mkv'

        hidden = shorten_sidecar_path(video_path, '.subtitle-translation-source.ocr.srt', hidden=True)

        again = shorten_sidecar_path(video_path, '.subtitle-translation-source.ocr.srt', hidden=True)
        self.assertEqual(hidden, again)
        self.assertEqual(1, os.path.basename(again).count('.subtitle-translation-source.ocr.srt'))


if __name__ == '__main__':
    unittest.main()
