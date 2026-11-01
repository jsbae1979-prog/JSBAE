"""Exact authenticated TOP-3 step, current-user key and approved app budget only."""
from contextvars import ContextVar
import re
from newsflow.creation.catalog import check_snapshot
from newsflow.creation.feed_costs import fingerprint
from newsflow.publishing.image_generation import ImageGenerationService
from newsflow.intelligence.credentials import AIKeyStore,CredentialError
from .character_authoring import _Store,_unlinked

PATH=re.compile(r'/api/feed-batches/([1-9][0-9]*)/step\Z')
_REQUEST=ContextVar('feed_image_request',default=None)
_KEY=ContextVar('feed_image_key',default=None)

class _Generation(ImageGenerationService):
    def __init__(self,owner,adapter=None):
        self.owner=owner
        super().__init__(owner.app.state.sessions,owner.profile,owner.keys,adapter=adapter)

    def _generate(self,article_id,analysis_id,rank,style,context,prompt,**kw):
        owner=self.owner;active=_REQUEST.get()
        if not active or active.get('owner') is not owner or active.get('used'):
            raise CredentialError('승인된 TOP 3 이미지 요청이 아닙니다.')
        row=owner.app.state.top_three_feeds.get(active['batch'])
        item=next((i for i in row.result['items'] if i['rank']==rank),None)
        q=owner.app.state.top_three_feeds.costs.quote(row)
        reservation=next((r for r in row.options.get('costs',{}).get('reservations',[])
                          if r['requestKey']==f"{row.id}:{rank}:{item['attempt']}"),None) if item else None
        bound=next((b for b in q['bounds'] if item and b['rank']==rank and b['attempt']==item['attempt']),None)
        source=next((s for s in row.evidence['sources'] if s['rank']==rank),None)
        if (not item or item['status']!='running' or not source or not reservation or not bound
                or reservation.get('quoteHash')!=q['hash'] or reservation.get('billingStatus')!='unconfirmed'
                or row.options['costs'].get('approval',{}).get('quoteHash')!=q['hash']
                or style!='full_card' or article_id!=source['article_id'] or analysis_id!=row.evidence['analysis_id']
                or context.get('batch_id')!=row.id or context.get('rank')!=rank or context.get('attempt')!=item['attempt']
                or fingerprint(prompt)!=bound.get('promptHash') or kw.get('reference') is not None
                or kw.get('provider','openai')!='openai' or kw.get('execution')!=row.options['selection']):
            raise CredentialError('이미지 예산·문구·작업 범위를 다시 확인하세요.')
        check_snapshot(kw['execution'],'image')
        active['used']=True
        token=_KEY.set(owner)
        try:return super()._generate(article_id,analysis_id,rank,style,context,prompt,**kw)
        finally:_KEY.reset(token)

class FeedImageAccess:
    def __init__(self,app,profile,nativefactory,*,adapter=None):
        self.app=app;self.profile=_unlinked(profile)
        if self.profile!=_unlinked(app.state.config.data_dir):raise CredentialError('데이터 경로를 확인하세요.')
        self.keys=_Store(self,'openai',AIKeyStore,nativefactory())
        self.generation=_Generation(self,adapter)
        app.state.top_three_feeds.generation=self.generation

    def active_key(self,provider):
        active=_REQUEST.get()
        if (provider!='openai' or _KEY.get() is not self or not active
                or active.get('owner') is not self or not active.get('used')):
            raise CredentialError('현재 승인된 이미지 요청만 키를 사용할 수 있습니다.')
        # Re-check the approved credential revision immediately before key access.
        self.app.state.top_three_feeds.costs.quote(self.app.state.top_three_feeds.get(active['batch']))

    def wrap(self,normal,authenticated):
        owner=self
        async def call(scope,receive,send):
            match=PATH.fullmatch(scope.get('path',''))
            if scope.get('type')!='http' or scope.get('method')!='POST' or not match:
                return await normal(scope,receive,send)
            token=_REQUEST.set({'owner':owner,'batch':int(match[1]),'used':False})
            try:return await authenticated(scope,receive,send)
            finally:_REQUEST.reset(token)
        return call

def install(app,profile,nativefactory):return FeedImageAccess(app,profile,nativefactory)
