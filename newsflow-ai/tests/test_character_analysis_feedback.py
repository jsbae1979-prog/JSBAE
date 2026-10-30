"""Bounded analysis diagnostics from Fake responses; never include raw content."""
import json

import pytest

from newsflow.character.authoring import analysis_failure_message
from newsflow.character.schema import CharacterError
from test_character_authoring_v3 import build, candidate, png
from test_character_automation_routes import gui


def analyze(service):
    return service.analyze(png(), provider='claude_api', model='claude-sonnet-4-6',
                           request_id='analysis:diagnostic', consent=True)


def test_overlong_appearance_is_still_rejected_with_safe_field_only():
    answer = candidate()
    answer['appearance'] = 'PRIVATE_RESPONSE_' + 'x' * 401
    service, adapter, budget = build('claude_api', answer)
    with pytest.raises(CharacterError) as caught:
        analyze(service)
    failure = service.last_failure
    assert failure['analysis_stage'] == 'schema'
    assert failure['analysis_feedback'] == [{'field': ['appearance'], 'type': 'string_too_long'}]
    assert analysis_failure_message(caught.value, failure) == '외형 설명: 글자 수 초과'
    assert 'PRIVATE_RESPONSE' not in json.dumps(failure)
    assert len(adapter.bodies) == 1 and budget.finished[0][1]['status'] == 'failed'


def test_nested_field_feedback_has_bounded_names_and_no_value():
    answer = candidate()
    answer['candidates'][1]['comedy_formula']['reaction'] = '비공개' * 40
    answer['private-api-key-field'] = 'synthetic-sensitive-value'
    service, adapter, budget = build('claude_api', answer)
    with pytest.raises(CharacterError): analyze(service)
    feedback = service.last_failure['analysis_feedback']
    assert {'field': ['candidates', 1, 'comedy_formula', 'reaction'], 'type': 'string_too_long'} in feedback
    assert {'field': ['field'], 'type': 'extra_forbidden'} in feedback
    safe = json.dumps(service.last_failure, ensure_ascii=False)
    assert 'private-api-key-field' not in safe and 'synthetic-sensitive-value' not in safe and '비공개' not in safe


@pytest.mark.parametrize('kind', ['envelope', 'json'])
def test_envelope_and_json_failures_have_distinct_safe_phase_without_retry(kind):
    service, adapter, budget = build('claude_api', candidate())
    original = adapter._post
    def response(body, options):
        document = original(body, options)
        if kind == 'envelope': document['stop_reason'] = 'max_tokens'
        else: document['content'][0]['text'] = '{"PRIVATE_RESPONSE":invalid}'
        return document
    adapter._post = response
    with pytest.raises(CharacterError) as caught: analyze(service)
    assert service.last_failure['analysis_stage'] == kind
    assert service.last_failure['analysis_feedback'] == []
    assert analysis_failure_message(caught.value, service.last_failure) == '이미지 분석 응답 형식 확인 필요'
    assert 'PRIVATE_RESPONSE' not in json.dumps(service.last_failure)
    assert len(adapter.bodies) == 1 and budget.finished[0][1]['status'] == 'failed'


def test_unknown_timeout_stays_unknown_and_does_not_claim_schema_failure():
    service, adapter, budget = build('claude_api', candidate())
    adapter.fail = True
    with pytest.raises(CharacterError) as caught: analyze(service)
    assert service.last_failure['analysis_stage'] == 'provider'
    assert not service.response_received
    assert budget.finished[0][1]['status'] == 'unknown' and len(adapter.bodies) == 1
    assert analysis_failure_message(caught.value, service.last_failure) == '이미지 분석을 완료하지 못했습니다'


def test_route_returns_short_safe_detail_and_does_not_register_or_retry(gui):
    answer = candidate()
    answer['appearance'] = 'x' * 401
    service, adapter, budget = build('claude_api', answer)
    gui.app.state.character_authoring = service
    response = gui.post('/api/studio/characters/profiles/analyze', asset=gui.asset,
        model='claude-sonnet-4-6', request_id='analysis:route', consent='true')
    assert response.status_code == 409
    assert response.json() == {'detail': '외형 설명: 글자 수 초과'}
    assert len(adapter.bodies) == 1
    assert gui.client.get('/api/studio/characters/profiles').json() == {'profiles': []}


def test_route_preflight_does_not_reuse_prior_schema_diagnostic(gui):
    answer = candidate()
    answer['appearance'] = 'x' * 401
    service, adapter, budget = build('claude_api', answer)
    gui.app.state.character_authoring = service
    path = '/api/studio/characters/profiles/analyze'
    assert gui.post(path, asset=gui.asset, model='claude-sonnet-4-6', request_id='first', consent='true').status_code == 409
    result = gui.post(path, asset=gui.asset, model='claude-sonnet-4-6', request_id='second', consent='false')
    assert result.json() == {'detail': '이미지 분석 전송 동의 필요'}
    assert len(adapter.bodies) == 1


def test_route_unknown_model_does_not_reuse_prior_schema_diagnostic(gui):
    from starlette.requests import Request
    from fastapi import HTTPException
    from newsflow.gui.character_automation_routes import profile_analyze

    answer = candidate()
    answer['appearance'] = 'x' * 401
    service, adapter, budget = build('claude_api', answer)
    gui.app.state.character_authoring = service
    request = Request({'type': 'http', 'app': gui.app})
    # Direct route calls deliberately reuse the same thread-local receipt.
    with pytest.raises(HTTPException) as first:
        profile_analyze(request, asset=gui.asset, model='claude-sonnet-4-6',
                        request_id='first', consent=True)
    assert first.value.detail == '외형 설명: 글자 수 초과'
    with pytest.raises(HTTPException) as second:
        profile_analyze(request, asset=gui.asset, model='unsupported-model',
                        request_id='second', consent=True)
    assert second.value.detail == '이미지 분석을 완료하지 못했습니다'
    assert len(adapter.bodies) == 1
