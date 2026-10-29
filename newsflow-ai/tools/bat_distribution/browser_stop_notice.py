"""Explicit BAT Stop notification behind the unchanged LocalAccess boundary.

GET only waits/reads; it cannot stop the app. Only Control's authenticated Stop
acceptance signals this channel. No token, nonce, user data or process ID is sent.
"""
from __future__ import annotations
import asyncio
import json
from newsflow.distribution.local_access import LocalAccess

PATH = '/api/studio/session-stop'


class BrowserStopNotice:
    def __init__(self, app, session, *, poll_seconds=15, grace_seconds=.5):
        if not .01 <= poll_seconds <= 25 or not 0 <= grace_seconds <= 1:
            raise ValueError('invalid-stop-notice-timeout')
        self.app, self.poll_seconds, self.grace_seconds = app, poll_seconds, grace_seconds
        self._stopping = asyncio.Event()
        self._delivered = asyncio.Event()
        self._authenticated = LocalAccess(self._serve, session)

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope.get('path') == PATH:
            return await self._authenticated(scope, receive, send)
        return await self.app(scope, receive, send)

    async def stop_accepted(self):
        """Called only after Control has accepted the existing private Stop."""
        self._stopping.set()
        try:
            await asyncio.wait_for(self._delivered.wait(), self.grace_seconds)
        except TimeoutError:
            pass  # No browser/closed tab must never prevent normal server Stop.

    async def _serve(self, scope, receive, send):
        status = 200
        accepted = False
        if scope.get('method') != 'GET':
            status = 405
        elif scope.get('query_string'):
            status = 400
        else:
            async def disconnected():
                while True:
                    if (await receive())['type'] == 'http.disconnect':
                        return
            stopping = asyncio.create_task(self._stopping.wait())
            disconnect = asyncio.create_task(disconnected())
            try:
                done, _ = await asyncio.wait({stopping, disconnect}, timeout=self.poll_seconds,
                                             return_when=asyncio.FIRST_COMPLETED)
                if disconnect in done:
                    return
                accepted = self._stopping.is_set()
            finally:
                stopping.cancel()
                disconnect.cancel()
                await asyncio.gather(stopping, disconnect, return_exceptions=True)
        body = json.dumps({'schemaVersion': 1, 'stopAccepted': accepted}).encode('ascii')
        await send({'type': 'http.response.start', 'status': status, 'headers': [
            (b'content-type', b'application/json'), (b'cache-control', b'no-store'),
            (b'x-content-type-options', b'nosniff')]})
        await send({'type': 'http.response.body', 'body': body})
        if status == 200 and accepted:
            self._delivered.set()
