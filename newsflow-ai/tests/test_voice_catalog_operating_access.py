"""Installed composition regression: global native decryption stays disabled."""
import io,json,urllib.request
from types import SimpleNamespace
import pytest
from starlette.testclient import TestClient
from newsflow.intelligence.credentials import CredentialError,FakeCipher
from newsflow.distribution.local_access import LocalAccess,LaunchSession
from newsflow.video.elevenlabs_tts import ElevenLabsKeys
from bat_distribution.operation import OperatingRequests
from bat_distribution.voice_catalog_access import install
from test_elevenlabs_voices import KEY,payload,MP3,no_real_network

class Cipher(FakeCipher):
    def __init__(self):super().__init__();self.reads=0
    def unprotect(self,*args):self.reads+=1;return super().unprotect(*args)

@pytest.fixture
def prepared(app,monkeypatch):
    cipher=Cipher();ElevenLabsKeys(app.state.config.data_dir,cipher).save(KEY)
    def blocked():raise AssertionError('Global native credential capability must stay disabled')
    monkeypatch.setattr('newsflow.intelligence.credentials._native_cipher',blocked)
    catalog=install(app,app.state.config.data_dir,lambda:cipher)
    calls=[]
    def read(self,request,timeout):
        assert request.get_method()=='GET' and request.data is None and request.get_header('Xi-api-key')==KEY
        assert request.full_url=='https://api.elevenlabs.io/v2/voices?page_size=100' and timeout==30
        calls.append('GET /v2/voices');return io.BytesIO(json.dumps(payload()).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector,'open',read)
    session=LaunchSession(18779);auth=LocalAccess(app,session)
    client=TestClient(catalog.wrap(OperatingRequests(auth),auth),base_url=session.origin,client=('127.0.0.1',41321),follow_redirects=False)
    client.cookies.set(session.cookie_name,session.claim(session.launch_url().split('#')[1]));client.get('/studio/shorts')
    return client,catalog,cipher,calls,session

@pytest.mark.parametrize('case',['valid','csrf','origin','session','consent'])
def test_explicit_authenticated_catalog_load_works_with_global_dpapi_disabled(prepared,case):
    client,catalog,cipher,calls,session=prepared
    fields={'csrf_token':client.cookies.get('newsflow_csrf'),'scope':'all','consent':'true'}
    headers={'Origin':session.origin,'Accept':'application/json'}
    if case=='csrf':fields['csrf_token']='bad'
    if case=='origin':headers['Origin']='https://outside.invalid'
    if case=='session':client.cookies.clear()
    if case=='consent':fields['consent']='false'
    response=client.post('/video/tts/voices/load',data=fields,headers=headers)
    if case=='valid':
        assert response.status_code==200 and response.json()=={'loaded':True}
        assert calls==['GET /v2/voices'] and cipher.reads==1
        assert catalog.cached()['voices'][0]['voice_id']=='voiceA'
    else:assert response.status_code in {401,403,422} and not calls and cipher.reads==0
    with pytest.raises(CredentialError):catalog.keys.key()
    with pytest.raises(CredentialError):catalog.load(all_voices=True)

@pytest.mark.parametrize('path',['/video/tts/check','/video/tts/key','/video/tts','/video/tts/voices/load/'])
def test_scope_never_grants_paid_key_or_other_paths(prepared,path):
    client,catalog,cipher,calls,session=prepared
    response=client.post(path,data={'csrf_token':client.cookies.get('newsflow_csrf'),'consent':'true'},headers={'Origin':session.origin})
    assert response.status_code==403 and not calls and cipher.reads==0

def test_pages_and_public_samples_never_use_key(prepared):
    client,catalog,cipher,calls,session=prepared
    data={'csrf_token':client.cookies.get('newsflow_csrf'),'scope':'all','consent':'true'}
    client.post('/video/tts/voices/load',data=data,headers={'Origin':session.origin,'Accept':'application/json'})
    before=cipher.reads;calls.clear();downloads=[]
    catalog.samples=SimpleNamespace(get=lambda url,timeout:downloads.append(url) or SimpleNamespace(status=200,body=MP3))
    assert client.get('/api/studio/modules/shorts').status_code==200
    response=client.post('/video/tts/voices/preview',data={'csrf_token':client.cookies.get('newsflow_csrf'),'voice_id':'voiceA','sample_consent':'true'},headers={'Origin':session.origin,'Accept':'application/json'})
    assert response.status_code==200 and response.json()['mediaUrl']=='/video/tts/voices/voiceA/sample'
    assert cipher.reads==before and not calls and len(downloads)==1
    assert client.get('/video/tts/voices/voiceA/sample').status_code==200

def test_network_failure_consumes_one_request_and_resets_key_scope(prepared,monkeypatch):
    client,catalog,cipher,calls,session=prepared
    def fail(self,request,timeout):calls.append('GET');raise TimeoutError()
    monkeypatch.setattr(urllib.request.OpenerDirector,'open',fail)
    response=client.post('/video/tts/voices/load',data={'csrf_token':client.cookies.get('newsflow_csrf'),'scope':'all','consent':'true'},headers={'Origin':session.origin,'Accept':'application/json'})
    assert response.status_code==422 and calls==['GET'] and cipher.reads==1
    with pytest.raises(CredentialError):catalog.keys.key()

def test_install_cannot_adopt_another_profile_or_replace_existing(app,tmp_path):
    with pytest.raises(CredentialError):install(app,tmp_path,FakeCipher)
    install(app,app.state.config.data_dir,FakeCipher)
    with pytest.raises(CredentialError):install(app,app.state.config.data_dir,FakeCipher)
