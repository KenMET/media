#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from media_mcp.subtitle.domain.embedded_subtitle import (
    EmbeddedSubtitleStream,
    set_mkv_default_subtitle,
)
from media_mcp.subtitle.domain.subtitle_ocr import ocr_embedded_pgs_to_srt


class EmbeddedSubtitleTest(unittest.TestCase):
    def test_mkvpropedit_uses_uid_selector(self):
        selected = EmbeddedSubtitleStream(
            stream_index=38,
            subtitle_ordinal=2,
            codec='subrip',
            language='zh-CN',
            raw_language='chi',
            title='Simplified',
            subtitle_type='normal',
            disposition_default=False,
            disposition_forced=False,
        )
        verified = [
            EmbeddedSubtitleStream(
                stream_index=38,
                subtitle_ordinal=2,
                codec='subrip',
                language='zh-CN',
                raw_language='chi',
                title='Simplified',
                subtitle_type='normal',
                disposition_default=True,
                disposition_forced=False,
            )
        ]

        with (
            patch('media_mcp.subtitle.domain.embedded_subtitle.os.stat', return_value=SimpleNamespace(st_nlink=1)),
            patch('media_mcp.subtitle.domain.embedded_subtitle.os.path.islink', return_value=False),
            patch('media_mcp.subtitle.domain.embedded_subtitle.shutil.which', return_value='/usr/bin/tool'),
            patch(
                'media_mcp.subtitle.domain.embedded_subtitle.ffprobe_subtitle_streams',
                side_effect=[[selected], verified],
            ),
            patch(
                'media_mcp.subtitle.domain.embedded_subtitle._mkv_track_uids',
                return_value=([111, 222], 222, 'track_mapped_by_ordinal'),
            ),
            patch(
                'media_mcp.subtitle.domain.embedded_subtitle.subprocess.run',
                return_value=subprocess.CompletedProcess([], 0, '', ''),
            ) as run,
        ):
            success, reason = set_mkv_default_subtitle('/media/movie.mkv', selected)

        self.assertTrue(success)
        self.assertEqual('embedded_default_set', reason)
        args = run.call_args.args[0]
        self.assertIn('track:=111', args)
        self.assertIn('track:=222', args)
        self.assertNotIn('track:@111', args)

    def test_pgs_ocr_reports_missing_tool(self):
        stream = EmbeddedSubtitleStream(
            stream_index=5,
            subtitle_ordinal=1,
            codec='hdmv_pgs_subtitle',
            language='en',
            raw_language='eng',
            title='English PGS',
            subtitle_type='normal',
            disposition_default=False,
            disposition_forced=False,
        )

        with (
            patch('media_mcp.subtitle.domain.subtitle_ocr.os.path.isfile', return_value=True),
            patch('media_mcp.subtitle.domain.subtitle_ocr.shutil.which', return_value=None),
        ):
            ok, reason = ocr_embedded_pgs_to_srt('/media/movie.mkv', stream, '/tmp/movie.ocr.srt')

        self.assertFalse(ok)
        self.assertEqual('pgstosrt_missing', reason)


if __name__ == '__main__':
    unittest.main()
