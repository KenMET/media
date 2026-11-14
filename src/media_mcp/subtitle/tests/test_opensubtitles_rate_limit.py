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


def _quota_response(headers=None, payload=None, status=406):
    response = Mock(status_code=status, headers=headers or {})
    if payload is None:
        response.json.side_effect = ValueError('no body')
    else:
        response.json.return_value = payload
    return response


class OpenSubtitlesQuotaResetSignalTest(unittest.TestCase):
    """Adversarial cases: untrusted rate-limit headers must not shorten cooldowns."""

    def setUp(self):
        self.provider = OpenSubtitlesProvider()
        self.provider.rate_limit_state_file = ''

    def test_malicious_reset_header_cannot_override_body_reset_time(self):
        # Observed incident: 'RateLimit-Reset: 1' produced a +1s retry_at and
        # a retry storm. The body reset_time_utc is authoritative.
        response = _quota_response(
            headers={'RateLimit-Reset': '1'},
            payload={
                'reset_time_utc': '2026-11-14 23:59:59 UTC',
                'message': 'Your quota will be renewed (2026-11-14 23:59:59 UTC)',
            },
        )
        blocked = self.provider._determine_blocked_until(
            response,
            response.json.return_value,
            response.json.return_value['message'],
            quota_exhausted=True,
            default_seconds=86400,
        )
        self.assertAlmostEqual(
            blocked,
            time.mktime(time.strptime('2026-11-14 23:59:59', '%Y-%m-%d %H:%M:%S')) - time.timezone,
            delta=5,
        )

    def test_malicious_reset_header_falls_back_to_message_timestamp(self):
        response = _quota_response(
            headers={'RateLimit-Reset': '1'},
            payload={},
        )
        blocked = self.provider._determine_blocked_until(
            response,
            {},
            'renewed in 15 hours (2026-11-14 23:59:59 UTC)',
            quota_exhausted=True,
            default_seconds=86400,
        )
        expected = time.mktime(time.strptime('2026-11-14 23:59:59', '%Y-%m-%d %H:%M:%S')) - time.timezone
        self.assertAlmostEqual(blocked, expected, delta=5)

    def test_unparseable_signals_fall_back_to_default_cooldown(self):
        response = _quota_response(headers={'RateLimit-Reset': 'garbage'}, payload=None)
        before = time.time()
        blocked = self.provider._determine_blocked_until(
            response, None, '', quota_exhausted=True, default_seconds=86400,
        )
        self.assertGreaterEqual(blocked, before + 86400 - 5)

    def test_near_term_reset_claim_rejected_for_quota(self):
        # A daily quota cannot recover in minutes; such claims are misparsed.
        response = _quota_response(
            headers={'Retry-After': '60'},
            payload={'reset_time_utc': '2020-01-01 00:00:00 UTC'},
        )
        before = time.time()
        blocked = self.provider._determine_blocked_until(
            response, {'reset_time_utc': '2020-01-01 00:00:00 UTC'}, 'no timestamp',
            quota_exhausted=True, default_seconds=86400,
        )
        self.assertGreaterEqual(blocked, before + 86400 - 5)

    def test_throttle_retry_after_stays_short(self):
        # Transient throttling must not be inflated to quota-scale cooldowns.
        response = _quota_response(headers={'Retry-After': '30'}, payload={}, status=429)
        before = time.time()
        blocked = self.provider._determine_blocked_until(
            response, {}, '', quota_exhausted=False, default_seconds=900,
        )
        self.assertAlmostEqual(blocked, before + 30, delta=3)

    def test_absolute_epoch_header_accepted_within_horizon(self):
        response = _quota_response(
            headers={'X-RateLimit-Reset': str(time.time() + 7200)}, payload={}, status=429,
        )
        before = time.time()
        blocked = self.provider._determine_blocked_until(
            response, {}, '', quota_exhausted=False, default_seconds=900,
        )
        self.assertAlmostEqual(blocked, before + 7200, delta=5)

    def test_far_future_signals_capped_at_horizon(self):
        response = _quota_response(
            headers={'RateLimit-Reset': str(time.time() + 999 * 86400)},
            payload={'reset_time_utc': '2099-01-01 00:00:00 UTC'},
        )
        before = time.time()
        blocked = self.provider._determine_blocked_until(
            response,
            {'reset_time_utc': '2099-01-01 00:00:00 UTC'},
            '',
            quota_exhausted=True,
            default_seconds=86400,
        )
        self.assertLessEqual(blocked, before + 48 * 3600 + 5)

    def test_end_to_end_check_rate_limit_uses_body_reset_time(self):
        response = _quota_response(
            headers={'RateLimit-Reset': '1'},
            payload={'reset_time_utc': '2026-11-14 23:59:59 UTC'},
        )
        with patch.dict(
            'os.environ',
            {'OPENSUBTITLES_RATE_LIMIT_STATE_FILE': ''},
            clear=False,
        ):
            provider = OpenSubtitlesProvider()
            provider.rate_limit_state_file = ''
            with self.assertRaises(ProviderTemporarilyUnavailable) as raised:
                provider._check_rate_limit(response, 'download')
        expected = time.mktime(time.strptime('2026-11-14 23:59:59', '%Y-%m-%d %H:%M:%S')) - time.timezone
        self.assertAlmostEqual(raised.exception.retry_at or 0, expected, delta=5)


if __name__ == '__main__':
    unittest.main()
