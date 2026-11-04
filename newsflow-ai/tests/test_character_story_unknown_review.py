"""Synthetic-only review of old unknown authoring without replay or global authority."""
from copy import deepcopy
from datetime import timedelta
import json
from uuid import uuid4
import urllib.request

import pytest
from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AuditLog, utcnow
from newsflow.character.kling import check, snapshot as settings_snapshot
from newsflow.intelligence.api_settings import APIBudgetService, APISettingsError
from newsflow.intelligence.settings import _set
from test_api_settings import sessions
from test_character_automation_routes import gui
from test_character_authoring_v3 import Store
from test_character_episode_schema import image
from test_character_operating_authoring import connected


AUTO = '/api/studio/characters/auto-story'
MODEL = 'claude-sonnet-4-6'


@pytest.fixture(autouse=True)
def never_external(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Only injected synthetic providers are permitted')
    monkeypatch.setattr(urllib.request, 'urlopen', forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, 'open', forbidden)


def old_unknown(c):
    budget = c.connection.authoring.budget
    row = budget.reserve(provider='claude_api', request_id='episode:' + 'a'*32 + ':script:1',
                         kind='script', model=MODEL, max_output_tokens=4000, key_store=Store())
    budget.finish(row.id, status='unknown')
    return row.id


def snapshot(c, identifier):
    with c.sessions() as session:
        row = session.get(APIRequestReservation, identifier)
        return {col.name: deepcopy(getattr(row, col.name)) for col in row.__table__.columns}


def acknowledgements(c):
    with c.sessions() as session:
        return [deepcopy(row.message) for row in session.scalars(select(AuditLog).where(
            AuditLog.event == 'api_episode_story_once_ack'))]


def review(c, identifier=None):
    return c.client.get(f'/api/studio/characters/{identifier or c.identifier}/story-review')


def token(c):
    response = review(c)
    assert response.status_code == 200, response.text
    state = response.json()
    assert state['ready'], state
    assert state['review']['count'] == 1
    assert state['review']['held_usd'] != '0'
    return state['review']['token']


def submit(c, identifier=None, **changes):
    values = {'job_id': identifier or c.identifier, 'consent': 'true', **changes}
    return c.post(AUTO, **values)


def new_episode(c, *, provider='claude_api', topic='또 다른 합성 정원 작업'):
    job = c.service.read(c.identifier)
    settings = check(job['studio_selection'])
    settings['script_model'] = MODEL if provider == 'claude_api' else 'gpt-4.1-mini'
    identifier, _ = c.service.create_episode(topic, '5', reference=image(), settings=settings,
        request_id=uuid4().hex, profile=c.profile)
    return identifier


def test_review_get_is_readonly_and_explicit_current_job_request_runs_once(connected):
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    before_job = deepcopy(c.service.read(c.identifier))
    reviewed = token(c)
    assert review(c).json()['review']['token'] == reviewed
    assert not c.state.calls and not c.state.decryptions
    assert c.service.read(c.identifier) == before_job and not acknowledgements(c)
    result = submit(c, review_token=reviewed, review_consent='true')
    assert result.status_code == 200, result.text
    assert c.service.read(c.identifier)['state'] == 'script_review'
    assert len(c.state.calls) == 1 and len(c.state.decryptions) == 1
    assert snapshot(c, old) == before
    assert len(acknowledgements(c)) == 1
    audit = json.loads(acknowledgements(c)[0])
    assert 'new_episode_story_once' in json.dumps(audit)
    assert submit(c, review_token=reviewed, review_consent='true').status_code == 200
    assert len(c.state.calls) == 1 and len(acknowledgements(c)) == 1
    assert snapshot(c, old) == before and not c.video.sent and not c.video.uploads


@pytest.mark.parametrize('approval', ['missing', 'token_only', 'consent_only'])
def test_unknown_cannot_be_skipped_without_both_review_and_consent(connected, approval):
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    reviewed = token(c)
    values = {'token_only': {'review_token': reviewed},
              'consent_only': {'review_consent': 'true'}}.get(approval, {})
    result = submit(c, **values)
    assert result.status_code == 409
    assert not c.state.calls and not c.state.decryptions and not acknowledgements(c)
    assert snapshot(c, old) == before


@pytest.mark.parametrize('kind', ['reserved', 'incomplete', 'current_job'])
def test_unfinished_or_current_job_requests_never_get_new_request_authority(connected, kind):
    c = connected
    old = old_unknown(c)
    with c.sessions.begin() as session:
        row = session.get(APIRequestReservation, old)
        if kind == 'reserved': row.status = 'reserved'
        if kind in {'reserved', 'incomplete'}: row.finished_at = None
        if kind == 'current_job': row.request_id = f'episode:{c.identifier}:script:1'
    before = snapshot(c, old)
    response = review(c)
    assert response.status_code == 200, response.text
    state = response.json()
    assert not state['ready']
    messages = {
        'reserved': '진행 중인 AI 요청이 있습니다. 완료 후 확인하세요.',
        'incomplete': '끝나지 않은 결과 불명 요청이 있습니다. 기존 요청 상태를 먼저 확인하세요.',
    }
    if kind in messages: assert state['message'] == messages[kind]
    assert not (state.get('review') or {}).get('token')
    assert submit(c, review_token='f'*64, review_consent='true').status_code == 409
    assert not c.state.calls and not c.state.decryptions
    assert snapshot(c, old) == before and not acknowledgements(c)


@pytest.mark.parametrize('change', ['topic', 'character', 'duration', 'model', 'budget',
                                   'unknown_cost', 'authentication', 'approval', 'new_unknown'])
def test_changed_review_context_cannot_dispatch_with_stale_token(connected, change):
    c = connected
    old = old_unknown(c)
    reviewed = token(c)
    if change in {'topic', 'character', 'duration', 'model', 'budget'}:
        job = c.service.read(c.identifier)
        if change == 'topic': job['topic'] = '변경된 합성 주제'
        if change == 'character': job['character']['personality'] = '변경된 합성 성격'
        if change == 'duration':
            job['duration'] = 20
            settings = check(job['studio_selection'])
            settings['duration'] = 20
            job['studio_selection'] = settings_snapshot(settings)
        if change == 'model':
            job['claude_model'] = 'claude-haiku-4-5-20251001'
            settings = check(job['studio_selection'])
            settings['script_model'] = 'claude-haiku-4-5-20251001'
            job['studio_selection'] = settings_snapshot(settings)
        if change == 'budget': job['episode_limit'] = '4.50'
        c.service.save(job)
    else:
        with c.sessions.begin() as session:
            if change == 'unknown_cost':
                session.get(APIRequestReservation, old).reserved_usd = '0.99'
            elif change == 'authentication':
                _set(session, 'api_claude_api_authentication_verified_at', utcnow().isoformat())
            elif change == 'approval':
                _set(session, 'api_claude_api_approved_at', '')
            else:
                row = session.get(APIRequestReservation, old)
                values = {col.name: deepcopy(getattr(row, col.name)) for col in row.__table__.columns}
                values.update(id=uuid4().hex, request_id='episode:' + 'b'*32 + ':script:1')
                session.add(APIRequestReservation(**values))
    before = snapshot(c, old)
    result = submit(c, review_token=reviewed, review_consent='true')
    assert result.status_code == 409, result.text
    assert not c.state.calls and not c.state.decryptions and not acknowledgements(c)
    assert snapshot(c, old) == before


@pytest.mark.parametrize('other', ['same_provider', 'other_provider'])
def test_token_cannot_move_to_another_episode_or_provider(connected, other):
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    reviewed = token(c)
    another = new_episode(c, provider='openai' if other == 'other_provider' else 'claude_api')
    result = submit(c, another, review_token=reviewed, review_consent='true')
    assert result.status_code == 409, result.text
    assert not c.state.calls and not c.state.decryptions and not acknowledgements(c)
    assert snapshot(c, old) == before


@pytest.mark.parametrize('guard', ['csrf', 'origin', 'cookie', 'execution_consent'])
def test_local_access_and_execution_consent_precede_review_authority(connected, guard):
    c = connected
    old_unknown(c)
    reviewed = token(c)
    values = {'job_id': c.identifier, 'consent': 'true', 'review_token': reviewed,
              'review_consent': 'true', 'csrf_token': c.client.cookies.get('newsflow_csrf')}
    headers = {'Origin': c.launch.origin}
    if guard == 'csrf': values['csrf_token'] = 'wrong'
    if guard == 'origin': headers['Origin'] = 'https://foreign.invalid'
    if guard == 'cookie': c.client.cookies.clear()
    if guard == 'execution_consent': values['consent'] = 'false'
    assert c.client.post(AUTO, data=values, headers=headers).status_code == 403
    assert not c.state.calls and not c.state.decryptions and not acknowledgements(c)


@pytest.mark.parametrize('kind', ['search', 'analysis', 'script'])
def test_scoped_story_review_never_allows_generic_provider_requests(connected, kind):
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    reviewed = token(c)
    assert submit(c, review_token=reviewed, review_consent='true').status_code == 200
    with pytest.raises(APISettingsError):
        c.connection.authoring.budget.reserve(provider='claude_api', request_id='unrelated:'+kind,
            kind=kind, model=MODEL, max_output_tokens=100, max_search_calls=int(kind == 'search'), key_store=Store())
    assert snapshot(c, old) == before and len(c.state.calls) == 1


@pytest.mark.parametrize('guard', ['request_cap', 'episode_cap', 'expired_auth'])
def test_review_does_not_bypass_cost_or_authentication_gates(connected, guard):
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    if guard == 'request_cap':
        with c.sessions.begin() as session: _set(session, 'api_claude_api_request_limit_usd', '0.01')
    elif guard == 'episode_cap':
        job = c.service.read(c.identifier)
        job['episode_limit'] = '0.01'
        c.service.save(job)
    else:
        c.connection.authoring.budget = APIBudgetService(c.sessions)
        with c.sessions.begin() as session:
            _set(session, 'api_claude_api_verified_model', MODEL)
            _set(session, 'api_claude_api_authentication_verified_at', (utcnow()-timedelta(hours=25)).isoformat())
    state = review(c).json()
    result = submit(c, review_token=(state.get('review') or {}).get('token', ''), review_consent='true')
    assert result.status_code == 409
    assert not c.state.calls and not c.state.decryptions
    assert snapshot(c, old) == before


def test_new_unknown_after_explicit_review_stays_unknown_and_is_not_replayed(connected):
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    reviewed = token(c)
    c.state.timeout = True
    assert submit(c, review_token=reviewed, review_consent='true').status_code == 409
    assert len(c.state.calls) == 1
    job = c.service.read(c.identifier)
    assert job['state'] == 'script_failed' and not job['response_received']
    assert not review(c).json()['ready']
    assert submit(c, review_token=reviewed, review_consent='true').status_code == 409
    assert len(c.state.calls) == 1 and snapshot(c, old) == before
    with c.sessions() as session:
        rows = list(session.scalars(select(APIRequestReservation)))
        assert len(rows) == 2 and all(row.status == 'unknown' for row in rows)




def test_new_reserved_request_after_review_blocks_before_dispatch(connected):
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    reviewed = token(c)
    pending_id = uuid4().hex
    with c.sessions.begin() as session:
        values = deepcopy(before)
        values.update(id=pending_id, request_id='episode:' + 'c'*32 + ':script:1',
                      status='reserved', finished_at=None)
        session.add(APIRequestReservation(**values))
    pending = snapshot(c, pending_id)
    assert submit(c, review_token=reviewed, review_consent='true').status_code == 409
    assert not c.state.calls and not c.state.decryptions and not acknowledgements(c)
    assert snapshot(c, old) == before and snapshot(c, pending_id) == pending
    with c.sessions() as session:
        assert len(list(session.scalars(select(APIRequestReservation)))) == 2


def test_audit_and_new_reservation_roll_back_together_on_database_failure(connected):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError
    c = connected
    old = old_unknown(c)
    before = snapshot(c, old)
    reviewed = token(c)
    injected = []

    def fail_after_flush(session, flush_context):
        new_request = any(isinstance(row, APIRequestReservation) and
            row.request_id.startswith(f'episode:{c.identifier}:script:') for row in session.new)
        if new_request:
            assert any(isinstance(row, AuditLog) and row.event == 'api_episode_story_once_ack'
                       for row in session.new)
            injected.append(True)
            raise SQLAlchemyError('synthetic database failure after both inserts')

    event.listen(c.sessions.class_, 'after_flush', fail_after_flush)
    try:
        result = submit(c, review_token=reviewed, review_consent='true')
    finally:
        event.remove(c.sessions.class_, 'after_flush', fail_after_flush)
    assert result.status_code == 409 and injected == [True]
    assert not c.state.calls and not c.state.decryptions and not acknowledgements(c)
    assert snapshot(c, old) == before
    with c.sessions() as session:
        assert [row.id for row in session.scalars(select(APIRequestReservation))] == [old]
