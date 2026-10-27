"""Approved disposable Windows Actions procedure. Never run against a PC profile."""
import os
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace as NS

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
    import socket
    import subprocess
    import urllib.request
    def denied(*args,**kwargs):raise AssertionError("Actual network/process access forbidden in synthetic app integration")
    # CPython on Windows implements its event-loop self-pipe with a socketpair
    # connected to its own ephemeral listener. No general loopback exception.
    import sys
    original_connect=socket.socket.connect
    socketpair_code=socket.socketpair.__code__
    def guarded_connect(sock,address):
        if sys._getframe(1).f_code is socketpair_code and isinstance(address,tuple) and address[0] in {"127.0.0.1","::1"} and address[1]!=8765:
            return original_connect(sock,address)
        return denied()
    monkeypatch.setattr(socket.socket,"connect",guarded_connect)
    monkeypatch.setattr(socket.socket,"connect_ex",denied)
    monkeypatch.setattr(socket,"getaddrinfo",denied)
    # Assert the exception cannot be used by application or adapter callers.
    for address in [("127.0.0.1",18765),("198.51.100.1",443)]:
        with socket.socket() as sock, pytest.raises(AssertionError):
            sock.connect(address)
    monkeypatch.setattr(subprocess,"Popen",denied)
    monkeypatch.setattr(urllib.request.OpenerDirector,"open",denied)
    from newsflow.config import Settings
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter
    from newsflow.publishing.calendar import PublishingCalendar
    from newsflow.scheduler.service import Scheduler
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
    c,_app=client
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
    c,_app=client
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
    c,_app=client
    csrf=token(c)
    response=c.post('/schedules',data={'csrf_token':csrf,'name':'합성 예약','kind':'daily','local_time':'09:00','source':'sample','duration':'30','platform':'youtube','voice':'offline-silence'})
    assert response.status_code==303,response.text
    row=c.get('/api/studio/modules/automation').json()['collections']['schedules'][0]
    assert row['status']!='active'
    assert c.post(f"/schedules/{row['id']}/state",data={'csrf_token':csrf,'action':'enable','revision':row['revision']}).status_code==422

def test_script_edit_keeps_revision_and_review_boundary(client):
    c,app=client
    import json

    from newsflow.db.models import ContentDraft, IntelligenceRun
    content={"title":"합성 편집","hook":"합성 뉴스의 변화를 살펴봅니다.","summary":"실제 사건을 주장하지 않는 합성 자료입니다.","scenes":[{"seconds":10,"narration":"합성 첫 장면입니다.","caption":"합성 첫 장면","material":"기본 카드"},{"seconds":10,"narration":"합성 둘째 장면입니다.","caption":"합성 둘째 장면","material":"기본 카드"},{"seconds":10,"narration":"합성 셋째 장면입니다.","caption":"합성 셋째 장면","material":"기본 카드"}],"closing":"합성 자료 검토를 마칩니다."}
    with app.state.sessions.begin() as session:
        run=IntelligenceRun(kind="script",status="success",provider="offline",options={},evidence={},result=content,message="")
        session.add(run);session.flush()
        draft=ContentDraft(run_id=run.id,duration=30,content=content,sources={"articles":[]},revision=1,review_status="review_required",review_notes=[])
        session.add(draft);session.flush();identifier=draft.id
    csrf=token(c)
    changed={**content,"title":"합성 편집 저장 검증"}
    response=c.post(f"/ai/drafts/{identifier}",data={"csrf_token":csrf,"revision":1,"content":json.dumps(changed,ensure_ascii=False)})
    assert response.status_code==303,response.text
    read=c.get('/api/studio/modules/shorts').json()['collections']['drafts'][0]
    assert read['revision']==2 and read['content']['title']==changed['title'] and read['review_status']!='approved'
    conflict=c.post(f"/ai/drafts/{identifier}",data={"csrf_token":csrf,"revision":1,"content":json.dumps(content,ensure_ascii=False)})
    assert conflict.status_code==409
    assert c.get('/api/studio/modules/shorts').json()['collections']['drafts'][0]['content']['title']==changed['title']
