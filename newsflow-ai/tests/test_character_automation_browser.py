"""Windows Chrome + actual React/Python routes, synthetic profile and Fake AI only."""
import os
from pathlib import Path
from types import SimpleNamespace
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
        page=context.new_page();errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(origin+'/studio/characters')
        picker=page.get_by_label('등록된 캐릭터',exact=True)
        expect(picker).to_be_visible()
        picker.select_option(second['id'])
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
