import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from starlette.testclient import TestClient

from media_mcp.platform.gateway import create_gateway
from media_mcp.platform.pairing import connect, loopback_url
import test_gateway


class PairSession:
    def __init__(self,client):
        self.client=client
        self.gets=0
    def get(self,url,**kwargs):
        self.gets+=1
        response=self.client.get(url)
        response.iter_content=response.iter_bytes
        return StreamResponse(response)
    def post(self,url,**kwargs):
        return self.client.post(url,json=kwargs['json'],headers=kwargs['headers'])


class StreamResponse:
    def __init__(self,response):
        self.response=response
    def __enter__(self):
        return self.response
    def __exit__(self,*args):
        pass


class ProxyDeploymentTests(unittest.TestCase):
    setUp=test_gateway.GatewayTests.setUp

    def test_only_explicit_proxy_container_ip_is_allowed(self):
        for proxy,other in (('172.18.0.3','172.18.0.4'),('10.3.0.7','10.3.0.8')):
            with patch.dict(os.environ,{'MEDIA_WEB_MODE':'proxy','MEDIA_PROXY_IPS':proxy}):
                app=create_gateway(self.remote,catalog=Mock(),http_request=self.transport.request)
                for peer,status in ((proxy,200),(other,403),('198.51.100.5',403)):
                    with TestClient(app,base_url='http://existing-proxy.test',client=(peer,9000)) as client:
                        self.assertEqual(client.get('/healthz',headers={'x-forwarded-for':proxy}).status_code,status)
        with patch.dict(os.environ,{'MEDIA_WEB_MODE':'proxy','MEDIA_PROXY_IPS':'172.18.0.0/16'}):
            with self.assertRaisesRegex(ValueError,'exact_ip_addresses'):
                with TestClient(create_gateway(self.remote,catalog=Mock(),http_request=self.transport.request)):
                    pass

    def test_cloud_gateway_default_listener_accepts_host_interfaces(self):
        from media_mcp.platform.gateway import main
        for configuration,expected in (
            ({},'0.0.0.0'),
            ({'MEDIA_WEB_BIND_HOST':'127.0.0.1'},'0.0.0.0'),
            ({'MEDIA_WEB_BIND_HOST':'127.0.0.1','MEDIA_GATEWAY_BIND':'0.0.0.0'},'0.0.0.0'),
            ({'MEDIA_GATEWAY_BIND':'127.0.0.1'},'127.0.0.1'),
            ({'MEDIA_CLOUD_WEB_BIND':'127.0.0.2','MEDIA_GATEWAY_BIND':'127.0.0.1'},'127.0.0.2'),
        ):
            with self.subTest(configuration=configuration),patch.dict(os.environ,configuration,clear=True),patch('media_mcp.platform.gateway.create_gateway',return_value=Mock()),patch('uvicorn.run') as run:
                main()
                self.assertEqual(run.call_args.kwargs['host'],expected)

    def test_cloud_web_port_names_keep_legacy_fallbacks(self):
        from media_mcp.platform.gateway import main
        for configuration,expected in (({},18214),({'MEDIA_WEB_PORT':'19514'},19514),
                ({'MEDIA_WEB_PORT':'19514','MEDIA_GATEWAY_PORT':'19515'},19515),
                ({'MEDIA_CLOUD_WEB_PORT':'19516','MEDIA_GATEWAY_PORT':'19515'},19516)):
            with self.subTest(configuration=configuration),patch.dict(os.environ,configuration,clear=True),patch('media_mcp.platform.gateway.create_gateway',return_value=Mock()),patch('uvicorn.run') as run:
                main()
                self.assertEqual(run.call_args.kwargs['port'],expected)

    def test_cloud_mcp_proxy_keeps_user_token_auth_without_domain_configuration(self):
        from media_mcp.server import main
        from media_mcp.platform.remote_mcp import RemoteTokenVerifier
        from media_mcp.platform.network import LoopbackProxyMiddleware
        server=Mock()
        with patch.dict(os.environ,{'MEDIA_WEB_MODE':'proxy','MEDIA_MCP_PUBLIC':'true',
                'MEDIA_ALLOWED_HOSTS':'','MEDIA_WEB_PUBLIC_URL':'',
                'MEDIA_CONTROL_URL':'http://127.0.0.1:28213'}),patch('media_mcp.server.create_server',return_value=server) as factory:
            main()
            self.assertIsInstance(factory.call_args.args[1],RemoteTokenVerifier)
            self.assertEqual(server.run.call_args.kwargs['middleware'][0].cls,LoopbackProxyMiddleware)

    def test_proxy_without_domain_keeps_network_web_access_authenticated(self):
        with patch.dict(os.environ,{'MEDIA_WEB_MODE':'proxy','MEDIA_ALLOWED_HOSTS':'',
                'MEDIA_WEB_PUBLIC_URL':'','MEDIA_WEB_SECURE_COOKIE':'true'}):
            app=create_gateway(self.remote,catalog=Mock(),http_request=self.transport.request)
            with TestClient(app,base_url='https://my-existing-proxy.test',client=('127.0.0.1',9000)) as client:
                result=client.post('/api/auth/login',json={'username':'alice','password':'alice-password-123'},
                    headers={'origin':'https://my-existing-proxy.test','x-real-ip':'198.51.100.4'})
                self.assertEqual(result.status_code,200)
                self.assertIn('Secure',result.headers['set-cookie'])
                self.assertEqual(client.get('/api/auth/me').status_code,200)
                self.assertEqual(client.post('/api/auth/login',json={},headers={
                    'origin':'https://attacker.test'}).status_code,403)
                self.assertEqual(client.get('/internal/pairing').status_code,404)
                self.assertEqual(client.get('/api/internal/pairing').status_code,400)
            with TestClient(app,base_url='https://my-existing-proxy.test',client=('192.168.8.50',9001)) as outsider:
                self.assertEqual(outsider.get('/healthz',headers={'x-forwarded-for':'127.0.0.1'}).status_code,200)
                self.assertEqual(outsider.get('/api/auth/me').status_code,401)
                self.assertEqual(outsider.post('/api/command',json={'operation':'jobs'}).status_code,401)
                from media_mcp.platform.network import browser_peer
                from starlette.requests import Request
                self.assertEqual(browser_peer(Request({'type':'http','client':('192.168.8.50',9001),
                    'headers':[(b'x-forwarded-for',b'127.0.0.1')]})),'192.168.8.50')

    def test_first_pairing_writes_private_file_then_seals_and_resumes(self):
        with tempfile.TemporaryDirectory() as cloud,patch.dict(os.environ,{
                'MEDIA_SERVICE_PAIRING':'true','MEDIA_WEB_BIND_HOST':'127.0.0.1'}):
            with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',9000)) as client:
                session=PairSession(client)
                destination=Path(cloud)/'control-token'
                connect('http://127.0.0.1:28213',destination,session)
                self.assertEqual(destination.stat().st_mode&0o777,0o600)
                self.assertEqual(client.get('/internal/pairing').json()['error_code'],'pairing_closed')
                connect('http://127.0.0.1:28213',destination,session)
                self.assertEqual(session.gets,1)
                original=destination.read_text()
                destination.write_text('wrong-existing-token-'+'x'*32)
                with self.assertRaises(Exception):
                    connect('http://127.0.0.1:28213',destination,session)
                self.assertNotEqual(destination.read_text(),original)
                self.assertEqual(session.gets,1)

    def test_pairing_requires_explicit_mode_loopback_bind_and_socket(self):
        with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',9000)) as client:
            self.assertEqual(client.get('/internal/pairing').status_code,403)
            with patch.dict(os.environ,{'MEDIA_SERVICE_PAIRING':'true','MEDIA_WEB_BIND_HOST':'0.0.0.0'}):
                self.assertEqual(client.get('/internal/pairing').status_code,403)
        with patch.dict(os.environ,{'MEDIA_SERVICE_PAIRING':'true','MEDIA_WEB_BIND_HOST':'127.0.0.1'}):
            with TestClient(self.local_app,base_url='http://127.0.0.1',client=('192.168.8.50',9001)) as client:
                self.assertEqual(client.get('/internal/pairing',headers={'x-forwarded-for':'127.0.0.1'}).status_code,403)
            with TestClient(self.local_app,base_url='http://127.0.0.1',client=('127.0.0.1',9000)) as client:
                self.assertEqual(client.post('/internal/pairing',json={}).status_code,403)

    def test_private_lan_binding_pairs_only_from_the_same_host_socket(self):
        with patch.dict(os.environ,{'MEDIA_SERVICE_PAIRING':'true','MEDIA_WEB_BIND_HOST':'192.168.8.1'}):
            with TestClient(self.local_app,base_url='http://192.168.8.1',client=('192.168.8.1',9000)) as local_frpc:
                self.assertEqual(local_frpc.get('/internal/pairing').status_code,200)
            for peer in ('192.168.8.50','127.0.0.1','203.0.113.5'):
                with TestClient(self.local_app,base_url='http://192.168.8.1',client=(peer,9000)) as other:
                    self.assertEqual(other.get('/internal/pairing',headers={
                        'x-forwarded-for':'192.168.8.1','x-real-ip':'192.168.8.1'}).status_code,403)
            with TestClient(self.local_app,base_url='http://192.168.8.2',client=('192.168.8.1',9000)) as different_listener:
                self.assertEqual(different_listener.get('/internal/pairing').status_code,403)

    def test_auto_pairing_never_fetches_non_loopback_or_redirect_targets(self):
        for url in ('http://192.168.8.1:18213','http://example.com','https://127.0.0.1',
                    'http://user:pass@127.0.0.1','http://127.0.0.1/path'):
            with self.subTest(url=url),self.assertRaisesRegex(ValueError,'loopback_frp_url'):
                loopback_url(url)

    def test_standard_local_proxy_uses_appended_peer_not_forged_first_forwarded_value(self):
        from types import SimpleNamespace
        from starlette.datastructures import Headers
        from media_mcp.platform.network import browser_peer
        request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'),headers=Headers({
            'x-forwarded-for':'192.0.2.99, 198.51.100.4','x-real-ip':'192.0.2.99'}))
        with patch.dict(os.environ,{'MEDIA_WEB_MODE':'proxy','MEDIA_WEB_TRUSTED_PROXIES':''}):
            self.assertEqual(browser_peer(request),'198.51.100.4')
            request.client.host='192.168.8.50'
            self.assertEqual(browser_peer(request),'192.168.8.50')
