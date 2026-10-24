import unittest
from starlette.testclient import TestClient
from media_mcp.server import create_server,make_auth
from media_mcp.lan import lan_middleware
from unittest.mock import patch


class LANTests(unittest.TestCase):
    def test_no_auth_from_private_address_and_public_peer_rejected(self):
        with patch.dict('os.environ',{'MEDIA_AUTH_MODE':'none'}):self.assertIsNone(make_auth())
        for host,code in [('192.168.8.2',200),('127.0.0.1',200),('8.8.8.8',403),('::ffff:192.168.1.2',200)]:
            app=create_server(object()).http_app(path='/mcp',middleware=lan_middleware(),stateless_http=True,json_response=True)
            with self.subTest(host=host),TestClient(app,client=(host,12345),base_url="http://192.168.8.1:18210") as client:
                result=client.get('/healthz',headers={'X-Forwarded-For':'192.168.8.2'})
                self.assertEqual(result.status_code,code)
