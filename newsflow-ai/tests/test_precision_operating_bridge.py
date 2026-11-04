"""Operating local precision screen only; synthetic profile and no live transport."""
import pytest
from starlette.testclient import TestClient
from bat_distribution.operation import OperatingRequests
from newsflow.distribution.local_access import LocalAccess, LaunchSession
from test_character_precision import precision
from test_character_precision_browser import dist, browser, local_server, browser_context
from playwright.sync_api import expect

BASE='/api/studio/character-precision'

@pytest.mark.parametrize('method,suffix,status',[
 ('GET','',204),('GET','/'+'a'*32,204),
 *[('POST','/'+'a'*32+'/'+op,204) for op in ('edit','quote','reconcile','confirm','handoff')],
 ('POST','/create',204),('POST','/'+'a'*32+'/story',403),
 ('POST','/'+'a'*32+'/generate',403),('GET','/'+'a'*31,403),
 ('GET','/'+'A'*32,403),('POST','/'+'a'*32+'/edit/extra',403),
 ('DELETE','/'+'a'*32,403),('POST','/anything',403)])
def test_precision_boundary_exact_local_routes(method,suffix,status):
 seen=[]
 async def inner(scope,receive,send):
  seen.append(scope.get('newsflow.precision_paid_available'))
  await send({'type':'http.response.start','status':204,'headers':[]})
  await send({'type':'http.response.body','body':b''})
 assert TestClient(OperatingRequests(inner)).request(method,BASE+suffix).status_code==status
 assert seen==([False] if status==204 else [])

def test_precision_local_routes_keep_auth_csrf_origin(precision,monkeypatch):
 f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
 session=LaunchSession(18779)
 with TestClient(OperatingRequests(LocalAccess(f.app,session)),base_url=session.origin,client=('127.0.0.1',43210)) as c:
  assert c.get(BASE).status_code==403
  token=session.launch_url().split('#',1)[1]
  assert c.post('/__local/claim',headers={'Origin':session.origin,'X-NewsFlow-Bootstrap':token}).status_code==204
  response=c.get(BASE);assert response.status_code==200 and response.json()['paid_available'] is False
  csrf=c.cookies['newsflow_csrf'];target=BASE+'/'+f.w['id']+'/reconcile'
  values={'revision':f.w['revision'],'csrf_token':'wrong'}
  assert c.post(target,data=values,headers={'Origin':session.origin}).status_code==403
  values['csrf_token']=csrf
  assert c.post(target,data=values,headers={'Origin':'https://outside.invalid'}).status_code==403
  assert c.post(target,data=values,headers={'Origin':session.origin}).status_code==200
  assert c.post(BASE+'/'+f.w['id']+'/story',data={**values,'consent':'true'},headers={'Origin':session.origin}).status_code==403
 assert not f.adapter.calls and not f.writer.calls

def test_operating_screen_explains_unconnected_paid_path(precision,browser,monkeypatch):
 f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
 f.app.state.image_studio=f.images
 with local_server(OperatingRequests(f.app)) as origin:
  context=browser_context(browser,origin);page=context.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(origin+'/studio/characters?precision='+f.w['id'])
  expect(page.get_by_text('정밀 제작의 AI 연결 준비 중 · 작품 편집과 검토는 사용할 수 있습니다.',exact=True)).to_be_visible()
  expect(page.get_by_role('button',name='스토리 만들기',exact=True)).to_be_disabled()
  page.get_by_text('직접 작성·복구',exact=True).click()
  expect(page.get_by_role('button',name='직접 작성',exact=True)).to_be_enabled()
  page.get_by_role('button',name='직접 작성',exact=True).click()
  expect(page.get_by_role('dialog',name='장면 내용 수정')).to_be_visible()
  assert not errors and not f.adapter.calls and not f.writer.calls
  context.close()
