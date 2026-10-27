"""Port-only split deployment must never select an external host implicitly."""
import os
import unittest
from unittest.mock import patch

from media_mcp.platform.transport import control_url


class SplitPortTests(unittest.TestCase):
    def test_port_selects_loopback_and_overrides_legacy_url(self):
        with patch.dict(os.environ, {'MEDIA_CONTROL_PORT':'28213',
                                    'MEDIA_CONTROL_URL':'https://legacy.example'}):
            self.assertEqual(control_url(), 'http://127.0.0.1:28213')

    def test_missing_port_preserves_legacy_configuration(self):
        with patch.dict(os.environ, {'MEDIA_CONTROL_PORT':'',
                                    'MEDIA_CONTROL_URL':'https://legacy.example'}):
            self.assertEqual(control_url(), 'https://legacy.example')

    def test_invalid_ports_fail_instead_of_using_legacy_url(self):
        for value in ('0','65536','-1','127.0.0.1:28213','https://host','２８２１３',' 28213'):
            with self.subTest(value=value), patch.dict(os.environ, {'MEDIA_CONTROL_PORT':value}):
                with self.assertRaisesRegex(ValueError,'invalid_media_control_port'):
                    control_url()
