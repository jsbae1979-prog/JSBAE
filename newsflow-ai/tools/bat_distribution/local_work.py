"""Synthetic-profile local editing, preserving inner auth/Origin/CSRF and paid gates."""
from urllib.parse import parse_qs
import re
from .restored_install import RestoredRequests

FIXTURE_URL = 'https://example.com/newsflow-local-write-fixture'
FIXTURE = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Synthetic local write</title><link>https://example.com/</link><description>Offline only</description><item><title>Synthetic local write news</title><link>https://example.com/newsflow-local-write-news</link><guid>newsflow-local-write-news</guid><description>Offline fixture for save and restore verification.</description></item></channel></rss>'


def offline_adapter():
    from newsflow.news.rss_adapter import FakeRSSAdapter
    return FakeRSSAdapter({FIXTURE_URL: FIXTURE})


class LocalWorkRequests(RestoredRequests):
    """Enable only local saves; never infer permission from a broad action risk label."""
    POSTS = {'/image-studio/drafts','/image-studio/defaults','/character','/character-defaults',
             '/ai/preferences','/ai-settings','/settings/collection','/settings/sources',
             '/collection','/api/feed-batches/defaults'}
    LEGACY_READS = {'/ai','/ai-settings','/settings','/character','/image-studio',
                    '/video','/news','/dashboard','/api/collection'}
    DRAFT = re.compile(r'/ai/drafts/[1-9][0-9]*\Z')
    async def __call__(self, scope, receive, send):
        if scope['type']!='http':
            return await super().__call__(scope,receive,send)
        method,path=scope['method'],scope['path']
        if method=='POST' and path in {'/ai/analyze','/ai/generate'}:
            # Bounded inspect + exact replay. The unchanged inner middleware
            # still validates Origin and signed CSRF against the same form body.
            headers={k.lower():v for k,v in scope.get('headers',[])}
            body=b'';valid=headers.get(b'content-type',b'').split(b';')[0]==b'application/x-www-form-urlencoded'
            while valid:
                message=await receive()
                if message['type']!='http.request':valid=False;break
                body+=message.get('body',b'')
                if len(body)>65536:valid=False;break
                if not message.get('more_body'):break
            if valid:
                try: valid=parse_qs(body.decode('utf-8'),keep_blank_values=True).get('provider')==['offline']
                except UnicodeError:valid=False
            if valid:
                delivered=False
                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered=True
                        return {'type':'http.request','body':body,'more_body':False}
                    return await receive()
                return await self.app(scope,replay,send)
        elif method=='POST' and (path in self.POSTS or self.DRAFT.fullmatch(path)):
            return await self.app(scope,receive,send)
        elif method in {'GET','HEAD'} and (path in self.LEGACY_READS or path.startswith('/image-studio/assets/')):
            return await self.app(scope,receive,send)
        return await super().__call__(scope,receive,send)
