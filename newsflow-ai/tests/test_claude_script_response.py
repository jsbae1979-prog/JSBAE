"""Claude script parser and strict review contracts, Fake HTTP and isolated SQLite only."""
import json
from copy import deepcopy

import pytest
from sqlalchemy import select
from test_claude_analysis_response import analyze, latest
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import sessions as sessions  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414
from test_claude_analysis_response import store as store  # noqa: PLC0414

from newsflow.db.models import APIRequestReservation, AuditLog, ContentDraft, IntelligenceRun
from newsflow.intelligence.api_providers import _safe_json
from newsflow.intelligence.api_settings import (
    APISettingsError,
    acknowledge_unknown_analysis,
    allow_script_once,
)
from newsflow.intelligence.provider import (
    OfflineProvider,
    Options,
    ProviderResponseError,
    ScriptResponseError,
)
from newsflow.intelligence.schema import Script
from newsflow.intelligence.service import IntelligenceError

RAW = 'PRIVATE_PROVIDER_BODY_NOT_TO_BE_STORED'


@pytest.fixture
def script_state(state):
    identifier = analyze(state)
    with state['sessions']() as session:
        evidence = deepcopy(session.get(IntelligenceRun, identifier).evidence)
    state['analysis_id'] = identifier
    state['payload'] = OfflineProvider().complete(evidence, 30, Options())
    state['document'] = {'stop_reason': 'end_turn',
                         'content': [{'type': 'text', 'text': json.dumps(state['payload'], ensure_ascii=False)}],
                         'usage': {'input_tokens': 1650, 'output_tokens': 824}}
    state['calls'].clear()
    return state


def generate(value):
    return value['service'].generate(value['analysis_id'], 30, 'claude_api', True,
                                     Options(model='claude-sonnet-4-6'))


def failure(value, reason, *, unknown=False):
    with pytest.raises(IntelligenceError) as caught:
        generate(value)
    assert caught.value.code == 'ai_bad_response' and not caught.value.retryable
    run, reservation = latest(value)
    assert run.kind == 'script' and run.status == 'failed'
    assert run.result['script_failure']['failure_reason'] == reason
    assert RAW not in json.dumps(run.result) + run.message
    assert reservation.status == ('unknown' if unknown else 'failed')
    assert len(value['calls']) == 1 and not value['adapter'].last_retried
    with value['sessions']() as session:
        assert list(session.scalars(select(ContentDraft))) == []
    return run, reservation


@pytest.mark.parametrize('version', ['v1', 'v2'])
@pytest.mark.parametrize('formatting', ['plain', 'fence', 'split'])
def test_one_complete_script_json_is_saved_for_review_with_original_limits(script_state, formatting, version, monkeypatch):
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', version)
    text = json.dumps(script_state['payload'], ensure_ascii=False)
    if formatting == 'fence':
        text = '```json\n' + text + '\n```'
        # Reproduce the former script parser failure without a network call.
        with pytest.raises(ProviderResponseError):
            _safe_json(text)
    blocks = [{'type': 'text', 'text': text}]
    if formatting == 'split':
        blocks = [{'type': 'text', 'text': text[:35]}, {'type': 'text', 'text': text[35:]}]
    script_state['document']['content'] = blocks
    draft_id = generate(script_state)
    with script_state['sessions']() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.review_status == 'review_required' and draft.duration == 30
        assert draft.content == script_state['payload']
        assert draft.sources['articles'][0]['id'] == script_state['article_id']
        assert session.get(IntelligenceRun, draft.run_id).options['analysis_run_id'] == script_state['analysis_id']
    assert len(script_state['calls']) == 1
    body = script_state['calls'][0]
    schema = body['output_config']['format']['schema']
    assert body['output_config']['format']['type'] == 'json_schema'
    assert schema['additionalProperties'] is False and schema['$defs']['Scene']['additionalProperties'] is False
    assert 'maxLength' not in schema['$defs']['Scene']['properties']['narration']
    assert '400' in schema['$defs']['Scene']['properties']['narration']['description']
    assert Script.model_json_schema()['$defs']['Scene']['properties']['narration']['maxLength'] == 400
    assert body['max_tokens'] == (2400 if version == 'v2' else 1800) and 'no Markdown' in body['system']
    assert ('analysis' in schema['properties']) == (version == 'v2')
    assert json.loads(body['messages'][0]['content'])['duration'] == 30 and 'tools' not in body


@pytest.mark.parametrize('kind,reason', [
    ('truncated', 'result_json'), ('prose', 'result_json'), ('two_json', 'result_json'),
    ('array', 'result_json'), ('trailing_prose', 'result_json'),
    ('non_text', 'response_text'), ('missing_text', 'response_text'),
    ('wrong_type', 'script_validation'), ('too_long', 'script_validation'),
    ('extra_field', 'script_validation'), ('duration', 'script_validation'),
    ('empty_scenes', 'script_validation'), ('body_url', 'script_validation'),
])
def test_script_parse_and_validation_failures_never_store_raw_or_retry(script_state, kind, reason):
    payload = deepcopy(script_state['payload'])
    text = json.dumps(payload)
    if kind == 'truncated':
        text = '{"title":"' + RAW
    elif kind == 'prose':
        text = RAW + '\n' + text
    elif kind == 'two_json':
        text += '\n{}'
    elif kind == 'array':
        text = '[]'
    elif kind == 'trailing_prose':
        text = '```json\n' + text + '\n```\n' + RAW
    elif kind == 'wrong_type':
        payload['scenes'][0]['seconds'] = '10'
    elif kind == 'too_long':
        payload['scenes'][0]['narration'] = '가' * 401
    elif kind == 'extra_field':
        payload['private'] = RAW
    elif kind == 'duration':
        payload['scenes'][0]['seconds'] = 9
    elif kind == 'empty_scenes':
        payload['scenes'] = []
    elif kind == 'body_url':
        payload['summary'] = 'https://example.com/' + RAW
    if kind in {'wrong_type', 'too_long', 'extra_field', 'duration', 'empty_scenes', 'body_url'}:
        text = json.dumps(payload)
    script_state['document']['content'] = [{'type': 'text', 'text': text}]
    if kind == 'non_text':
        script_state['document']['content'] = [{'type': 'tool_use', 'private': RAW}]
    elif kind == 'missing_text':
        script_state['document']['content'] = [{'type': 'text', 'private': RAW}]
    failure(script_state, reason)


@pytest.mark.parametrize('stop', ['max_tokens', 'refusal', 'pause_turn', None])
def test_incomplete_script_is_not_continued(script_state, stop):
    script_state['document']['stop_reason'] = stop
    failure(script_state, 'incomplete_response')


def test_script_missing_usage_keeps_unknown_outcome_and_no_dispatch_on_next_request(script_state):
    script_state['document']['usage'] = {}
    script_state['document']['content'][0]['text'] = RAW
    failure(script_state, 'result_json', unknown=True)
    with pytest.raises(IntelligenceError, match='결과 불명'):
        generate(script_state)
    assert len(script_state['calls']) == 1


def test_failed_scoped_script_keeps_old_unknown_amount_ack_and_consumed_approval(script_state):
    sessions, budget, store = script_state['sessions'], script_state['budget'], script_state['store']
    old = budget.reserve(provider='claude_api', request_id='legacy:unknown', kind='analysis',
                         model='claude-sonnet-4-6', max_output_tokens=1800, key_store=store)
    budget.finish(old.id, status='unknown')
    with sessions.begin() as session:
        session.get(APIRequestReservation, old.id).reserved_usd = '9.165'
    review = budget.readiness('claude_api', store, 'analysis')['unknown_analysis_reviews'][0]
    acknowledge_unknown_analysis(sessions, 'claude_api', reservation_id=old.id,
                                 fingerprint=review['fingerprint'], consent=True)
    with sessions() as session:
        before = {c.name: getattr(session.get(APIRequestReservation, old.id), c.name)
                  for c in APIRequestReservation.__table__.columns}
        ack = [(r.id, r.message) for r in session.scalars(select(AuditLog))]
    allow_script_once(sessions, 'claude_api', analysis_id=script_state['analysis_id'],
                      model='claude-sonnet-4-6', duration=30, consent=True)
    script_state['document']['content'][0]['text'] = RAW
    failure(script_state, 'result_json')
    with pytest.raises(IntelligenceError):
        generate(script_state)
    with pytest.raises(APISettingsError):
        allow_script_once(sessions, 'claude_api', analysis_id=script_state['analysis_id'],
                          model='claude-sonnet-4-6', duration=30, consent=True)
    assert len(script_state['calls']) == 1
    with sessions() as session:
        after = {c.name: getattr(session.get(APIRequestReservation, old.id), c.name)
                 for c in APIRequestReservation.__table__.columns}
        assert before == after
        assert all(session.get(AuditLog, identifier).message == text for identifier, text in ack)
        assert len(list(session.scalars(select(AuditLog).where(AuditLog.event == 'api_script_once_consumed')))) == 1


def test_script_diagnostics_revalidate_mutated_attributes():
    error = ScriptResponseError('result_json', stop_reason='end_turn')
    error.args = (RAW,)
    error.failure_reason = {'private': RAW}
    error.stop_reason = RAW
    assert error.diagnostics() == {'failure_reason': 'response_envelope', 'stop_reason': 'other'}
    assert RAW not in str(error.safe_copy())

@pytest.mark.parametrize('bad_envelope', [False, True])
def test_invalid_envelope_or_echoed_key_never_persists_body(script_state, monkeypatch, bad_envelope):
    def send(request, timeout, limit):
        script_state['calls'].append(json.loads(request.data))
        if bad_envelope:
            return RAW.encode()
        return json.dumps({'private': script_state['store'].key(), 'raw': RAW}).encode()
    monkeypatch.setattr(script_state['adapter'], '_open', send)
    failure(script_state, 'response_envelope', unknown=True)


def test_long_source_copy_is_still_rejected(script_state):
    summary = '제공된 합성 원문을 그대로 사용하지 않고 요약하는지 확인합니다. ' * 5
    with script_state['sessions'].begin() as session:
        analysis = session.get(IntelligenceRun, script_state['analysis_id'])
        evidence = deepcopy(analysis.evidence)
        evidence['articles'][0]['summary'] = summary
        analysis.evidence = evidence
    payload = deepcopy(script_state['payload'])
    payload['scenes'][0]['narration'] = summary[:120]
    script_state['document']['content'][0]['text'] = json.dumps(payload)
    failure(script_state, 'script_validation')
