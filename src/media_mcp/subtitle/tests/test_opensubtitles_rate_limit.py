#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from media_mcp.subtitle.providers.base import ProviderTemporarilyUnavailable
from media_mcp.adapters.subtitle.opensubtitles import OpenSubtitlesProvider


class OpenSubtitlesRateLimitTest(unittest.TestCase):
    def test_429_opens_and_persists_circuit(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = os.path.join(directory, 'rate-limit.json')
            response = Mock(
                status_code=429,
                headers={'Retry-After': '120'},
            )
            response.json.return_value = {'message': 'Throttle limit reached'}

            with patch.dict(
                'os.environ',
                {
                    'OPENSUBTITLES_API_KEY': 'test-key',
                    'OPENSUBTITLES_RATE_LIMIT_STATE_FILE': state_file,
                },
                clear=False,
            ):
                provider = OpenSubtitlesProvider()
                with self.assertRaises(ProviderTemporarilyUnavailable) as raised:
                    provider._check_rate_limit(response, 'search')
                reloaded = OpenSubtitlesProvider()

            self.assertGreater(raised.exception.retry_at or 0, time.time() + 100)
            with open(state_file, 'r', encoding='utf-8') as handle:
                state = json.load(handle)
            self.assertIn('request throttled', state['reason'])
            with self.assertRaises(ProviderTemporarilyUnavailable):
                reloaded._ensure_available()

    def test_download_quota_uses_long_cooldown(self):
        response = Mock(status_code=406, headers={})
        response.json.return_value = {'message': 'Download limit reached'}
        provider = OpenSubtitlesProvider()
        provider.rate_limit_state_file = ''
        provider.default_quota_seconds = 86400

        with self.assertRaises(ProviderTemporarilyUnavailable) as raised:
            provider._check_rate_limit(response, 'download')

        self.assertGreater(raised.exception.retry_at or 0, time.time() + 86000)

    def test_successful_last_download_opens_circuit_for_later_requests(self):
        response = Mock(status_code=200, headers={})
        provider = OpenSubtitlesProvider()
        provider.rate_limit_state_file = ''
        provider.default_quota_seconds = 86400

        provider._record_exhausted_quota(
            response,
            {'remaining': 0, 'reset_time_utc': 'tomorrow'},
        )

        self.assertGreater(provider._blocked_until, time.time() + 86000)
        with self.assertRaises(ProviderTemporarilyUnavailable):
            provider._ensure_available()


if __name__ == '__main__':
    unittest.main()
