"""Synthetic progress UI. No external API calls or operating profile writes."""
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
from threading import Event
import os
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_collection_controls_browser import browser_context
from test_character_precision import precision,scripted

@pytest.fixture(autouse=True)
def dist(monkeypatch):
    monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

def setup(f,monkeypatch):
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.character=f.owner;f.app.state.image_studio=f.images

def test_story_modal_shows_elapsed_and_waiting_without_duplicate_submit(precision,browser,monkeypatch,tmp_path):
    f=precision;setup(f,monkeypatch);release=Event();entered=Event();original=f.writer.generate
    def slow(*args,**kw):
        entered.set();assert release.wait(20);return original(*args,**kw)
    monkeypatch.setattr(f.writer,'generate',slow)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[];errors=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto(origin+'/studio/characters?precision='+f.w['id'])
            expect(page.locator('details.precision-work-context')).to_have_attribute('open','')
            page.get_by_role('button',name='스토리 만들기',exact=True).click()
            dialog=page.get_by_role('dialog',name='스토리 만들기')
            dialog.get_by_role('button',name='유료 스토리 생성 승인',exact=True).click()
            status=dialog.get_by_role('status',name='제작 진행 상태')
            expect(status).to_contain_text('스토리 생성 중')
            expect(status.get_by_label('경과 시간')).to_be_visible()
            expect(status.get_by_role('progressbar')).not_to_have_attribute('value','0')
            expect(dialog.get_by_role('button',name='스토리 생성 중…')).to_be_disabled()
            expect(dialog.get_by_role('button',name='스토리 만들기 닫기')).to_be_disabled()
            assert entered.wait(2)
            page.screenshot(path=str(tmp_path/'story-progress.jpg'))
            release.set();expect(dialog).not_to_be_visible(timeout=15000)
            expect(page.get_by_role('heading',name='장면 이미지 검토')).to_be_visible()
            assert sum(u.endswith('/story') for u in posts)==1
            assert len(f.writer.calls)==1 and not f.adapter.calls and not errors
        finally:release.set();context.close()

@pytest.mark.parametrize('unknown',[False,True])
def test_failed_response_notice_is_visible_without_opening_details(precision,browser,monkeypatch,unknown):
    f=precision;setup(f,monkeypatch);w=f.w
    attempt={'state':'unknown' if unknown else 'failed','at':datetime.now(timezone.utc).isoformat()}
    if not unknown:attempt['candidate']=deepcopy(f.story)
    w.update(state='story_failed',story_attempts=[attempt]);f.s.save(w)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        status=page.get_by_role('status',name='제작 진행 상태',exact=True)
        expect(status).to_contain_text('스토리 결과 확인 필요' if unknown else '스토리 응답 검토 필요')
        expect(status.get_by_role('progressbar')).to_have_count(0)
        if not unknown:expect(page.get_by_role('button',name='보관된 응답 검토·수정 · 무료')).to_be_visible()
        else:expect(page.get_by_role('button',name='보관된 응답 검토·수정 · 무료')).to_have_count(0)
        assert not posts and not f.writer.calls and not f.adapter.calls
        context.close()

def test_image_progress_uses_saved_completion_not_a_fake_percentage(precision,browser,monkeypatch):
    f=precision;setup(f,monkeypatch);w=scripted(f)
    w['state']='generating';w['events'].append({'kind':'image_approval','at':(datetime.now(timezone.utc)-timedelta(seconds=125)).isoformat()})
    w['scenes'][0]['versions']=[{'version':1,'state':'success'}];w['scenes'][0]['selected']=1
    w['scenes'][1]['versions']=[{'version':1,'state':'requesting'}]
    f.s.save(w)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        status=page.get_by_role('status',name='제작 진행 상태',exact=True)
        expect(status).to_contain_text('1/5장 저장 완료')
        expect(status.get_by_label('경과 시간')).to_contain_text('2분')
        expect(status.get_by_role('progressbar')).to_have_attribute('value','1')
        expect(status.get_by_role('progressbar')).to_have_attribute('max','5')
        assert not posts and not f.adapter.calls
        context.close()
