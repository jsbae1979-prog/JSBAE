"""Only synthetic accounts, quotes, DBs and adapters. No provider network."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from newsflow.creation.catalog import DEFAULTS
from newsflow.creation.feed_costs import binding
from newsflow.publishing.service import PublishingError
from test_top_three_selection import feeds

@pytest.fixture
def ready(feeds,monkeypatch):
    feeds.costs.clock=lambda:100
    feeds.costs.account_scope=lambda:'synthetic-account'
    feeds.costs.cached_quote=lambda selection,scope,pending,account:{
        'currency':'USD','accountScope':account,'expiresAt':200,'binding':scope,
        'upperBoundVerified':True,'bounds':[{**i,'maximumUsd':'0.10'} for i in pending]}
    calls=[]
    def generate(*args,**kw):
        row=feeds.get(identifier)
        assert len(row.options['costs']['reservations'])==len(calls)+1
        calls.append(deepcopy(kw));return len(calls)
    feeds.generation._generate=generate
    monkeypatch.setattr(feeds,'_accept',lambda row,item,out:item.update(status='success',generation_id=out))
    identifier=feeds.create(42,DEFAULTS['image'])
    return feeds,identifier,calls

def approve(service,identifier,limit='0.30'):
    service.cost_review(identifier,service.get(identifier).result['revision'])
    row=service.get(identifier)
    service.cost_review(identifier,row.result['revision'],limit=limit,
        quote_hash=row.options['costs']['quote']['hash'],consent=True)

def test_three_fake_calls_each_has_durable_reservation_before_dispatch(ready):
    s,i,calls=ready;approve(s,i)
    for _ in range(4):s.step(i,consent=True,reviewed=True)
    row=s.get(i)
    assert len(calls)==3 and row.status=='success'
    assert len(row.options['costs']['reservations'])==3
    assert s.costs.view(row)['reservedUsd']=='0.30'
    assert not s.costs.view(row)['billingVerified']

@pytest.mark.parametrize('limit',['0.29','0','NaN','Infinity','-1','1001'])
def test_invalid_or_insufficient_budget_cannot_dispatch(ready,limit):
    s,i,calls=ready
    with pytest.raises(PublishingError):approve(s,i,limit)
    with pytest.raises(PublishingError):s.step(i,consent=True,reviewed=True)
    assert not calls

@pytest.mark.parametrize('change',['edit','account','expired','hash','consent'])
def test_modified_scope_expiry_and_explicit_approval(ready,change):
    s,i,calls=ready;approve(s,i)
    if change=='edit':s.change(i,s.get(i).result['revision'],'edit',rank=1,title='Changed',body='New content')
    if change=='account':s.costs.account_scope=lambda:'other-synthetic-account'
    if change=='expired':s.costs.clock=lambda:201
    if change=='hash':
        row=s.get(i);opts=deepcopy(row.options);opts['costs']['quote']['bounds'][0]['maximumUsd']='0.01'
        s._save(i,row.result,options=opts)
    with pytest.raises(PublishingError):s.step(i,consent=change!='consent',reviewed=True)
    assert not calls

def test_unknown_never_replays_or_releases_exposure(ready):
    s,i,calls=ready;approve(s,i)
    def fail(*a,**k):calls.append('uncertain');raise TimeoutError()
    s.generation._generate=fail
    s.step(i,consent=True,reviewed=True)
    with pytest.raises(PublishingError):s.step(i,consent=True,reviewed=True)
    with pytest.raises(PublishingError):s.cost_review(i,s.get(i).result['revision'])
    assert calls==['uncertain'] and s.costs.view(s.get(i))['reservedUsd']=='0.10'

def test_known_failure_stops_remaining_items(ready,monkeypatch):
    s,i,calls=ready;approve(s,i)
    monkeypatch.setattr(s,'_accept',lambda row,item,out:item.update(status='failed',generation_id=out))
    s.step(i,consent=True,reviewed=True)
    with pytest.raises(PublishingError):s.step(i,consent=True,reviewed=True)
    assert len(calls)==1 and s.costs.view(s.get(i))['reservedUsd']=='0.10'

def test_no_quote_does_not_accept_client_price_or_claim_billing(feeds):
    i=feeds.create(42,DEFAULTS['image']);feeds.cost_review(i,1)
    v=feeds.view(i)
    assert not v['canGenerate'] and v['costReview']['remainingMaximumUsd'] is None
    assert v['costReview']['billingVerified'] is False
    with pytest.raises(PublishingError):feeds.cost_review(i,v['revision'],limit='999',quote_hash='x',consent=True)

def test_local_route_has_csrf_and_cannot_open_submit(app,feeds):
    from starlette.testclient import TestClient
    from bat_distribution.operation import OperatingRequests
    i=feeds.create(42,DEFAULTS['image'])
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1:18779') as c:
        c.get('/studio/images');csrf=c.cookies.get('newsflow_csrf')
        path=f'/api/feed-batches/{i}/cost-review'
        assert c.post(path,data={'revision':1,'csrf_token':'bad'}).status_code==403
        assert c.post(path,data={'revision':1,'csrf_token':csrf}).status_code==200
        assert c.post(path,data={'revision':1,'csrf_token':csrf}).status_code==409
        assert c.post(f'/api/feed-batches/{i}/step',data={'csrf_token':csrf,'consent':'true','reviewed':'true'}).status_code==403

def test_fresh_quotes_keep_prior_exposure_and_require_new_consent(ready,monkeypatch):
    s,i,calls=ready;approve(s,i)
    monkeypatch.setattr(s,'_accept',lambda row,item,out:item.update(status='failed',generation_id=out))
    s.step(i,consent=True,reviewed=True)
    s.change(i,s.get(i).result['revision'],'regenerate',rank=1,consent=True,reviewed=True)
    with pytest.raises(PublishingError):s.step(i,consent=True,reviewed=True)
    with pytest.raises(PublishingError):approve(s,i,'0.30')
    approve(s,i,'0.40')
    assert s.costs.view(s.get(i))['reservedUsd']=='0.10'


def test_repeated_approval_does_not_double_count_reserved_image(ready):
    s,i,calls=ready;approve(s,i)
    s.step(i,consent=True,reviewed=True)
    row=s.get(i)
    assert s.costs.view(row)['remainingMaximumUsd']=='0.20'
    s.cost_review(i,row.result['revision'],limit='0.30',quote_hash=row.options['costs']['quote']['hash'],consent=True)
    s.step(i,consent=True,reviewed=True)
    assert len(calls)==2 and s.costs.view(s.get(i))['reservedUsd']=='0.20'
