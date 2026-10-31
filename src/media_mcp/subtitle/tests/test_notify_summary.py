#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import unittest

from media_mcp.subtitle.domain.notify_summary import (
    failure_detail_key,
    subtitle_notify_parts,
    translation_detail_key,
)


class SubtitleNotifySummaryTest(unittest.TestCase):
    def test_detail_parts_split_translation_source_language_and_failure_stage(self):
        counts = {
            'embedded_default_set': 1,
            'downloaded:online_synced': 2,
            translation_detail_key('embedded_translation', 'en'): 1,
            translation_detail_key('embedded_translation', 'ja'): 1,
            translation_detail_key('sidecar_translation', 'en'): 1,
            translation_detail_key('provider_translation', 'ja'): 1,
            failure_detail_key('translation'): 1,
        }

        self.assertEqual(
            [
                'Embedded selected: 1',
                'Online downloaded and synced: 2',
                'Embedded EN translation: 1',
                'Embedded JP translation: 1',
                'Sidecar EN translation: 1',
                'Downloaded JP translation: 1',
                'Translation error: 1',
            ],
            subtitle_notify_parts(counts),
        )


if __name__ == '__main__':
    unittest.main()
