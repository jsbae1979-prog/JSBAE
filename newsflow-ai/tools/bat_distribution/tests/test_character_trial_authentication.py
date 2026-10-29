"""Only synthetic metadata GETs behind real LocalAccess and existing CSRF middleware."""
import ast
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import pytest
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.testclient import TestClient

from bat_distribution import character_trial as m
from newsflow.character.schema import CharacterError
from newsflow.distribution.local_access import LaunchSession, LocalAccess
from newsflow.intelligence import api_connection
from newsflow.intelligence.credentials import CredentialError
from test_character_trial import sample, read, KEY


@pytest.fixture
def authentication(sample, monkeypatch, request):
    if getattr(request, 'param', None) in {'archive', 'archive-one'}:
        review = request.getfixturevalue('batch')
        if request.param == 'archive-one':
            review = dict(list(review.items())[:1])
        sample.service.sessions = request.getfixturevalue('sessions')
        sample.trial = m.Trial(sample.service, sample.root, sample.policy, unknown_review=review)
    app = FastAPI()
    api_keys = object()
    app.state.api_keys = api_keys
    m._register_routes(app, sample.trial)
    # Compile the unchanged two security functions, not create_app or a launcher.
    source = Path(__file__).resolve().parents[3] / 'src/newsflow/main.py'
    tree = ast.parse(source.read_text(encoding='utf8'))
    nodes = [node for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {'valid', 'security'}]
    assert len(nodes) == 2
    namespace = dict(app=app, secret=b'synthetic-auth-csrf', hashlib=hashlib, hmac=hmac, re=re,
                     secrets=secrets, Request=Request, HTMLResponse=HTMLResponse,
                     StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    session = LaunchSession(18772)
    authenticated = LocalAccess(app, session)
    client = TestClient(sample.trial.wrap(authenticated, authenticated), base_url=session.origin,
                        client=('127.0.0.1', 11002))
    state = SimpleNamespace(requests=[], checks=0, verified=False, timeout=False, other_scope=False)
    monkeypatch.setattr(m, '_authentication', lambda sessions: (m.CLAUDE, state.verified))

    def transport(request, timeout, limit):
        state.requests.append(request)
        assert request.get_method() == 'GET'
        assert request.full_url == 'https://api.anthropic.com/v1/models/' + m.CLAUDE
        if state.timeout:
            raise TimeoutError
        return json.dumps({'type': 'model', 'id': m.CLAUDE}).encode()

    def check(sessions, key_store, *, consent):
        state.checks += 1
        assert sessions is sample.service.sessions and key_store is sample.service.keys and consent is True
        if state.other_scope:
            with pytest.raises(CharacterError):
                sample.service.video_keys.key()
            with pytest.raises(CredentialError):
                key_store._cipher.unprotect(bytearray(b'synthetic'), bytearray(b'wrong-entropy'))
            assert sample.native.calls == 0
        code = api_connection._check_model(m.CLAUDE, key_store.key(), transport)
        state.verified = code == 'success'
        return api_connection._result(code)

    monkeypatch.setattr(api_connection, 'check_claude_connection', check)

    def login():
        bootstrap = session.launch_url().split('#', 1)[1]
        assert client.post('/__local/claim', headers={'Origin': session.origin,
                           'X-NewsFlow-Bootstrap': bootstrap}).status_code == 204
        assert client.get(m._STATUS).status_code == 200
        return client.cookies.get('newsflow_csrf')

    def post(csrf, *, consent='true', origin=None):
        return client.post(m._AUTHENTICATE, headers={'Origin': origin or session.origin},
                           data={'csrf_token': csrf, 'consent': consent})

    return SimpleNamespace(sample=sample, client=client, session=session, state=state, login=login, post=post,
                           app=app, api_keys=api_keys)


def test_authenticate_denied_auth_origin_csrf_and_consent_never_claim_or_decrypt(authentication):
    a = authentication
    assert a.post('bad').status_code == 403
    assert a.client.get(m._STATUS).status_code == 403
    csrf = a.login()
    assert a.post('bad').status_code == 403
    assert a.post(csrf, origin='https://outside.invalid').status_code == 403
    assert a.post(csrf, consent='false').status_code == 409
    assert not read(a.sample)['calls']
    assert a.state.checks == 0 and a.state.requests == [] and a.sample.native.calls == 0


def test_authenticate_performs_one_metadata_get_without_job_or_general_key_replacement(authentication):
    a = authentication
    csrf = a.login()
    before = a.client.get(m._STATUS).json()
    assert before['ready'] and not before['authAttempted'] and not before['authenticationVerified']
    assert a.sample.native.calls == 0
    result = a.post(csrf)
    assert result.status_code == 200 and result.json()['ok'] is True and result.json()['code'] == 'success'
    assert set(result.json()) == {'ok', 'code', 'message'} and KEY not in result.text
    after = a.client.get(m._STATUS).json()
    assert not after['ready'] and after['authAttempted'] and after['authenticationVerified']
    row = read(a.sample)
    assert row['calls'] == {'authenticate': 1} and row['job_id'] is None
    assert row['script']['state'] == 'unspent' and row['video']['state'] == 'unspent'
    assert a.state.checks == len(a.state.requests) == a.sample.native.calls == 1
    assert a.app.state.api_keys is a.api_keys
    assert m._CONTEXT.get() is None


def test_authentication_timeout_consumes_one_attempt_and_never_retries(authentication):
    a = authentication
    csrf = a.login()
    a.state.timeout = True
    response = a.post(csrf)
    assert response.status_code == 200 and response.json()['code'] == 'timeout'
    assert a.post(csrf).status_code == 409
    assert a.state.checks == len(a.state.requests) == 1
    assert read(a.sample)['outcomes']['authenticate'] == 'failed_or_unknown'
    assert a.client.get(m._STATUS).json()['authAttempted'] is True


def test_authentication_scope_cannot_decrypt_video_key_or_wrong_entropy(authentication):
    a = authentication
    csrf = a.login()
    a.state.other_scope = True
    assert a.post(csrf).json()['ok'] is True
    assert a.sample.native.calls == 1 and len(a.state.requests) == 1


def test_authentication_outside_scoped_wrapper_cannot_use_keys(authentication):
    a = authentication
    with pytest.raises(CharacterError):
        a.sample.trial.authenticate(consent=True)
    with pytest.raises(CharacterError):
        a.sample.service.keys.key()
    assert not read(a.sample)['calls'] and a.sample.native.calls == 0 and a.state.checks == 0
