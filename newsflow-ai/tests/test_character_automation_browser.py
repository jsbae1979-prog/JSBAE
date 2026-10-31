"""Windows Chrome + actual React/Python routes, synthetic profile and Fake AI only."""
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_automation import FakeAuthoring, FakeVideo, image, profile
from newsflow.character.registry import CharacterRegistry
from newsflow.character.kling import DEFAULTS, O3

CAPTURE_DIR = Path(os.environ["NEWSFLOW_CHARACTER_CAPTURE_DIR"]).resolve() if os.environ.get("NEWSFLOW_CHARACTER_CAPTURE_DIR") else None


def test_registered_profiles_openai_script_editor_and_responsive_layout(app,browser,tmp_path):
    state=app.state
    class Key:
        def status(self):return {'configured':True}
        def key(self):raise AssertionError('Real credentials must never be read')
    state.api_keys={'claude_api':Key(),'openai':Key()}
    state.character_authoring=FakeAuthoring()
    video=FakeVideo({**DEFAULTS,'video_model':O3,'native_resolution':'std'},tmp_path,Path('unused-ffmpeg'))
    state.character.video=video;state.character.video_override=video
    registry=CharacterRegistry(state.config.data_dir,state.image_studio)
    first=registry.save(profile('합성 토끼','rabbit'),state.image_studio.asset_bytes(image()))
    second=registry.save(profile('합성 펭귄','penguin'),state.image_studio.asset_bytes(image('green')))
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1920,'height':1080})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        context.route('**/api/studio/characters/*/story-review',lambda route:route.fulfill(
            json={'ready':True,'review':{'token':'','count':0,'held_usd':'0'}}))
        page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(origin+'/studio/characters')
        page.get_by_role('button',name='내 캐릭터',exact=True).click()
        picker=page.get_by_label('저장된 캐릭터',exact=True)
        expect(picker).to_be_visible()
        picker.select_option('profile:'+second['id'])
        page.get_by_label('대본 AI',exact=True).select_option('openai')
        page.get_by_label('영상 길이',exact=True).select_option('35')
        page.get_by_label('스토리 주제',exact=True).fill('정원의 아침')
        expect(page.get_by_role('button',name='스토리 자동 생성하기')).to_be_enabled()
        page.get_by_role('button',name='스토리 자동 생성하기').click()
        expect(page.get_by_role('heading',name='한글 스토리 · 합성 펭귄의 정원',exact=True)).to_be_visible(timeout=20000)
        expect(page.get_by_label('스토리 주제',exact=True)).to_have_value('정원의 아침')
        expect(page.get_by_role('button',name='스토리 자동 생성하기')).to_be_disabled()
        assert len(state.character_authoring.calls)==1
        assert state.character_authoring.calls[0]['character']['species']=='penguin'
        job=state.character.listing()[0]
        assert job['duration']==35 and job['script_provider']=='openai' and len(job['script']['scenes'])==3
        expect(page.get_by_label('영상 모델',exact=True)).to_be_disabled()
        expect(page.get_by_label('영상 길이',exact=True)).to_be_disabled()
        expect(page.get_by_text('0:22 - 0:35',exact=True)).to_be_visible()
        page.get_by_text('장면 연출·자막·효과음 검토',exact=True).click()
        page.get_by_label('첫 자막',exact=True).fill('느긋한 아침')
        expect(page.get_by_role('button',name='영상 견적 확인',exact=True)).to_be_disabled()
        page.get_by_role('button',name='변경 저장 · 승인 다시 받기',exact=True).click()
        expect(page.get_by_role('button',name='영상 견적 확인',exact=True)).to_be_enabled()
        assert state.character.read(job['id'])['script']['hook_caption']=='느긋한 아침'
        assert not video.sent and not video.uploads
        page.get_by_text('장면 연출·자막·효과음 검토',exact=True).click()
        page.locator('.kling-character-story-result').evaluate('(el)=>el.scrollTop=0')
        for width,height in ((1920,1080),(1366,768)):
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            for title in ('1. 캐릭터 선택','2. 스토리 생성','3. 영상 제작'):
                expect(page.get_by_role('heading',name=title,exact=False)).to_be_visible()
            folder=CAPTURE_DIR or tmp_path/'captures'
            folder.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(folder/f'character-automation-{width}x{height}.png'),full_page=True)
        assert not errors
        context.close()


def test_pending_topic_response_cannot_switch_character_or_start_another_request(app,browser,tmp_path):
    from threading import Event
    release=Event();called=Event();seen=[]
    class Key:
        def status(self):return {'configured':True}
        def key(self):raise AssertionError('No real keys')
    class DelayedFake(FakeAuthoring):
        def topics(self,character,count,existing,**kwargs):
            seen.append(character['id']);called.set()
            assert release.wait(10),'Synthetic response was not released'
            return [{'topic':'정원의 작은 실수','category':'정원','joke_type':'반전'}]
    state=app.state;state.api_keys={'claude_api':Key(),'openai':Key()};state.character_authoring=DelayedFake()
    registry=CharacterRegistry(state.config.data_dir,state.image_studio)
    first=registry.save(profile('합성 토끼','rabbit'),state.image_studio.asset_bytes(image()))
    second=registry.save(profile('합성 펭귄','penguin'),state.image_studio.asset_bytes(image('green')))
    with local_server(app) as origin:
        context=browser.new_context()
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();page.goto(origin+'/studio/characters')
        page.get_by_role('button',name='내 캐릭터',exact=True).click()
        picker=page.get_by_label('저장된 캐릭터',exact=True);picker.select_option('profile:'+first['id'])
        page.get_by_text('주제 자동 생성·기록',exact=True).click()
        page.get_by_label('주제 개수',exact=True).fill('1')
        expect(page.get_by_label('주제 생성 유료 요청에 동의합니다.',exact=True)).to_have_count(0)
        try:
            page.get_by_role('button',name='주제 자동 생성',exact=True).click()
            assert called.wait(5)
            expect(picker).to_be_disabled()
            expect(page.get_by_label('대본 AI',exact=True)).to_be_disabled()
            expect(page.get_by_role('button',name='특징 수정',exact=True)).to_be_disabled()
        finally:release.set()
        expect(page.get_by_role('button',name='정원의 작은 실수',exact=True)).to_be_visible()
        expect(picker).to_be_enabled()
        picker.select_option('profile:'+second['id'])
        expect(page.get_by_role('button',name='정원의 작은 실수',exact=True)).to_have_count(0)
        assert seen==[first['id']]
        context.close()


def test_character_registration_modal_keyboard_responsive_and_explicit_save(app,browser,tmp_path):
    state=app.state
    registry=CharacterRegistry(state.config.data_dir,state.image_studio)
    calls=[]
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();page.on('request',lambda r:calls.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters')
        expect(page.get_by_label('저장된 캐릭터',exact=True)).to_have_count(0)
        page.get_by_label('캐릭터 참조 이미지 업로드',exact=True).set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':image()})
        trigger=page.get_by_role('button',name='새 캐릭터 등록',exact=True)
        trigger.click()
        dialog=page.get_by_role('dialog',name='새 캐릭터 등록',exact=True)
        expect(dialog).to_be_visible()
        expect(dialog.get_by_label('캐릭터 이름',exact=True)).to_be_focused()
        assert dialog.get_by_label('캐릭터 이름',exact=True).evaluate('(e)=>e.tagName')=='INPUT'
        assert dialog.get_by_label('고정 스타일 · 영어',exact=True).evaluate('(e)=>e.tagName')=='INPUT'
        assert dialog.get_by_label('성격',exact=True).evaluate('(e)=>e.tagName')=='TEXTAREA'
        page.keyboard.press('Escape')
        expect(dialog).to_have_count(0);expect(trigger).to_be_focused()
        assert not registry.list() and not calls
        trigger.click();dialog=page.get_by_role('dialog',name='새 캐릭터 등록',exact=True)
        values=profile('새 합성 토끼','rabbit')
        dialog.get_by_text('추가 정보 · 선택',exact=True).click()
        for label,key in [('캐릭터 이름','name_ko'),('종류','species'),('외형 · 영어','appearance'),('성격','personality'),('고정 스타일 · 영어','style_lock')]:
            dialog.get_by_label(label,exact=True).fill(values[key])
        for label,key in [('이야기의 세계','world'),('반복되는 상황','setup'),('캐릭터만의 반응','reaction')]:
            dialog.get_by_label(label,exact=True).fill(values['comedy_formula'][key])
        dialog.get_by_text('추가 정보 · 선택',exact=True).click()
        for width,height in ((1920,1080),(1366,768),(390,844)):
            page.set_viewport_size({'width':width,'height':height})
            assert dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
            bounds=dialog.bounding_box();assert bounds and bounds['x']>=0 and bounds['x']+bounds['width']<=width+1
            expect(dialog.get_by_role('button',name='캐릭터 저장',exact=True)).to_be_visible()
            expect(dialog.get_by_role('button',name='취소',exact=True)).to_be_visible()
            positions=dialog.locator('.character-profile-form > .character-profile-fields > label').evaluate_all('(es)=>es.slice(1,3).map(e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y}))')
            if width==390:assert positions[0]['y']<positions[1]['y'] and positions[0]['x']==positions[1]['x']
            else:assert positions[0]['y']==positions[1]['y'] and positions[0]['x']<positions[1]['x']
            out=CAPTURE_DIR or tmp_path/'captures';out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/f'character-registration-modal-{width}x{height}.png'))
        dialog.get_by_role('button',name='캐릭터 저장',exact=True).click()
        expect(dialog).to_have_count(0)
        picker=page.get_by_label('저장된 캐릭터',exact=True)
        expect(picker).to_be_visible()
        saved=registry.list();assert len(saved)==1 and saved[0]['name_ko']==values['name_ko']
        expect(picker).to_have_value('profile:'+saved[0]['id'])
        assert not any('/analyze' in url or '/auto-story' in url for url in calls)
        preview=page.get_by_role('button',name='참조 이미지 크게 보기',exact=True);preview.click()
        expect(page.get_by_role('dialog',name='참조 이미지 미리보기',exact=True)).to_be_visible()
        page.keyboard.press('Escape');expect(preview).to_be_focused()
        context.close()


def test_saved_image_is_not_profile_until_registered_and_profile_edit_is_local(app,browser,tmp_path):
    state=app.state
    registry=CharacterRegistry(state.config.data_dir,state.image_studio)
    saved=registry.save(profile('기존 합성 토끼','rabbit'),state.image_studio.asset_bytes(image()))
    # Existing image-only library records remain distinct and are never auto-registered.
    raw=image('green')
    image_row=state.image_studio.save_character(raw,'기존 이미지')
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();page.goto(origin+'/studio/characters')
        page.get_by_role('button',name='내 캐릭터',exact=True).click()
        picker=page.get_by_label('저장된 캐릭터',exact=True)
        assert picker.locator('optgroup').count()==2
        picker.select_option('image:'+image_row['id'])
        expect(page.get_by_role('button',name='이 이미지로 캐릭터 등록',exact=True)).to_be_enabled()
        expect(page.get_by_role('button',name='스토리 자동 생성하기',exact=False)).to_be_disabled()
        assert len(registry.list())==1
        page.get_by_role('button',name='이 이미지로 캐릭터 등록',exact=True).click()
        page.get_by_role('dialog',name='새 캐릭터 등록',exact=True).get_by_role('button',name='취소',exact=True).click()
        assert len(registry.list())==1
        picker.select_option('profile:'+saved['id'])
        page.get_by_role('button',name='특징 수정',exact=True).click()
        dialog=page.get_by_role('dialog',name='캐릭터 특징 수정',exact=True)
        dialog.get_by_role('textbox',name='성격',exact=True).fill('조용하지만 호기심이 많은 성격')
        dialog.get_by_role('button',name='캐릭터 저장',exact=True).click()
        expect(dialog).to_have_count(0)
        updated=registry.get(saved['id'])
        assert updated['revision']==saved['revision']+1 and updated['personality']=='조용하지만 호기심이 많은 성격'
        assert updated['asset']==saved['asset'] and state.image_studio.asset(image_row['id']).read_bytes()
        assert len(registry.list())==1 and not state.character.listing()
        context.close()


@pytest.mark.parametrize('failure_kind,detail', [
    ('generic', '입력·저장 상태·API 승인 한도를 확인하세요. 결과가 불명확하면 자동 재요청하지 않습니다.'),
    ('schema', '외형 설명: 글자 수 초과'),
])
def test_analysis_failure_is_visible_in_modal_footer_and_preserves_draft(app,browser,tmp_path,failure_kind,detail):
    from urllib.parse import parse_qs
    attempts=[]
    class Key:
        def status(self):return {'configured':True}
        def key(self):raise AssertionError('No real keys')
    app.state.api_keys={'claude_api':Key()}
    def fail_analysis(route):
        assert route.request.method=='POST'
        attempts.append(parse_qs(route.request.post_data))
        route.fulfill(status=409,json={'detail':detail})
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        context.route('**/api/studio/characters/profiles/analyze',fail_analysis)
        page=context.new_page();page.goto(origin+'/studio/characters')
        page.get_by_label('캐릭터 참조 이미지 업로드',exact=True).set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':image()})
        page.get_by_role('button',name='새 캐릭터 등록',exact=True).click()
        dialog=page.get_by_role('dialog',name='새 캐릭터 등록',exact=True)
        dialog.get_by_role('textbox',name='캐릭터 이름',exact=True).fill('보존할 합성 캐릭터')
        dialog.get_by_role('textbox',name='성격',exact=True).fill('천천히 주변을 살펴보는 성격')
        dialog.get_by_text('AI로 특징 초안 만들기 · 선택 사항',exact=True).click()
        expect(dialog.get_by_label('선택한 AI에 참조 이미지를 전송하는 유료 분석에 동의합니다.',exact=True)).to_have_count(0)
        dialog.get_by_role('button',name='이미지로 특징 초안 만들기',exact=True).click()
        alert=dialog.get_by_role('alert')
        expect(alert).to_have_text('특징 초안을 만들지 못했습니다.'+(' 외형 설명: 글자 수 초과' if failure_kind=='schema' else ''))
        dialog.locator('.character-modal-body').evaluate('(e)=>e.scrollTop=0')
        expect(alert).to_be_in_viewport()
        expect(dialog.locator('.character-modal-footer').get_by_role('alert')).to_have_count(1)
        expect(dialog.get_by_role('button',name='취소',exact=True)).to_be_enabled()
        expect(dialog.get_by_role('textbox',name='캐릭터 이름',exact=True)).to_have_value('보존할 합성 캐릭터')
        expect(dialog.get_by_role('textbox',name='성격',exact=True)).to_have_value('천천히 주변을 살펴보는 성격')
        assert len(attempts)==1 and attempts[0]['consent']==['true']
        assert not CharacterRegistry(app.state.config.data_dir,app.state.image_studio).list()
        out=CAPTURE_DIR or tmp_path/'captures';out.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(out/f'character-analysis-failure-{failure_kind}-1366x768.png'))
        context.close()


def test_compact_reference_and_topic_controls_preserve_explicit_actions(app,browser,tmp_path):
    registry=CharacterRegistry(app.state.config.data_dir,app.state.image_studio)
    saved=registry.save(profile('합성 토끼','rabbit'),app.state.image_studio.asset_bytes(image()))
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters')
        page.get_by_label('캐릭터 참조 이미지 업로드',exact=True).set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':image()})
        expect(page.get_by_role('button',name='새 캐릭터 등록',exact=True)).to_be_enabled()
        expect(page.get_by_text('이미지를 선택했습니다. 이름과 특징을 등록하면 주제·스토리에 사용할 수 있습니다.',exact=True)).to_have_count(0)
        expect(page.get_by_text('이미지만 보관합니다. 이름과 특징은 캐릭터 등록에서 저장하세요.',exact=True)).to_have_count(0)
        checkbox=page.get_by_label('참조 이미지 보관',exact=True)
        box=checkbox.bounding_box();assert box and box['width']<=20 and box['height']<=20
        assert checkbox.locator('..').evaluate('(e)=>getComputedStyle(e).flexDirection')=='row'
        panel=page.locator('.character-profile-editor')
        assert panel.evaluate('(e)=>getComputedStyle(e).borderTopWidth')=='0px'
        out=CAPTURE_DIR or tmp_path/'captures';out.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(out/'character-reference-compact-1366x768.png'))
        page.get_by_role('button',name='내 캐릭터',exact=True).click()
        page.get_by_label('저장된 캐릭터',exact=True).select_option('profile:'+saved['id'])
        page.get_by_label('스토리 주제',exact=True).fill('정원의 느긋한 아침')
        tools=page.locator('.character-topic-tools')
        assert tools.evaluate('(e)=>e.open') is False
        assert page.get_by_label('스토리 주제',exact=True).bounding_box()['y']<tools.bounding_box()['y']
        page.get_by_text('주제 자동 생성·기록',exact=True).click()
        consent=page.get_by_label('주제 생성 유료 요청에 동의합니다.',exact=True)
        expect(consent).to_have_count(0)
        assert page.get_by_label('주제 개수',exact=True).bounding_box()['width']<=90
        expect(tools.locator('.character-batch')).to_have_count(0)
        expect(tools.locator('.character-topic-import')).to_have_count(0)
        expect(tools.locator('.character-topic-advanced')).to_have_count(0)
        expect(page.get_by_role('button',name='입력한 주제 저장',exact=True)).to_be_enabled()
        expect(page.get_by_role('button',name='주제 자동 생성',exact=True)).to_be_disabled()
        for width,height in ((1920,1080),(1366,768)):
            page.set_viewport_size({'width':width,'height':height})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(out/f'character-topic-compact-{width}x{height}.png'),full_page=True)
        assert not posts and len(registry.list())==1
        context.close()
