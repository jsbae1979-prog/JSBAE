"""Exact local endpoint deltas; all auth/data and providers are synthetic."""
import ast
import hashlib
import hmac
import re
import secrets
from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.testclient import TestClient

from bat_distribution.operation import OperatingRequests
from bat_distribution.restored_install import RestoredRequests
from newsflow.distribution.local_access import LaunchSession, LocalAccess

JOB = 'a' * 32


def complete_request(coroutine):
    # These fake ASGI calls await only inline fakes; no OS loop/socket is needed.
    with pytest.raises(StopIteration) as completed:
        coroutine.send(None)
    return completed.value.value


def test_local_render_delegates_to_existing_auth_boundary_without_bypass():
    received=[]
    async def authenticated(scope,receive,send):
        received.append(scope)
        authorized=dict(scope['headers']).get(b'x-synthetic-auth')==b'accepted'
        await send({'type':'http.response.start','status':204 if authorized else 403,'headers':[]})
        await send({'type':'http.response.body','body':b''})
    boundary=OperatingRequests(authenticated)
    async def request(headers):
        sent=[]
        async def receive():return {'type':'http.request','body':b'reviewed=true','more_body':False}
        async def send(event):sent.append(event)
        scope={'type':'http','method':'POST','path':'/character/'+JOB+'/render','headers':headers}
        await boundary(scope,receive,send)
        assert received[-1] is scope
        return sent[0]['status']
    assert complete_request(request([]))==403
    assert complete_request(request([(b'x-synthetic-auth',b'accepted')]))==204
    assert len(received)==2


def test_render_exception_keeps_external_actions_and_inexact_paths_closed():
    received=[]
    async def inner(scope,receive,send):received.append(scope)
    boundary=OperatingRequests(inner)
    async def request(method,path):
        sent=[]
        async def receive():return {'type':'http.request','body':b'','more_body':False}
        async def send(event):sent.append(event)
        await boundary({'type':'http','method':method,'path':path,'headers':[]},receive,send)
        assert sent[0]['status']==403
    for method,path in [('POST','/character/'+JOB+'/'+action) for action in ('submit','check','prepare','write')]+[
            ('GET','/character/'+JOB+'/render'),('POST','/character/'+JOB+'/render/'),
            ('POST','/character/'+'A'*32+'/render'),('POST','/api/studio/characters/auto-story')]:
        complete_request(request(method,path))
    assert not received


def recorder():
    received = []

    async def app(scope, receive, send):
        data = b''
        if scope['method'] == 'POST':
            while True:
                event = await receive()
                data += event.get('body', b'')
                if not event.get('more_body'):
                    break
        received.append((scope['method'], scope['path'], data))
        await send({'type': 'http.response.start', 'status': 204, 'headers': []})
        await send({'type': 'http.response.body', 'body': b''})

    return app, received


@pytest.mark.parametrize('method,path', [
    ('GET', '/api/studio/video-models'), ('HEAD', '/api/studio/video-models'),
    ('POST', '/api/studio/characters/' + JOB + '/settings'),
    ('POST', '/character/' + JOB + '/render'),
    ('GET', '/api/samples/character-robot/copy-file'),
    ('HEAD', '/api/samples/character-robot/copy-file'),
    ('GET', '/character/' + JOB + '/clips/1'),
    ('HEAD', '/character/' + JOB + '/clips/1'),
])
def test_only_exact_local_paths_reach_inner_app(method, path):
    app, received = recorder()
    body = b'csrf_token=synthetic&settings=%7B%7D'
    response = TestClient(OperatingRequests(app)).request(
        method, path, content=body if method == 'POST' else None,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
    )
    assert response.status_code == 204
    assert received == [(method, path, body if method == 'POST' else b'')]


@pytest.mark.parametrize('method,path', [
    ('POST', '/api/studio/video-models'), ('GET', '/api/studio/characters/' + JOB + '/settings'),
    ('POST', '/api/studio/characters/auto-story'),
    ('POST', '/character/' + JOB + '/write'), ('POST', '/character/' + JOB + '/prepare'),
    ('POST', '/character/' + JOB + '/submit'), ('POST', '/character/' + JOB + '/check'),
    ('GET', '/character/' + JOB + '/render'), ('POST', '/character/' + JOB + '/render/'),
    ('POST', '/character/' + 'A' * 32 + '/render'),
    ('POST', '/api/samples/character-robot/copy-file'),
    ('POST', '/api/samples/character-robot/copy'), ('POST', '/api/samples/character-robot/visibility'),
    ('GET', '/api/samples'), ('GET', '/api/samples/character-robot/file'),
    ('GET', '/api/samples/character-robot/poster'),
    ('GET', '/api/samples/' + 'a' * 49 + '/copy-file'),
    ('GET', '/api/samples/id_with_underscore/copy-file'),
    ('POST', '/api/studio/characters/' + 'a' * 31 + '/settings'),
    ('POST', '/api/studio/characters/' + 'A' * 32 + '/settings'),
    ('POST', '/api/studio/characters/' + JOB + '/settings/other'),
    ('POST', '/api/feed-batches/1/step'), ('GET', '/oauth/callback'),
    ('POST', '/publish/1'),
    ('POST', '/character/' + JOB + '/clips/1'),
    ('GET', '/character/' + JOB + '/clips/0'),
    ('GET', '/character/' + JOB + '/clips/61'),
])
def test_wrong_methods_paths_and_external_actions_remain_denied(method, path):
    app, received = recorder()
    assert TestClient(OperatingRequests(app)).request(method, path).status_code == 403
    assert not received


def test_delta_does_not_change_original_readonly_validation_class():
    app, received = recorder()
    client = TestClient(RestoredRequests(app))
    assert client.get('/api/studio/video-models').status_code == 403
    assert client.post('/api/studio/characters/' + JOB + '/settings').status_code == 403
    assert client.get('/api/samples/character-robot/copy-file').status_code == 403
    assert not received


def test_new_endpoints_keep_real_localaccess_origin_and_original_csrf_middleware():
    app = FastAPI()
    requests = []

    @app.get('/api/studio/video-models')
    async def models():
        requests.append('models')
        return {'synthetic': True}

    @app.post('/api/studio/characters/{job}/settings')
    async def settings(job: str):
        requests.append('settings')
        return {'synthetic': True}

    @app.post('/character/{job}/render')
    async def render(job: str):
        requests.append('render')
        return {'synthetic': True}

    # Load precisely the existing two middleware functions, not the app factory.
    source = Path(__file__).resolve().parents[3] / 'src/newsflow/main.py'
    tree = ast.parse(source.read_text(encoding='utf8'))
    nodes = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in {'valid', 'security'}]
    assert len(nodes) == 2
    scope = dict(app=app, secret=b'synthetic-csrf-only', hashlib=hashlib, hmac=hmac,
                 re=re, secrets=secrets, Request=Request, HTMLResponse=HTMLResponse,
                 StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), scope)
    session = LaunchSession(18771)
    client = TestClient(OperatingRequests(LocalAccess(app, session)),
                        base_url=session.origin, client=('127.0.0.1', 11001))
    assert client.get('/api/studio/video-models').status_code == 403
    assert not requests
    # Synthetic one-time claim only; no real token, cookie or browser session is read.
    token = session.launch_url().split('#', 1)[1]
    claim = client.post('/__local/claim', headers={'Origin': session.origin, 'X-NewsFlow-Bootstrap': token})
    assert claim.status_code == 204
    assert client.get('/api/studio/video-models').status_code == 200
    assert requests == ['models']
    csrf = client.cookies.get('newsflow_csrf')
    target = '/api/studio/characters/' + JOB + '/settings'
    assert client.post(target, data={'csrf_token': 'bad'}, headers={'Origin': session.origin}).status_code == 403
    assert client.post(target, data={'csrf_token': csrf}, headers={'Origin': 'https://outside.invalid'}).status_code == 403
    assert requests == ['models']
    assert client.post(target, data={'csrf_token': csrf}, headers={'Origin': session.origin}).status_code == 200
    assert requests == ['models', 'settings']
    target = '/character/' + JOB + '/render'
    assert client.post(target, data={'csrf_token': 'bad'}, headers={'Origin': session.origin}).status_code == 403
    assert client.post(target, data={'csrf_token': csrf}, headers={'Origin': 'https://outside.invalid'}).status_code == 403
    assert requests == ['models', 'settings']
    assert client.post(target, data={'csrf_token': csrf}, headers={'Origin': session.origin}).status_code == 200
    assert requests == ['models', 'settings', 'render']
    assert client.post('/character/' + JOB + '/submit', data={'csrf_token': csrf}, headers={'Origin': session.origin}).status_code == 403
    assert client.post('/api/studio/characters/auto-story', data={'csrf_token': csrf}, headers={'Origin': session.origin}).status_code == 403
    assert requests == ['models', 'settings', 'render']


@pytest.mark.parametrize('method,path',[
 ('GET','/api/studio/characters/profiles'),
 ('GET','/api/studio/characters/profiles/char_'+JOB+'/topics'),
 ('GET','/api/studio/characters/queues'),
 ('GET','/api/studio/characters/queues/'+JOB),
 ('POST','/api/studio/characters/profiles/save'),
 ('POST','/api/studio/characters/profiles/char_'+JOB+'/topics/manual'),
 ('POST','/api/studio/characters/'+JOB+'/script'),
 ('GET','/character/'+JOB+'/clips/60'),
])
def test_episode_local_routes_retain_inner_security(method,path):
    app,received=recorder()
    assert TestClient(OperatingRequests(app)).request(method,path).status_code==204
    assert received

@pytest.mark.parametrize('path',[
 '/api/studio/characters/profiles/analyze',
 '/api/studio/characters/profiles/char_'+JOB+'/topics/generate',
 '/api/studio/characters/queues/'+JOB+'/scripts',
 '/api/studio/characters/queues/'+JOB+'/advance',
 '/api/studio/characters/queues/'+JOB+'/approve-videos',
 '/api/studio/characters/profiles/char_'+JOB+'/delete/extra',
])
def test_local_route_delta_does_not_grant_external_execution(path):
    app,received=recorder()
    assert TestClient(OperatingRequests(app)).post(path).status_code==403
    assert not received
