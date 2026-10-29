"""Explicit known-failure retries: synthetic ASGI, key cipher and transport only."""
from copy import copy, deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

import pytest

from bat_distribution import character_story_only as m
from newsflow.character.claude import CharacterWriter
from newsflow.character.schema import CharacterError
from newsflow.character.service import SAFE_ERRORS
from newsflow.intelligence.api_settings import APIBudgetService
from newsflow.intelligence.credentials import CredentialError
from test_api_settings import sessions, store
from test_character_kling_studio import studio
from test_character_story_only import sample


@pytest.fixture
def approved(sample, monkeypatch):
    def private(path):
        assert path.is_relative_to(sample.profile)
        path.mkdir(exist_ok=True)
        return path

    monkeypatch.setattr(m, '_private', private)
    original_transport = CharacterWriter._post
    mode = SimpleNamespace(known_failure=True)

    def transport(writer, body, options):
        # Shared fixture asserts a durable claim and a synthetic cipher before IO.
        # Its old scope pointer is replaced below only in this test transport.
        if scope_holder[0] is not sample.scope:
            assert scope_holder[0].read_receipt()['state'] == 'started_or_unknown'
            assert writer.key_provider().startswith('synthetic-story-only-key-')
            sample.state.calls.append('story')
            sample.state.payloads.append(deepcopy(body))
            if sample.state.fail:
                raise TimeoutError('synthetic unknown')
            writer.last_usage = {'prompt_tokens': 100, 'completion_tokens': 500}
            from test_character_kling_studio import story
            result = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(story(30, 'off'))}]}
        else:
            result = original_transport(writer, body, options)
        if mode.known_failure:
            result['content'][0]['text'] = '{}'
        return result

    scope_holder = [sample.scope]
    monkeypatch.setattr(CharacterWriter, '_post', transport)
    assert sample.post() == 409  # Prior approved call got a known, malformed response.
    job = sample.service.read(sample.identifier)
    assert job['response_received'] is True and job['script_attempts'] == 1
    old_path = sample.scope.path
    old_bytes = old_path.read_bytes()
    policy = {'schemaVersion': 2, 'id': '9' * 32, 'job_id': sample.identifier,
              'approved_at': datetime.now(UTC).isoformat(),
              'expires_at': (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
              **{key: sample.policy[key] for key in ('topic_sha256', 'reference_sha256', 'selection_sha256', 'script_model')},
              'script_limit_usd': '0.25', 'story_total_limit_usd': '10',
              'prior_story_exposure_usd': '0.50', 'prior_video_exposure_usd': '3.40',
              'prior_trial_journals': sample.policy['prior_journals'],
              'prior_story_journals': {sample.policy['id']: hashlib.sha256(old_bytes).hexdigest()}}
    fresh = copy(sample.scope.local)
    fresh.keys, fresh.writer, fresh.budget, fresh.video_for = sample.original
    app = SimpleNamespace(state=SimpleNamespace(character=fresh, config=SimpleNamespace(data_dir=sample.profile)))
    scope = m.install(app, sample.profile, policy, sample.native)
    scope_holder[0] = scope
    mode.known_failure = False
    boundary = SimpleNamespace(inner=0, normal=0)

    async def denied(environ, receive, send):
        boundary.normal += 1
        await send({'type': 'http.response.start', 'status': 403, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'normal denied'})

    async def inner(environ, receive, send):
        boundary.inner += 1
        body = (await receive())['body']
        values, headers = parse_qs(body.decode()), dict(environ['headers'])
        status = 403
        if (headers.get(b'x-synthetic-auth') == b'yes' and headers.get(b'origin') == b'http://127.0.0.1:18768'
                and values.get('csrf_token') == ['synthetic-csrf']):
            identifier = environ['path'].split('/')[2] if environ['path'].startswith('/character/') else values['job_id'][0]
            try:
                fresh.write(identifier, consent=values.get('consent') == ['true'])
                status = 200
            except (ValueError, CredentialError, *SAFE_ERRORS) as error:
                import traceback
                from pathlib import Path
                boundary.last_failure = [(Path(item.filename).name, item.name, item.lineno)
                                         for item in traceback.extract_tb(error.__traceback__)]
                status = 409
        await send({'type': 'http.response.start', 'status': status, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'synthetic'})

    def post(*, auto=False, path=None, auth=True, csrf=True, consent=True,
             origin='http://127.0.0.1:18768', extra=None):
        values = {'consent': 'true' if consent else 'false', 'csrf_token': 'synthetic-csrf' if csrf else 'wrong'}
        if auto:
            values['job_id'] = sample.identifier
        values.update(extra or {})
        body, messages = urlencode(values).encode(), []

        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(message):
            messages.append(message)

        environ = {'type': 'http', 'method': 'POST',
            'path': path or (m.PATH if auto else '/character/' + sample.identifier + '/write'),
            'headers': [(b'content-type', b'application/x-www-form-urlencoded'),
                        (b'x-synthetic-auth', b'yes' if auth else b'no'), (b'origin', origin.encode())]}
        coroutine = scope.wrap(denied, inner)(environ, receive, send)
        with pytest.raises(StopIteration):
            coroutine.send(None)
        return messages[0]['status']

    return SimpleNamespace(sample=sample, scope=scope, service=fresh, policy=policy, app=app,
        old_path=old_path, old_bytes=old_bytes, mode=mode, post=post, boundary=boundary)


@pytest.mark.parametrize('auto', [False, True])
def test_explicit_known_failure_retry_uses_new_id_and_preserves_all_old_exposures(approved, auto):
    a = approved
    assert a.post(auto=auto) == 200, getattr(a.boundary, 'last_failure', None)
    row = a.scope.read_receipt()
    assert row['attempt'] == 2 and row['state'] == 'success'
    assert row['reserved_usd'] == '0.25' and 'estimated_usage_usd' in row
    assert a.scope.prior_exposure() == m.Decimal('.50')
    assert a.scope._document()['reserved_usd'] == '0.25'
    assert a.scope._document()['generation_requests'] == 0
    assert a.service.read(a.sample.identifier)['state'] == 'script_review'
    assert a.old_path.read_bytes() == a.old_bytes and a.sample.prior.read_bytes() == a.sample.old
    assert len(a.sample.state.calls) == 2
    assert a.post() == 409 and len(a.sample.state.calls) == 2


def test_known_failure_needs_another_click_and_existing_three_attempt_limit_remains(approved):
    a = approved
    a.mode.known_failure = True
    assert a.post() == 409
    assert len(a.sample.state.calls) == 2 and a.scope.read_receipt()['state'] == 'known_failed'
    first = deepcopy(a.scope.read_receipt())
    assert a.post() == 409
    assert len(a.sample.state.calls) == 3 and a.scope.read_receipt()['attempt'] == 3
    assert a.scope._document()['attempts'][0] == first
    assert a.scope._document()['reserved_usd'] == '0.50'
    assert a.post() == 409 and len(a.sample.state.calls) == 3
    assert a.old_path.read_bytes() == a.old_bytes


def test_unknown_response_is_never_retryable_even_with_more_budget(approved):
    a = approved
    a.sample.state.fail = True
    assert a.post() == 409
    assert a.scope.read_receipt()['state'] == 'failed_or_unknown'
    assert a.post() == 409 and len(a.sample.state.calls) == 2
    assert a.scope._document()['reserved_usd'] == '0.25'


def test_job_flag_alone_cannot_turn_unknown_ledger_result_into_known_failure(approved):
    from sqlalchemy import select
    from newsflow.db.models import APIRequestReservation
    a = approved
    with a.service.sessions.begin() as session:
        row = session.scalar(select(APIRequestReservation).where(
            APIRequestReservation.request_id == 'character:' + a.sample.identifier))
        row.status = 'unknown'
    assert a.post() == 409 and len(a.sample.state.calls) == 1
    assert not a.scope.path.exists()


@pytest.mark.parametrize('kwargs', [{'auth': False}, {'csrf': False}, {'consent': False},
                                  {'origin': 'https://example.com'}, {'extra': {'job_id': 'a' * 32}}])
def test_exact_post_context_auth_origin_csrf_and_consent_precede_retry(approved, kwargs):
    assert approved.post(**kwargs) == 403
    assert len(approved.sample.state.calls) == 1 and not approved.scope.path.exists()


@pytest.mark.parametrize('suffix', ['submit', 'prepare', 'check', 'retry-scene'])
def test_story_scope_never_adds_any_video_execution_authority(approved, suffix):
    assert approved.post(path='/character/' + approved.sample.identifier + '/' + suffix) == 403
    assert approved.boundary.inner == 0 and approved.boundary.normal == 1
    assert not approved.scope.path.exists()


@pytest.mark.parametrize('which', ['trial', 'story'])
def test_hash_pinned_past_journals_cannot_be_changed_to_release_exposure(approved, which):
    path = approved.sample.prior if which == 'trial' else approved.old_path
    path.write_bytes(b'{}')
    assert approved.post() == 409 and len(approved.sample.state.calls) == 1
    assert not approved.scope.path.exists()


def test_new_scope_keeps_existing_account_gate_and_monthly_rules(approved):
    approved.scope.local.budget.original = APIBudgetService(approved.service.sessions)
    assert approved.post() == 409
    assert len(approved.sample.state.calls) == 1
    assert approved.scope.read_receipt()['state'] == 'failed_or_unknown'
    assert approved.scope.read_receipt()['reserved_usd'] == '0.25'


@pytest.mark.parametrize('changes', [{'script_limit_usd': '.26'}, {'job_id': 'other'}, {'approved_at': '2000-01-01T00:00:00+00:00'}])
def test_policy_cannot_expand_per_request_authority(approved, changes):
    with pytest.raises(CharacterError):
        m.validate_policy({**approved.policy, **changes})


def test_legacy_total_limit_does_not_block_explicit_bounded_request(approved):
    a=approved
    a.scope.policy['story_total_limit_usd']='0'
    assert m.validate_policy(a.scope.policy)['story_total_limit_usd']=='0'
    assert a.post()==200
    assert a.scope.read_receipt()['reserved_usd']=='0.25'
    assert a.scope.prior_exposure()==m.Decimal('.50')
    assert a.old_path.read_bytes()==a.old_bytes
