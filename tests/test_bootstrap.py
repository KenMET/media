import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from media_mcp.bootstrap import initialize_services
from media_mcp.adapters.jackett import Jackett


class BootstrapTests(unittest.TestCase):
    def test_managed_keys_are_created_once_and_not_required_in_env(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'jackett/Jackett/ServerConfig.json'
            with patch.dict(os.environ,{'JACKETT_CONFIG_FILE':str(config),'JACKETT_API_KEY':'',
                    'QBITTORRENT_CONFIG_DIR':str(root/'qb'),'MEDIA_DATA_ROOT':str(root/'data'),
                    'PUID':str(os.getuid()),'PGID':str(os.getgid())}):
                initialize_services()
                first=json.loads(config.read_text())['APIKey']
                initialize_services()
                self.assertEqual(json.loads(config.read_text())['APIKey'],first)
                self.assertTrue(Jackett().configured)
                qb=(root/'qb/qBittorrent/qBittorrent.conf').read_text()
                self.assertIn('WebUI\\LocalHostAuth=false',qb)
                self.assertIn('WebUI\\AuthSubnetWhitelistEnabled=true',qb)
                self.assertIn('WebUI\\Password_PBKDF2=',qb)
                self.assertEqual(config.stat().st_mode & 0o777,0o600)

    def test_new_nonroot_configs_have_matching_owners_and_existing_files_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'jackett/Jackett/ServerConfig.json'
            qb=root/'qb/qBittorrent/qBittorrent.conf'
            with patch.dict(os.environ, {'JACKETT_CONFIG_FILE':str(config),
                    'QBITTORRENT_CONFIG_DIR':str(root/'qb'),'MEDIA_DATA_ROOT':str(root/'data'),
                    'PUID':'2000','PGID':'2001'}), patch('media_mcp.bootstrap.os.chown') as chown:
                initialize_services()
                self.assertTrue(any(call.args==(qb,2000,2001) for call in chown.call_args_list))
                self.assertTrue(any(call.args==(config,2000,2001) for call in chown.call_args_list))
                saved=qb.read_bytes();chown.reset_mock()
                initialize_services()
                self.assertEqual(qb.read_bytes(),saved)
                self.assertFalse(any(call.args[0] in (qb,config) for call in chown.call_args_list))
