"""User-approved application budgets, never provider-guaranteed charge ceilings."""
from copy import deepcopy
from decimal import Decimal
from .feed_costs import FeedCosts, binding, fingerprint, money, exposure, unreserved
from . import image_pricing as rates
from newsflow.publishing.service import PublishingError

class FeedBudget(FeedCosts):
    def __init__(self,readiness,clock=None):
        super().__init__(account_scope=readiness.account_scope,readiness=readiness,clock=clock)

    def quote(self,row):
        q=super().quote(row)
        if q.get('basis')!='app_budget_estimate' or q.get('pricingVersion')!=rates.VERSION or not rates.current(self.clock()):
            raise PublishingError('새 이미지 예산을 계산하고 승인하세요.')
        selected=self.readiness(row.options['selection'])
        if not selected['modelVerified']:
            raise PublishingError('선택한 OpenAI 모델의 연결 테스트를 확인하세요.')
        return q

    def refresh(self,row):
        try:
            self.quote(row);return deepcopy(row.options['costs'])
        except PublishingError:pass
        from .top_three_feeds import prompt_for
        from newsflow.publishing.feed_titles import TITLE_LAYOUT
        scope=self.account_scope();status=self.readiness(row.options['selection'])
        if not scope or not status['modelVerified']:
            raise PublishingError('설정에서 선택한 OpenAI 이미지 모델의 연결 테스트를 먼저 확인하세요.')
        bounds=[]
        for item in row.result['items']:
            if item['status']!='pending':continue
            source=next(s for s in row.evidence['sources'] if s['rank']==item['rank'])
            prompt=prompt_for(source,item['content'],row.id,item['attempt'],local_title=row.options.get('title_layout')==TITLE_LAYOUT,safety_version=item.get('safety_version'))
            result=rates.estimate(row.options['selection'],prompt,now=self.clock())
            bounds.append({'rank':item['rank'],'attempt':item['attempt'],
                           'maximumUsd':result['reserveUsd'],'estimate':result,
                           'promptHash':fingerprint(prompt)})
        if not bounds:raise PublishingError('생성 대기 이미지가 없습니다.')
        q={'basis':'app_budget_estimate','pricingVersion':rates.VERSION,'providerChargeCap':False,
           'binding':binding(row),'accountScope':scope,'expiresAt':min(self.clock()+3600,rates.VALID_UNTIL),
           'currency':'USD','bounds':bounds}
        q['hash']=fingerprint(q)
        return {'quote':q,'reservations':deepcopy(row.options.get('costs',{}).get('reservations',[]))}

    def blocked(self,state):
        for r in state.get('reservations',[]):
            if r.get('billingStatus') in {'unconfirmed','usage_unconfirmed'}:
                return '이전 요청의 사용량을 확인할 수 없어 다음 생성을 중단했습니다.'
            if r.get('overReserve'):
                return '응답 사용량 비용이 계획 예산을 넘었습니다. 다음 생성은 중단했습니다.'
        return None

    def approve(self,row,quote_hash,limit,consent):
        reason=self.blocked(row.options.get('costs',{}))
        if reason:raise PublishingError(reason)
        return super().approve(row,quote_hash,limit,consent)

    def reserve(self,row,item):
        reason=self.blocked(row.options.get('costs',{}))
        if reason:raise PublishingError(reason)
        state=super().reserve(row,item)
        state['reservations'][-1].update(basis='app_budget_estimate',pricingVersion=rates.VERSION)
        return state

    def settle(self,row,item,generated):
        state=deepcopy(row.options.get('costs',{}))
        key=f"{row.id}:{item['rank']}:{item['attempt']}"
        entry=next((r for r in state.get('reservations',[]) if r['requestKey']==key),None)
        if not entry or entry.get('basis')!='app_budget_estimate':return state
        source=generated.evidence.get('source',{})
        if (generated.kind!='feed_image' or generated.provider!='openai'
                or source.get('batch_id')!=row.id or source.get('rank')!=item['rank']
                or source.get('attempt')!=item['attempt']):
            raise PublishingError('저장된 이미지 사용량의 작업 연결이 다릅니다.')
        usage=generated.result.get('usage')
        amount=rates.usage_cost(usage)
        entry.update(generationId=generated.id,billingStatus='usage_unconfirmed',billingVerified=False)
        if amount is not None and generated.status=='success':
            entry.update(usage=deepcopy(usage),observedUsd=amount,billingStatus='usage_calculated',
                         overReserve=Decimal(amount)>money(entry['reservedUsd']))
        return state

    def view(self,row):
        v=super().view(row);q=None
        try:q=self.quote(row)
        except PublishingError:pass
        state=row.options.get('costs',{});reason=self.blocked(state)
        v.update(basis='app_budget_estimate',providerChargeCap=False,stopReason=reason,
                 estimatedUsd=str(sum((Decimal(b['estimate']['estimatedUsd']) for b in unreserved(row,state,q)),Decimal(0))) if q else None,
                 usageCalculatedUsd=str(sum((Decimal(r.get('observedUsd','0')) for r in state.get('reservations',[])),Decimal(0))),
                 usageUnknown=any(r.get('billingStatus') in {'unconfirmed','usage_unconfirmed'} for r in state.get('reservations',[])))
        v['approved']=v['approved'] and not reason
        if reason:v['message']=reason
        elif q:v['message']='앱 예산 계산 완료 · 예상 비용이며 OpenAI의 최종 청구 상한을 보장하지 않습니다.'
        return v
