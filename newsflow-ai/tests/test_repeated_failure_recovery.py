from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from newsflow.db.models import AppSetting, IntelligenceRun
from newsflow.gui.curation_routes import _once
from newsflow.intelligence.service import IntelligenceError
from newsflow.news.analysis_candidates import shortlist
from newsflow.character.scene_identity import resolve_scene_identity
from newsflow.character.schema import CharacterError
from newsflow.character.episode_story import EpisodeScript, SCRIPT_INSTRUCTION
from newsflow.character.episode_recovery import recover
from test_character_story_preflight import episode
from test_episode_saved_candidate import capped_budget
from test_character_episode_schema import script


@pytest.mark.parametrize('name',['몽실','느긋해 대리'])
def test_only_selected_proper_name_is_resolved(name):
    original=script();original['scenes'][0]['action']=name+' picks up a tool.'
    original['scenes'][0]['camera']='Close-up on '+name
    fixed=resolve_scene_identity(original,{'name_ko':name})
    assert EpisodeScript.model_validate(fixed).scenes[0].action=='the character picks up a tool.'
    assert original['scenes'][0]['action'].startswith(name)
    assert fixed['title']==original['title'] and fixed['scenes'][0]['seconds']==original['scenes'][0]['seconds']
    assert resolve_scene_identity(original,{'name_ko':'다른 이름'})==original
    assert 'never the Korean character name' in SCRIPT_INSTRUCTION


@pytest.mark.parametrize('text',['몽실이가 walks','몽실 jumps 그리고 웃는다','다른 캐릭터 walks'])
def test_no_general_korean_stripping_or_validation_relaxation(text):
    value=script();value['scenes'][0]['action']=text
    with pytest.raises(ValueError):EpisodeScript.model_validate(resolve_scene_identity(value,{'name_ko':'몽실'}))


def test_paid_response_with_name_is_used_once_and_original_retained(tmp_path):
    service,authoring,adapter,identifier=episode(tmp_path,None,capped_budget())
    adapter.candidate['scenes'][0]['action']='별 picks up a tool.'
    service.write(identifier,consent=True)
    job=service.read(identifier)
    assert job['state']=='script_review' and job['script']['scenes'][0]['action']=='the character picks up a tool.'
    raw=service.folder(identifier)/job['script_responses'][0]['file']
    assert json.loads(raw.read_bytes())['candidate']['scenes'][0]['action']=='별 picks up a tool.'
    assert len(adapter.bodies)==1
    job.update(state='script_failed',script=None,scenes=[],script_failure={'failure_stage':'schema'})
    service.save(job)
    before=raw.read_bytes();costs=deepcopy(job['text_reservations'])
    recover(service,identifier,consent=True)
    assert len(adapter.bodies)==1 and raw.read_bytes()==before
    assert service.read(identifier)['text_reservations']==costs
    assert service.read(identifier)['script_recovery']['identity_normalized']


def test_shortlist_bounds_all_categories_without_mutating_articles():
    from newsflow.news.ranking import CATEGORIES
    rows=[SimpleNamespace(id=n*100+i,category=c,published_at=None) for n,c in enumerate((*CATEGORIES,'other')) for i in range(70)]
    chosen,info=shortlist(rows)
    assert len(chosen)==270 and len(rows)==630
    assert all(x['selected']==30 for x in info['categories'])
    assert info['strategy']=='latest_per_category'
    assert [a.id for a in chosen]==[a.id for a in shortlist(list(reversed(rows)))[0]]


def test_preflight_retry_keeps_history_and_success_is_reused(app):
    request=SimpleNamespace(app=app);calls=[]
    def fail(remember):
        calls.append('preflight');raise IntelligenceError('too many','invalid_selection',False)
    with pytest.raises(IntelligenceError):_once(request,['analysis','synthetic'],fail,retry_preflight=True)
    def good(remember):calls.append('send');return {'run_id':123}
    assert _once(request,['analysis','synthetic'],good,retry_preflight=True)['run_id']==123
    assert _once(request,['analysis','synthetic'],good,retry_preflight=True)['run_id']==123
    assert calls==['preflight','send']
    with app.state.sessions() as session:
        record=json.loads(session.scalar(select(AppSetting).where(AppSetting.key.like('curation_once:%'))).value)
    assert record['history']==[{'status':'failed'}]


@pytest.mark.parametrize('status,dispatch,allowed',[('failed','not_sent',True),('failed','sent_or_unknown',False),('running','not_sent',False),('failed',None,False)])
def test_retry_requires_definite_no_dispatch(app,status,dispatch,allowed):
    request=SimpleNamespace(app=app)
    def first(remember):
        with app.state.sessions.begin() as session:
            row=IntelligenceRun(kind='analysis',provider='claude_api',status=status,message='Synthetic failure',options={},evidence={},result={'dispatch_state':dispatch} if dispatch else {})
            session.add(row);session.flush();identifier=row.id
        remember(identifier)
        raise IntelligenceError('failed','ai_failed',False)
    with pytest.raises(IntelligenceError):_once(request,['analysis','synthetic'],first,retry_preflight=True)
    calls=[]
    def second(remember):calls.append(1);return {'run_id':321}
    if allowed:assert _once(request,['analysis','synthetic'],second,retry_preflight=True)['run_id']==321
    else:
        with pytest.raises(HTTPException):_once(request,['analysis','synthetic'],second,retry_preflight=True)
    assert len(calls)==int(allowed)
