"""Normal key-save UI only; fake cipher/temp profile/ASGI, never a live app or API."""
import ast
import hashlib
import hmac
from pathlib import Path
import re
import secrets
from types import SimpleNamespace

import pytest
from fastapi import FastAPI,Request
from fastapi.responses import HTMLResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.testclient import TestClient

from bat_distribution import higgsfield_key_registration as m
from bat_distribution.operation import OperatingRequests
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.gui.video_ai_routes import router
from newsflow.intelligence.credentials import CredentialError
from newsflow.video.ai.keys import VideoAIKeyStore

KEY='synthetic-higgsfield-only-key-0123456789'
NEXT='synthetic-next-higgsfield-key-0123456789'


class Native:
    def __init__(self):
        self.protect_calls=0
        self.unprotect_calls=0
        self.failure=False
        self.last_plain=None
    def protect(self,payload,entropy):
        self.protect_calls+=1
        self.last_plain=payload
        assert bytes(entropy)==hashlib.sha256(VideoAIKeyStore.ENTROPY).digest()
        if self.failure:raise ValueError('synthetic native error must be hidden')
        return bytearray(b'SYNTHETIC-DPAPI\0'+bytes(v^0x5A for v in payload))
    def unprotect(self,*args):
        self.unprotect_calls+=1
        raise AssertionError('Registration must never decrypt')


@pytest.fixture
def ui(tmp_path,monkeypatch):
    profile=tmp_path/'profile'
    profile.mkdir()
    def private(path):
        assert path.is_relative_to(tmp_path)
        path.mkdir(exist_ok=True)
        return path
    monkeypatch.setattr(m,'_private',private)
    app=FastAPI()
    old=VideoAIKeyStore(profile)
    app.state.video_ai=SimpleNamespace(keys=old)
    app.state.config=SimpleNamespace(data_dir=profile)
    untouched=SimpleNamespace(keys=object(),video_keys=object(),budget=object(),calls={'prepare':1})
    app.state.character=untouched
    app.include_router(router)
    @app.get('/api/studio/modules/settings')
    async def metadata():return app.state.video_ai.keys.status()
    source=Path(__file__).resolve().parents[3]/'src/newsflow/main.py'
    tree=ast.parse(source.read_text(encoding='utf8'))
    nodes=[node for node in ast.walk(tree)
           if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'valid','security'}]
    assert len(nodes)==2
    namespace=dict(app=app,secret=b'synthetic-registration-csrf',hashlib=hashlib,hmac=hmac,re=re,
                   secrets=secrets,Request=Request,HTMLResponse=HTMLResponse,StarletteHTTPException=StarletteHTTPException)
    exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),namespace)
    native=Native()
    registration=m.install(app,profile,lambda:native)
    session=LaunchSession(18771)
    authenticated=LocalAccess(app,session)
    client=TestClient(registration.wrap(OperatingRequests(authenticated),authenticated),
                      base_url=session.origin,client=('127.0.0.1',11001),follow_redirects=False)
    def authenticate():
        token=session.launch_url().split('#',1)[1]
        assert client.post('/__local/claim',headers={'Origin':session.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
        assert client.get('/api/studio/modules/settings').status_code==200
    def save(value=KEY,**changes):
        headers={'Origin':session.origin,**changes.pop('headers',{})}
        data={'api_key':value,'csrf_token':client.cookies.get('newsflow_csrf','bad'),**changes}
        return client.post(m.PATH,data=data,headers=headers)
    return SimpleNamespace(app=app,native=native,registration=registration,client=client,
                           session=session,authenticate=authenticate,save=save,profile=profile,
                           target=profile/VideoAIKeyStore.FILE,untouched=untouched,old=old)


def test_real_auth_origin_csrf_and_explicit_submit_are_required(ui):
    assert ui.save().status_code==403
    assert ui.native.protect_calls==0 and not ui.target.exists()
    ui.authenticate()
    assert ui.save(csrf_token='bad').status_code==403
    assert ui.save(headers={'Origin':'https://outside.invalid'}).status_code==403
    assert ui.native.protect_calls==0 and not ui.target.exists()
    response=ui.save()
    assert response.status_code==303 and response.headers['location']=='/video-ai-settings?saved=key'
    assert ui.target.exists() and KEY.encode() not in ui.target.read_bytes()
    assert KEY not in response.text and KEY not in repr(dict(response.headers))
    assert ui.native.protect_calls==1 and ui.native.unprotect_calls==0
    assert all(value==0 for value in ui.native.last_plain)
    assert m._CONTEXT.get() is None
    assert ui.app.state.character is ui.untouched and ui.untouched.calls=={'prepare':1}


def test_reregistration_keeps_recoverable_original_ciphertext_without_logging(ui,capsys):
    ui.authenticate()
    assert ui.save().status_code==303
    original=ui.target.read_bytes()
    assert ui.save(NEXT).status_code==303
    assert ui.target.read_bytes()!=original
    backups=list((ui.profile/'credential-backups').glob('higgsfield-*/video-ai-key.dpapi'))
    assert len(backups)==1 and backups[0].read_bytes()==original
    assert not list(ui.profile.glob('*.tmp')) and ui.native.protect_calls==2
    captured=capsys.readouterr()
    assert not captured.out and not captured.err
    status=ui.client.get('/api/studio/modules/settings').json()
    assert status['configured'] and status['stored'] and 'key' not in status
    assert ui.native.unprotect_calls==0


def test_registration_never_decrypts_clears_or_restores_global_native_factory(ui,monkeypatch):
    from newsflow.oauth import vault,production_dpapi
    first,second=object(),object()
    monkeypatch.setattr(vault,'_DPAPI',first)
    monkeypatch.setattr(production_dpapi,'_DPAPI',second)
    store=ui.app.state.video_ai.keys
    with pytest.raises(CredentialError):store.key()
    with pytest.raises(CredentialError):store.clear()
    with pytest.raises(CredentialError):store.save(KEY)
    with pytest.raises(CredentialError):store._cipher.unprotect(bytearray(),bytearray())
    with pytest.raises(CredentialError):store._cipher.protect(bytearray(KEY.encode()),bytearray(m._ENTROPY))
    ui.authenticate()
    assert ui.save().status_code==303
    assert vault._DPAPI is first and production_dpapi._DPAPI is second
    assert ui.native.protect_calls==1 and ui.native.unprotect_calls==0


@pytest.mark.parametrize('method,path',[('GET',m.PATH),('POST',m.PATH+'/'),('POST',m.PATH+'/clear'),
    ('POST','/video-ai-settings/models'),('POST','/video-ai-settings'),('POST','/api/studio/characters/auto-story'),
    ('POST','/character/'+'a'*32+'/submit')])
def test_no_other_route_method_or_paid_permission_is_added(ui,method,path):
    ui.authenticate()
    response=ui.client.request(method,path,data={'api_key':KEY,'csrf_token':ui.client.cookies.get('newsflow_csrf')},
                               headers={'Origin':ui.session.origin})
    assert response.status_code==403 and ui.native.protect_calls==0 and not ui.target.exists()


def test_invalid_key_never_creates_file_backup_or_native_request(ui):
    ui.authenticate()
    assert ui.save('short').status_code==422
    assert not ui.target.exists() and not (ui.profile/'credential-backups').exists()
    assert ui.native.protect_calls==0


def test_native_failure_preserves_original_and_backup_and_hides_diagnostics(ui):
    ui.authenticate()
    old=b'synthetic previous ciphertext'
    ui.target.write_bytes(old)
    ui.native.failure=True
    response=ui.save()
    assert response.status_code==422 and ui.target.read_bytes()==old
    backups=list((ui.profile/'credential-backups').glob('higgsfield-*/video-ai-key.dpapi'))
    assert len(backups)==1 and backups[0].read_bytes()==old
    assert 'synthetic native error' not in response.text and KEY not in response.text
    assert not list(ui.profile.glob('*.tmp')) and all(value==0 for value in ui.native.last_plain)


def test_backup_failure_stops_before_encryption_or_replacement(ui,monkeypatch):
    ui.authenticate()
    old=b'synthetic previous ciphertext'
    ui.target.write_bytes(old)
    def fail_backup(target):raise CredentialError('보호 파일 백업을 완료하지 못했습니다.')
    monkeypatch.setattr(ui.registration,'backup',fail_backup)
    assert ui.save().status_code==422
    assert ui.target.read_bytes()==old and ui.native.protect_calls==0


def test_wrong_entropy_is_denied_even_inside_authenticated_save(ui,monkeypatch):
    ui.authenticate()
    cipher=ui.app.state.video_ai.keys._cipher
    original=cipher.protect
    monkeypatch.setattr(cipher,'protect',lambda payload,entropy:original(payload,bytearray(b'wrong entropy')))
    assert ui.save().status_code==422 and ui.native.protect_calls==0 and not ui.target.exists()


def test_wrong_target_path_cannot_save_another_user_file(ui,tmp_path):
    ui.authenticate()
    other=tmp_path/'other-user.dpapi'
    other.write_bytes(b'synthetic other user ciphertext')
    ui.app.state.video_ai.keys.path=other
    assert ui.save().status_code==422 and other.read_bytes()==b'synthetic other user ciphertext'
    assert ui.native.protect_calls==0 and not ui.target.exists()


def test_install_rejects_profile_other_than_app_data_directory(ui,tmp_path):
    other=tmp_path/'other-profile'
    other.mkdir()
    before=ui.app.state.video_ai.keys
    with pytest.raises(CredentialError):m.install(ui.app,other,lambda:ui.native)
    assert ui.app.state.video_ai.keys is before


def test_source_hook_is_operating_only_before_deny_and_inside_existing_control():
    path=Path(__file__).resolve().parents[1]/'windows_live.py'
    source=path.read_text(encoding='utf8')
    tree=ast.parse(source)
    start=next(node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name=='start')
    segment=ast.get_source_segment(source,start)
    assert segment.index('character_native_factory = _DPAPI')<segment.index('disable_credential_decryption()')
    assert segment.index('disable_credential_decryption()')<segment.index('install_key_registration(app, config.profile, character_native_factory)')
    installers=[node for node in ast.walk(start) if isinstance(node,ast.If)
                and any(isinstance(child,ast.Call) and isinstance(child.func,ast.Name)
                        and child.func.id=='install_key_registration' for child in ast.walk(node))]
    exact=[node for node in installers if ast.unparse(node.test)=="config.profile_kind in {'restored-local-operation', 'portable-local-operation'}"]
    assert len(exact)==1
    assert segment.index('character_trial.wrap(')<segment.index('key_registration.wrap(')<segment.index('protected = Control(')
    assert 'key_registration.wrap(request_boundary, authenticated_app)' in segment
