"""Finite schema diagnostics for explicitly approved retries; no raw model output escapes."""
from copy import deepcopy
import json

import pytest
from pydantic import ValidationError

from newsflow.character.episode_story import (EpisodeScript, validate_episode, validation_feedback,
    bounded_validation_feedback)
from newsflow.character.kling import O3
from newsflow.character.schema import CharacterError
from newsflow.video_models.catalog import CATALOG
from test_character_authoring_v3 import build
from test_character_episode_automation import setup_episode
from test_character_episode_schema import script


def bounded_authoring(value):
    authoring, adapter, budget = build('claude_api', value)
    original = budget.reserve
    def reserve(**kwargs):
        result = original(**kwargs)
        result.reserved_usd = '0.25'
        return result
    budget.reserve = reserve
    return authoring, adapter, budget


def test_unknown_field_names_error_context_and_input_are_never_returned():
    value = script()
    value['scenes'][0]['action'] = 'PRIVATE-SYNTHETIC-RESPONSE-' * 20
    value['PRIVATE-SYNTHETIC-KEY-FIELD'] = 'PRIVATE-SYNTHETIC-TOKEN'
    with pytest.raises(ValidationError) as failed:
        EpisodeScript.model_validate(value)
    feedback = validation_feedback(failed.value)
    assert {'field':['scenes',0,'action'],'type':'string_too_long'} in feedback
    assert {'field':['unknown_field'],'type':'extra_forbidden'} in feedback
    wire = json.dumps(feedback)
    assert not any(word in wire for word in ('PRIVATE', 'input', 'message', 'ctx', 'url'))
    assert all(set(row) == {'field','type'} for row in feedback)
    assert bounded_validation_feedback([{'field':['PRIVATE-FIELD',999], 'type':'PRIVATE-ERROR',
        'message':'PRIVATE'}]) == [{'field':['unknown_field','index'],'type':'invalid_value'}]


def test_schema_failure_is_stored_safely_and_sent_only_on_next_explicit_request(tmp_path):
    service, video, identifier, _, _ = setup_episode(tmp_path)
    invalid = script(); invalid['scenes'][0]['caption'] = '비공개실패응답' * 8
    invalid['PRIVATE-SYNTHETIC-KEY-FIELD'] = 'PRIVATE-SYNTHETIC-TOKEN'
    authoring, adapter, budget = bounded_authoring(invalid)
    service.authoring = authoring
    with pytest.raises(CharacterError):
        service.write(identifier, consent=True)
    first = service.read(identifier)
    expected = first['script_validation_feedback']
    assert first['state']=='script_failed' and first['response_received'] is True
    assert authoring.last_failure['validation_feedback']==expected
    assert len(adapter.bodies)==1 and not video.sent
    assert 'PRIVATE' not in json.dumps(first['script_validation_history'])
    assert '비공개실패응답' not in json.dumps(first,ensure_ascii=False)
    adapter.candidate = script()
    service.write(identifier, consent=True)
    final = service.read(identifier)
    body = json.loads(adapter.bodies[1]['messages'][0]['content'])
    assert body['validation_feedback']==expected
    assert len(adapter.bodies)==2 and final['state']=='script_review'
    assert 'script_validation_feedback' not in final and 'script_failure' not in final
    assert final['script_validation_history'][0]['feedback']==expected
    assert [row['status'] for _,row in budget.finished]==['failed','success']


@pytest.mark.parametrize('kind',['scene_count','duration','sound','edited_duration','sfx'])
def test_semantic_validation_reports_only_finite_reason_codes(kind):
    value = script()
    native = True
    if kind == 'scene_count':
        value['scenes'] = [deepcopy(value['scenes'][0]) for _ in range(4)]
        for index, row in enumerate(value['scenes']): row['no']=index+1
        value['scenes'][-1]['freeze_end']='medium'
    elif kind == 'duration': value['scenes'][0]['seconds']=16
    elif kind == 'sound': native=False
    elif kind == 'edited_duration': value['scenes'][0]['seconds']=3
    else: value['scenes'][-1]['sfx'][0]['key']='unregistered'
    with pytest.raises(CharacterError) as failed:
        validate_episode(value,15,CATALOG.model(O3),native)
    result = validation_feedback(failed.value)
    assert result and result[0]['type']==kind
    assert all(set(row)=={'field','type'} for row in result)


def test_duration_failure_reaches_next_explicit_retry_without_raw_response(tmp_path):
    service, _, identifier, _, _ = setup_episode(tmp_path)
    invalid=script(); invalid['scenes'][0]['seconds']=3
    authoring, adapter, _ = bounded_authoring(invalid)
    service.authoring=authoring
    with pytest.raises(CharacterError): service.write(identifier,consent=True)
    first=service.read(identifier)
    assert first['script_validation_feedback']==[{'field':['scenes'],'type':'edited_duration'}]
    assert len(adapter.bodies)==1
    adapter.candidate=script()
    service.write(identifier,consent=True)
    assert json.loads(adapter.bodies[-1]['messages'][0]['content'])['validation_feedback']==first['script_validation_feedback']
    assert len(adapter.bodies)==2


def test_ambiguous_response_has_no_schema_feedback_and_cannot_be_retried(tmp_path):
    service, _, identifier, _, _=setup_episode(tmp_path)
    authoring, adapter, budget=bounded_authoring(script())
    adapter.fail=True
    service.authoring=authoring
    with pytest.raises(CharacterError): service.write(identifier,consent=True)
    job=service.read(identifier)
    assert job['state']=='script_failed' and job['response_received'] is False
    assert 'script_validation_feedback' not in job and 'validation_feedback' not in authoring.last_failure
    with pytest.raises(CharacterError): service.write(identifier,consent=True)
    assert len(adapter.bodies)==1 and budget.finished[-1][1]['status']=='unknown'
