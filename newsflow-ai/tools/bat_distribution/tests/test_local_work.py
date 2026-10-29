import pytest
from starlette.testclient import TestClient
from bat_distribution.local_work import LocalWorkRequests, offline_adapter, FIXTURE_URL
from bat_distribution.restored_install import RestoredRequests

async def inner(scope,receive,send):
    body=b''
    if scope['method']=='POST':
        while True:
            message=await receive();body+=message.get('body',b'')
            if not message.get('more_body'):break
    await send({'type':'http.response.start','status':200,'headers':[]})
    await send({'type':'http.response.body','body':body or b'LOCAL'})

@pytest.mark.parametrize('path',['/image-studio/drafts','/character','/ai/drafts/1','/settings/collection'])
def test_local_saves_reach_unchanged_inner_app(path):
    assert TestClient(LocalWorkRequests(inner)).post(path,data={'csrf_token':'test'}).status_code==200

@pytest.mark.parametrize('provider',['openai','claude_api','codex','claude_code'])
def test_live_providers_remain_blocked(provider):
    assert TestClient(LocalWorkRequests(inner)).post('/ai/generate',data={'provider':provider}).status_code==403


def test_offline_form_body_is_replayed_exactly():
    body=b'provider=offline&csrf_token=synthetic&duration=30'
    response=TestClient(LocalWorkRequests(inner)).post('/ai/generate',content=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
    assert response.status_code==200 and response.content==body


def test_ambiguous_provider_is_rejected():
    assert TestClient(LocalWorkRequests(inner)).post('/ai/generate',content='provider=offline&provider=openai',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==403


def test_real_restored_profile_stays_read_only():
    assert TestClient(RestoredRequests(inner)).post('/image-studio/drafts',data={'csrf_token':'test'}).status_code==403


def test_fake_collection_has_no_public_transport():
    adapter=offline_adapter()
    assert b'Synthetic local write news' in adapter.fetch(FIXTURE_URL,10)
    assert adapter.calls==[FIXTURE_URL]
