#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import unittest

from media_mcp.subtitle.providers.base import ProviderTemporarilyUnavailable
from media_mcp.subtitle.providers.cloud_mcp import _provider_unavailable_from_error


class CloudMCPProviderTest(unittest.TestCase):
    def test_http_500_is_treated_as_temporary_provider_failure(self):
        error = RuntimeError(
            "MCP tool 'subtitle.search' failed: HTTPError: 500 Server Error: "
            'Internal Server Error for url: https://www.subtitlecat.com/index.php?search=movie'
        )

        unavailable = _provider_unavailable_from_error('subtitlecat', error)

        self.assertIsInstance(unavailable, ProviderTemporarilyUnavailable)
        self.assertEqual('subtitlecat', unavailable.provider)
        self.assertIn('transient provider error', unavailable.reason)
        self.assertGreater(unavailable.retry_at or 0, time.time())

    def test_validation_errors_are_not_treated_as_temporary_provider_failure(self):
        error = RuntimeError('subtitle archive contained no usable subtitle')

        unavailable = _provider_unavailable_from_error('subtitlecat', error)

        self.assertIsNone(unavailable)


if __name__ == '__main__':
    unittest.main()
