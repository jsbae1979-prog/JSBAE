"""Approved disposable Windows Actions procedure. Never run against a PC profile."""
import os
from pathlib import Path
from types import SimpleNamespace as NS
from io import BytesIO
import pytest

@pytest.fixture
def client(tmp_path,monkeypatch):
    assert os.environ.get("GITHUB_ACTIONS")=="true" and os.name=="nt", "Full app checks are only approved in disposable Windows Actions"
    runner=Path(os.environ["RUNNER_TEMP"]).resolve()
    root=runner/"studio-v3-synthetic-profile"
    root.mkdir(exist_ok=True)
    assert root.is_relative_to(runner)
    # No production keys/profiles, real adapters, automatic schedulers or network.
    for key in list(os.environ):
        if key.startswith(("NEWSFLOW_","OPENAI_","ANTHROPIC_","ELEVENLABS_","SERPAPI_","HF_")):
            monkeypatch.delenv(key,raising=False)
    for key in ("LOCALAPPDATA","APPDATA"):
        folder=root/key;folder.mkdir(exist_ok=True);monkeypatch.setenv(key,str(folder))
    import socket,subprocess,urllib.request
    def denied(*args,**kwargs):raise AssertionError("Actual network/process access forbidden in synthetic app integration")
    monkeypatch.setattr(socket.socket,"connect",denied)
    monkeypatch.setattr(subprocess,"Popen",denied)
    monkeypatch.setattr(urllib.request.OpenerDirector,"open",denied)
    from newsflow.config import Settings
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter
    from newsflow.scheduler.service import Scheduler
    from newsflow.publishing.calendar import PublishingCalendar
    monkeypatch.setattr(Scheduler,"start",lambda self:None)
    monkeypatch.setattr(PublishingCalendar,"start",lambda self:None)
    from fastapi.testclient import TestClient
    app=create_app(Settings(data_dir=tmp_path/"fresh-synthetic",port=18765,secret_key="synthetic-studio-csrf-secret-00000000"),FakeRSSAdapter({}),automatic_start=True)
    app.state.studio_synthetic=True
    with TestClient(app,base_url="http://127.0.0.1:18765",follow_redirects=False) as c:
        yield c,app

def token(client):
    response=client.get('/api/studio/modules/images')
    assert response.status_code==200,response.text
    return response.json()['csrfToken']

def test_all_react_shells_and_read_models(client):
    c,app=client
    for module in ['dashboard','create','news','shorts','characters','images','automation','library','publishing','analytics','settings','onboarding']:
        response=c.get('/studio/'+module)
        assert response.status_code==200 and '<div id="root">' in response.text
        assert "unsafe-inline" not in response.headers['Content-Security-Policy']
        if module not in {'dashboard','create'}:
            read=c.get('/api/studio/modules/'+module)
            assert read.status_code==200,read.text
            assert read.json()['module']==module
    assert c.get('/api/studio/modules/not-supported').status_code==422

def test_original_forms_csrf_origin_and_local_save(client):
    c,app=client
    csrf=token(c)
    payload={'prompt':'합성 이미지 지시문','model':'gpt-image-2.5-flare-2026-09-08','size':'1024x1024','quality':'low','provider':'openai'}
    assert c.post('/image-studio/drafts',data=payload).status_code==403
    assert c.post('/image-studio/drafts',data={**payload,'csrf_token':csrf},headers={'Origin':'https://external.invalid'}).status_code==403
    saved=c.post('/image-studio/drafts',data={**payload,'csrf_token':csrf})
    assert saved.status_code==303,saved.text
    view=c.get('/api/studio/modules/images').json()
    draft=view['collections']['drafts'][0]
    assert draft['status']=='saved' and draft['mediaUrl'] is None
    assert c.post(f"/image-studio/{draft['id']}/generate",data={'csrf_token':csrf}).status_code==422
    assert c.get('/api/studio/modules/images').json()['collections']['drafts'][0]['status']=='saved'

def test_fake_generation_once_verified_image_and_reference_boundary(client):
    c,app=client
    from PIL import Image
    class Fake:
        calls=0
        def generate(self,prompt,key,*,selection):
            assert key=='synthetic-only-image-key'
            self.calls+=1
            raw=BytesIO();Image.new('RGB',(1024,1024),'teal').save(raw,'JPEG')
            return raw.getvalue(),{'input_tokens':1,'output_tokens':1,'total_tokens':2}
    fake=Fake();app.state.image_generation.adapter=fake
    app.state.image_generation.keys=NS(key=lambda:'synthetic-only-image-key',status=lambda:{'configured':True})
    csrf=token(c)
    response=c.post('/image-studio/drafts',data={'csrf_token':csrf,'prompt':'합성 기하학','model':'gpt-image-2.5-flare-2026-09-08','provider':'openai','size':'1024x1024','quality':'low'})
    assert response.status_code==303,response.text
    draft=c.get('/api/studio/modules/images').json()['collections']['drafts'][0]
    for _ in range(2):
        response=c.post(f"/image-studio/{draft['id']}/generate",data={'csrf_token':csrf,'consent':'true','reviewed':'true'})
        assert response.status_code==303,response.text
    assert fake.calls==1
    item=c.get('/api/studio/modules/images').json()['collections']['drafts'][0]
    assert item['status']=='success' and item['outputId']!=item['id'] and item['mediaUrl']==f"/image-studio/{draft['id']}/file"
    file=c.get(item['mediaUrl']);assert file.status_code==200 and file.headers['content-type']=='image/jpeg'
    app.state.image_generation.path(item['outputId']).write_bytes(b'corrupted-synthetic')
    assert c.get('/api/studio/modules/images').json()['collections']['drafts'][0]['mediaUrl'] is None

def test_paused_schedule_and_local_post_without_account(client):
    c,app=client
    csrf=token(c)
    response=c.post('/schedules',data={'csrf_token':csrf,'name':'합성 예약','kind':'daily','local_time':'09:00','source':'sample','duration':'30','platform':'youtube','voice':'offline-silence'})
    assert response.status_code==303,response.text
    row=c.get('/api/studio/modules/automation').json()['collections']['schedules'][0]
    assert row['status']!='active'
    assert c.post(f"/schedules/{row['id']}/state",data={'csrf_token':csrf,'action':'enable','revision':row['revision']}).status_code==422
