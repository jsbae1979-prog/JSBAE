"""Two new scripts from saved analysis; real budget with Fake HTTP, never live API."""

import json
from copy import deepcopy
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_comparison_approval import (
    CONSUMED,
    OPTIONS,
    analyze,
    approve,
    originals,
    respond,
    script,
)
from test_comparison_approval import comparison as comparison  # noqa: PLC0414
from test_comparison_approval import no_external_calls as no_external_calls  # noqa: PLC0414
from test_comparison_approval import sessions as sessions  # noqa: PLC0414
from test_comparison_approval import state as state  # noqa: PLC0414
from test_comparison_approval import store as store  # noqa: PLC0414
from test_explainer_review_safety import compact_script

from newsflow.db.models import (
    APIRequestReservation,
    AuditLog,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    utcnow,
)
from newsflow.intelligence.api_settings import APISettingsError
from newsflow.intelligence.comparison_approval import approve_comparison, comparison_review
from newsflow.intelligence.provider import ProviderTimeoutError
from newsflow.intelligence.service import IntelligenceError


def completed_comparison(value):
    grant = approve(value)
    v1, v2 = analyze(value, grant), analyze(value, grant, 'v2')
    script(value, grant, v1, 'v1', 0)
    script(value, grant, v2, 'v2', 0)
    script(value, grant, v2, 'v2', 1)
    assert len(value['calls']) == 5
    return v2


def approve_recheck(value, parent, consent=True):
    review = comparison_review(value['sessions'], value['ids'], analysis_id=parent)
    assert review['steps'] == ['script-a-v2', 'script-b-v2']
    return approve_comparison(value['sessions'], article_ids=value['ids'], analysis_id=parent,
                               review_token=review['token'], consent=consent)


def recheck(value, grant, parent, index=0, **changes):
    respond(value, compact_script())
    fields = {'article_ids': [value['ids'][index]], 'news_usage': 'STANDARD',
              'script_prompt_version': 'v2', 'comparison_approval_id': grant,
              'comparison_step': 'script-b-v2' if index else 'script-a-v2'}
    fields.update(changes)
    return value['service'].generate(parent, 30, 'claude_api', True, OPTIONS, **fields)


def test_reuses_successful_analysis_for_exactly_two_new_scripts_without_resetting_old_grant(comparison):
    value = comparison
    parent = completed_comparison(value)
    before = originals(value)
    with value['sessions']() as session:
        saved_parent = deepcopy(session.get(IntelligenceRun, parent).result)
        old_drafts = {d.id: (d.content, d.revision, d.review_status) for d in session.scalars(select(ContentDraft))}
    grant = approve_recheck(value, parent)
    assert approve_recheck(value, parent) == grant
    a = recheck(value, grant, parent)
    b = recheck(value, grant, parent, 1)
    assert a != b and len(value['calls']) == 7
    with pytest.raises(IntelligenceError):
        recheck(value, grant, parent)
    assert len(value['calls']) == 7 and originals(value) == before
    with value['sessions']() as session:
        assert session.get(IntelligenceRun, parent).result == saved_parent
        assert all((session.get(ContentDraft, i).content, session.get(ContentDraft, i).revision,
                    session.get(ContentDraft, i).review_status) == old for i, old in old_drafts.items())
        assert len([v for v in session.scalars(select(AuditLog).where(AuditLog.event == CONSUMED))
                    if json.loads(v.message).get('approval_id') == grant]) == 2
    assert not value['budget'].readiness('claude_api', value['store'], 'script')['ready']


@pytest.mark.parametrize('consent', [False, None, 1])
def test_new_paid_scope_still_requires_explicit_consent(comparison, consent):
    parent = completed_comparison(comparison)
    with pytest.raises(APISettingsError):
        approve_recheck(comparison, parent, consent)
    assert len(comparison['calls']) == 5


@pytest.mark.parametrize('change', ['parent_result', 'parent_usage', 'proof', 'expiry', 'wrong_step'])
def test_changed_saved_context_or_analysis_attempt_cannot_dispatch(comparison, change):
    value = comparison
    parent = completed_comparison(value)
    grant = approve_recheck(value, parent)
    with value['sessions'].begin() as session:
        if change == 'parent_result':
            row = session.get(IntelligenceRun, parent)
            row.result = {**row.result, 'overview': '수정된 내용'}
        elif change == 'parent_usage':
            row = session.scalar(select(APIRequestReservation).where(
                APIRequestReservation.request_id == f'intelligence:{parent}'))
            row.usage = {**row.usage, 'prompt_tokens': 999}
        elif change == 'proof':
            row = session.scalar(select(APIRequestReservation).where(
                APIRequestReservation.request_id == f'intelligence:{parent}'))
            row.status = 'unknown'
        elif change == 'expiry':
            row = session.get(AuditLog, grant)
            value_json = json.loads(row.message)
            value_json['expires_at'] = (utcnow()-timedelta(seconds=1)).isoformat()
            row.message = json.dumps(value_json)
    with pytest.raises(IntelligenceError):
        if change == 'wrong_step':
            analyze(value, grant, 'v2')
        else:
            recheck(value, grant, parent)
    assert len(value['calls']) == 5


def test_current_article_edits_never_replace_the_approved_saved_source(comparison):
    value = comparison
    parent = completed_comparison(value)
    grant = approve_recheck(value, parent)
    with value['sessions'].begin() as session:
        saved = deepcopy(session.get(IntelligenceRun, parent).evidence['articles'][0]['summary'])
        session.get(NewsArticle, value['ids'][0]).summary += ' 새로 수집된 다른 내용'
    identifier = recheck(value, grant, parent)
    payload = json.loads(value['calls'][-1]['messages'][0]['content'])
    assert payload['evidence']['articles'][0]['summary'] == saved
    with value['sessions']() as session:
        assert session.get(ContentDraft, identifier).sources['articles'][0]['summary'] == saved
    assert len(value['calls']) == 6


@pytest.mark.parametrize('failure', ['timeout', 'bad_json', 'missing_usage', 'timing_warning', 'hook_warning'])
def test_first_script_failure_unknown_or_review_warning_stops_second(comparison, monkeypatch, failure):
    value = comparison
    parent = completed_comparison(value)
    grant = approve_recheck(value, parent)
    original = value['adapter']._open

    def broken(*args):
        if failure == 'timeout':
            value['calls'].append('synthetic timeout')
            raise ProviderTimeoutError()
        if failure == 'bad_json':
            value['document']['content'][0]['text'] = 'PRIVATE_BAD_RESPONSE'
        elif failure == 'missing_usage':
            value['document']['usage'] = {}
        elif failure in {'timing_warning', 'hook_warning'}:
            payload = compact_script()
            if failure == 'timing_warning':
                payload['scenes'][1]['narration'] *= 2
            else:
                payload['hook'] = '내레이션에 없는 질문인가요?'
            value['document']['content'][0]['text'] = json.dumps(payload)
        return original(*args)

    with monkeypatch.context() as patch:
        patch.setattr(value['adapter'], '_open', broken)
        if failure in {'timeout', 'bad_json'}:
            with pytest.raises(IntelligenceError):
                recheck(value, grant, parent)
        else:
            recheck(value, grant, parent)
    with pytest.raises(IntelligenceError):
        recheck(value, grant, parent, 1)
    with pytest.raises(IntelligenceError):
        recheck(value, grant, parent)
    assert len(value['calls']) == 6
