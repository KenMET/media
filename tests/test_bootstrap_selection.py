import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from media_mcp.bootstrap import initialize_services


class BootstrapSelectionTests(unittest.TestCase):
    def test_selected_bootstrap_does_not_touch_other_service_or_its_owners(self):
        for service in ('qbittorrent', 'jackett'):
            with self.subTest(service=service), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                qb = root/'qb/qBittorrent/qBittorrent.conf'
                jackett = root/'jackett/Jackett/ServerConfig.json'
                external = jackett if service == 'qbittorrent' else qb
                external.parent.mkdir(parents=True)
                external.write_text('preserve-existing-config')
                with patch.dict(os.environ, {
                    'QBITTORRENT_CONFIG_DIR': str(root/'qb'),
                    'JACKETT_CONFIG_FILE': str(jackett),
                    'MEDIA_DATA_ROOT': str(root/'data'),
                    'PUID': '2000', 'PGID': '2001',
                }), patch('media_mcp.bootstrap.os.chown') as chown:
                    initialize_services(service)
                    self.assertEqual(external.read_text(), 'preserve-existing-config')
                    external_root = root/('jackett' if service == 'qbittorrent' else 'qb')
                    self.assertFalse(any(call.args[0].is_relative_to(external_root)
                                         for call in chown.call_args_list))
                    selected = qb if service == 'qbittorrent' else jackett
                    self.assertTrue(selected.is_file())
                    self.assertEqual((root/'data').exists(), service == 'qbittorrent')
