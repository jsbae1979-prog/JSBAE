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
        expect(panel.get_by_role('heading',name='장면 이미지 검토')).to_be_visible()
        expect(panel.locator('.precision-scenes article')).to_have_count(5)
        panel.get_by_role('button',name='장면 이미지 만들기',exact=True).click()
        popup=page.get_by_role('dialog',name='장면 이미지 만들기',exact=True)
        expect(popup).to_be_visible();assert not f.adapter.calls
        page.keyboard.press('Escape');assert not f.adapter.calls
        panel.get_by_role('button',name='장면 이미지 만들기',exact=True).click()
        page.get_by_role('button',name='참조 이미지 전송·생성 승인').click()
        expect(panel.get_by_role('status')).to_contain_text('5/5장 완료',timeout=20000)
        assert len(f.adapter.calls)==5
        first=panel.locator('.precision-scenes article').first
        panel.locator('.precision-selected .precision-image').click()
        popup=page.get_by_role('dialog',name='장면 이미지',exact=True)
        expect(popup.get_by_role('img')).to_be_visible()
        assert popup.bounding_box()['height']<=768
        page.keyboard.press('Escape');expect(popup).not_to_be_visible()
        panel.get_by_role('button',name='확정하고 다음 장면').click()
        expect(first.get_by_text('이미지 확정',exact=True)).to_be_visible()
        expect(panel.get_by_role('button',name='영상 제작으로 이동')).to_have_count(0)
        expect(panel.locator('.precision-selected img')).to_have_attribute('alt','장면 2')
        panel.get_by_role('button',name='장면 1 ·').click()
        expect(panel.get_by_role('button',name='사용 중인 이미지')).to_be_disabled()
        panel.get_by_role('button',name='장면 2 ·').click()
        expect(panel.locator('.precision-selected img')).to_have_attribute('alt','장면 2')
        expect(panel.get_by_label('장면 2 이미지 버전')).not_to_be_visible()
        panel.get_by_text('버전·프롬프트 더보기',exact=True).click()
        expect(panel.get_by_label('장면 2 이미지 버전')).to_be_visible()
        # Selection does not generate, confirm or alter another scene.
        saved=f.s.read(w['id']);assert saved['scenes'][0]['confirmed'] and not saved['scenes'][1]['confirmed']
        assert len(f.adapter.calls)==5 and not errors
        old_asset=saved['scenes'][1]['versions'][0]['asset']
        quoted=f.s.quote(w['id'],saved['revision'],[2],regenerate=True)
        newer=f.s.generate(w['id'],quoted['quote']['hash'],consent=True,reference_consent=True)
        new_asset=newer['scenes'][1]['versions'][-1]['asset']
        assert old_asset!=new_asset
        page.reload()
        panel.get_by_role('button',name='장면 2 ·').click()
        expect(panel.locator('.precision-selected img')).to_have_attribute('src','/image-studio/assets/'+new_asset)
        panel.get_by_text('버전·프롬프트 더보기',exact=True).click()
        panel.get_by_label('장면 2 이미지 버전').select_option('1')
        expect(panel.locator('.precision-selected img')).to_have_attribute('src','/image-studio/assets/'+old_asset)
        panel.get_by_label('장면 2 이미지 버전').select_option('2')
        expect(panel.locator('.precision-selected img')).to_have_attribute('src','/image-studio/assets/'+new_asset)
        assert f.s.read(w['id'])==newer and len(f.adapter.calls)==6 and not errors
        panel.get_by_text('버전·프롬프트 더보기',exact=True).click()
        panel.get_by_role('heading',name='장면 이미지 검토',exact=True).click()
        page.screenshot(path=str(tmp_path/'precision-five-scene-review.png'),full_page=True)
        context.close()

@pytest.mark.parametrize('width',[1366,1920])
def test_precision_mode_keeps_fast_and_new_work_controls(precision,browser,monkeypatch,tmp_path,width):
    f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();page.set_viewport_size({'width':width,'height':900})
        page.goto(origin+'/studio/characters')
        expect(page.get_by_role('checkbox',name='장면 이미지를 먼저 검토',exact=True)).not_to_be_checked()
        page.get_by_role('checkbox',name='장면 이미지를 먼저 검토',exact=True).check()
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(panel.get_by_label('스토리 주제',exact=True)).to_be_visible()
        expect(panel.get_by_label('작품명',exact=True)).to_have_count(0)
        expect(panel.get_by_label('총 길이(초)')).to_have_value('20')
        expect(panel.locator('.precision-person')).to_have_count(2)
        page.wait_for_function("Array.from(document.querySelectorAll('.precision-person img')).every(i=>i.complete&&i.naturalWidth>0)")
        expect(panel.get_by_role('button',name='작품 저장 · 무료')).to_have_count(0)
        expect(panel.get_by_role('button',name='스토리 만들기',exact=True)).to_be_disabled()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        panel.get_by_label('스토리 주제',exact=True).fill('선택한 캐릭터의 새로운 하루')
        panel.locator('.precision-person').filter(has_text=f.chars[0]['name_ko']).locator('input[type=checkbox]').check()
        panel.get_by_text('직접 작성·상세 설정',exact=True).click()
        expect(panel.get_by_label('그림 스타일',exact=True)).to_have_value(f.chars[0]['style_lock'])
        expect(panel.get_by_label('세계관',exact=True)).to_have_value(f.chars[0]['comedy_formula']['world'])
        panel.get_by_label('그림 스타일',exact=True).fill('User selected watercolor')
        panel.get_by_text('직접 작성·상세 설정',exact=True).click()
        page.get_by_role('checkbox',name='장면 이미지를 먼저 검토',exact=True).uncheck()
        expect(panel).not_to_be_visible()
        page.get_by_role('checkbox',name='장면 이미지를 먼저 검토',exact=True).check()
        expect(panel.get_by_label('스토리 주제',exact=True)).to_have_value('선택한 캐릭터의 새로운 하루')
        expect(panel.locator('.precision-person').filter(has_text=f.chars[0]['name_ko']).locator('input[type=checkbox]')).to_be_checked()
        panel.locator('.precision-person').filter(has_text=f.chars[0]['name_ko']).locator('input[type=checkbox]').uncheck()
        panel.locator('.precision-person').filter(has_text=f.chars[1]['name_ko']).locator('input[type=checkbox]').check()
        panel.get_by_text('직접 작성·상세 설정',exact=True).click()
        expect(panel.get_by_label('그림 스타일',exact=True)).to_have_value('User selected watercolor')
        panel.get_by_text('직접 작성·상세 설정',exact=True).click()
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
        expect(page.get_by_role('checkbox',name='장면 이미지를 먼저 검토',exact=True)).not_to_be_checked()
        duration=page.get_by_label('영상 길이',exact=True)
        expect(duration).to_have_value('26');expect(duration).to_be_disabled()
        page.get_by_role('link',name='← 확정한 장면 이미지 보기').click()
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(panel.get_by_role('button',name='사용 중인 이미지')).to_be_disabled()
        expect(panel.get_by_role('link',name='영상 제작 열기',exact=True)).to_have_attribute('href','/studio/characters?job_id='+w['video_job_id'])
        assert f.s.read(w['id'])==w
        assert not errors and not f.video.sent and not f.video.uploads and len(f.adapter.calls)==5
        context.close()


def test_precision_create_reuses_profile_without_paid_call(precision,browser,monkeypatch):
    f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page()
        page.goto(origin+'/studio/characters?precision=')
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        panel.locator('.precision-person').filter(has_text=f.chars[0]['name_ko']).locator('input[type=checkbox]').check()
        panel.get_by_label('스토리 주제',exact=True).fill('정원에서 찾은 작은 선물')
        panel.locator('.precision-budget-settings summary').click()
        panel.get_by_label('이미지 작업 예산(USD)',exact=True).fill('5')
        panel.get_by_label('스토리·영상 예산(USD)',exact=True).fill('5')
        panel.get_by_text('직접 작성·상세 설정',exact=True).click()
        panel.get_by_role('button',name='직접 작성',exact=True).click()
        expect(page.get_by_role('dialog',name='장면 내용 수정')).to_be_visible()
        page.keyboard.press('Escape')
        expect(panel.get_by_role('button',name='스토리 만들기')).to_be_visible()
        expect(panel.get_by_role('button',name='스토리 만들기')).to_be_enabled()
        identifier=page.url.split('precision=')[1].split('&')[0]
        w=f.s.read(identifier)
        assert w['common']['title']=='정원에서 찾은 작은 선물'
        assert w['common']['duration']==20
        assert list(w['cast'])==[f.chars[0]['id']]
        assert w['cast'][f.chars[0]['id']]['outfit']=='참조 이미지의 의상·액세서리 유지'
        assert w['common']['style']==f.chars[0]['style_lock']
        assert not f.adapter.calls and not f.writer.calls and not f.video.sent
        # A new unsaved work must remain new after a page refresh.
        panel.get_by_role('button',name='새 작품',exact=True).click()
        page.reload()
        expect(panel.get_by_label('스토리 주제',exact=True)).to_have_value('')
        panel.get_by_label('저장한 작품').select_option(identifier)
        expect(panel.get_by_role('button',name='스토리 만들기')).to_be_enabled()
        assert f.s.read(identifier)==w
        context.close()


def test_precision_story_autosave_requires_confirmation_and_runs_once(precision,browser,monkeypatch):
    from copy import deepcopy
    f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    story=deepcopy(f.story)
    for row in story['scenes']:row['seconds']=4
    f.writer.scenario=story
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();requests=[]
        page.on('request',lambda r:requests.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision=')
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(panel.locator('.precision-person input[type=checkbox]')).to_have_count(2)
        for box in panel.locator('.precision-person input[type=checkbox]').all():box.check()
        topic='정원에서 작은 선물을 찾고 친구와 나누는 하루'
        panel.get_by_label('스토리 주제',exact=True).fill(topic)
        panel.get_by_role('button',name='스토리 만들기',exact=True).click()
        popup=page.get_by_role('dialog',name='스토리 만들기',exact=True)
        expect(popup).to_contain_text('US$5');assert not requests and not f.writer.calls
        page.keyboard.press('Escape');assert len(f.s.listing())==1
        panel.get_by_role('button',name='스토리 만들기',exact=True).click()
        page.get_by_role('button',name='유료 스토리 생성 승인').dblclick()
        expect(panel.get_by_role('button',name='장면 이미지 만들기',exact=True)).to_be_visible()
        identifier=page.url.split('precision=')[1].split('&')[0];w=f.s.read(identifier)
        assert w['common']['title']==topic and w['common']['duration']==20
        assert len(f.writer.calls)==1 and len(f.s.listing())==2
        assert sum(url.endswith('/create') for url in requests)==1
        assert sum(url.endswith('/story') for url in requests)==1
        assert not f.adapter.calls and not f.video.sent
        page.reload();assert len(f.writer.calls)==1
        context.close()


def test_precision_story_failure_preserves_draft_without_replay(precision,browser,monkeypatch):
    f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    def fail(*args,**kwargs):
        f.writer.calls.append('attempt');raise TimeoutError('synthetic timeout')
    f.writer.response_received=False;f.writer.generate=fail
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page()
        page.goto(origin+'/studio/characters?precision=')
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        panel.locator('.precision-person input[type=checkbox]').first.check()
        panel.get_by_label('스토리 주제',exact=True).fill('저장된 작품은 지우지 않기')
        panel.get_by_role('button',name='스토리 만들기',exact=True).click()
        page.get_by_role('button',name='유료 스토리 생성 승인').click()
        expect(panel.get_by_role('status')).to_contain_text('스토리 확인 필요')
        expect(panel.get_by_role('button',name='스토리 만들기',exact=True)).to_be_disabled()
        identifier=page.url.split('precision=')[1].split('&')[0];w=f.s.read(identifier)
        assert w['story_attempts'][0]['state']=='unknown'
        page.reload()
        expect(panel.get_by_role('button',name='스토리 만들기',exact=True)).to_be_disabled()
        assert f.s.read(identifier)==w and len(f.writer.calls)==1 and not f.adapter.calls
        context.close()


def test_precision_confirmed_images_move_to_video_without_generation(precision,browser,monkeypatch):
    from test_character_precision import confirmed
    f=precision;w=confirmed(f)
    f.app.state.character=f.owner;f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page()
        page.goto(origin+'/studio/characters?precision='+w['id'])
        page.get_by_role('button',name='영상 제작으로 이동',exact=True).click()
        expect(page.get_by_label('영상 길이',exact=True)).to_have_value('26')
        assert '?job_id=' in page.url
        assert not f.video.sent and not f.video.uploads and len(f.adapter.calls)==5
        context.close()


def test_precision_first_budget_is_visible_and_still_required(precision,browser,monkeypatch,tmp_path):
    f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page()
        def fresh(route):
            response=route.fetch();data=response.json();data['recent_settings']=None
            route.fulfill(response=response,json=data)
        page.route('**/api/studio/character-precision',fresh)
        page.goto(origin+'/studio/characters?precision=')
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(panel.locator('.precision-person')).to_have_count(2)
        panel.locator('.precision-person input[type=checkbox]').first.check()
        panel.get_by_label('스토리 주제',exact=True).fill('처음 만드는 작품')
        expect(panel.get_by_label('스토리·영상 예산(USD)',exact=True)).to_be_visible()
        expect(panel.get_by_role('button',name='스토리 만들기',exact=True)).to_be_disabled()
        panel.get_by_label('이미지 작업 예산(USD)',exact=True).fill('1')
        panel.get_by_label('스토리·영상 예산(USD)',exact=True).fill('5')
        expect(panel.get_by_role('button',name='스토리 만들기',exact=True)).to_be_enabled()
        panel.get_by_label('스토리·영상 예산(USD)',exact=True).fill('0')
        expect(panel.get_by_role('button',name='스토리 만들기',exact=True)).to_be_disabled()
        assert not f.writer.calls and not f.adapter.calls and not f.video.sent
        page.screenshot(path=str(tmp_path/'first-budget-visible.png'),full_page=True)
        context.close()


def test_precision_review_five_clicks_then_video(precision,browser,monkeypatch,tmp_path):
    from test_character_precision import generated
    f=precision;w=generated(f)
    f.app.state.image_studio=f.images;f.app.state.character=f.owner
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();page.set_viewport_size({'width':1366,'height':768})
        page.goto(origin+'/studio/characters?precision='+w['id'])
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(panel.get_by_text('캐릭터·스토리·설정 보기',exact=True)).to_be_visible()
        expect(panel.locator('.precision-saved')).not_to_be_visible()
        expect(panel.get_by_role('heading',name='장면 이미지 검토',exact=True)).to_be_in_viewport()
        page.screenshot(path=str(tmp_path/'review-condensed.png'),full_page=True)
        for n in range(1,6):
            expect(panel.locator('.precision-selected img')).to_have_attribute('alt',f'장면 {n}')
            panel.get_by_role('button',name='확정하고 다음 장면' if n<5 else '이미지 확정',exact=True).click()
            expect(panel.get_by_role('status')).to_contain_text(f'{n}장 확정')
            expect(page.get_by_role('dialog')).to_have_count(0)
        saved=f.s.read(w['id']);assert all(row['confirmed'] for row in saved['scenes'])
        assert len(f.adapter.calls)==5 and not f.video.sent
        panel.get_by_role('button',name='영상 제작으로 이동',exact=True).click()
        expect(page.get_by_label('영상 길이',exact=True)).to_have_value('26')
        assert not f.video.sent and not f.video.uploads
        context.close()


def test_precision_edit_only_selected_scene_preserves_others(precision,browser,monkeypatch,tmp_path):
    from copy import deepcopy
    from test_character_precision import generated
    f=precision;w=generated(f);before=deepcopy(w)
    f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page()
        page.goto(origin+'/studio/characters?precision='+w['id'])
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        panel.get_by_role('button',name='장면 3 ·').click()
        panel.get_by_text('버전·프롬프트 더보기',exact=True).click()
        panel.get_by_role('button',name='장면 내용 수정',exact=True).click()
        modal=page.get_by_role('dialog',name='장면 내용 수정',exact=True)
        expect(modal.get_by_label('편집할 장면')).to_have_value('3')
        expect(modal.locator('fieldset')).to_have_count(1)
        expect(modal.get_by_label('영상 동작 · 영어',exact=True)).not_to_be_visible()
        modal.get_by_role('textbox',name='장면 설명',exact=True).fill('친구가 숨겨 둔 쿠키 단서를 발견한다')
        modal.get_by_label('편집할 장면').select_option('2')
        expect(modal.get_by_role('textbox',name='장면 설명',exact=True)).to_have_value(before['scenes'][1]['plan']['description'])
        modal.get_by_label('편집할 장면').select_option('3')
        expect(modal.get_by_role('textbox',name='장면 설명',exact=True)).to_have_value('친구가 숨겨 둔 쿠키 단서를 발견한다')
        page.screenshot(path=str(tmp_path/'single-scene-editor.png'),full_page=True)
        modal.get_by_role('button',name='장면 저장 · 무료').click()
        expect(modal).not_to_be_visible()
        after=f.s.read(w['id'])
        assert after['scenes'][2]['plan']['description']=='친구가 숨겨 둔 쿠키 단서를 발견한다'
        for i in (0,1,3,4):assert after['scenes'][i]==before['scenes'][i]
        assert after['scenes'][2]['versions']==before['scenes'][2]['versions']
        assert len(f.adapter.calls)==5 and not f.writer.calls and not f.video.sent
        context.close()


def test_precision_failed_confirmation_stays_on_scene_without_retry(precision,browser,monkeypatch):
    from test_character_precision import generated
    f=precision;w=generated(f);f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();attempts=[]
        def fail(route):
            attempts.append(route.request.url)
            route.fulfill(status=503,content_type='application/json',body='{"detail":"synthetic confirmation failure"}')
        page.route('**/character-precision/*/confirm',fail)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        panel.get_by_role('button',name='확정하고 다음 장면',exact=True).click()
        expect(panel.get_by_role('alert')).to_be_visible()
        expect(panel.get_by_role('button',name='확정하고 다음 장면',exact=True)).to_be_enabled()
        expect(panel.locator('.precision-selected img')).to_have_attribute('alt','장면 1')
        assert len(attempts)==1 and f.s.read(w['id'])==w
        assert len(f.adapter.calls)==5 and not f.video.sent
        context.close()




def test_precision_double_click_does_not_confirm_next_scene(precision,browser,monkeypatch):
    from test_character_precision import generated
    f=precision;w=generated(f);f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();requests=[]
        page.on('request',lambda r:requests.append(r.url) if r.method=='POST' and r.url.endswith('/confirm') else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        panel=page.get_by_role('region',name='정밀 제작',exact=True)
        panel.get_by_role('button',name='확정하고 다음 장면',exact=True).dblclick()
        expect(panel.locator('.precision-selected img')).to_have_attribute('alt','장면 2')
        expect(panel.get_by_role('status')).to_contain_text('1장 확정')
        assert len(requests)==1
        assert sum(bool(row['confirmed']) for row in f.s.read(w['id'])['scenes'])==1
        assert len(f.adapter.calls)==5 and not f.video.sent
        context.close()


def test_precision_invalid_timing_blocks_before_approval_or_post(precision,browser,monkeypatch):
    f=precision;monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision=')
        p=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(p.locator('.precision-person')).to_have_count(2)
        p.locator('.precision-person input[type=checkbox]').first.check()
        p.get_by_label('스토리 주제',exact=True).fill('요청 전 길이 확인')
        p.get_by_label('총 길이(초)').fill('15');p.get_by_label('장면 수',exact=True).fill('12')
        expect(p.get_by_role('alert')).to_contain_text('15초를 12장면으로 만들 수 없습니다')
        expect(p.get_by_role('button',name='스토리 만들기',exact=True)).to_be_disabled()
        p.get_by_label('장면 수',exact=True).fill('5')
        expect(p.get_by_role('button',name='스토리 만들기',exact=True)).to_be_enabled()
        assert not posts and not f.writer.calls and not f.adapter.calls
        ctx.close()


def test_precision_reload_resumes_readonly_progress_and_stops_when_done(precision,browser,monkeypatch):
    from copy import deepcopy
    from test_character_precision import generated
    f=precision;w=generated(f);w['state']='generating';f.s.save(w)
    f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();gets=[];posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else gets.append(r.url) if r.url.endswith('/character-precision/'+w['id']) else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        p=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(p.get_by_role('status')).to_contain_text('이미지 생성 중')
        finished=deepcopy(w);finished['state']='images';f.s.save(finished)
        expect(p.get_by_role('button',name='확정하고 다음 장면')).to_be_enabled(timeout=8000)
        assert len(gets)>=2 and not posts
        count=len(gets);page.wait_for_timeout(2200)
        assert len(gets)==count and len(f.adapter.calls)==5 and not f.video.sent
        ctx.close()


def test_precision_progress_get_failure_recovers_without_post(precision,browser,monkeypatch):
    from test_character_precision import generated
    f=precision;w=generated(f);w['state']='generating';f.s.save(w)
    f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();attempts=[];posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        def response(route):
            attempts.append(1)
            if len(attempts)==2:route.fulfill(status=503,content_type='application/json',body='{}')
            else:route.continue_()
        page.route('**/character-precision/'+w['id'],response)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        p=page.get_by_role('region',name='정밀 제작',exact=True)
        expect(p.get_by_role('alert')).to_contain_text('진행 상태를 확인하지 못했습니다',timeout=8000)
        w['state']='images';f.s.save(w)
        expect(p.get_by_role('button',name='확정하고 다음 장면')).to_be_enabled(timeout=8000)
        expect(p.get_by_role('alert')).to_have_count(0)
        assert len(attempts)>=3 and not posts and len(f.adapter.calls)==5
        ctx.close()


def test_precision_unsaved_editor_close_requires_discard_confirmation(precision,browser,monkeypatch):
    from test_character_precision import generated
    f=precision;w=generated(f);f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();choices=[]
        def handle(dialog):
            choices.append(dialog.message)
            if len(choices)==1:dialog.dismiss()
            else:dialog.accept()
        page.on('dialog',handle)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        p=page.get_by_role('region',name='정밀 제작',exact=True)
        p.get_by_text('버전·프롬프트 더보기',exact=True).click()
        p.get_by_role('button',name='장면 내용 수정').click()
        modal=page.get_by_role('dialog',name='장면 내용 수정',exact=True)
        page.keyboard.press('Escape');expect(modal).not_to_be_visible();assert not choices
        p.get_by_role('button',name='장면 내용 수정').click()
        modal.get_by_role('textbox',name='장면 설명',exact=True).fill('보존할 편집 내용')
        page.keyboard.press('Escape')
        expect(modal).to_be_visible()
        expect(modal.get_by_role('textbox',name='장면 설명',exact=True)).to_have_value('보존할 편집 내용')
        assert len(choices)==1
        page.keyboard.press('Escape');expect(modal).not_to_be_visible()
        assert len(choices)==2 and f.s.read(w['id'])==w and len(f.adapter.calls)==5
        ctx.close()


def test_precision_editor_errors_are_inline_and_preserve_input(precision,browser,monkeypatch,tmp_path):
    from test_character_precision import generated
    f=precision;w=generated(f);f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        p=page.get_by_role('region',name='정밀 제작',exact=True)
        p.get_by_text('버전·프롬프트 더보기',exact=True).click()
        p.get_by_role('button',name='장면 내용 수정').click()
        modal=page.get_by_role('dialog',name='장면 내용 수정',exact=True)
        field=modal.get_by_role('textbox',name='장면 설명',exact=True);field.fill('')
        modal.get_by_role('button',name='장면 저장 · 무료').click()
        expect(modal.get_by_role('alert')).to_be_visible()
        expect(field).to_have_attribute('aria-invalid','true')
        expect(modal.get_by_text('내용을 입력하세요.',exact=True)).to_be_visible()
        assert not posts
        field.fill('수정한 장면 내용')
        page.route('**/character-precision/*/edit',lambda route:route.fulfill(status=409,content_type='application/json',body='{"detail":"저장 충돌: 최신 상태를 확인하세요."}'))
        modal.get_by_role('button',name='장면 저장 · 무료').click()
        expect(modal.get_by_role('alert')).to_contain_text('저장 충돌')
        expect(field).to_have_value('수정한 장면 내용')
        assert len(posts)==1 and f.s.read(w['id'])==w and len(f.adapter.calls)==5
        page.screenshot(path=str(tmp_path/'editor-inline-error.png'),full_page=True)
        ctx.close()


def test_precision_obsolete_image_is_labelled_and_cannot_confirm(precision,browser,monkeypatch):
    from copy import deepcopy
    from test_character_precision import generated
    f=precision;w=generated(f);changed=deepcopy(w['scenario']);changed['scenes'][0]['pose']='문 옆에서 접시를 봄'
    w=f.s.edit(w['id'],w['revision'],changed);f.app.state.image_studio=f.images
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        ctx=browser_context(browser,origin);page=ctx.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        p=page.get_by_role('region',name='정밀 제작',exact=True)
        p.get_by_text('버전·프롬프트 더보기',exact=True).click()
        p.get_by_label('장면 1 이미지 버전').select_option('1')
        expect(p.get_by_role('button',name='이전 장면 이미지',exact=True)).to_be_disabled()
        expect(p.get_by_text('이전 장면의 이미지입니다. 현재 장면에 맞게 다시 만든 뒤 확정하세요.',exact=True)).to_be_visible()
        expect(p.locator('.precision-selected img')).to_be_visible()
        assert not posts and f.s.read(w['id'])==w and len(f.adapter.calls)==5
        ctx.close()
