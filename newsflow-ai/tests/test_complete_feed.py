from copy import deepcopy
from io import BytesIO
from hashlib import sha256
import pytest
from PIL import Image
from newsflow.db.models import AppSetting
from newsflow.creation.complete_feed import STYLE, plan, reference
from newsflow.creation.catalog import DEFAULTS
from newsflow.creation.top_three_feeds import prompt_for
from newsflow.publishing.service import PublishingError
from test_top_three_selection import feeds
from test_feed_budget import budget_setup, step

def settings(b,limit='3',approved=True):
    with b.service.sessions.begin() as s:
        for key,val in {'ai_approved_at':'2026-11-03T00:00:00+00:00' if approved else '', 'api_openai_request_limit_usd':limit}.items():
            row=s.get(AppSetting,key)
            if row:row.value=val
            else:s.add(AppSetting(key=key,value=val))

def complete(b):
    row=b.service.get(b.id);result=deepcopy(row.result)
    for item,source in zip(result['items'],row.evidence['sources']):item['creative_plan']=plan(source,item['content'])
    b.service._save(b.id,result,options={**row.options,'feed_style':STYLE})

def test_complete_style_generated_with_copy_and_no_local_overlay(budget_setup,monkeypatch):
    b=budget_setup;settings(b);complete(b)
    def forbidden(*a,**k):raise AssertionError('No local post-generation text/layout')
    monkeypatch.setattr('newsflow.creation.feed_art_direction.compose',forbidden)
    for n in range(3):
        r=step(b);assert r.status_code==200,r.text
        assert r.json()['items'][n]['status']=='success'
    assert len(b.calls)==3
    for item,call in zip(b.service.get(b.id).result['items'],b.calls):
        assert 'exact Korean title' in call['prompt'] and 'NO text' not in call['prompt']
        assert item['creative_plan']['headline'] in call['prompt']
        assert 'auto_design' not in item and 'title_header_bottom' not in item

@pytest.mark.parametrize('bad',['not_approved','zero','small','no_consent','no_review','revoked'])
def test_settings_budget_does_not_bypass_gates(budget_setup,bad):
    b=budget_setup;settings(b,'0' if bad=='zero' else '.001' if bad=='small' else '3',bad!='not_approved')
    if bad=='revoked':
        row=b.service.get(b.id);b.service.cost_review(b.id,row.result['revision']);settings(b,'3',False)
        # A settings-derived grant is invalid once revoked, even if its quote remains fresh.
    r=b.post('step',{'consent':str(bad!='no_consent').lower(),'reviewed':str(bad!='no_review').lower()})
    assert r.status_code in (403,422),r.text
    assert not b.calls

def test_complete_edit_keeps_original_and_other_results_and_uses_exact_reference(budget_setup):
    b=budget_setup;settings(b);complete(b)
    for _ in range(3):assert step(b).status_code==200
    s=b.service;row=s.get(b.id);other=deepcopy(row.result['items'][1:]);old=s.path(b.id,1);before=sha256(old.read_bytes()).hexdigest()
    calls=[]
    class Edit:
        def generate(self,prompt,key,*,selection,reference=None):
            assert reference is not None
            assert Image.open(BytesIO(reference)).size==(1080,1350)
            calls.append((prompt,sha256(reference).hexdigest()))
            out=BytesIO();Image.new('RGB',tuple(map(int,selection['size'].split('x'))),(20,40,80)).save(out,'JPEG')
            return out.getvalue(),{'input_tokens':500,'output_tokens':400,'total_tokens':900}
    b.owner.generation.adapter=Edit()
    r=b.post('change',{'revision':row.result['revision'],'action':'design_edit','rank':1,'title':'변경한 합성 제목','body':'계획은 검토 중이다.','accent':'#aabbcc'})
    assert r.status_code==200,r.text
    assert not calls
    r=step(b);assert r.status_code==200,r.text
    assert r.json()['items'][0]['status']=='success',r.text
    assert len(calls)==1 and '#aabbcc' in calls[0][0] and '변경한 합성 제목' in calls[0][0]
    fresh=s.get(b.id)
    assert fresh.result['items'][1:]==other and sha256(old.read_bytes()).hexdigest()==before
    assert fresh.result['items'][0]['history'][0]['sha256']==before
    assert s.path(b.id,1)!=old
    assert s.path(b.id,1,attempt=1)==old
    with pytest.raises(PublishingError):s.path(b.id,1,attempt=999)
    response=b.client.get(f'/api/feed-batches/{b.id}/items/1/file?attempt=1')
    assert response.status_code==200 and sha256(response.content).hexdigest()==before
    assert step(b).status_code==200 and len(calls)==1

def test_edit_reference_tamper_is_preflight_failure_without_paid_request(budget_setup):
    b=budget_setup;settings(b);complete(b)
    for _ in range(3):assert step(b).status_code==200
    s=b.service;row=s.get(b.id)
    s.change(b.id,row.result['revision'],'design_edit',rank=1,title='합성 제목',body='검토 중',accent='#aabbcc')
    row=s.get(b.id);old=row.result['items'][0]['creative_plan']['reference']
    path=s.root/old['filename'];path.write_bytes(b'changed fake file')
    before=len(b.calls)
    with pytest.raises(PublishingError,match='원본'):s.step(b.id,consent=True,reviewed=True)
    assert len(b.calls)==before and s.get(b.id).result['items'][0]['status']=='pending'

def test_view_and_input_preparation_never_call_provider(budget_setup):
    b=budget_setup;settings(b);complete(b)
    for _ in range(3):b.service.view(b.id)
    assert not b.calls and 'costs' not in b.service.get(b.id).options

def test_settings_budget_stops_on_unknown_without_retry(budget_setup):
    b=budget_setup;settings(b);b.response['error']=TimeoutError('fake')
    assert step(b).status_code==200 and len(b.calls)==1
    assert step(b).status_code==422 and len(b.calls)==1

def test_complete_new_job_frozen_plan(feeds):
    i=feeds.create(42,DEFAULTS['image'],feed_style=STYLE)
    row=feeds.get(i)
    assert all(x['creative_plan']['version']==STYLE for x in row.result['items'])
    assert all(x['creative_plan']['accent']=='#ffb45c' for x in row.result['items'])

def test_new_complete_style_preserves_existing_news_batch(feeds):
    old=feeds.create(42,DEFAULTS['image'],feed_style='photo_feed_v1')
    before=deepcopy(feeds.get(old).result)
    new=feeds.create(42,DEFAULTS['image'],feed_style=STYLE)
    assert new!=old and feeds.get(old).result==before
    assert feeds.create(42,DEFAULTS['image'],feed_style=STYLE)==new
