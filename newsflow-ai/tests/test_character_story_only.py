"""Synthetic files, ASGI and provider only. No installed application is imported."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode

import pytest

from bat_distribution import character_story_only as m
from newsflow.character.claude import CharacterWriter
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.schema import CharacterError
from newsflow.character.service import fingerprint, SAFE_ERRORS
from newsflow.intelligence.api_settings import APIBudgetService
from newsflow.intelligence.credentials import AnthropicKeyStore, CredentialError
from test_api_settings import sessions, store
from test_character_kling_studio import studio, png, story

KEY = 'synthetic-story-only-key-0123456789'


@pytest.fixture
def sample(studio, monkeypatch):
    service = studio.service
    profile = service.root.parent
    profile.mkdir(exist_ok=True)
    started = datetime.now(UTC) - timedelta(seconds=2)
    identifier, _ = service.create_studio('합성 테스트 주제', '2', '4.50', reference=png(),
        settings={**DEFAULTS, 'video_model': O3, 'native_resolution': 'std',
                  'duration': 30, 'clip_seconds': 6, 'sound': 'on'}, request_id='d' * 32)
    job = service.read(identifier)
    old = profile / 'character-trials' / ('e' * 32)
    old.mkdir(parents=True)
    prior = old / 'journal.json'
    prior.write_text(json.dumps({'schemaVersion': 1,
        'script': {'state': 'unknown_or_over_limit', 'reserved_usd': '.25'},
        'video': {'state': 'reserved', 'reserved_usd': '3.40'}}), encoding='utf8')
    (profile / AnthropicKeyStore.FILE).write_bytes(b'synthetic ciphertext')
    policy = {'schemaVersion': 1, 'id': 'f' * 32, 'created_after': started.isoformat(),
              'expires_at': (started + timedelta(hours=1)).isoformat(),
              'topic_sha256': hashlib.sha256(job['topic'].encode()).hexdigest(),
              'reference_sha256': job['reference_sha256'],
              'selection_sha256': fingerprint(job['studio_selection']),
              'script_model': m.CLAUDE, 'script_limit_usd': '.25',
              'prior_exposure_usd': '3.65', 'total_limit_usd': '4.50',
              'prior_journals': {'e' * 32: hashlib.sha256(prior.read_bytes()).hexdigest()}}
    state = SimpleNamespace(calls=[], native=0, fail=False, payloads=[], inner=0, normal=0)

    def private(path):
        assert path.is_relative_to(profile)
        path.mkdir(exist_ok=True)
        return path

    monkeypatch.setattr(m, '_private', private)

    class Native:
        def unprotect(self, payload, entropy):
            state.native += 1
            assert bytes(payload) == b'synthetic ciphertext'
            assert bytes(entropy) == hashlib.sha256(AnthropicKeyStore.ENTROPY).digest()
            return bytearray(KEY.encode())

    def fake_post(writer, body, options):
        assert scope.read_receipt()['state'] == 'started_or_unknown'
        assert writer.key_provider() == KEY
        state.calls.append('story')
        state.payloads.append(deepcopy(body))
        if state.fail:
            raise TimeoutError('synthetic unknown response')
        writer.last_usage = {'prompt_tokens': 100, 'completion_tokens': 500}
        result = story(duration=30, sound='off')
        return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(result)}]}

    monkeypatch.setattr(CharacterWriter, '_post', fake_post)
    monkeypatch.setattr(CharacterWriter, '_open', lambda *args, **kwargs: pytest.fail('No network'))
    app = SimpleNamespace(state=SimpleNamespace(character=service, config=SimpleNamespace(data_dir=profile)))
    original = (service.keys, service.writer, service.budget, service.video_for)
    scope = m.install(app, profile, policy, Native)

    async def normal(environ, receive, send):
        state.normal += 1
        await send({'type': 'http.response.start', 'status': 403, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'normal denied'})

    async def inner(environ, receive, send):
        state.inner += 1
        body = (await receive())['body']
        values, headers = parse_qs(body.decode()), dict(environ['headers'])
        status = 403
        if (headers.get(b'x-synthetic-auth') == b'yes'
                and headers.get(b'origin') == b'http://127.0.0.1:18768'
                and values.get('csrf_token') == ['synthetic-csrf']):
            try:
                service.write(values['job_id'][0], consent=values.get('consent') == ['true'])
                status = 200
            except (ValueError, CharacterError, CredentialError, *SAFE_ERRORS):
                status = 409
        await send({'type': 'http.response.start', 'status': status, 'headers': []})
        await send({'type': 'http.response.body', 'body': b'synthetic'})

    def post(*, path=m.PATH, job_id=None, auth=True, csrf=True, origin='http://127.0.0.1:18768',
             consent=True, method='POST'):
        body = urlencode({'job_id': job_id or identifier, 'consent': 'true' if consent else 'false',
                          'csrf_token': 'synthetic-csrf' if csrf else 'wrong'}).encode()
        messages = []

        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}

        async def send(value):
            messages.append(value)

        environ = {'type': 'http', 'method': method, 'path': path,
                   'headers': [(b'content-type', b'application/x-www-form-urlencoded'),
                               (b'x-synthetic-auth', b'yes' if auth else b'no'), (b'origin', origin.encode())]}
        coroutine = scope.wrap(normal, inner)(environ, receive, send)
        with pytest.raises(StopIteration):
            coroutine.send(None)
        return messages[0]['status']

    return SimpleNamespace(scope=scope, service=service, identifier=identifier, profile=profile,
                           state=state, policy=policy, prior=prior, old=prior.read_bytes(), original=original,
                           post=post, app=app, native=Native)


def test_one_approved_story_reuses_writer_service_budget_and_keeps_video_closed(sample):
    assert sample.post() == 200
    job = sample.service.read(sample.identifier)
    assert job['state'] == 'script_review' and job['duration'] == 30
    assert [scene['seconds'] for scene in job['script']['scenes']] == [6] * 5
    assert all(scene['narration'] == '' for scene in job['script']['scenes'])
    row = sample.scope.read_receipt()
    assert row['state'] == 'success' and row['reserved_usd'] == '0.25'
    assert 'estimated_usage_usd' in row and 'reported_usd' not in row
    assert row['generation_requests'] == 0 and row['job_id'] == sample.identifier
    assert sample.state.calls == ['story'] and sample.state.native == 1
    assert sample.prior.read_bytes() == sample.old
    assert (sample.service.keys, sample.service.writer, sample.service.budget, sample.service.video_for) == sample.original
    assert sample.service.writer.calls == 0
    assert sample.post() == 409 and sample.state.calls == ['story']


def test_outbound_story_has_only_topic_and_timing_text_no_image_or_private_context(sample):
    assert sample.post() == 200
    body = sample.state.payloads[0]
    assert body['model'] == m.CLAUDE and body['max_tokens'] == 3000
    assert len(body['messages']) == 1 and isinstance(body['messages'][0]['content'], str)
    text = body['messages'][0]['content']
    assert '합성 테스트 주제' in text
    for forbidden in ('base64', 'image', 'reference', 'recent_topics', 'character', 'data:', 'sk-'):
        assert forbidden not in text
    assert '3000' not in text


def test_second_matching_new_job_cannot_consume_same_approval(sample):
    assert sample.post() == 200
    original = sample.service.read(sample.identifier)
    second, _ = sample.service.create_studio(original['topic'], '2', '4.50', reference=png(),
        settings={key: original['studio_selection'][key] for key in DEFAULTS}, request_id='b' * 32)
    assert sample.post(job_id=second) == 409
    assert sample.service.read(second)['state'] == 'needs_script'
    assert sample.scope.read_receipt()['job_id'] == sample.identifier
    assert sample.state.calls == ['story'] and sample.prior.read_bytes() == sample.old


@pytest.mark.parametrize('arguments', [{'auth': False}, {'csrf': False}, {'origin': 'https://example.com'}, {'consent': False}])
def test_auth_csrf_origin_and_explicit_consent_precede_claim(sample, arguments):
    assert sample.post(**arguments) == 403
    assert sample.state.calls == [] and sample.state.native == 0
    assert not sample.scope.path.exists()


@pytest.mark.parametrize('mutation', ['topic', 'reference', 'settings', 'model', 'old_job', 'expired'])
def test_only_exact_approval_subject_and_fresh_job_can_bind(sample, mutation):
    job = sample.service.read(sample.identifier)
    if mutation == 'topic':
        job['topic'] = '다른 합성 주제'
    elif mutation == 'reference':
        (sample.service.folder(sample.identifier) / 'reference.png').write_bytes(png('JPEG'))
    elif mutation == 'settings':
        job['studio_selection']['sound'] = 'off'
    elif mutation == 'model':
        job['claude_model'] = 'claude-haiku-4-5'
    elif mutation == 'old_job':
        job['created_at'] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    else:
        sample.scope.policy['expires_at'] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    sample.service.save(job)
    assert sample.post() == 409
    assert sample.state.calls == [] and sample.state.native == 0
    assert not sample.scope.path.exists()


def test_prior_reserved_and_unknown_exposure_cannot_be_changed_or_refunded(sample):
    sample.prior.write_text('{}', encoding='utf8')
    assert sample.post() == 409
    assert sample.state.calls == [] and sample.state.native == 0


def test_unknown_outcome_preserves_claim_and_refuses_replay_after_scope_recreation(sample):
    sample.state.fail = True
    assert sample.post() == 409
    assert sample.scope.read_receipt()['state'] == 'failed_or_unknown'
    assert sample.scope.read_receipt()['reserved_usd'] == '0.25'
    assert sample.post() == 409 and sample.state.calls == ['story']
    # The same durable receipt also prevents a new in-memory scope from replaying.
    replacement = m.StoryOnly(sample.scope.local, sample.profile, sample.policy, sample.native)
    assert replacement.read_receipt()['state'] == 'failed_or_unknown'
    assert sample.prior.read_bytes() == sample.old


def test_existing_real_authentication_gate_is_not_bypassed(sample):
    sample.scope.local.budget.original = APIBudgetService(sample.service.sessions)
    assert sample.post() == 409
    assert sample.state.calls == [] and sample.state.native == 0
    assert sample.scope.read_receipt()['state'] == 'failed_or_unknown'
    assert sample.scope.read_receipt()['reserved_usd'] == '0.25'


def test_price_bound_over_quarter_dollar_is_rejected_before_io(sample, monkeypatch):
    monkeypatch.setattr(m, '_prices', lambda sessions: {'input': '100', 'output': '100'})
    assert sample.post() == 409
    assert sample.state.calls == [] and sample.state.native == 0


@pytest.mark.parametrize('path,method', [('/character/' + 'a' * 32 + '/submit', 'POST'),
    ('/character/' + 'a' * 32 + '/prepare', 'POST'), ('/ai/generate', 'POST'),
    ('/api/studio/characters/auto-story/', 'POST'), (m.PATH, 'GET')])
def test_unrelated_routes_preserve_original_boundary(sample, path, method):
    assert sample.post(path=path, method=method) == 403
    assert sample.state.normal == 1 and sample.state.inner == 0
    assert sample.state.calls == [] and not sample.scope.path.exists()


def test_scoped_key_never_available_outside_request_or_for_mutation(sample):
    with pytest.raises(CharacterError):
        sample.scope.local.keys.key()
    with pytest.raises(CredentialError):
        sample.scope.local.keys.save(KEY)
    with pytest.raises(CredentialError):
        sample.scope.local.keys.clear()
    with pytest.raises(CredentialError):
        sample.scope.local.keys._cipher.protect(bytearray(b'x'), bytearray())
    assert sample.state.native == 0


def test_overlapping_old_trial_scope_is_not_activated(sample):
    sample.service._approved_character_trial = object()
    with pytest.raises(CharacterError):
        m.install(sample.app, sample.profile, sample.policy, sample.native)
    assert sample.state.native == 0


def test_operating_loader_requires_exact_pinned_policy(sample, tmp_path):
    from bat_distribution.windows_live import character_story_policy
    from bat_distribution.lifecycle import Blocked
    program = tmp_path / 'program'
    (program / 'app').mkdir(parents=True)
    source = sample.profile / 'character-story-only-policy.private.json'
    raw = json.dumps(sample.policy).encode()
    source.write_bytes(raw)
    (program / 'app/layout.json').write_text(json.dumps({
        'characterStoryOnlyPolicySha256': hashlib.sha256(raw).hexdigest()}))
    config = SimpleNamespace(profile_kind='restored-local-operation', program=program, profile=sample.profile)
    assert character_story_policy(config) == sample.policy
    source.write_bytes(raw + b' ')
    with pytest.raises(Blocked):
        character_story_policy(config)


def test_operating_loader_never_revives_expired_or_unconfigured_scope(sample, tmp_path):
    from bat_distribution.windows_live import character_story_policy
    program = tmp_path / 'program'
    (program / 'app').mkdir(parents=True)
    config = SimpleNamespace(profile_kind='restored-local-operation', program=program, profile=sample.profile)
    (program / 'app/layout.json').write_text('{}')
    assert character_story_policy(config) is None
    policy = dict(sample.policy, expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat())
    raw = json.dumps(policy).encode()
    (sample.profile/'character-story-only-policy.private.json').write_bytes(raw)
    (program / 'app/layout.json').write_text(json.dumps({
        'characterStoryOnlyPolicySha256': hashlib.sha256(raw).hexdigest()}))
    assert character_story_policy(config) is None
