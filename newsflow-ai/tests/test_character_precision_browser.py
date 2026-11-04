"""Windows Chromium with temporary app, synthetic reference assets and Fake providers."""
from pathlib import Path
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

def test_precision_cards_approval_confirm_and_version_selection(precision,browser,monkeypatch,tmp_path):
    f=precision;w=scripted(f)
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    # HTTP media routes serve the same isolated image store used by the Fake service.
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters?precision='+w['id'])
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(panel.get_by_role('heading',name='③ 장면 이미지 제작')).to_be_visible()
        expect(panel.locator('.precision-scenes article')).to_have_count(5)
        panel.get_by_role('button',name='전체 미생성 장면 예산 확인').click()
        button=panel.get_by_role('button',name='승인한 장면 이미지 생성')
        expect(button).to_be_disabled();assert not f.adapter.calls
        panel.get_by_role('checkbox',name='선택한 캐릭터 참조 이미지 전송과 표시된 이미지 생성 비용에 동의합니다.').check()
        button.click()
        expect(panel.get_by_role('status')).to_contain_text('5/5장 완료',timeout=20000)
        assert len(f.adapter.calls)==5
        first=panel.locator('.precision-scenes article').first
        first.locator('.precision-image').click()
        popup=page.get_by_role('dialog',name='장면 이미지',exact=True)
        expect(popup.get_by_role('img')).to_be_visible()
        assert popup.bounding_box()['height']<=768
        page.keyboard.press('Escape');expect(popup).not_to_be_visible()
        first.get_by_role('button',name='이 이미지 검토·확정').click()
        page.get_by_role('button',name='검토 완료 · 이미지 확정').click()
        expect(first.get_by_text('이미지 확정',exact=True)).to_be_visible()
        expect(panel.get_by_role('button',name='④ 영상 제작으로 이동 준비 · 무료')).to_be_disabled()
        assert not errors
        page.screenshot(path=str(tmp_path/'precision-five-scene-review.png'),full_page=True)
        context.close()

@pytest.mark.parametrize('width',[1366,1920])
def test_precision_mode_keeps_fast_and_new_work_controls(precision,browser,monkeypatch,tmp_path,width):
    f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(origin+'/studio/characters')
        expect(page.get_by_role('button',name='빠른 제작',exact=True)).to_have_attribute('aria-pressed','true')
        page.get_by_role('button',name='정밀 제작 · 장면 이미지 먼저 만들기',exact=True).click()
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(panel.get_by_label('작품명',exact=True)).to_be_visible()
        expect(panel.get_by_label('총 길이(초)')).to_have_value('26')
        expect(panel.locator('.precision-person')).to_have_count(2)
        page.wait_for_function("Array.from(document.querySelectorAll('.precision-person img')).every(i=>i.complete&&i.naturalWidth>0)")
        expect(panel.get_by_role('button',name='작품 저장 · 무료')).to_be_disabled()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        assert not f.adapter.calls and not f.writer.calls
        page.screenshot(path=str(tmp_path/f'precision-setup-{width}.png'),full_page=True)
        context.close()


def test_precision_handoff_opens_existing_video_screen_at_26_seconds(precision,browser,monkeypatch):
    from test_character_precision import confirmed
    f=precision;w=confirmed(f);w=f.s.handoff(w['id'],w['revision'])
    f.app.state.character=f.owner;f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters?job_id='+w['video_job_id'])
        expect(page.get_by_role('button',name='빠른 제작',exact=True)).to_have_attribute('aria-pressed','true')
        duration=page.get_by_label('영상 길이',exact=True)
        expect(duration).to_have_value('26');expect(duration).to_be_disabled()
        assert not errors and not f.video.sent and not f.video.uploads and len(f.adapter.calls)==5
        context.close()
