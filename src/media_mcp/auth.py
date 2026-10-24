"""Private single-owner OAuth with SDK PKCE, persistent one-use grants and rotation.

The SDK validates clients, redirect URIs, PKCE and token request schemas. This
provider authenticates the owner in a browser and stores only hashes of tokens.
"""
import hashlib
import hmac
import html
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlencode, urlsplit
from fastmcp.server.auth import OAuthProvider
from mcp.server.auth.provider import (AccessToken, AuthorizationCode, AuthorizationParams,
    OAuthClientInformationFull, OAuthToken, RefreshToken, RegistrationError, TokenError, AuthorizeError)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route


class OwnerOAuth(OAuthProvider):
    def __init__(self, base_url, password, path):
        if len(password) < 24:
            raise ValueError('oauth_owner_password_requires_24_characters')
        self.url = base_url.rstrip('/')
        parsed = urlsplit(self.url)
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1','localhost')):
            raise ValueError('oauth_requires_https_or_loopback')
        self.password = password
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS oauth_state (
                kind TEXT NOT NULL, key TEXT PRIMARY KEY, value TEXT NOT NULL,
                expires REAL NOT NULL, family TEXT NOT NULL DEFAULT '')''')
        os.chmod(self.path, 0o600)
        super().__init__(base_url=self.url, required_scopes=['media:access'],
            client_registration_options=ClientRegistrationOptions(enabled=True,
                valid_scopes=['media:access'], default_scopes=['media:access']),
            revocation_options=RevocationOptions(enabled=True))

    def connection(self):
        return sqlite3.connect(self.path, timeout=10)

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def save(self, kind, key, value, expires, family=''):
        with self.connection() as db:
            db.execute('DELETE FROM oauth_state WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO oauth_state VALUES (?,?,?,?,?)',
                       (kind,self.digest(key),json.dumps(value),expires,family))

    def load(self, kind, key, consume=False):
        with self.connection() as db:
            query = ('DELETE FROM oauth_state WHERE kind=? AND key=? AND expires>? RETURNING value'
                     if consume else 'SELECT value FROM oauth_state WHERE kind=? AND key=? AND expires>?')
            row = db.execute(query, (kind,self.digest(key),time.time())).fetchone()
        return json.loads(row[0]) if row else None

    async def get_client(self, client_id):
        value = self.load('client', client_id)
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def register_client(self, client_info):
        for uri in client_info.redirect_uris:
            parsed = urlsplit(str(uri))
            valid_chatgpt = (parsed.scheme=='https' and parsed.netloc=='chatgpt.com' and
                (parsed.path.startswith('/connector/oauth/') or parsed.path=='/connector_platform_oauth_redirect'))
            local = parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost')
            if not (valid_chatgpt or local) or parsed.fragment:
                raise RegistrationError('invalid_redirect_uri', 'Only ChatGPT and loopback callbacks are supported')
        self.save('client', client_info.client_id, client_info.model_dump(mode='json'), time.time()+365*86400)

    async def authorize(self, client, params):
        if params.resource != self.url+'/mcp':
            raise AuthorizeError('invalid_target', 'Expected the media MCP resource URL')
        nonce = secrets.token_urlsafe(32)
        self.save('pending', nonce, {'client_id':client.client_id, 'params':params.model_dump(mode='json')}, time.time()+600)
        return self.url+'/owner-login?'+urlencode({'request':nonce})

    async def login(self, request):
        headers = {'Cache-Control':'no-store', 'Content-Security-Policy':"default-src 'none'; form-action 'self'; frame-ancestors 'none'",
                   'Referrer-Policy':'no-referrer', 'X-Content-Type-Options':'nosniff'}
        if request.method == 'GET':
            nonce = request.query_params.get('request','')
            value = self.load('pending',nonce)
            if not value:
                return HTMLResponse('授权请求已过期，请重新连接。',status_code=400,headers=headers)
            csrf = secrets.token_urlsafe(32)
            self.save('csrf',csrf,{'nonce':nonce},time.time()+600)
            response = HTMLResponse('<!doctype html><meta charset="utf-8"><title>Media MCP</title>'
                '<h1>连接你的 Media MCP</h1><p>允许当前客户端搜索资源、提交下载和处理媒体及字幕。</p>'
                '<p>请在这里输入 media/.env 中的 MEDIA_OWNER_PASSWORD；不要发给聊天模型。</p>'
                '<form method="post"><input type="hidden" name="request" value="'+html.escape(nonce)+'">'
                '<input type="hidden" name="csrf" value="'+html.escape(csrf)+'">'
                '<label>所有者密码 <input type="password" name="password" required autocomplete="current-password"></label>'
                '<button type="submit">授权连接</button></form>',headers=headers)
            response.set_cookie('media_oauth_csrf',csrf,httponly=True,secure=self.url.startswith('https:'),samesite='lax',max_age=600)
            return response
        form = await request.form()
        csrf = str(form.get('csrf',''))
        saved = self.load('csrf',csrf,consume=True)
        nonce = str(form.get('request',''))
        if not saved or saved['nonce'] != nonce or not hmac.compare_digest(csrf.encode(),request.cookies.get('media_oauth_csrf','').encode()):
            return HTMLResponse('授权校验失败，请重新连接。',status_code=400,headers=headers)
        # Persistent global throttle bounds password guessing, including across new DCR clients.
        bucket = str(int(time.time()//600))
        with self.connection() as db:
            db.execute('INSERT OR IGNORE INTO oauth_state VALUES (?,?,?,?,?)',('attempts',bucket,'0',time.time()+1200,''))
            db.execute('UPDATE oauth_state SET value=CAST(value AS INTEGER)+1 WHERE key=?',(bucket,))
            attempts = int(db.execute('SELECT value FROM oauth_state WHERE key=?',(bucket,)).fetchone()[0])
        if attempts > 10 or not hmac.compare_digest(str(form.get('password','')).encode(),self.password.encode()):
            return HTMLResponse('认证失败，请稍后重新连接。',status_code=403,headers=headers)
        value = self.load('pending',nonce,consume=True)
        if not value:
            return HTMLResponse('授权请求已过期。',status_code=400,headers=headers)
        params = AuthorizationParams.model_validate(value['params'])
        raw = secrets.token_urlsafe(32)
        grant = AuthorizationCode(code=raw,client_id=value['client_id'],scopes=params.scopes or ['media:access'],
            expires_at=time.time()+120,code_challenge=params.code_challenge,redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,resource=params.resource,subject='owner')
        self.save('code',raw,grant.model_dump(mode='json',exclude={'code'}),grant.expires_at)
        params_out = {'code':raw, 'iss':self.url, **({'state':params.state} if params.state else {})}
        uri = str(params.redirect_uri)
        response = RedirectResponse(uri+('&' if '?' in uri else '?')+urlencode(params_out),status_code=303,headers=headers)
        response.delete_cookie('media_oauth_csrf')
        return response

    async def load_authorization_code(self, client, authorization_code):
        value = self.load('code',authorization_code)
        return AuthorizationCode(code=authorization_code,**value) if value and value['client_id']==client.client_id else None

    def issue(self, client_id, scopes, resource):
        family = secrets.token_hex(16)
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        common = {'client_id':client_id,'scopes':scopes,'resource':resource,'subject':'owner'}
        self.save('access',access,{**common,'expires_at':int(time.time())+3600},time.time()+3600,family)
        self.save('refresh',refresh,{**common,'expires_at':int(time.time())+30*86400},time.time()+30*86400,family)
        return OAuthToken(access_token=access,refresh_token=refresh,expires_in=3600,scope=' '.join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        value = self.load('code',authorization_code.code,consume=True)
        if not value or value['client_id'] != client.client_id:
            raise TokenError('invalid_grant','Authorization code already used or expired')
        return self.issue(client.client_id,authorization_code.scopes,authorization_code.resource)

    async def load_refresh_token(self, client, refresh_token):
        value = self.load('refresh',refresh_token)
        return RefreshToken(token=refresh_token,**value) if value and value['client_id']==client.client_id else None

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        with self.connection() as db:
            row = db.execute("DELETE FROM oauth_state WHERE kind='refresh' AND key=? AND expires>? RETURNING value,family",
                (self.digest(refresh_token.token),time.time())).fetchone()
            if row:
                db.execute('DELETE FROM oauth_state WHERE family=?',(row[1],))
        value = json.loads(row[0]) if row else None
        if not value or value['client_id']!=client.client_id or not set(scopes).issubset(value['scopes']):
            raise TokenError('invalid_grant','Refresh token expired or reused')
        await self.revoke_token(refresh_token)
        return self.issue(client.client_id,scopes,refresh_token.resource)

    async def load_access_token(self, token):
        value = self.load('access',token)
        if value and value['resource']==self.url+'/mcp':
            return AccessToken(token=token,**value)
        return None

    async def revoke_token(self, token):
        with self.connection() as db:
            row = db.execute('SELECT family FROM oauth_state WHERE key=?',(self.digest(token.token),)).fetchone()
            if row:
                db.execute('DELETE FROM oauth_state WHERE family=? AND family<>\'\'',(row[0],))

    async def revocation(self, request):
        # SDK 1.30 RevocationRequest incorrectly requires client_secret even for
        # public clients. Use its authenticator while accepting RFC 7009 forms.
        from mcp.server.auth.middleware.client_auth import ClientAuthenticator, AuthenticationError
        try:
            client = await ClientAuthenticator(self).authenticate_request(request)
        except AuthenticationError:
            return Response(status_code=401)
        form = await request.form()
        raw = form.get('token')
        if not isinstance(raw,str) or not raw:
            return Response(status_code=400)
        token = await self.load_access_token(raw) or await self.load_refresh_token(client,raw)
        if token and token.client_id==client.client_id:
            await self.revoke_token(token)
        return Response(status_code=200,headers={'Cache-Control':'no-store'})

    def get_routes(self,mcp_path=None):
        routes = super().get_routes(mcp_path)
        routes = [Route('/revoke',self.revocation,methods=['POST']) if route.path=='/revoke' else route for route in routes]
        return [*routes,Route('/owner-login',self.login,methods=['GET','POST'])]
