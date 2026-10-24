import unittest
from media_mcp.lan import LANOnlyMiddleware


class BrowserBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, host=b'192.168.8.1:18210', origin=None, peer='192.168.8.2', allowed_hosts=None, websocket=False):
        events=[]
        async def app(scope,receive,send):
            await send({'type':'http.response.start','status':200})
            await send({'type':'http.response.body','body':b'ok'})
        async def receive(): return {'type':'http.request','body':b''}
        async def send(message): events.append(message)
        headers=[] if host is None else [(b'host',host)]
        if origin is not None: headers.append((b'origin',origin))
        headers.append((b'x-forwarded-for',b'192.168.8.2'))
        await LANOnlyMiddleware(app,allowed_hosts=allowed_hosts)(
            {'type':'websocket' if websocket else 'http','client':(peer,1),'headers':headers},receive,send)
        return events[0].get('status'),events

    async def test_native_and_same_origin_lan_access(self):
        for origin in (None,b'http://192.168.8.1:18210'):
            status,_=await self.call(origin=origin);self.assertEqual(status,200)

    async def test_rebinding_host_and_cross_site_origin_denied(self):
        for host,origin in ((b'evil.example',None),(b'192.168.8.1:18210',b'https://evil.example'),
                            (b'192.168.8.1:18210',b'null'),(None,None),
                            (b'user:pass@192.168.8.1',None)):
            status,_=await self.call(host=host,origin=origin);self.assertEqual(status,403)

    async def test_explicit_hostname_and_public_peer(self):
        self.assertEqual((await self.call(host=b'media.home:18210',allowed_hosts='media.home'))[0],200)
        self.assertEqual((await self.call(peer='8.8.8.8'))[0],403)
        self.assertEqual((await self.call(peer='::ffff:192.168.8.2'))[0],200)

    async def test_websocket_cross_origin_rejected(self):
        _,events=await self.call(websocket=True,origin=b'https://evil.example')
        self.assertEqual(events[0],{'type':'websocket.close','code':1008})
