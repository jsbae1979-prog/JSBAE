"""Same-call feed copy, frozen originals and exact design instructions; Fake only."""
from copy import deepcopy
from hashlib import sha256
import json
import pytest
from newsflow.intelligence.curation import enrich, validate_ranking, ranking_model, CurationValidationError
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.provider import Options, OpenAIProvider
from newsflow.intelligence.feed_copy import FeedCopy, INSTRUCTION
from newsflow.creation.complete_feed import plan, request_prompt, STYLE
from newsflow.creation.top_three_feeds import content_for
from newsflow.creation.catalog import DEFAULTS
from newsflow.publishing.image_selection import selection
from newsflow.db.models import IntelligenceRun
from test_google_news_trends import article, NOW, CuratorResponse, no_external_calls, prepared
from test_global_news_policy import GlobalAI
from curation_wire_fixture import wire_output
from image_selection_fixture import selected
from test_top_three_selection import feeds
from test_feed_budget import budget_setup, step
from test_complete_feed import settings


def evidence(global_policy=False, enabled=True):
    articles=[{**article(), 'id':i, 'title':f'합성 연구소 {i} 계획 검토',
               'summary':f'연구소 {i}는 계획을 검토 중이며 도입은 확정되지 않았다.'} for i in (1,2,3,4)]
    snapshot={'collection_policy':'global_trends_v1'} if global_policy else None
    return enrich({'articles':articles,'groups':[[i] for i in (1,2,3,4)]},snapshot,NOW,top_k=3,feed_copy=enabled)


def output(e):
    fake=(GlobalAI if e['curation_contract']['profile'].startswith('global') else CuratorResponse)('claude_api')
    data=fake.analyze(e,Options())
    if e['curation_contract']['profile'].startswith('global'):
        for item in data['ranking']:
            item['components']['exposure_frequency']=None
            item['score']=round(sum(v or 0 for v in item['components'].values())*100/120)
    return data


@pytest.mark.parametrize('global_policy',[False,True])
def test_new_contract_required_and_originals_immutable(global_policy):
    e=evidence(global_policy);before=deepcopy(e);data=output(e)
    result=validate_ranking(data,e)
    assert e==before and len(result['ranking'])==3
    for item in result['ranking']:
        original=next(a for a in e['articles'] if a['id']==item['representative_id'])
        assert item['title']==original['title'] and item['feed_copy']['title']!=item['title']
    del data['ranking'][0]['feed_copy']
    with pytest.raises(CurationValidationError):validate_ranking(data,e)
    old=evidence(global_policy,False)
    assert 'feed_copy_version' not in old['curation_contract']
    assert all('feed_copy' not in i for i in validate_ranking(output(old),old)['ranking'])


@pytest.mark.parametrize('mode',['claude','openai'])
def test_same_single_request_contains_copy_and_returns_it(mode):
    e=evidence();data=output(e);calls=[]
    if mode=='claude':
        provider=AnthropicProvider(lambda:'fake')
        def post(body,options):
            calls.append(body)
            return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(wire_output(data))}]}
        provider._post=post
    else:
        provider=OpenAIProvider(lambda:'fake')
        def request(instruction,payload,options):
            calls.append(payload);return deepcopy(data)
        provider.request=request
    result=validate_ranking(provider.analyze(e,Options()),e)
    assert len(calls)==1 and result['ranking'][0]['feed_copy']==data['ranking'][0]['feed_copy']
    wire=json.dumps(calls[0],ensure_ascii=False)
    assert 'feed_copy_version' in wire and 'Do not copy the original title' in wire
    if mode=='claude':
        schema=calls[0]['output_config']['format']['schema']
        def walk(node):
            if isinstance(node,dict):
                assert not set(node)&{'pattern','minLength','maxLength','minimum','maximum','maxItems'}
                assert node.get('minItems',0)<=1
                for v in node.values():walk(v)
            elif isinstance(node,list):
                for v in node:walk(v)
        walk(schema)
        assert 'feed_copy' in str(schema)


@pytest.mark.parametrize('field,value',[('title','오류 999999'),('description','오류 999999'),('title',' '),('description','가'*141)])
def test_invalid_copy_never_silently_truncated(field,value):
    e=evidence();data=output(e);data['ranking'][0]['feed_copy'][field]=value
    with pytest.raises(CurationValidationError):validate_ranking(data,e)


@pytest.mark.parametrize('prepared',['claude_api','openai'],indirect=True)
def test_service_saves_copy_with_one_analysis_and_no_script(client,app,prepared):
    svc,fake,mode,options,ids=prepared
    run=svc.analyze(ids,mode,True,options,curate=True,curation_top_k=3)
    assert fake.calls==['analysis']
    assert fake.payloads[0]['curation_contract']['feed_copy_version']==1
    with app.state.sessions() as session:
        from sqlalchemy import select
        rows=list(session.scalars(select(IntelligenceRun).where(IntelligenceRun.kind=='analysis')))
        assert len(rows)==1 and rows[0].status=='success'
        assert rows[0].result['ranking'][0]['feed_copy']['title']
    assert fake.calls==['analysis']


def test_selection_keeps_original_script_but_uses_feed_copy_for_image(app,selected):
    identifier,ids,draft_id=selected
    with app.state.sessions.begin() as session:
        row=session.get(IntelligenceRun,identifier);data=deepcopy(row.result)
        for item in data['ranking']:
            item['feed_copy']={'title':f"피드 제목 {item['rank']}",'description':f"핵심 사실 {item['rank']}"}
        row.result=data
    with app.state.sessions() as session:
        before=deepcopy(session.get(IntelligenceRun,identifier).result)
        items=selection(session,identifier)['items']
        assert items[0]['title']=='기존 릴스 대본 제목'
        for item in items:
            copy=content_for(item)
            assert copy['title']==item['feed_copy']['title']
            assert copy['body']==item['feed_copy']['description']
        assert session.get(IntelligenceRun,identifier).result==before


@pytest.mark.parametrize('feeds',['analysis_feed_copy'],indirect=True)
def test_exact_copy_dark_design_and_manual_override(budget_setup):
    b=budget_setup;settings(b);row=b.service.get(b.id)
    evidence_copy=deepcopy(row.evidence);result=deepcopy(row.result)
    for item,source in zip(result['items'],evidence_copy['sources']):
        item['content']=content_for(source);item['creative_plan']=plan(source,item['content'])
    b.service._save(b.id,result,options={**row.options,'feed_style':STYLE})
    for _ in range(3):b.service.view(b.id)
    assert not b.calls
    for _ in range(3):assert step(b).status_code==200
    assert len(b.calls)==3
    for call,source in zip(b.calls,evidence_copy['sources']):
        text=call['prompt'];assert 'navy/charcoal' in text and 'white type and warm orange' in text
        assert 'lower third' in text and 'Do NOT rewrite' in text
        assert json.dumps(source['feed_copy']['title'],ensure_ascii=False) in text
    row=b.service.get(b.id);other=deepcopy(row.result['items'][1:]);old=b.service.path(b.id,1)
    digest=sha256(old.read_bytes()).hexdigest()
    response=b.post('change',{'revision':row.result['revision'],'action':'design_edit','rank':1,
        'title':'직접 수정한 제목','body':'직접 수정한 설명','accent':'#ff5500'})
    assert response.status_code==200,response.text
    fresh=b.service.get(b.id);p=fresh.result['items'][0]['creative_plan']
    assert p['headline']=='직접 수정한 제목' and p['key_fact']=='직접 수정한 설명'
    assert p['copy_mode']=='exact_user_copy' and p['editorial_revision']==4
    assert fresh.result['items'][1:]==other and len(b.calls)==3
    assert sha256(old.read_bytes()).hexdigest()==digest and fresh.evidence==evidence_copy
