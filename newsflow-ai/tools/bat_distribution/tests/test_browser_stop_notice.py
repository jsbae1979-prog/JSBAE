"""Synthetic ASGI only; no browser, real server, process or credentials."""
import asyncio
import json
from types import SimpleNamespace
import pytest
from bat_distribution.browser_stop_notice import BrowserStopNotice, PATH
from bat_distribution.windows_live import Control
from newsflow.distribution.local_access import LaunchSession

ORIGIN='http://127.0.0.1:18780'
NONCE='synthetic-stop-nonce'

def fixture():
    session=LaunchSession(18780)
    token=session.claim(session.launch_url().split('#')[1])
    cookie=f'{session.cookie_name}={token}'
    async def app(scope,receive,send):
        await send({'type':'http.response.start','status':404,'headers':[]})
        await send({'type':'http.response.body','body':b'not found'})
    notice=BrowserStopNotice(app,session,poll_seconds=.02,grace_seconds=.05)
    stopped=[]
    control=Control(notice,SimpleNamespace(session_nonce=NONCE),ORIGIN,
                    lambda:stopped.append(True),stop_notice=notice.stop_accepted)
    return control,notice,cookie,stopped

async def request(app,cookie,path=PATH,method='GET',extra=(),query=b'',disconnect=False):
    headers=[(b'host',b'127.0.0.1:18780'),(b'origin',ORIGIN.encode())]
    if cookie: headers.append((b'cookie',cookie.encode()))
    headers.extend(extra)
    scope={'type':'http','path':path,'method':method,'query_string':query,
           'client':('127.0.0.1',1234),'headers':headers}
    queue=asyncio.Queue()
    await queue.put({'type':'http.disconnect'} if disconnect else {'type':'http.request','body':b''})
    messages=[]
    async def send(item): messages.append(item)
    await app(scope,queue.get,send)
    return messages

def body(messages):
    return json.loads(messages[-1]['body'])

def test_get_is_read_only_and_timeout_does_not_authorize_close():
    async def run():
        app,notice,cookie,stopped=fixture()
        response=await request(app,cookie)
        assert response[0]['status']==200 and body(response)=={'schemaVersion':1,'stopAccepted':False}
        assert not notice._stopping.is_set() and not stopped
    asyncio.run(run())

@pytest.mark.parametrize('case',['missing-cookie','cross-origin','duplicate-host','cross-site'])
def test_same_local_access_boundary_is_required(case):
    async def run():
        app,notice,cookie,stopped=fixture()
        extra=[]
        if case=='missing-cookie': cookie=''
        if case=='cross-origin': extra=[(b'origin',b'https://example.invalid')]
        if case=='duplicate-host': extra=[(b'host',b'127.0.0.1:18780')]
        if case=='cross-site': extra=[(b'sec-fetch-site',b'cross-site')]
        response=await request(app,cookie,extra=extra)
        assert response[0]['status']==403
        assert not notice._stopping.is_set() and not stopped
    asyncio.run(run())

@pytest.mark.parametrize('method,query,status',[('POST',b'',405),('GET',b'any=1',400),('HEAD',b'',405)])
def test_exact_get_only(method,query,status):
    async def run():
        app,notice,cookie,stopped=fixture()
        response=await request(app,cookie,method=method,query=query)
        assert response[0]['status']==status and body(response)['stopAccepted'] is False
        assert not notice._stopping.is_set() and not stopped
    asyncio.run(run())

def test_only_accepted_private_stop_notifies_authenticated_listener():
    async def run():
        app,notice,cookie,stopped=fixture()
        listener=asyncio.create_task(request(app,cookie))
        await asyncio.sleep(0)
        response=await request(app,'',path='/__bat/stop',method='POST',extra=[(b'x-newsflow-stop',NONCE.encode())])
        event=await listener
        assert response[0]['status']==202 and stopped==[True]
        assert body(event)=={'schemaVersion':1,'stopAccepted':True}
        assert NONCE.encode() not in event[-1]['body'] and cookie.encode() not in event[-1]['body']
        repeated=await request(app,'',path='/__bat/stop',method='POST',extra=[(b'x-newsflow-stop',NONCE.encode())])
        assert repeated[0]['status']==409 and stopped==[True]
    asyncio.run(run())

def test_rejected_stop_cannot_notify_or_close():
    async def run():
        app,notice,cookie,stopped=fixture()
        response=await request(app,'',path='/__bat/stop',method='POST',extra=[(b'x-newsflow-stop',b'wrong')])
        assert response[0]['status']==403 and not stopped
        assert body(await request(app,cookie))['stopAccepted'] is False
    asyncio.run(run())

def test_no_listener_does_not_prevent_normal_stop():
    async def run():
        app,notice,cookie,stopped=fixture()
        response=await request(app,'',path='/__bat/stop',method='POST',extra=[(b'x-newsflow-stop',NONCE.encode())])
        assert response[0]['status']==202 and stopped==[True]
    asyncio.run(run())

def test_disconnected_listener_has_no_side_effect_or_response():
    async def run():
        app,notice,cookie,stopped=fixture()
        assert await request(app,cookie,disconnect=True)==[]
        assert not notice._stopping.is_set() and not stopped
    asyncio.run(run())
