import base64
import hashlib
import tempfile
import unittest
from urllib.parse import urlsplit,parse_qs
from starlette.testclient import TestClient
from media_mcp.auth import OwnerOAuth
from media_mcp.server import create_server


class OAuthTests(unittest.TestCase):
    def test_owner_login_pkce_rotation_revocation_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            password = 'owner-test-'+'x'*32
            provider = OwnerOAuth('http://127.0.0.1:18210',password,directory+'/auth.db')
            app = create_server(object(),provider).http_app(path='/mcp',stateless_http=True,json_response=True)
            with TestClient(app,base_url='http://127.0.0.1:18210') as client:
                self.assertEqual(client.post('/mcp',json={}).status_code,401)
                metadata = client.get('/.well-known/oauth-authorization-server').json()
                self.assertIn('S256',metadata['code_challenge_methods_supported'])
                registration = client.post('/register',json={'redirect_uris':['http://127.0.0.1:9000/callback'],
                    'token_endpoint_auth_method':'none','grant_types':['authorization_code','refresh_token'],
                    'response_types':['code'],'scope':'media:access'})
                self.assertEqual(registration.status_code,201,registration.text)
                client_id = registration.json()['client_id']
                verifier = 'v'*64
                challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                auth = client.get('/authorize',params={'client_id':client_id,'redirect_uri':'http://127.0.0.1:9000/callback',
                    'response_type':'code','code_challenge':challenge,'code_challenge_method':'S256',
                    'scope':'media:access','state':'state123','resource':'http://127.0.0.1:18210/mcp'},follow_redirects=False)
                self.assertIn(auth.status_code,(302,303),auth.text)
                login = client.get(auth.headers['location'])
                self.assertEqual(login.status_code,200)
                csrf = client.cookies.get('media_oauth_csrf')
                nonce = parse_qs(urlsplit(auth.headers['location']).query)['request'][0]
                approved = client.post('/owner-login',data={'password':password,'csrf':csrf,'request':nonce},follow_redirects=False)
                self.assertEqual(approved.status_code,303,approved.text)
                code = parse_qs(urlsplit(approved.headers['location']).query)['code'][0]
                payload = {'grant_type':'authorization_code','client_id':client_id,'code':code,
                           'code_verifier':verifier,'redirect_uri':'http://127.0.0.1:9000/callback',
                           'resource':'http://127.0.0.1:18210/mcp'}
                invalid = client.post('/token',data={**payload,'code_verifier':'incorrect'*8})
                self.assertEqual(invalid.status_code,400)
                response = client.post('/token',data=payload)
                self.assertEqual(response.status_code,200,response.text)
                tokens = response.json()
                self.assertEqual(client.post('/token',data=payload).status_code,400)
                import asyncio
                reboot = OwnerOAuth('http://127.0.0.1:18210',password,directory+'/auth.db')
                self.assertIsNotNone(asyncio.run(reboot.load_access_token(tokens['access_token'])))
                refresh_payload = {'grant_type':'refresh_token','client_id':client_id,'refresh_token':tokens['refresh_token'],
                                   'resource':'http://127.0.0.1:18210/mcp'}
                refreshed = client.post('/token',data=refresh_payload)
                self.assertEqual(refreshed.status_code,200,refreshed.text)
                self.assertIsNone(asyncio.run(reboot.load_access_token(tokens['access_token'])))
                self.assertEqual(client.post('/token',data=refresh_payload).status_code,400)
                access = refreshed.json()['access_token']
                result = client.post('/revoke',data={'client_id':client_id,'token':access})
                self.assertEqual(result.status_code,200)
                self.assertIsNone(asyncio.run(reboot.load_access_token(access)))
                self.assertNotIn(access,__import__('pathlib').Path(directory+'/auth.db').read_bytes().decode(errors='ignore'))

    def test_redirect_and_csrf_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            app = create_server(object(),OwnerOAuth('http://127.0.0.1:18210','p'*32,directory+'/auth.db')).http_app()
            with TestClient(app) as client:
                result = client.post('/register',json={'redirect_uris':['https://attacker.example/callback'],
                    'token_endpoint_auth_method':'none'})
                self.assertEqual(result.status_code,400)
                result = client.post('/owner-login',data={'password':'p'*32,'csrf':'bad','request':'bad'})
                self.assertEqual(result.status_code,400)
