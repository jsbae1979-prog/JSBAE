"""Explicit scene text budgets; isolated Fake providers, no real user data or requests."""

import json
from copy import deepcopy
from dataclasses import asdict

import pytest
from sqlalchemy import select
from test_claude_analysis_response import analyze
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import sessions as sessions  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414
from test_claude_analysis_response import store as store  # noqa: PLC0414
from test_explainer_prompts import evidence
from test_explainer_review_safety import compact_script

from newsflow.db.models import APIRequestReservation, ContentDraft, IntelligenceRun, NewsArticle
from newsflow.intelligence.api_providers import AnthropicProvider, _script_output_schema
from newsflow.intelligence.korean import speech_plan, speech_seconds
from newsflow.intelligence.news_usage import api_news_contract, explainer_findings
from newsflow.intelligence.provider import OpenAIProvider, Options
from newsflow.intelligence.schema import Script
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.shortform import Shortform
from newsflow.video.production_policy import check_draft


def source(duration=30, mode='STANDARD'):
    result = evidence()
    result['articles'] = result['articles'][:1]
    result['news_usage'] = mode
    result['news_usage_contract'] = api_news_contract(result, mode, duration)
    return result


@pytest.mark.parametrize('duration', [30, 45, 60])
@pytest.mark.parametrize('mode', ['QUICK', 'STANDARD'])
@pytest.mark.parametrize('rate,pause', [(-5, 0), (0, 250), (5, 1000)])
def test_countable_budgets_follow_saved_voice_and_keep_time_estimator(duration, mode, rate, pause):
    inputs = source(duration, mode)
    contract = api_news_contract(inputs, mode, duration, speech={'rate': rate, 'pause_ms': pause})
    budgets = contract['scene_narration_budgets']
    assert contract['narration_characters_maximum'] == sum(b['maximum_characters'] for b in budgets)
    assert sum(b['seconds'] for b in budgets) == duration
    assert all(b['maximum_sentences'] == 1 for b in budgets[1:-1])
    assert sum(b['maximum_sentences'] for b in budgets) == contract['speech_estimate']['sentence_count_hint']
    for b in budgets:
        units = b['maximum_spoken_units']
        narration = ('가' * (units // 2) + '. ' + '나' * (units - units // 2) + '.'
                     if b['maximum_sentences'] == 2 else '가' * units + '.')
        assert len(narration) <= b['maximum_characters']
        assert speech_seconds(narration, rate=rate, pause_ms=pause) <= b['seconds']
    old = api_news_contract(inputs, mode, duration, speech={'rate': rate, 'pause_ms': pause}, version='v1')
    assert 'narration_limits_version' not in old


def test_character_sentence_and_repetition_findings_do_not_modify_a_draft():
    inputs, content = source(), compact_script()
    assert not explainer_findings(content, inputs) and speech_plan(content, 30)['fits']
    content['scenes'][1]['narration'] = ' '.join([content['scenes'][1]['narration']] * 2)
    before = deepcopy(content)
    notes = explainer_findings(content, inputs)
    assert {'narration_character_limit', 'narration_sentence_limit', 'narration_repeated_sentence'} <= {
        n['code'] for n in notes}
    assert any(n['code'] == 'narration_repeated_sentence' and n['level'] == 'info' for n in notes)
    assert content == before
    legacy = deepcopy(inputs)
    legacy['news_usage_contract'].pop('narration_limits_version')
    assert not any(n['code'].startswith('narration_') for n in explainer_findings(content, legacy))


def test_spaces_count_as_characters_even_when_audio_estimate_is_short():
    inputs, content = source(), compact_script()
    limit = inputs['news_usage_contract']['scene_narration_budgets'][1]['maximum_characters']
    content['scenes'][1]['narration'] = '확인합니다.' + ' ' * limit
    assert speech_seconds(content['scenes'][1]['narration']) < 8
    assert any(n['code'] == 'narration_character_limit' for n in explainer_findings(content, inputs))


def test_user_seconds_edit_recalculates_length_advice_but_not_original_voice_or_text():
    inputs, content = source(), compact_script()
    content['scenes'][0]['narration'] = content['hook'] + ' 합성 자료에서 금리 동결과 계약 조건을 나눠 살펴봅니다.'
    assert any(n['code'] == 'narration_character_limit' and '장면 1 ' in n['message']
               for n in explainer_findings(content, inputs))
    content['scenes'][0]['seconds'], content['scenes'][1]['seconds'] = 9, 5
    before, original_contract = deepcopy(content), deepcopy(inputs['news_usage_contract'])
    assert not any(n['code'] == 'narration_character_limit' and '장면 1 ' in n['message']
                   for n in explainer_findings(content, inputs))
    assert content == before and inputs['news_usage_contract'] == original_contract


def test_review_uses_explicit_job_speech_without_changing_frozen_default_or_narration():
    inputs, content = source(), compact_script()
    content['scenes'][0]['narration'] = content['scenes'][0]['narration'].replace(
        '합성 자료는', '합성 자료는 이번 사례의')
    original_content, original_source = deepcopy(content), deepcopy(inputs)
    service = IntelligenceService.__new__(IntelligenceService)
    service.speech = {'rate': 0, 'pause_ms': 250}
    assert any(n['code'] == 'narration_character_limit' and '장면 1 ' in n['message']
               for n in service._review_notes(content, inputs, 30))
    service.speech = {'rate': 5, 'pause_ms': 250}  # explicit job setting, never an automatic speed-up
    assert not any(n['code'] == 'narration_character_limit' and '장면 1 ' in n['message']
                   for n in service._review_notes(content, inputs, 30))
    assert content == original_content and inputs == original_source
    assert inputs['news_usage_contract']['speech_estimate']['rate'] == 0


@pytest.mark.parametrize('duration', [15, 30, 35])
def test_shortform_hook_and_single_sentence_constraints_remain(duration):
    inputs = source()
    inputs['shortform'] = asdict(Shortform(enabled=True, target_seconds=duration))
    contract = api_news_contract(inputs, 'STANDARD', duration)
    assert contract['scene_narration_budgets'][0]['seconds'] <= 3
    assert all(b['maximum_sentences'] == 1 for b in contract['scene_narration_budgets'])
    assert sum(b['seconds'] for b in contract['scene_narration_budgets']) == duration


@pytest.mark.parametrize('provider', ['claude_api', 'openai'])
def test_actual_wire_gets_concrete_budgets_without_unsupported_schema_bounds(provider, monkeypatch):
    inputs, calls = source(), []
    adapter = AnthropicProvider(lambda: 'synthetic-wire-key') if provider == 'claude_api' else OpenAIProvider(
        lambda: 'synthetic-wire-key', allow_retry=False)
    payload = compact_script()
    response = ({'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(payload)}],
                 'usage': {'input_tokens': 100, 'output_tokens': 50}} if provider == 'claude_api' else
                {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(payload)}}],
                 'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})

    def send(request, *_):
        calls.append(json.loads(request.data))
        return json.dumps(response).encode()

    monkeypatch.setattr(adapter, '_open', send)
    output = adapter.complete(inputs, 30, Options(model='claude-sonnet-4-6' if provider == 'claude_api' else 'gpt-4.1-mini'))
    assert output == payload and len(calls) == 1 and not adapter.last_retried
    body = calls[0]
    if provider == 'claude_api':
        schema = body['output_config']['format']['schema']
        narration = schema['$defs']['Scene']['properties']['narration']
        assert '36자/2문장' in narration['description'] and '55자/1문장' in narration['description']
        assert '400' not in narration['description'] and 'maxLength' not in narration
        assert '<=400' not in body['system']
        assert Script.model_json_schema()['$defs']['Scene']['properties']['narration']['maxLength'] == 400
        assert '400' in _script_output_schema('v1')['$defs']['Scene']['properties']['narration']['description']
        message = body['messages'][0]['content']
    else:
        assert body['response_format'] == {'type': 'json_object'}
        message = body['messages'][-1]['content']
    assert json.loads(message)['evidence']['news_usage_contract']['narration_characters_maximum'] == 197
    assert body['max_tokens'] == 2400


def test_fake_long_response_stays_reviewable_and_edits_need_no_regeneration(state, tmp_path):
    with state['sessions'].begin() as session:
        article = session.get(NewsArticle, state['article_id'])
        article.title, article.summary = evidence()['articles'][0]['title'], evidence()['articles'][0]['summary']
    parent = analyze(state)
    valid, long = compact_script(), compact_script()
    long['scenes'][1]['narration'] = ' '.join([long['scenes'][1]['narration']] * 2)
    state['document']['content'][0]['text'] = json.dumps(long)
    identifier = state['service'].generate(parent, 30, 'claude_api', True, Options(model='claude-sonnet-4-6'))
    with state['sessions']() as session:
        draft = session.get(ContentDraft, identifier)
        assert draft.content == long and draft.review_status == 'review_required'
        assert any(n['code'] == 'narration_character_limit' and n['level'] == 'warning' for n in draft.review_notes)
        with pytest.raises(IntelligenceError):
            check_draft(state['sessions'], draft, {'speech': {'rate': 0, 'pause_ms': 250}}, tmp_path)
        parent_result = deepcopy(session.get(IntelligenceRun, parent).result)
    state['service'].edit(identifier, 1, valid)
    with state['sessions']() as session:
        draft = session.get(ContentDraft, identifier)
        assert draft.content == valid and draft.revision == 2 and draft.review_status == 'review_required'
        assert not any(n['level'] != 'info' for n in draft.review_notes)
        check_draft(state['sessions'], draft, {'speech': {'rate': 0, 'pause_ms': 250}}, tmp_path)
        assert session.get(IntelligenceRun, parent).result == parent_result
        assert all(r.status == 'success' and r.test_only for r in session.scalars(select(APIRequestReservation)))
    assert len(state['calls']) == 2 and not state['adapter'].last_retried

