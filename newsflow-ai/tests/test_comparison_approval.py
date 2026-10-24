"""Real budget/service + Fake HTTP; no operating DB, keys, authentication or paid requests."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import sessions as sessions  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414
from test_claude_analysis_response import store as store  # noqa: PLC0414
from test_explainer_prompts import evidence, interpretive

from newsflow.db.models import (
    APIRequestReservation,
    AppSetting,
    AuditLog,
    IntelligenceRun,
    NewsArticle,
    utcnow,
)
from newsflow.intelligence.api_settings import (
    APIBudgetService,
    APISettingsError,
    acknowledge_unknown_analysis,
)
from newsflow.intelligence.comparison_approval import (
    APPROVAL,
    CONSUMED,
    FINISHED,
    approve_comparison,
    comparison_review,
)
from newsflow.intelligence.provider import OfflineProvider, Options
from newsflow.intelligence.service import IntelligenceError
from newsflow.intelligence.settings import _set

MODEL = 'claude-sonnet-4-6'
OPTIONS = Options(model=MODEL, timeout=300)


@pytest.fixture
def comparison(state, monkeypatch):
    sources = evidence()['articles']
    with state['sessions'].begin() as session:
        first = session.get(NewsArticle, state['article_id'])
        first.title, first.summary = sources[0]['title'], sources[0]['summary']
        other = NewsArticle(source_id=first.source_id, title=sources[1]['title'], summary=sources[1]['summary'],
                            publisher='합성 B', url='https://example.org/fixture-b', canonical_url='https://example.org/fixture-b')
        session.add(other)
        session.flush()
        identifiers = [first.id, other.id]
        for name, value in [('authentication_verified_at', utcnow().isoformat()), ('verified_model', MODEL)]:
            _set(session, 'api_claude_api_' + name, value)
        for request_id, kind in [('intelligence:12', 'analysis'), ('feed-card:47', 'script')]:
            session.add(APIRequestReservation(id=uuid4().hex, request_id=request_id, provider='claude_api', kind=kind,
                model=MODEL, status='unknown', reserved_usd='9.165', usage={}, bounds={}, prices={},
                created_at=utcnow()-timedelta(days=1), finished_at=utcnow()-timedelta(hours=2), test_only=False))
    budget = APIBudgetService(state['sessions'])
    review = budget.readiness('claude_api', state['store'], 'analysis')['unknown_analysis_reviews'][0]
    acknowledge_unknown_analysis(state['sessions'], 'claude_api', reservation_id=review['id'],
                                 fingerprint=review['fingerprint'], consent=True)
    state['budget'] = state['service'].api_budget = budget
    state['ids'] = identifiers
    state['old'] = originals(state)

    def send(request, timeout, limit):
        assert request.full_url == 'https://api.anthropic.com/v1/messages' and request.method == 'POST'
        body = json.loads(request.data)
        assert body['model'] == MODEL and 'tools' not in body
        state['calls'].append(body)
        return json.dumps(state['document']).encode()

    monkeypatch.setattr(state['adapter'], '_open', send)
    return state


def originals(value):
    with value['sessions']() as session:
        return {'rows': {r.id: {c.name: getattr(r, c.name) for c in r.__table__.columns}
                         for r in session.scalars(select(APIRequestReservation)) if r.request_id in {'intelligence:12', 'feed-card:47'}},
                'settings': {r.key: r.value for r in session.scalars(select(AppSetting))},
                'old_audit': {r.id: r.message for r in session.scalars(select(AuditLog))
                              if r.event not in {APPROVAL, CONSUMED, FINISHED}}}


def approve(value, **changes):
    review = comparison_review(value['sessions'], value['ids'])
    return approve_comparison(value['sessions'], article_ids=value['ids'], review_token=review['token'], consent=True, **changes)


def respond(value, payload):
    value['document'] = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(payload)}],
                         'usage': {'input_tokens': 1000, 'output_tokens': 500}}


def analyze(value, approval, version='v1', **changes):
    ids = value['ids']
    respond(value, {'overview': '합성 자료의 일상 확인 관점을 비교합니다.',
        'comparisons': [{'article_ids': [i], 'reason': '입력 자료의 확인 관점', 'uncertainties': '사실 확인 미완료'} for i in ids],
        'recommended_article_id': ids[0], 'selection_reason': '계약 조건의 확인 관점'})
    fields = {'news_usage': 'STANDARD', 'script_prompt_version': version,
              'comparison_approval_id': approval, 'comparison_step': 'analysis-' + version}
    fields.update(changes)
    return value['service'].analyze(ids, 'claude_api', True, OPTIONS, **fields)


def script(value, approval, parent, version, index):
    source = value['service'].evidence_for([value['ids'][index]])
    payload = interpretive() if version == 'v2' and index == 0 else OfflineProvider().complete(source, 30, OPTIONS)
    respond(value, payload)
    return value['service'].generate(parent, 30, 'claude_api', True, OPTIONS, article_ids=[value['ids'][index]],
        news_usage='STANDARD', script_prompt_version=version, comparison_approval_id=approval,
        comparison_step=f'script-{"a" if index == 0 else "b"}-{version}')


def test_exact_five_steps_survive_service_reopen_and_preserve_every_legacy_value(comparison):
    value = comparison
    grant = approve(value)
    assert approve(value) == grant
    v1 = analyze(value, grant)
    value['service'].api_budget = APIBudgetService(value['sessions'])
    v2 = analyze(value, grant, 'v2')
    script(value, grant, v1, 'v1', 0)
    script(value, grant, v2, 'v2', 0)
    script(value, grant, v2, 'v2', 1)
    assert [c['max_tokens'] for c in value['calls']] == [1800, 2200, 1800, 2400, 2400]
    assert originals(value) == value['old']
    with value['sessions']() as session:
        audits = list(session.scalars(select(AuditLog)))
        assert sum(a.event == APPROVAL for a in audits) == 1
        assert sum(a.event == CONSUMED for a in audits) == sum(a.event == FINISHED for a in audits) == 5
        assert all('9.165' not in a.message and value['store'].key() not in a.message for a in audits)
        rows = list(session.scalars(select(APIRequestReservation)))
        assert sum(r.status == 'success' for r in rows) == 5
        assert all(r.reserved_usd == '0' for r in rows if r.status == 'success')
    with pytest.raises(IntelligenceError):
        analyze(value, grant)
    assert len(value['calls']) == 5
    # General API readiness and the original request's replay block are unchanged.
    assert not value['budget'].readiness('claude_api', value['store'], 'analysis')['ready']
    with pytest.raises(APISettingsError):
        value['budget'].reserve(provider='claude_api', request_id='feed-card:47', kind='script', model=MODEL,
                                max_output_tokens=1800, key_store=value['store'])


@pytest.mark.parametrize('consent', [False, None, 1])
def test_preview_never_grants_consent(comparison, consent):
    value = comparison
    review = comparison_review(value['sessions'], value['ids'])
    with pytest.raises(APISettingsError):
        approve_comparison(value['sessions'], article_ids=value['ids'], review_token=review['token'], consent=consent)
    assert not value['calls'] and originals(value) == value['old']


@pytest.mark.parametrize('change', ['old_record', 'new_unknown', 'reserved', 'source', 'settings', 'expiry', 'order', 'missing_scope'])
def test_changed_context_never_dispatches(comparison, change):
    value = comparison
    grant = approve(value)
    with value['sessions'].begin() as session:
        if change == 'old_record':
            session.get(APIRequestReservation, next(iter(value['old']['rows']))).reserved_usd = '9.166'
        elif change in {'new_unknown', 'reserved'}:
            session.add(APIRequestReservation(id=uuid4().hex, provider='claude_api', model=MODEL, kind='analysis',
                request_id='another:new', status='reserved' if change == 'reserved' else 'unknown', reserved_usd='0',
                bounds={}, prices={}, usage={}, finished_at=utcnow() if change == 'new_unknown' else None))
        elif change == 'source':
            session.get(NewsArticle, value['ids'][0]).summary += ' 새로 바뀐 자료'
        elif change == 'settings':
            _set(session, 'api_claude_api_monthly_limit_usd', '40')
        elif change == 'expiry':
            row = session.get(AuditLog, grant)
            data = json.loads(row.message)
            data['expires_at'] = (utcnow()-timedelta(seconds=1)).isoformat()
            row.message = json.dumps(data)
    with pytest.raises(IntelligenceError):
        analyze(value, grant, **({'comparison_step': 'analysis-v2'} if change == 'order' else
                                {'comparison_approval_id': None, 'comparison_step': None} if change == 'missing_scope' else {}))
    assert not value['calls']


@pytest.mark.parametrize('problem', ['expired_auth', 'no_key', 'monthly_used', 'not_approved'])
def test_scope_does_not_bypass_real_auth_key_consent_or_reported_usage_limit(comparison, problem, monkeypatch):
    value = comparison
    grant = approve(value)
    with value['sessions'].begin() as session:
        if problem == 'expired_auth':
            _set(session, 'api_claude_api_authentication_verified_at', (utcnow()-timedelta(hours=25)).isoformat())
        elif problem == 'not_approved':
            _set(session, 'api_claude_api_approved_at', '')
        elif problem == 'monthly_used':
            session.add(APIRequestReservation(id=uuid4().hex, provider='claude_api', model=MODEL, kind='analysis',
                request_id='reported:cost', status='success', reserved_usd='0', estimated_usd='30',
                bounds={}, prices={}, usage={'prompt_tokens': 10}, finished_at=utcnow()))
    if problem == 'no_key':
        monkeypatch.setattr(value['store'], 'status', lambda: {'configured': False})
    with pytest.raises(IntelligenceError):
        analyze(value, grant)
    assert not value['calls']


@pytest.mark.parametrize('failure', ['bad_json', 'max_tokens', 'missing_usage'])
def test_failed_or_unknown_first_request_permanently_stops_remaining_scope(comparison, monkeypatch, failure):
    value = comparison
    grant = approve(value)
    actual = value['adapter']._open

    def fail(*args):
        if failure == 'bad_json':
            value['document']['content'][0]['text'] = 'PRIVATE_UNSAFE_RESPONSE'
        elif failure == 'max_tokens':
            value['document']['stop_reason'] = 'max_tokens'
        else:
            value['document']['usage'] = {}
        return actual(*args)

    monkeypatch.setattr(value['adapter'], '_open', fail)
    if failure == 'missing_usage':
        analyze(value, grant)  # valid JSON, unknown accounting; never authorizes the next step
    else:
        with pytest.raises(IntelligenceError):
            analyze(value, grant)
    with pytest.raises(IntelligenceError):
        analyze(value, grant, 'v2')
    with pytest.raises(IntelligenceError):
        analyze(value, grant)
    assert len(value['calls']) == 1 and originals(value) == value['old']


def test_two_simultaneous_requests_consume_only_one_step(comparison):
    value = comparison
    grant = approve(value)

    def call():
        try:
            return analyze(value, grant)
        except IntelligenceError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(), range(2)))
    assert sum(r is not None for r in results) == 1
    assert len(value['calls']) == 1


def test_parent_result_change_stops_child_script(comparison):
    value = comparison
    grant = approve(value)
    v1, _v2 = analyze(value, grant), analyze(value, grant, 'v2')
    with value['sessions'].begin() as session:
        run = session.get(IntelligenceRun, v1)
        run.result = {**run.result, 'overview': '바뀐 분석 내용'}
    with pytest.raises(IntelligenceError):
        script(value, grant, v1, 'v1', 0)
    assert len(value['calls']) == 2


def test_authentication_refresh_does_not_renew_scope_or_change_old_records(comparison):
    value = comparison
    with value['sessions'].begin() as session:
        _set(session, 'api_claude_api_authentication_verified_at', (utcnow()-timedelta(hours=25)).isoformat())
    grant = approve(value)
    with pytest.raises(IntelligenceError):
        analyze(value, grant)
    assert not value['calls']
    # Simulate a separately authorized successful metadata check; never send a GET here.
    with value['sessions'].begin() as session:
        _set(session, 'api_claude_api_authentication_verified_at', utcnow().isoformat())
    assert approve(value) == grant
    assert analyze(value, grant)
    assert originals(value)['rows'] == value['old']['rows']
    assert len(value['calls']) == 1


def test_expired_approval_is_not_renewed_by_duplicate_consent(comparison):
    value = comparison
    grant = approve(value)
    with value['sessions'].begin() as session:
        row = session.get(AuditLog, grant)
        payload = json.loads(row.message)
        payload['expires_at'] = (utcnow()-timedelta(seconds=1)).isoformat()
        row.message = json.dumps(payload)
    assert approve(value) == grant
    with pytest.raises(IntelligenceError):
        analyze(value, grant)
    assert not value['calls']


@pytest.mark.parametrize('field,value', [('max_tokens', 2400), ('timeout', 30), ('temperature', .8)])
def test_mutated_request_options_cannot_expand_the_reviewed_call(comparison, field, value):
    target = comparison
    grant = approve(target)

    def alter(identifier):
        with target['sessions'].begin() as session:
            run = session.get(IntelligenceRun, identifier)
            run.options = {**run.options, field: value}

    with pytest.raises(IntelligenceError):
        analyze(target, grant, on_run=alter)
    assert not target['calls']


def test_bad_old_audit_payloads_do_not_grant_scope_or_break_unrelated_finish(comparison):
    value = comparison
    with value['sessions'].begin() as session:
        session.add_all([AuditLog(level='info', event=APPROVAL, message='INVALID_JSON'),
                         AuditLog(level='info', event=CONSUMED, message='[]')])
    grant = approve(value)
    assert analyze(value, grant)
    assert len(value['calls']) == 1


def test_review_is_read_only_and_stale_preview_cannot_be_approved(comparison):
    value = comparison
    review = comparison_review(value['sessions'], value['ids'])
    assert review['unknown_count'] == 2 and originals(value) == value['old']
    with value['sessions'].begin() as session:
        session.get(NewsArticle, value['ids'][0]).title += ' 변경'
    with pytest.raises(APISettingsError):
        approve_comparison(value['sessions'], article_ids=value['ids'], review_token=review['token'], consent=True)
    with value['sessions']() as session:
        assert list(session.scalars(select(AuditLog).where(AuditLog.event == APPROVAL))) == []
    assert not value['calls']


@pytest.mark.parametrize('change', ['version', 'duration', 'article', 'style', 'parent', 'provider'])
def test_script_cannot_change_approved_content_duration_parent_or_provider(comparison, change):
    value = comparison
    grant = approve(value)
    v1, v2 = analyze(value, grant), analyze(value, grant, 'v2')
    source = value['service'].evidence_for([value['ids'][0]])
    respond(value, OfflineProvider().complete(source, 30, OPTIONS))
    fields = {'article_ids': [value['ids'][0]], 'news_usage': 'STANDARD', 'script_prompt_version': 'v1',
              'comparison_approval_id': grant, 'comparison_step': 'script-a-v1'}
    if change == 'version':
        fields['script_prompt_version'] = 'v2'
    elif change == 'article':
        fields['article_ids'] = [value['ids'][1]]
    elif change == 'style':
        fields['script_style'] = 'explainer'
    with pytest.raises(IntelligenceError):
        value['service'].generate(v2 if change == 'parent' else v1, 45 if change == 'duration' else 30,
            'openai' if change == 'provider' else 'claude_api', True, OPTIONS, **fields)
    assert len(value['calls']) == 2


def test_script_failure_after_two_successes_never_replays_success_or_runs_remaining_steps(comparison, monkeypatch):
    value = comparison
    grant = approve(value)
    v1, v2 = analyze(value, grant), analyze(value, grant, 'v2')
    actual = value['adapter']._open

    def broken(*args):
        value['document']['content'][0]['text'] = 'PRIVATE_BAD_SCRIPT'
        return actual(*args)

    monkeypatch.setattr(value['adapter'], '_open', broken)
    with pytest.raises(IntelligenceError):
        script(value, grant, v1, 'v1', 0)
    with pytest.raises(IntelligenceError):
        script(value, grant, v2, 'v2', 0)
    with pytest.raises(IntelligenceError):
        analyze(value, grant)
    assert len(value['calls']) == 3 and originals(value) == value['old']
