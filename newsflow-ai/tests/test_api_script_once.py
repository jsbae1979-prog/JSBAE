"""One explicit script exception with immutable old records; no external requests."""
import json
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_api_settings import configured, reserve
from test_api_settings import sessions as sessions  # noqa: PLC0414
from test_api_settings import store as store  # noqa: PLC0414
from test_api_unknown_acknowledgement import acknowledge, original, unknown
from test_api_unknown_acknowledgement import no_external_calls as no_external_calls  # noqa: PLC0414

from newsflow.db.models import AuditLog, IntelligenceRun, utcnow
from newsflow.intelligence.api_settings import APISettingsError, FakeAPIBudgetService, allow_script_once

MODEL = 'claude-sonnet-4-6'


def prepare(sessions, store):
    configured(sessions)
    old = unknown(sessions, store)
    acknowledge(sessions, store, old)
    with sessions.begin() as session:
        analysis = IntelligenceRun(kind='analysis', status='success', provider='claude_api',
                                   options={'model': MODEL}, evidence={'articles': [{'id': 31}]},
                                   result={'summary': 'synthetic'}, message='synthetic', finished_at=utcnow())
        session.add(analysis)
        session.flush()
        identifier = analysis.id
    return identifier


def approve(sessions, identifier, **changes):
    args = {'analysis_id': identifier, 'model': MODEL, 'duration': 30, 'consent': True}
    args.update(changes)
    allow_script_once(sessions, 'claude_api', **args)


def script(sessions, identifier, **changes):
    with sessions.begin() as session:
        options = {'model': MODEL, 'duration': 30, 'analysis_run_id': identifier, **changes}
        run = IntelligenceRun(kind='script', status='running', provider='claude_api', options=options,
                              evidence={}, result={}, message='synthetic')
        session.add(run)
        session.flush()
        return run.id


def attempt(sessions, store, run_id):
    return reserve(FakeAPIBudgetService(sessions), store, f'intelligence:{run_id}', kind='script')


def test_one_script_consumes_approval_atomically_preserving_originals(sessions, store):
    identifier = prepare(sessions, store)
    before = original(sessions)
    approve(sessions, identifier)
    record = attempt(sessions, store, script(sessions, identifier))
    FakeAPIBudgetService(sessions).finish(record.id, status='unknown')
    current = {row['id']: row for row in original(sessions)}
    assert all(current[row['id']] == row for row in before)
    with sessions() as session:
        assert len(list(session.scalars(select(AuditLog).where(AuditLog.event == 'api_script_once_consumed')))) == 1
    with pytest.raises(APISettingsError):
        attempt(sessions, store, script(sessions, identifier))
    with pytest.raises(APISettingsError):
        approve(sessions, identifier)


@pytest.mark.parametrize('changes', [{'duration': 45}, {'model': 'other'}, {'analysis_run_id': 999}])
def test_scope_mismatch_never_allows_dispatch(sessions, store, changes):
    identifier = prepare(sessions, store)
    approve(sessions, identifier)
    with pytest.raises(APISettingsError):
        attempt(sessions, store, script(sessions, identifier, **changes))
    assert len(original(sessions)) == 1


@pytest.mark.parametrize('consent', [False, None, 1])
def test_explicit_approval_required(sessions, store, consent):
    identifier = prepare(sessions, store)
    with pytest.raises(APISettingsError):
        approve(sessions, identifier, consent=consent)


def test_expiry_changed_analysis_and_old_unknown_invalidate_grant(sessions, store):
    identifier = prepare(sessions, store)
    approve(sessions, identifier)
    with sessions.begin() as session:
        entry = session.scalar(select(AuditLog).where(AuditLog.event == 'api_script_once_approval'))
        value = json.loads(entry.message)
        value['expires_at'] = (utcnow() - timedelta(seconds=1)).isoformat()
        entry.message = json.dumps(value)
    with pytest.raises(APISettingsError):
        attempt(sessions, store, script(sessions, identifier))


def test_search_and_general_script_readiness_stay_blocked(sessions, store):
    identifier = prepare(sessions, store)
    approve(sessions, identifier)
    budget = FakeAPIBudgetService(sessions)
    for kind in ['search', 'script']:
        assert not budget.readiness('claude_api', store, kind)['ready']
        with pytest.raises(APISettingsError):
            reserve(budget, store, 'arbitrary:' + kind, kind=kind, max_search_calls=int(kind == 'search'))


def test_prior_failed_script_prevents_new_approval(sessions, store):
    identifier = prepare(sessions, store)
    run_id = script(sessions, identifier)
    with sessions.begin() as session:
        session.get(IntelligenceRun, run_id).status = 'failed'
    with pytest.raises(APISettingsError):
        approve(sessions, identifier)

@pytest.mark.parametrize('version', ['v1', 'v2'])
@pytest.mark.parametrize('fail', [False, True])
def test_service_dispatches_only_one_script_and_preserves_analysis(sessions, store, fail, version, monkeypatch):
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', version)
    from newsflow.db.models import ContentDraft
    from newsflow.intelligence.api_providers import FakeAPIProvider
    from newsflow.intelligence.provider import Options, ProviderTimeoutError
    from newsflow.intelligence.service import IntelligenceError, IntelligenceService

    identifier = prepare(sessions, store)
    with sessions.begin() as session:
        analysis = session.get(IntelligenceRun, identifier)
        analysis.evidence = {'articles': [{'id': 31, 'title': '합성 지역 정책 자료', 'summary': '합성 요약',
                                          'url': 'https://example.com/story', 'publisher': '합성 출처',
                                          'sources': [{'url': 'https://example.com/story', 'publisher': '합성 출처'}]}],
                             'groups': [[31]]}
    approve(sessions, identifier)
    adapter = FakeAPIProvider('claude_api', ProviderTimeoutError() if fail else None)
    service = IntelligenceService(sessions, api_key_stores={'claude_api': store},
                                  api_providers={'claude_api': adapter}, api_budget=FakeAPIBudgetService(sessions))
    options = Options(model=MODEL)
    with pytest.raises(IntelligenceError):
        service.generate(identifier, 30, 'claude_api', False, options)
    assert adapter.calls == []
    if fail:
        with pytest.raises(IntelligenceError):
            service.generate(identifier, 30, 'claude_api', True, options)
    else:
        draft_id = service.generate(identifier, 30, 'claude_api', True, options)
        with sessions() as session:
            draft = session.get(ContentDraft, draft_id)
            assert draft.duration == 30 and draft.review_status == 'review_required'
            assert sum(scene['seconds'] for scene in draft.content['scenes']) == 30
    assert adapter.calls == ['script']
    with pytest.raises(IntelligenceError):
        service.generate(identifier, 30, 'claude_api', True, options)
    assert adapter.calls == ['script']


@pytest.mark.parametrize('mutate', ['analysis', 'unknown', 'request_limit'])
def test_changed_bound_records_or_budget_remain_blocked(sessions, store, mutate):
    from newsflow.db.models import APIRequestReservation
    from newsflow.intelligence.settings import _set

    identifier = prepare(sessions, store)
    approve(sessions, identifier)
    with sessions.begin() as session:
        if mutate == 'analysis':
            session.get(IntelligenceRun, identifier).result = {'summary': 'changed'}
        elif mutate == 'unknown':
            session.scalar(select(APIRequestReservation)).reserved_usd = '123'
        else:
            _set(session, 'api_claude_api_request_limit_usd', '0')
    with pytest.raises(APISettingsError):
        attempt(sessions, store, script(sessions, identifier))

def test_fresh_explicit_recheck_is_once_and_preserves_consumed_failure(sessions, store):
    identifier = prepare(sessions, store)
    approve(sessions, identifier)
    failed_id = script(sessions, identifier)
    record = attempt(sessions, store, failed_id)
    FakeAPIBudgetService(sessions).finish(record.id, status='failed', usage={
        'prompt_tokens': 1650, 'completion_tokens': 824, 'search_calls': 0})
    with sessions.begin() as session:
        session.get(IntelligenceRun, failed_id).status = 'failed'
    before = {row['id']: row for row in original(sessions)}
    approve(sessions, identifier, previous_script_id=failed_id)
    with pytest.raises(APISettingsError):
        approve(sessions, identifier, previous_script_id=failed_id)
    next_id = script(sessions, identifier)
    fresh = attempt(sessions, store, next_id)
    assert fresh.id != record.id
    with pytest.raises(APISettingsError):
        attempt(sessions, store, script(sessions, identifier))
    after = {row['id']: row for row in original(sessions)}
    assert all(after[key] == value for key, value in before.items())


@pytest.mark.parametrize('state', ['unknown', 'success', 'reserved'])
def test_explicit_recheck_never_allows_unknown_success_or_active(sessions, store, state):
    identifier = prepare(sessions, store)
    approve(sessions, identifier)
    prior = script(sessions, identifier)
    record = attempt(sessions, store, prior)
    if state != 'reserved':
        FakeAPIBudgetService(sessions).finish(record.id, status=state, usage={
            'prompt_tokens': 10, 'completion_tokens': 10, 'search_calls': 0})
    with sessions.begin() as session:
        session.get(IntelligenceRun, prior).status = 'failed'
    with pytest.raises(APISettingsError):
        approve(sessions, identifier, previous_script_id=prior)
