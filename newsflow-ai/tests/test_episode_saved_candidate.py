from copy import deepcopy
import json
import pytest
from newsflow.character.episode_story import character_limits, script_input, SCRIPT_INSTRUCTION, EpisodeScript
from newsflow.character.episode_recovery import preview, recover
from newsflow.character.schema import CharacterError
from newsflow.character.kling import O3
from newsflow.video_models.catalog import CATALOG
from test_character_story_preflight import episode
from test_character_authoring_v3 import Budget
from test_character_episode_schema import profile
from test_character_automation_routes import gui


def capped_budget():
    budget=Budget();original=budget.reserve
    def reserve(**kwargs):
        row=original(**kwargs);row.reserved_usd='0.252';return row
    budget.reserve=reserve
    return budget


def failed(root):
    budget=Budget();orig=budget.reserve
    def reserve(**kwargs):
        row=orig(**kwargs);row.reserved_usd='0.252';return row
    budget.reserve=reserve
    service,authoring,adapter,identifier=episode(root,None,budget)
    adapter.candidate['scenes'][0]['camera']='C'*121
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    return service,authoring,adapter,budget,identifier


def test_character_limits_derive_from_unchanged_local_schema_without_image_input():
    limits=character_limits()
    assert limits['scene']['action']==300 and limits['scene']['camera']==120
    assert limits['plan']['situation']==150 and limits['upload']['title']==60
    payload=script_input(profile(),'정원',15,CATALOG.model(O3),True)
    assert payload['character_limits']==limits
    assert 'Unicode characters' in SCRIPT_INSTRUCTION and '<=220' in SCRIPT_INSTRUCTION and '<=80' in SCRIPT_INSTRUCTION
    assert 'appearance' not in payload['character'] and 'image' not in payload


def test_failed_complete_candidate_is_saved_before_validation_and_can_be_edited_locally(tmp_path):
    service,authoring,adapter,budget,identifier=failed(tmp_path)
    job=service.read(identifier);receipt=job['script_responses'][0]
    path=service.folder(identifier)/receipt['file'];original=path.read_bytes()
    assert job['response_received'] and json.loads(original)['candidate']==adapter.candidate
    state=preview(service,identifier);assert state['additionalProviderCalls']==0
    costs=deepcopy(budget.finished);job_before=(service.folder(identifier)/'jobs.json').read_bytes()
    with pytest.raises(ValueError):recover(service,identifier,consent=True)
    assert (service.folder(identifier)/'jobs.json').read_bytes()==job_before
    edited=deepcopy(state['candidate']);edited['scenes'][0]['camera']='Slow close-up'
    recover(service,identifier,consent=True,script=edited,expected_hash=state['expected_hash'])
    done=service.read(identifier)
    assert done['state']=='script_review' and done['script']['scenes'][0]['camera']=='Slow close-up'
    assert done['script_recovery']['provider_calls']==0 and done['script_recovery']['previous_failure']
    assert done['text_reservations']==job['text_reservations'] and budget.finished==costs
    assert len(adapter.bodies)==1 and path.read_bytes()==original
    assert done['script_hash'] and done['plan_hash']
    with pytest.raises(CharacterError):recover(service,identifier,consent=True)
    assert len(adapter.bodies)==1


@pytest.mark.parametrize('change',['file','topic','profile','reference','provider','attempt','model','cap','not_received'])
def test_tampered_or_stale_saved_response_cannot_be_recovered(tmp_path,change):
    service,authoring,adapter,budget,identifier=failed(tmp_path)
    state=preview(service,identifier);job=service.read(identifier)
    if change=='file':
        path=service.folder(identifier)/job['script_responses'][0]['file'];path.write_bytes(path.read_bytes()+b' ')
    elif change=='reference':(service.folder(identifier)/'reference.png').write_bytes(b'changed')
    else:
        if change=='topic':job['topic']='다른 이야기'
        elif change=='profile':job['character']['name_ko']='다른 캐릭터'
        elif change=='provider':job['script_provider']='openai'
        elif change=='attempt':job['script_attempts']=2
        elif change=='model':job['studio_selection']['script_model']='claude-haiku-4-5-20251001'
        elif change=='cap':job['episode_limit']='6'
        else:job['response_received']=False
        service.save(job)
    before=(service.folder(identifier)/'jobs.json').read_bytes()
    with pytest.raises((CharacterError,ValueError,OSError)):
        recover(service,identifier,consent=True,script=state['candidate'],expected_hash=state['expected_hash'])
    assert (service.folder(identifier)/'jobs.json').read_bytes()==before and len(adapter.bodies)==1


@pytest.mark.parametrize('change',['consent','hash','still_long','korean','duration'])
def test_local_recovery_requires_consent_hash_and_full_original_validation(tmp_path,change):
    service,authoring,adapter,budget,identifier=failed(tmp_path)
    state=preview(service,identifier);edited=deepcopy(state['candidate']);edited['scenes'][0]['camera']='Close-up'
    if change=='still_long':edited['scenes'][0]['camera']='C'*121
    if change=='korean':edited['scenes'][0]['action']='토끼 walks.'
    if change=='duration':edited['scenes'][0]['seconds']=3
    before=(service.folder(identifier)/'jobs.json').read_bytes()
    with pytest.raises((CharacterError,ValueError)):
        recover(service,identifier,consent=change!='consent',script=edited,
                expected_hash='0'*64 if change=='hash' else state['expected_hash'])
    assert (service.folder(identifier)/'jobs.json').read_bytes()==before and len(adapter.bodies)==1


def test_no_complete_response_or_storage_failure_never_invents_a_saved_candidate(tmp_path,monkeypatch):
    service,authoring,adapter,identifier=episode(tmp_path,None,capped_budget());adapter.fail=True
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    assert not service.read(identifier).get('script_responses')
    with pytest.raises(CharacterError):preview(service,identifier)
    service,authoring,adapter,identifier=episode(tmp_path,None,capped_budget());adapter.candidate['scenes'][0]['camera']='C'*121
    monkeypatch.setattr('newsflow.character.story_response.persist_candidate',lambda *a,**k:(_ for _ in ()).throw(OSError()))
    with pytest.raises(CharacterError):service.write(identifier,consent=True)
    assert service.read(identifier)['script_evidence_error']=='write_unavailable'
    assert not service.read(identifier).get('script_responses') and len(adapter.bodies)==1


def test_successful_response_is_retained_and_readonly_preview_requires_failed_owned_job(tmp_path):
    service,authoring,adapter,identifier=episode(tmp_path,None,capped_budget())
    service.write(identifier,consent=True)
    assert service.read(identifier)['script_responses']
    with pytest.raises(CharacterError):preview(service,identifier)
    assert len(adapter.bodies)==1


def test_recovery_http_contract_preserves_csrf_origin_and_never_calls_provider(gui):
    service,authoring,adapter,budget,identifier=failed(gui.root)
    gui.app.state.character=service
    get=f'/api/studio/characters/{identifier}/story-response';post=f'/api/studio/characters/{identifier}/recover-story'
    state=gui.client.get(get);assert state.status_code==200
    state=state.json();edited=state['candidate'];edited['scenes'][0]['camera']='Slow close-up'
    values={'consent':'true','script':json.dumps(edited),'expected_hash':state['expected_hash']}
    assert gui.client.post(post,data=values).status_code==403
    assert gui.client.post(post,data={**values,'csrf_token':gui.client.cookies.get('newsflow_csrf')},headers={'Origin':'https://outside.invalid'}).status_code==403
    response=gui.post(post,**values)
    assert response.status_code==200 and response.json()['additionalProviderCalls']==0
    assert len(adapter.bodies)==1
