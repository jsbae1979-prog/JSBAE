from pathlib import Path
from types import SimpleNamespace
import hashlib
import pytest
from starlette.testclient import TestClient
from bat_distribution import serpapi_key_registration as m
from bat_distribution.operation import OperatingRequests
from newsflow.distribution.local_access import LaunchSession,LocalAccess
from newsflow.intelligence.credentials import FakeCipher,CredentialError
from newsflow.news.serpapi import SerpApiKeys
from newsflow.news.serpapi_settings import settings
from newsflow.gui.serpapi_routes import router
from test_api_settings import sessions
from test_character_automation_routes import gui

@pytest.fixture
def registration(gui,sessions):
    from newsflow.distribution.windows_profile import private_directory
    gui.root=private_directory(gui.root/'private-profile')
    gui.app.state.sessions=sessions;gui.app.state.config=SimpleNamespace(data_dir=gui.root)
    gui.app.state.coordinator=SimpleNamespace(lock_path=gui.root/'collection.lock')
    gui.app.include_router(router)
    class Native(FakeCipher):
        buffers=[];calls=0
        def protect(self,plain,entropy):
            assert bytes(entropy)==hashlib.sha256(SerpApiKeys.ENTROPY).digest()
            self.buffers.append(plain);self.calls+=1
            return super().protect(plain,entropy)
        def unprotect(self,*args):pytest.fail('Registration must never decrypt')
    native=Native();owner=m.install(gui.app,gui.root,lambda:native)
    launch=LaunchSession(18779);auth=LocalAccess(gui.app,launch)
    client=TestClient(owner.wrap(OperatingRequests(auth),auth),base_url=launch.origin,
        client=('127.0.0.1',43211),follow_redirects=False)
    client.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]))
    client.get('/api/studio/characters/profiles')
    def post(**values):return client.post(m.PATH,data={'csrf_token':client.cookies.get('newsflow_csrf'),**values},
        headers={'Origin':launch.origin})
    return SimpleNamespace(gui=gui,owner=owner,client=client,native=native,post=post,sessions=sessions,launch=launch)

def test_registration_encrypts_only_on_explicit_save_and_preserves_previous_ciphertext(registration):
    r=registration;target=r.gui.root/SerpApiKeys.FILE;target.write_bytes(b'previous synthetic ciphertext')
    assert r.native.calls==0
    assert r.post(api_key='sk-synthetic-serpapi-registration-0123456789',approved='true').status_code==303
    assert target.read_bytes().startswith(b'FAKE') and r.native.calls==1
    assert all(not any(p) for p in r.native.buffers)
    backups=list((r.gui.root/'credential-backups').glob('serpapi-*/'+SerpApiKeys.FILE))
    assert len(backups)==1 and backups[0].read_bytes()==b'previous synthetic ciphertext'
    before=target.read_bytes()
    assert r.post(api_key='',approved='true').status_code==303
    assert target.read_bytes()==before and r.native.calls==1 and settings(r.sessions)['approved_at']
    with pytest.raises(CredentialError):r.gui.app.state.serpapi_keys.key()
    with pytest.raises(CredentialError):r.gui.app.state.serpapi_keys.save('sk-synthetic-not-authorized-0123456789')
    assert r.client.post('/news/curation/serpapi').status_code==403

@pytest.mark.parametrize('mode',['csrf','origin','session'])
def test_key_registration_keeps_auth_origin_csrf_and_secret_unchanged(registration,mode):
    r=registration;target=r.gui.root/SerpApiKeys.FILE;target.write_bytes(b'preserve')
    body={'api_key':'sk-synthetic-invalid-auth-0123456789','csrf_token':r.client.cookies.get('newsflow_csrf')}
    headers={'Origin':r.launch.origin}
    if mode=='csrf':body['csrf_token']='bad'
    if mode=='origin':headers['Origin']='https://outside.invalid'
    if mode=='session':r.client.cookies.clear()
    assert r.client.post(m.PATH,data=body,headers=headers).status_code in {401,403}
    assert target.read_bytes()==b'preserve' and r.native.calls==0

def test_wrong_profile_rejected_before_native_construction(registration,tmp_path):
    with pytest.raises(CredentialError):m.install(registration.gui.app,tmp_path/'other',lambda:pytest.fail('No native'))

@pytest.mark.parametrize('failure',['protect','replace'])
def test_failed_key_replace_preserves_existing_key_and_redacts_error(registration,monkeypatch,failure):
    r=registration;target=r.gui.root/SerpApiKeys.FILE;target.write_bytes(b'original protected key')
    def fail(*args):raise OSError('synthetic secret diagnostic must not escape')
    if failure=='protect':monkeypatch.setattr(r.native,'protect',fail)
    else:monkeypatch.setattr(m.os,'replace',fail)
    response=r.post(api_key='sk-synthetic-failed-save-0123456789',approved='true')
    assert response.status_code==422 and 'diagnostic' not in response.text
    assert 'sk-synthetic' not in response.text and target.read_bytes()==b'original protected key'
    assert all(not any(p) for p in r.native.buffers)
    assert not list(r.gui.root.glob('*.registration-*.tmp'))
