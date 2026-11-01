"""Server-owned cached cost bounds; no network, key loading or client-priced grants.

The production Images API has no integrated bounded quote source yet. A missing
source fails closed. Constructor-injected cached bounds are exercised with Fakes.
Reservations survive failures and fresh quotes; they are exposure, not invoices.
"""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from newsflow.publishing.service import PublishingError

def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

def money(value):
    try:
        if isinstance(value,bool):raise ValueError()
        amount=Decimal(str(value))
        if not amount.is_finite() or not 0<amount<=1000:raise ValueError()
        return amount
    except (ValueError,InvalidOperation):
        raise PublishingError('이번 작업의 USD 사용 한도를 확인하세요.') from None

def binding(row):
    return fingerprint({'id':row.id,'source':row.options['source_hash'],'selection':row.options['selection'],
        'items':[{k:i[k] for k in ('rank','attempt','content')} for i in row.result['items']]})

def exposure(state):
    return sum((money(r['reservedUsd']) for r in state.get('reservations',[])),Decimal(0))

def unreserved(row,state,quote):
    used={r['requestKey'] for r in state.get('reservations',[])}
    return [b for b in quote['bounds'] if f"{row.id}:{b['rank']}:{b['attempt']}" not in used]

class FeedCosts:
    def __init__(self,cached_quote=None,account_scope=None,clock=None):
        # A cached quote resolver is a trusted server dependency, never form data.
        self.cached_quote,self.account_scope=cached_quote,account_scope
        self.clock=clock or (lambda:datetime.now(timezone.utc).timestamp())

    def refresh(self,row):
        prior=row.options.get('costs',{})
        state={'reservations':deepcopy(prior.get('reservations',[]))}
        if self.cached_quote is None or self.account_scope is None:
            return state
        scope=self.account_scope()
        if not isinstance(scope,str) or not scope:raise PublishingError('저장된 계정의 모델 권한 확인이 필요합니다.')
        pending=[{'rank':i['rank'],'attempt':i['attempt']} for i in row.result['items'] if i['status']=='pending']
        if not pending:raise PublishingError('생성 대기 이미지가 없습니다.')
        raw=self.cached_quote(deepcopy(row.options['selection']),binding(row),deepcopy(pending),scope)
        if not isinstance(raw,dict) or raw.get('currency')!='USD' or raw.get('accountScope')!=scope:
            raise PublishingError('계정에 연결된 공식 비용 상한이 필요합니다.')
        expires=raw.get('expiresAt')
        if type(expires) not in (int,float) or not self.clock()<expires<=self.clock()+3600:
            raise PublishingError('비용 확인이 만료되었습니다.')
        bounds=raw.get('bounds',[])
        if (not isinstance(bounds,list) or len(bounds)!=len(pending)
                or sorted((b.get('rank'),b.get('attempt')) for b in bounds)!=sorted((b['rank'],b['attempt']) for b in pending)):
            raise PublishingError('비용 확인 범위가 선택한 이미지와 다릅니다.')
        if raw.get('binding')!=binding(row) or raw.get('upperBoundVerified') is not True:
            raise PublishingError('예상 금액만으로 유료 실행을 승인할 수 없습니다.')
        quote={'binding':binding(row),'accountScope':scope,'expiresAt':expires,'currency':'USD',
            'bounds':[{'rank':b['rank'],'attempt':b['attempt'],'maximumUsd':str(money(b['maximumUsd']))} for b in bounds]}
        quote['hash']=fingerprint(quote)
        state['quote']=quote
        return state

    def quote(self,row):
        quote=row.options.get('costs',{}).get('quote')
        if (not quote or self.account_scope is None or quote['accountScope']!=self.account_scope()
                or quote['binding']!=binding(row) or self.clock()>=quote['expiresAt']
                or fingerprint({k:v for k,v in quote.items() if k!='hash'})!=quote['hash']):
            raise PublishingError('공식 견적·계정 권한·비용 상한 확인 후 승인할 수 있습니다.')
        return quote

    def approve(self,row,quote_hash,limit,consent):
        if consent is not True:raise PublishingError('표시된 생성 범위와 비용을 승인하세요.')
        quote=self.quote(row);cap=money(limit)
        if quote_hash!=quote['hash']:raise PublishingError('비용 확인 내용이 변경되었습니다.')
        state=deepcopy(row.options['costs'])
        total=exposure(state)+sum((money(b['maximumUsd']) for b in unreserved(row,state,quote)),Decimal(0))
        if total>cap:raise PublishingError('기존 요청의 보류 금액을 포함하면 이번 작업 한도를 넘습니다.')
        state['approval']={'quoteHash':quote_hash,'limitUsd':str(cap)}
        return state

    def reserve(self,row,item):
        quote=self.quote(row);state=deepcopy(row.options['costs']);approval=state.get('approval',{})
        if approval.get('quoteHash')!=quote['hash']:raise PublishingError('이번 이미지 제작 비용을 먼저 승인하세요.')
        key=f"{row.id}:{item['rank']}:{item['attempt']}"
        if any(r['requestKey']==key for r in state['reservations']):raise PublishingError('이미 접수된 요청입니다. 결과를 확인하세요.')
        bound=next((b for b in quote['bounds'] if (b['rank'],b['attempt'])==(item['rank'],item['attempt'])),None)
        if not bound:raise PublishingError('승인된 이미지 범위를 벗어났습니다.')
        amount=money(bound['maximumUsd'])
        if exposure(state)+amount>money(approval['limitUsd']):raise PublishingError('이번 작업 한도를 넘습니다.')
        state['reservations'].append({'requestKey':key,'reservedUsd':str(amount),'quoteHash':quote['hash'],
                                     'billingStatus':'unconfirmed'})
        return state

    def view(self,row):
        state=row.options.get('costs',{});quote=None
        try:quote=self.quote(row)
        except PublishingError:pass
        approval=state.get('approval',{})
        return {'currency':'USD','quoteHash':quote['hash'] if quote else None,
            'remainingMaximumUsd':str(sum((money(b['maximumUsd']) for b in unreserved(row,state,quote)),Decimal(0))) if quote else None,
            'reservedUsd':str(exposure(state)),'approvedLimitUsd':approval.get('limitUsd'),
            'approved':bool(quote and approval.get('quoteHash')==quote['hash']),
            'ready':bool(quote),'billingVerified':False,
            'message':'선택 범위의 비용 상한 확인됨 · 실제 청구액 별도' if quote else
                '장당 비용 미확정 · OpenAI 계정 권한과 비용 상한을 확인해야 생성할 수 있습니다.'}
