"""Production wiring with synthetic profile, Fake DPAPI and Fake image provider."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from io import BytesIO
import json
from types import SimpleNamespace
import pytest
from PIL import Image
from starlette.testclient import TestClient
from newsflow.creation.catalog import DEFAULTS,IMAGE_MODELS,save_defaults
from newsflow.creation.feed_budget import FeedBudget
from newsflow.creation.feed_readiness import FeedReadiness
from newsflow.creation.image_pricing import VALID_UNTIL
from newsflow.intelligence.credentials import FakeCipher,AIKeyStore,CredentialError
from newsflow.intelligence.provider_connections import ProviderConnections
from newsflow.db.models import AppSetting,utcnow
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.publishing.service import PublishingError
from bat_distribution.operation import OperatingRequests
from bat_distribution.feed_image_access import FeedImageAccess
from test_top_three_selection import feeds

@pytest.fixture
def budget_setup(app,feeds,monkeypatch):
    root=app.state.config.data_dir;cipher=FakeCipher();store=AIKeyStore(root,cipher=cipher)
    secret='synthetic-feed-image-key-123456789';store.save(secret)
    app.state.ai_keys=store
    readiness=FeedReadiness(app.state)
    def metadata(request,*args):
        return json.dumps({'object':'model','id':request.full_url.rsplit('/',1)[-1]}).encode()
    readiness.connections.transport=metadata
    assert readiness.connections.check('openai','image',consent=True)['verified']
    feeds.costs=FeedBudget(readiness)
    calls=[];response={'usage':{'input_tokens':100,'output_tokens':500,'total_tokens':600},'error':None}
    class Adapter:
        def generate(self,prompt,key,*,selection):
            assert key==secret
            row=feeds.get(identifier[0]);state=row.options['costs']
            assert len(state['reservations'])==len(calls)+1
            calls.append({'prompt':prompt,'selection':deepcopy(selection)})
            if response['error']:raise response['error']
            image=Image.new('RGB',tuple(map(int,selection['size'].split('x'))),(45,80,110))
            out=BytesIO();image.save(out,'JPEG');return out.getvalue(),response['usage']
    owner=FeedImageAccess(app,root,lambda:cipher,adapter=Adapter())
    identifier=[feeds.create(42,DEFAULTS['image'])]
    session=LaunchSession(18779);auth=LocalAccess(app,session)
    with TestClient(owner.wrap(OperatingRequests(auth),auth),base_url=session.origin,client=('127.0.0.1',43210),follow_redirects=False) as c:
        c.cookies.set(session.cookie_name,session.claim(session.launch_url().split('#')[1]));c.get('/studio/images')
        headers={'Origin':session.origin};csrf=c.cookies.get('newsflow_csrf')
        def post(suffix,data=None):
            return c.post(f'/api/feed-batches/{identifier[0]}/{suffix}',data={'csrf_token':csrf,**(data or {})},headers=headers)
        yield SimpleNamespace(service=feeds,id=identifier[0],client=c,post=post,owner=owner,store=store,
                              calls=calls,response=response,readiness=readiness,headers=headers,csrf=csrf)

def approve(b,limit='1'):
    s=b.service;i=b.id
    r=b.post('cost-review',{'revision':s.get(i).result['revision']});assert r.status_code==200,r.text
    q=s.get(i).options['costs']['quote']
    r=b.post('cost-review',{'revision':s.get(i).result['revision'],'limit':limit,'quote_hash':q['hash'],'consent':'true'})
    return r

def step(b):return b.post('step',{'consent':'true','reviewed':'true'})

def test_exact_scope_budget_three_images_and_usage_preserved(budget_setup):
    b=budget_setup;assert approve(b).status_code==200
    for n in range(3):
        r=step(b);assert r.status_code==200,r.text
        assert len(b.calls)==n+1
        assert r.json()['costReview']['basis']=='app_budget_estimate'
        assert not r.json()['costReview']['providerChargeCap']
    row=b.service.get(b.id);assert row.status=='success'
    assert all(b.service.path(b.id,n).is_file() for n in (1,2,3))
    assert all(r['billingStatus']=='usage_calculated' and not r['billingVerified'] for r in row.options['costs']['reservations'])
    assert step(b).status_code==200 and len(b.calls)==3
    with pytest.raises(CredentialError):b.owner.keys.key()
    assert b.post('cost-review',{'revision':row.result['revision'],'limit':'1','quote_hash':row.options['costs']['quote']['hash'],'consent':'true'}).status_code==200
    assert len(b.calls)==3

@pytest.mark.parametrize('bad',['no_approval','small_budget','wrong_hash','bad_csrf','bad_origin','no_consent','no_review','no_session','key_changed','model_changed','expired','rate_expired','tamper_content'])
def test_no_paid_submission_when_scope_or_budget_invalid(budget_setup,bad):
    b=budget_setup
    if bad!='no_approval':
        result=approve(b,'0.01' if bad=='small_budget' else '1')
        assert result.status_code==(422 if bad=='small_budget' else 200)
    if bad=='wrong_hash':
        row=b.service.get(b.id);options=deepcopy(row.options);options['costs']['quote']['bounds'][0]['maximumUsd']='0.001';b.service._save(b.id,row.result,options=options)
    if bad=='key_changed':b.store.save('different-synthetic-feed-key-12345678')
    if bad=='model_changed':save_defaults(b.service.sessions,'image',{**DEFAULTS['image'],'model':IMAGE_MODELS[1]})
    if bad=='expired':b.service.costs.clock=lambda:datetime.now(timezone.utc).timestamp()+3601
    if bad=='rate_expired':b.service.costs.clock=lambda:VALID_UNTIL
    if bad=='tamper_content':
        row=b.service.get(b.id);result=deepcopy(row.result);result['items'][0]['content']['title']='changed';b.service._save(b.id,result)
    if bad=='no_session':b.client.cookies.clear()
    data={'csrf_token':'bad' if bad=='bad_csrf' else b.csrf,'consent':str(bad!='no_consent').lower(),'reviewed':str(bad!='no_review').lower()}
    headers={'Origin':'https://outside.invalid'} if bad=='bad_origin' else b.headers
    r=b.client.post(f'/api/feed-batches/{b.id}/step',data=data,headers=headers)
    assert r.status_code in {403,422},r.text
    assert not b.calls

@pytest.mark.parametrize('problem',['timeout','http_failure','usage_missing','usage_invalid','over_reserve'])
def test_failure_unknown_or_over_plan_stops_next_image(budget_setup,problem):
    from newsflow.publishing.image_generation import ImageGenerationError
    b=budget_setup;assert approve(b).status_code==200
    if problem=='timeout':b.response['error']=TimeoutError('synthetic')
    if problem=='http_failure':b.response['error']=ImageGenerationError('http',uncertain=False,http_status=400)
    if problem=='usage_missing':b.response['usage']=None
    if problem=='usage_invalid':b.response['usage']={'input_tokens':True,'output_tokens':2,'total_tokens':3}
    if problem=='over_reserve':b.response['usage']={'input_tokens':100,'output_tokens':500000,'total_tokens':500100}
    r=step(b);assert r.status_code==200,r.text
    assert not r.json()['canGenerate'] and r.json()['costReview']['stopReason']
    assert step(b).status_code==422 and len(b.calls)==1
    row=b.service.get(b.id);assert row.result['items'][1]['status']=='pending'
    assert len(row.options['costs']['reservations'])==1
    if problem=='over_reserve':assert Decimal(b.service.view(b.id)['costReview']['reservedUsd'])>Decimal('1')

def test_status_refresh_never_calls_provider_or_revokes_approval(budget_setup):
    b=budget_setup;assert approve(b).status_code==200;row=b.service.get(b.id)
    before=deepcopy(row.options)
    for _ in range(2):
        r=b.client.get(f'/api/feed-batches/{b.id}/cost-review');assert r.status_code==200
        assert r.json()['costReview']['approved']
    assert b.service.get(b.id).options==before and not b.calls

def test_other_generation_paths_and_direct_key_use_stay_closed(budget_setup):
    b=budget_setup
    for path in ['/news/curation/generate','/api/feed-batches/1/step/','/api/image-studio/generate']:
        assert b.client.post(path,data={'csrf_token':b.csrf},headers=b.headers).status_code==403
    with pytest.raises(CredentialError):b.owner.generation._generate(1,42,1,'full_card',{},'test')
    assert not b.calls


def test_direct_images_wire_matches_budget_selection(budget_setup):
    import base64
    from newsflow.publishing.image_generation import OpenAIImageAdapter
    b=budget_setup;assert approve(b).status_code==200
    requests=[]
    class Opener:
        def open(self,request,timeout):
            data=json.loads(request.data);requests.append(data)
            assert request.full_url=='https://api.openai.com/v1/images/generations'
            assert request.method=='POST' and timeout==180 and data['n']==1
            selected=b.service.get(b.id).options['selection']
            assert all(data[k]==selected[k] for k in ('model','size','quality'))
            assert 'image' not in data and 'max_cost' not in data
            raw=BytesIO();Image.new('RGB',tuple(map(int,data['size'].split('x')))).save(raw,'JPEG')
            return BytesIO(json.dumps({'data':[{'b64_json':base64.b64encode(raw.getvalue()).decode()}],
                                     'usage':b.response['usage']}).encode())
    b.owner.generation.adapter=OpenAIImageAdapter(Opener())
    assert step(b).status_code==200 and len(requests)==1
    assert b.service.get(b.id).result['items'][0]['status']=='success'


def test_saved_result_recovers_budget_after_interrupted_accept(budget_setup,monkeypatch):
    b=budget_setup;assert approve(b).status_code==200
    accept=b.service._accept
    def interrupted(*args):raise OSError('synthetic interrupted local save')
    monkeypatch.setattr(b.service,'_accept',interrupted)
    assert step(b).status_code==200 and len(b.calls)==1
    row=b.service.get(b.id);assert row.result['items'][0]['status']=='unknown'
    monkeypatch.setattr(b.service,'_accept',accept)
    b.service.change(b.id,row.result['revision'],'recover')
    row=b.service.get(b.id)
    assert row.result['items'][0]['status']=='success'
    assert row.options['costs']['reservations'][0]['billingStatus']=='usage_calculated'
    assert b.service.view(b.id)['canGenerate'] and len(b.calls)==1
