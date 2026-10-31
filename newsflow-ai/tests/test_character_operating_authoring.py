"""Operating authoring boundaries with synthetic profiles, keys and transports only."""
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from starlette.testclient import TestClient

from bat_distribution import character_authoring as m
from bat_distribution.operation import OperatingRequests
from newsflow.character.authoring import CHARACTER_ANALYSIS_INSTRUCTION, TOPIC_INSTRUCTION
from newsflow.character.schema import CharacterError
from newsflow.db.models import APIRequestReservation, utcnow
from newsflow.distribution.local_access import LocalAccess, LaunchSession
from newsflow.intelligence.api_providers import AnthropicProvider, OpenAISearchProvider
from newsflow.intelligence.api_settings import APIBudgetService, FakeAPIBudgetService
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, FakeCipher, CredentialError
from newsflow.intelligence.settings import _set
from test_api_settings import sessions, configured
from test_character_authoring_v3 import candidate
from test_character_automation_routes import gui
from test_character_episode_automation import setup_episode
from test_character_episode_schema import script

KEYS = {'claude_api': 'synthetic-authoring-anthropic-0123456789',
        'openai': 'synthetic-authoring-openai-0123456789'}


@pytest.fixture
def connected(gui, sessions, monkeypatch):
    # This scope never prepares/renders video; no FFmpeg binary is needed or run.
    from newsflow.video.engine import FFmpegAdapter
    monkeypatch.setattr(FFmpegAdapter, 'executable', staticmethod(lambda name, config: gui.root / (name+'.exe')))
    service, video, identifier, registry, profile = setup_episode(gui.root)
    service.sessions = sessions
    gui.app.state.character = service
    state = SimpleNamespace(calls=[], decryptions=[], buffers=[], timeout=False)
    for provider, kind in (('claude_api', AnthropicKeyStore), ('openai', AIKeyStore)):
        kind(gui.root, FakeCipher()).save(KEYS[provider])
        configured(sessions, provider)

    class Native(FakeCipher):
        def unprotect(self, payload, entropy):
            state.decryptions.append(bytes(entropy))
            result = super().unprotect(payload, entropy)
            state.buffers.append(result)
            return result

    def fake_post(adapter, body, options):
        provider = 'claude_api' if isinstance(adapter, AnthropicProvider) else 'openai'
        assert adapter.key_provider() == KEYS[provider]
        state.calls.append((provider, deepcopy(body)))
        if state.timeout:
            raise TimeoutError('synthetic unknown')
        adapter.last_usage = {'prompt_tokens': 10, 'completion_tokens': 20}
        instruction = body.get('system', body.get('instructions'))
        if instruction == CHARACTER_ANALYSIS_INSTRUCTION:
            answer = candidate()
        elif instruction == TOPIC_INSTRUCTION:
            answer = {'topics': [{'topic': '정리하다 낮잠을 자는 토끼', 'category': '정원', 'joke_type': '반전'}]}
        else:
            answer = script()
        text = json.dumps(answer, ensure_ascii=False)
        if provider == 'claude_api':
            return {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': text}]}
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}

    monkeypatch.setattr(AnthropicProvider, '_post', fake_post)
    monkeypatch.setattr(OpenAISearchProvider, '_post', fake_post)
    monkeypatch.setattr(m, 'APIBudgetService', FakeAPIBudgetService)
    connection = m.install(gui.app, gui.root, Native)
    launch = LaunchSession(18779)
    authenticated = LocalAccess(gui.app, launch)
    boundary = connection.wrap(OperatingRequests(authenticated), authenticated)
    client = TestClient(boundary, base_url=launch.origin, client=('127.0.0.1', 43123))
    # Synthetic session bootstrap, never any operating cookie/token.
    token = launch.claim(launch.launch_url().split('#')[1])
    client.cookies.set(launch.cookie_name, token)
    assert client.get('/api/studio/characters/profiles').status_code == 200
    def post(path, **values):
        return client.post(path, data={**values, 'csrf_token': client.cookies.get('newsflow_csrf')},
                           headers={'Origin': launch.origin})
    return SimpleNamespace(gui=gui, service=service, video=video, identifier=identifier, profile=profile,
                           connection=connection, client=client, post=post, state=state, sessions=sessions,
                           launch=launch)


@pytest.mark.parametrize('model,provider,kind', [('claude-sonnet-4-6', 'claude_api', AnthropicKeyStore),
                                              ('gpt-4.1-mini', 'openai', AIKeyStore)])
def test_authenticated_analysis_uses_only_selected_stored_key(connected, model, provider, kind):
    c = connected
    result = c.post(m.ANALYZE, asset=c.gui.asset, model=model, request_id='analysis:one', consent='true')
    assert result.status_code == 200 and len(result.json()['candidates']) == 3
    assert c.state.calls[0][0] == provider
    assert c.state.decryptions == [hashlib.sha256(kind.ENTROPY).digest()]
    assert all(not any(buffer) for buffer in c.state.buffers)
    with pytest.raises(CharacterError): c.connection.authoring.keys[provider].key()
    with pytest.raises(CredentialError): c.connection.authoring.keys[provider].save('not-permitted')
    with pytest.raises(CredentialError): c.connection.authoring.keys[provider].clear()
    assert not c.video.sent


def test_topics_and_new_episode_use_existing_product_budget_and_explicit_commands(connected):
    c = connected
    path = f"/api/studio/characters/profiles/{c.profile['id']}/topics/generate"
    result = c.post(path, count=1, model='claude-sonnet-4-6', request_id='topics:one', consent='true')
    assert result.status_code == 200 and len(result.json()['topics']) == 1
    assert c.post(m.AUTO_STORY, job_id=c.identifier, consent='true').status_code == 200
    job = c.service.read(c.identifier)
    assert job['state'] == 'script_review' and job['script']['schema_version'] == 3
    assert len(c.state.calls) == 2
    assert c.post(m.AUTO_STORY, job_id=c.identifier, consent='true').status_code == 200
    assert len(c.state.calls) == 2  # Existing valid story is reused.
    with c.sessions() as session:
        rows = list(session.scalars(select(APIRequestReservation)))
        assert len(rows) == 2 and all(row.status == 'success' for row in rows)
    assert not c.video.sent


def test_separate_requests_are_supported_without_a_global_one_shot_gate(connected):
    c = connected
    for identifier in ('analysis:first', 'analysis:second'):
        assert c.post(m.ANALYZE, asset=c.gui.asset, model='gpt-4.1-mini', request_id=identifier,
                      consent='true').status_code == 200
    assert len(c.state.calls) == 2
    assert c.post(m.ANALYZE, asset=c.gui.asset, model='gpt-4.1-mini', request_id='analysis:first',
                  consent='true').status_code == 409
    assert len(c.state.calls) == 2  # Existing idempotency reservation prevents replay.


@pytest.mark.parametrize('failure', ['cookie', 'csrf', 'origin', 'consent'])
def test_auth_origin_csrf_and_consent_still_precede_key_access(connected, failure):
    c = connected
    values = {'asset': c.gui.asset, 'model': 'claude-sonnet-4-6', 'request_id': 'analysis:blocked',
              'consent': 'true', 'csrf_token': c.client.cookies.get('newsflow_csrf')}
    headers = {'Origin': c.launch.origin}
    if failure == 'cookie': c.client.cookies.clear()
    if failure == 'csrf': values['csrf_token'] = 'invalid'
    if failure == 'origin': headers['Origin'] = 'https://outside.invalid'
    if failure == 'consent': values['consent'] = 'false'
    assert c.client.post(m.ANALYZE, data=values, headers=headers).status_code == 403
    assert not c.state.calls and not c.state.decryptions


@pytest.mark.parametrize('path', ['/api/studio/characters/queues/'+'a'*32+'/scripts',
    '/api/studio/characters/'+'a'*32+'/regeneration/submit', '/character/'+'a'*32+'/submit',
    '/ai/analyze', '/api/studio/characters/profiles/analyze/extra'])
def test_unrelated_external_routes_remain_closed(connected, path):
    assert connected.post(path, consent='true').status_code in {403, 404}
    assert not connected.state.calls and not connected.state.decryptions


def test_missing_stored_key_never_uses_environment(connected, monkeypatch):
    c = connected
    (c.gui.root / AnthropicKeyStore.FILE).unlink()
    monkeypatch.setenv(AnthropicKeyStore.ENV, KEYS['claude_api'])
    assert c.post(m.ANALYZE, asset=c.gui.asset, model='claude-sonnet-4-6', request_id='missing',
                  consent='true').status_code == 409
    assert not c.connection.authoring.keys['claude_api'].status()['configured']
    assert not c.state.calls and not c.state.decryptions


def test_unknown_response_preserves_reservation_and_is_never_replayed(connected):
    c = connected
    c.state.timeout = True
    values = {'asset': c.gui.asset, 'model': 'claude-sonnet-4-6', 'request_id': 'unknown', 'consent': 'true'}
    assert c.post(m.ANALYZE, **values).status_code == 409
    assert c.post(m.ANALYZE, **values).status_code == 409
    assert len(c.state.calls) == 1
    with c.sessions() as session:
        row = session.scalar(select(APIRequestReservation))
        assert row.status == 'unknown' and row.reserved_usd != '0'


@pytest.mark.parametrize('verified', [False, True])
def test_real_budget_missing_or_expired_verification_is_not_bypassed(connected, verified):
    c = connected
    c.connection.authoring.budget = APIBudgetService(c.sessions)
    if verified:
        with c.sessions.begin() as session:
            _set(session, 'api_claude_api_verified_model', 'claude-sonnet-4-6')
            _set(session, 'api_claude_api_authentication_verified_at', (utcnow()-timedelta(hours=25)).isoformat())
    assert c.post(m.ANALYZE, asset=c.gui.asset, model='claude-sonnet-4-6', request_id='unverified',
                  consent='true').status_code == 409
    assert not c.state.calls and not c.state.decryptions


def test_direct_authoring_outside_authenticated_request_has_no_authority(connected):
    with pytest.raises(CharacterError):
        connected.connection.authoring.analyze(b'not-an-image', provider='claude_api',
            model='claude-sonnet-4-6', request_id='outside', consent=True)
    assert connected.connection.authoring.last_failure['dispatched'] is False
    assert not connected.state.calls and not connected.state.decryptions


def test_legacy_episode_uses_original_scope_without_new_authority(connected):
    c = connected
    job = c.service.read(c.identifier)
    job.pop('automation_version')
    c.service.save(job)
    assert c.post(m.AUTO_STORY, job_id=c.identifier, consent='true').status_code == 403
    assert not c.state.calls and not c.state.decryptions
