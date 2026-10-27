import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from starlette.datastructures import Headers

from media_mcp.platform.network import browser_peer, validate_public_origin


class PublicNetworkTests(unittest.TestCase):
    def test_explicit_multi_user_mcp_rejects_unscoped_auth_before_starting(self):
        from media_mcp.server import main
        with patch.dict(os.environ,{'MEDIA_MULTI_USER':'true','MEDIA_CONTROL_URL':'','MEDIA_AUTH_MODE':'none'}):
            with self.assertRaisesRegex(ValueError,'multi_user_requires_platform_auth'):
                main()

    def request(self, peer, values):
        return SimpleNamespace(client=SimpleNamespace(host=peer),headers=Headers(raw=values))

    def test_public_requires_https_exact_origin(self):
        for value in ('','http://media.test','https://attacker.test','https://u:p@media.test',
                      'https://media.test/path','https://media.test?query=1'):
            with self.subTest(value=value),patch.dict(os.environ,{'MEDIA_WEB_PUBLIC_URL':value}):
                with self.assertRaisesRegex(ValueError,'public_web_requires_https_origin'):
                    validate_public_origin(['media.test'])
        with patch.dict(os.environ,{'MEDIA_WEB_PUBLIC_URL':'https://media.test:443/'}):
            validate_public_origin(['media.test'])

    def test_only_exact_trusted_proxy_can_assert_one_address(self):
        headers=[(b'x-real-ip',b'203.0.113.1'),(b'x-forwarded-for',b'198.51.100.1')]
        with patch.dict(os.environ,{'MEDIA_WEB_TRUSTED_PROXIES':''}):
            self.assertEqual(browser_peer(self.request('127.0.0.1',headers)),'127.0.0.1')
        with patch.dict(os.environ,{'MEDIA_WEB_TRUSTED_PROXIES':'127.0.0.1/32'}):
            self.assertEqual(browser_peer(self.request('127.0.0.1',headers)),'203.0.113.1')
            self.assertEqual(browser_peer(self.request('192.0.2.1',headers)),'192.0.2.1')
            for values in ([],headers+[(b'x-real-ip',b'192.0.2.1')],[(b'x-real-ip',b'203.0.113.1,192.0.2.1')]):
                with self.assertRaisesRegex(ValueError,'invalid_client_address'):
                    browser_peer(self.request('127.0.0.1',values))
