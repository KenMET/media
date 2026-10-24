import os
import unittest

from media_mcp.ingest.domain.file_utils import MAX_FILENAME_BYTES
from media_mcp.subtitle.domain.path_builder import build_sidecar_path, shorten_sidecar_path


class SubtitlePathBuilderTest(unittest.TestCase):
    def test_translation_source_sidecar_preserves_suffix_with_long_media_name(self):
        video_path = os.path.join(
            '/data/media_hub/series/齐木楠雄的灾难(斉木楠雄のΨ難)/第02季',
            '齐木楠雄的灾难(斉木楠雄のΨ難) - S02E21 - '
            '再来访！外公外婆流浪记 ／ 偿还人情！鸟束的绝食修行 ／ '
            '错开的男女交际（前篇） ／ 错开的男女交际（后篇） ／ '
            '刊登特别报道吧！ - 2016.mkv',
        )

        sidecar = shorten_sidecar_path(video_path, '.subtitle-translation-source-21.srt')

        self.assertLessEqual(len(os.path.basename(sidecar).encode('utf-8')), MAX_FILENAME_BYTES)
        self.assertTrue(sidecar.endswith('.subtitle-translation-source-21.srt'))
        self.assertIn('S02E21', os.path.basename(sidecar))
        self.assertIn('2016', os.path.basename(sidecar))

    def test_build_sidecar_path_limits_tagged_subtitle_name(self):
        video_path = os.path.join('/library', f'{"长标题" * 80} - S01E01 - 2024.mkv')

        sidecar = build_sidecar_path(video_path, '.ass', 'zh-CN-bilingual', 'normal', prefer_plain=False)

        self.assertLessEqual(len(os.path.basename(sidecar).encode('utf-8')), MAX_FILENAME_BYTES)
        self.assertTrue(sidecar.endswith('.zh-CN-bilingual.ass'))


if __name__ == '__main__':
    unittest.main()
