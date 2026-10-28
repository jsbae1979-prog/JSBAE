"""Per-launch bearer authentication outside the unchanged application CSRF layer.

Bootstrap secrets only travel in the browser URL fragment and one bounded header.
Nothing is persisted, logged, placed in a query, or accepted as a cookie on claim.
"""
from __future__ import annotations

import hmac
from http.cookies import SimpleCookie, CookieError
import json
import re
import secrets
import threading
import time

CONNECT = b'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>NewsFlow AI</title><p id="status">NewsFlow AI local session...</p><script src="/__local/connect.js"></script></html>'''
SCRIPT = b'''(async()=>{const token=location.hash.slice(1);history.replaceState(null,'','/__local/connect');try{if(!/^[A-Za-z0-9_-]{43}$/.test(token))throw Error();const r=await fetch('/__local/claim',{method:'POST',headers:{'X-NewsFlow-Bootstrap':token},credentials:'same-origin'});if(!r.ok)throw Error();location.replace('/studio/dashboard');}catch{document.getElementById('status').textContent='Local session unavailable. Open NewsFlow AI again from your own Windows account.';}})();'''


class LaunchSession:
    def __init__(self, port: int, *, clock=time.monotonic):
        if not 1024 <= port <= 65535 or port == 8765:
            raise ValueError('private-user-port-required')
        self.port = port
        self.origin = f'http://127.0.0.1:{port}'
        self.cookie_name = f'nf_local_{port}'
        self._clock = clock
        self._born = clock()
        self._bootstrap = secrets.token_urlsafe(32)
        self._session = secrets.token_urlsafe(32)
        self._lock = threading.Lock()

    def launch_url(self):
        return self.origin + '/__local/connect#' + self._bootstrap

    def claim(self, token):
        with self._lock:
            if (self._clock()-self._born > 120 or not self._bootstrap
                    or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token) or not hmac.compare_digest(token, self._bootstrap)):
                return None
            self._bootstrap = ''
            return self._session

    def valid_cookie(self, value):
        if self._clock()-self._born > 12*3600:
            return False
        try:
            cookie = SimpleCookie(value)
            token = cookie[self.cookie_name].value if self.cookie_name in cookie else ''
        except CookieError:
            return False
        return bool(re.fullmatch(r'[A-Za-z0-9_-]{43}',token)) and hmac.compare_digest(token, self._session)


class LocalAccess:
    """ASGI wrapper: gates all data/static/media, keeps inner Origin/CSRF intact."""
    def __init__(self, app, session: LaunchSession):
        self.app, self.session = app, session

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'lifespan':
            return await self.app(scope, receive, send)
        if scope['type'] != 'http':
            if scope['type'] == 'websocket':
                await send({'type':'websocket.close','code':1008})
            return
        raw = scope.get('headers', [])
        headers = {k.lower():v.decode('latin1') for k,v in raw}
        method, path = scope['method'], scope['path']
        s = self.session
        valid_host = headers.get(b'host') == f'127.0.0.1:{s.port}'
        peer = (scope.get('client') or ('',0))[0]
        duplicate = any(sum(k.lower() == name for k,_ in raw)>1 for name in
                        (b'host',b'origin',b'cookie',b'x-newsflow-bootstrap'))
        boundary = (peer == '127.0.0.1' and valid_host and not duplicate
                    and headers.get(b'sec-fetch-site') != 'cross-site'
                    and (not headers.get(b'origin') or headers[b'origin'] == s.origin))
        async def reply(status, body=b'Local Windows session authentication required.', content=b'text/plain; charset=utf-8', extra=()):
            base = [(b'content-type',content),(b'cache-control',b'no-store'),
                    (b'referrer-policy',b'no-referrer'),(b'x-content-type-options',b'nosniff'),
                    (b'content-security-policy',b"default-src 'none'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")]
            await send({'type':'http.response.start','status':status,'headers':base+list(extra)})
            await send({'type':'http.response.body','body':body})
        if not boundary:
            return await reply(403)
        if path == '/__local/connect' and method == 'GET' and not scope.get('query_string'):
            return await reply(200, CONNECT, b'text/html; charset=utf-8')
        if path == '/__local/connect.js' and method == 'GET':
            return await reply(200, SCRIPT, b'text/javascript; charset=utf-8')
        if path == '/__local/claim':
            if method != 'POST' or headers.get(b'origin') != s.origin or scope.get('query_string'):
                return await reply(403)
            # Never read arbitrary request bodies or echo bootstrap/session material.
            if headers.get(b'content-length','0') != '0' or b'transfer-encoding' in headers:
                return await reply(413)
            token = s.claim(headers.get(b'x-newsflow-bootstrap',''))
            if token is None:
                return await reply(403)
            cookie = f'{s.cookie_name}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200'
            return await reply(204,b'',extra=[(b'set-cookie',cookie.encode('ascii'))])
        if path.startswith('/__local/') or not s.valid_cookie(headers.get(b'cookie','')):
            return await reply(403)
        if method not in {'GET','HEAD','OPTIONS'} and headers.get(b'origin') != s.origin:
            return await reply(403)
        return await self.app(scope, receive, send)
