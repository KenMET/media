#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from media_mcp.ingest.domain.file_utils import create_hardlink_with_target, get_main_media


class FileUtilsTest(unittest.TestCase):
    def test_create_hardlink_reports_shortened_target_path(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = os.path.join(directory, 'source.mkv')
            with open(source_path, 'wb') as handle:
                handle.write(b'media')

            long_filename = f'{"a" * 260} - 2024.mkv'
            requested_target = os.path.join(directory, 'links', long_filename)

            ok, reason, actual_target = create_hardlink_with_target(source_path, requested_target)

            self.assertTrue(ok, reason)
            self.assertIsNotNone(actual_target)
            self.assertNotEqual(requested_target, actual_target)
            self.assertTrue(os.path.isfile(actual_target))
            self.assertIn('Shortened filename:', reason)

class HardlinkCollisionTest(unittest.TestCase):
    def test_unreadable_directory_is_not_acknowledged_as_an_empty_scan(self):
        def inaccessible(*args,**kwargs):
            kwargs['onerror'](PermissionError('unreadable download directory'))
            return iter(())
        with tempfile.TemporaryDirectory() as directory,patch('media_mcp.ingest.domain.file_utils.os.walk',side_effect=inaccessible):
            with self.assertRaises(PermissionError):get_main_media(directory)

    def test_short_episode_is_not_dropped_next_to_large_video(self):
        with tempfile.TemporaryDirectory() as directory:
            large=os.path.join(directory,'feature.mkv');small=os.path.join(directory,'show.S01E01.ts')
            for path,size in ((large,100*1024*1024),(small,1024*1024)):
                with open(path,'wb') as handle:handle.truncate(size)
            self.assertEqual({item['path'] for item in get_main_media(directory)}, {large,small})

    def test_equal_size_different_inode_is_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = (os.path.join(directory,name) for name in ('source.mkv','target.mkv'))
            with open(source,'wb') as handle: handle.write(b'AAAA')
            with open(target,'wb') as handle: handle.write(b'BBBB')
            ok, reason, _ = create_hardlink_with_target(source,target)
            self.assertFalse(ok)
            self.assertIn('conflict',reason.lower())
            with open(target,'rb') as handle:self.assertEqual(handle.read(),b'BBBB')

    def test_same_inode_is_success(self):
        with tempfile.TemporaryDirectory() as directory:
            source,target = (os.path.join(directory,name) for name in ('source.mkv','target.mkv'))
            with open(source,'wb') as handle:handle.write(b'data')
            os.link(source,target)
            self.assertEqual(create_hardlink_with_target(source,target)[:2],(True,'Skip hardlink'))


if __name__ == '__main__':
    unittest.main()
