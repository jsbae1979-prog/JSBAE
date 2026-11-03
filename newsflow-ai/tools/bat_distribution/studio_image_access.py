"""Authenticated standalone image generation, settings budget and one durable attempt."""
from contextvars import ContextVar
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import re
import time
from filelock import FileLock, Timeout
from newsflow.creation import image_pricing as rates
from newsflow.creation.feed_costs import fingerprint, money
from newsflow.creation.feed_readiness import FeedReadiness
from newsflow.db.models import IntelligenceRun
from newsflow.intelligence.credentials import AIKeyStore, CredentialError
from newsflow.publishing.image_generation import ImageGenerationService
from newsflow.publishing.service import PublishingError
from .character_authoring import _Store, _unlinked

PATH=re.compile(r'/image-studio/([1-9][0-9]*)/generate\Z')
_REQUEST=ContextVar('studio_image_request',default=None)
_KEY=ContextVar('studio_image_key',default=None)


class _Generation(ImageGenerationService):
    def __init__(self,owner,adapter=None):
        self.owner=owner
        super().__init__(owner.app.state.sessions,owner.profile,owner.keys,adapter=adapter)

    def _generate(self,article_id,analysis_id,rank,style,context,prompt,**kw):
        owner=self.owner;active=_REQUEST.get()
        if not active or active.get('owner') is not owner or active.get('used'):
            raise PublishingError('현재 화면에서 승인한 이미지 생성 요청이 필요합니다.')
        identifier=active['draft'];studio=owner.app.state.image_studio
        row=studio.get(identifier)
        reference=studio.asset(row.options['reference']).read_bytes() if row.options.get('reference') else None
        if (style!='studio' or article_id is not None or analysis_id is not None or rank is not None
                or context!={'image_studio_draft':identifier} or kw.get('draft_id')!=identifier
                or prompt!=row.result['prompt'] or kw.get('execution')!=row.options['selection']
                or kw.get('provider','openai')!='openai' or kw.get('reference')!=reference):
            raise PublishingError('저장된 이미지 지시문·모델·참조 이미지와 요청이 다릅니다.')
        active['used']=True
        try:
            with owner.lock:
                prior=studio.output(identifier)
                if prior:return prior.id  # Never replay a completed/failed/unknown attempt.
                row=studio.get(identifier)
                if row.options.get('image_budget'):
                    raise PublishingError('이 이미지의 이전 요청 상태를 확인하세요. 자동 재요청하지 않습니다.')
                scope=owner.ready.account_scope();limit=owner.ready.standing_limit()
                if not scope or not owner.ready(row.options['selection'])['modelVerified']:
                    raise PublishingError('설정에서 선택한 OpenAI 이미지 모델의 API 연결을 확인하세요.')
                if not limit:
                    raise PublishingError('설정에서 OpenAI 이미지 사용 승인과 작업당 한도를 저장하세요.')
                estimate=rates.estimate(row.options['selection'],prompt,now=time.time())
                if reference is not None:
                    raise PublishingError('참조 이미지 입력 비용은 아직 계산할 수 없습니다. 현재는 참조 이미지 없는 새 이미지 생성만 지원합니다.')
                if money(estimate['reserveUsd'])>money(limit):
                    raise PublishingError('이미지 예상 비용의 계획 예산이 설정된 작업 한도를 넘습니다. 품질·크기 또는 한도를 확인하세요.')
                state={**estimate,'accountScope':scope,'limitUsd':limit,'billingStatus':'unconfirmed',
                       'dispatchState':'not_sent','binding':fingerprint([prompt,row.options['selection'],
                            sha256(reference).hexdigest() if reference else None])}
                owner.save(identifier,state)
                active.update(scope=scope,limit=limit,selection=row.options['selection'])
                token=_KEY.set(owner)
                try:
                    # Persist uncertainty BEFORE handing control to any external adapter.
                    state['dispatchState']='sent_or_unknown';owner.save(identifier,state)
                    output=super()._generate(article_id,analysis_id,rank,style,context,prompt,**kw)
                finally:_KEY.reset(token)
                with owner.app.state.sessions() as session:generated=session.get(IntelligenceRun,output)
                usage=generated.result.get('usage');cost=rates.usage_cost(usage)
                state.update(generationId=output,billingStatus='usage_unconfirmed',billingVerified=False)
                if cost is not None:
                    state.update(observedUsd=cost,usage=deepcopy(usage),billingStatus='usage_calculated',
                                 overReserve=Decimal(cost)>money(state['reserveUsd']))
                owner.save(identifier,state)
                return output
        except Timeout:
            raise PublishingError('이미지 요청을 처리 중입니다. 잠시 후 결과를 확인하세요.') from None


class StudioImageAccess:
    def __init__(self,app,profile,nativefactory,*,adapter=None):
        self.app=app;self.profile=_unlinked(profile)
        if self.profile!=_unlinked(app.state.config.data_dir):raise CredentialError('데이터 경로를 확인하세요.')
        self.ready=FeedReadiness(app.state)
        self.keys=_Store(self,'openai',AIKeyStore,nativefactory())
        self.lock=FileLock(str(self.profile/'studio-image-request.lock'),timeout=0)
        self.generation=_Generation(self,adapter)
        app.state.image_studio.generation=self.generation

    def save(self,identifier,state):
        with self.app.state.sessions.begin() as session:
            row=session.get(IntelligenceRun,identifier)
            row.options={**row.options,'image_budget':deepcopy(state)}

    def active_key(self,provider):
        active=_REQUEST.get()
        if (provider!='openai' or _KEY.get() is not self or not active or active.get('owner') is not self
                or not active.get('used') or active.get('scope')!=self.ready.account_scope()
                or active.get('limit')!=self.ready.standing_limit()
                or not self.ready(active['selection'])['modelVerified']):
            raise CredentialError('현재 승인된 이미지 요청에서만 키를 사용할 수 있습니다.')

    def wrap(self,normal,authenticated):
        async def call(scope,receive,send):
            match=PATH.fullmatch(scope.get('path',''))
            if scope.get('type')!='http' or scope.get('method')!='POST' or not match:
                return await normal(scope,receive,send)
            token=_REQUEST.set({'owner':self,'draft':int(match[1]),'used':False})
            try:return await authenticated(scope,receive,send)
            finally:_REQUEST.reset(token)
        return call


def install(app,profile,nativefactory):return StudioImageAccess(app,profile,nativefactory)
