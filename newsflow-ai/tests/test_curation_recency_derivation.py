from copy import deepcopy
from datetime import timedelta
import json
import pytest
from sqlalchemy import select
from conftest import csrf
from curation_wire_fixture import wire_output
from test_google_news_trends import article,NOW,CuratorResponse,no_external_calls,prepared
from newsflow.intelligence.curation import enrich,validate_ranking,CurationValidationError
from newsflow.intelligence.curation_wire import decode,SCORE_DERIVATION
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.provider import Options
from newsflow.news.curator import Curator
from newsflow.db.models import IntelligenceRun

def example():
    rows=[{**article(),'id':i,'summary':'연구 계획 설명','published_at':(NOW-timedelta(hours=h)).isoformat()} for i,h in [(1,2),(2,30),(3,4)]]
    rows[1]['summary']='연구 계획의 적용 범위와 검토 과정을 자세하게 설명한 자료입니다.'
    e=enrich({'articles':rows,'groups':[[1,2],[3]]},None,NOW,top_k=3)
    wire=wire_output(CuratorResponse('claude_api').analyze(e,Options()))
    return e,wire

def activate(e,wire):
    e['curation_contract']['score_derivation']=dict(SCORE_DERIVATION)
    for item in wire['ranking']:item['components'].pop('recency')

def test_old_mismatch_reproduces_and_new_contract_uses_same_representative():
    e,wire=example();wire['ranking'][0]['components']['recency']=20
    with pytest.raises(CurationValidationError) as err:validate_ranking(decode(wire,e),e)
    assert err.value.failure_reason=='curation_recency'
    activate(e,wire);before=deepcopy((e,wire))
    result=validate_ranking(decode(wire,e),e)
    grouped=next(i for i in result['ranking'] if i['article_ids']==[1,2])
    assert grouped['representative_id']==2 and grouped['components']['recency']==10
    assert grouped['score']==sum(v or 0 for v in grouped['components'].values())
    assert [i['score'] for i in result['ranking']]==sorted([i['score'] for i in result['ranking']],reverse=True)
    assert (e,wire)==before

@pytest.mark.parametrize('stored',[None,0,4,10,16,20])
def test_uses_frozen_score_not_current_clock_and_preserves_unknown(stored):
    e,wire=example();activate(e,wire)
    e['articles'][1]['curation_recency']=stored
    result=validate_ranking(decode(wire,e),e)
    row=next(i for i in result['ranking'] if i['representative_id']==2)
    assert row['components']['recency'] is stored
    assert row['assessed_max']==(80 if stored is None else 100)

def test_tie_break_lowest_id_and_extra_generated_recency_rejected():
    e,wire=example();e['articles'][1]['summary']=e['articles'][0]['summary'];activate(e,wire)
    result=validate_ranking(decode(wire,e),e)
    assert next(i for i in result['ranking'] if i['article_ids']==[1,2])['representative_id']==1
    wire['ranking'][0]['components']['recency']=20
    with pytest.raises(CurationValidationError):decode(wire,e)

@pytest.mark.parametrize('defect',['missing','invalid_component','foreign_number'])
def test_other_validation_is_not_relaxed(defect):
    e,wire=example();activate(e,wire)
    if defect=='missing':wire['article_groups'].pop()
    elif defect=='invalid_component':wire['ranking'][0]['components']['impact']=21
    else:wire['ranking'][0]['summary']='검증되지 않은 수치 999999'
    with pytest.raises(CurationValidationError):validate_ranking(decode(wire,e),e)

def test_actual_claude_schema_omits_recency_and_roundtrips_once():
    e,wire=example();activate(e,wire);calls=[]
    provider=AnthropicProvider(lambda:pytest.fail('No real key'))
    def fake(body,options):
        calls.append(body)
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(wire)}]}
    provider._post=fake
    result=validate_ranking(provider.analyze(e,Options()),e)
    assert len(calls)==1 and len(result['ranking'])==2
    schema=calls[0]['output_config']['format']['schema']
    component=next(d for d in schema['$defs'].values() if 'public_interest' in d.get('properties',{}))
    assert 'recency' not in component['properties'] and 'recency' not in component['required']
    assert 'do NOT return components.recency' in calls[0]['system']
    transmitted=json.loads(calls[0]['messages'][0]['content'])['evidence']
    assert transmitted['articles'][1]['curation_recency']==10

@pytest.mark.parametrize('prepared',['claude_api'],indirect=True)
def test_service_enables_contract_and_saves_result_with_one_mock_request(client,app,prepared):
    svc,_,_,_,_=prepared;seen=[]
    adapter=AnthropicProvider(lambda:pytest.fail('No real key'))
    def post(body,options):
        seen.append(body)
        evidence=json.loads(body['messages'][0]['content'])['evidence']
        assert evidence['curation_contract']['score_derivation']['recency']=='representative_evidence_v1'
        output=wire_output(CuratorResponse('claude_api').analyze(evidence,Options()))
        for row in output['ranking']:row['components'].pop('recency')
        return {'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(output)}]}
    adapter._post=post;svc.api_providers['claude_api']=adapter
    ctx=Curator(app.state.coordinator).context()
    response=client.post('/news/curation/analyze',data={'csrf_token':csrf(client),'consent':'true','collection_context_id':ctx['run_id']})
    assert response.status_code==200,response.text
    assert len(seen)==1
    with app.state.sessions() as db:
        run=db.scalar(select(IntelligenceRun).where(IntelligenceRun.kind=='analysis'))
        assert run.status=='success'
        assert run.evidence['curation_contract']['score_derivation']['recency']=='representative_evidence_v1'
        assert len(run.result['ranking'])>0
