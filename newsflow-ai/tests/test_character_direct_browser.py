"""Direct mode quotes an image/topic without any writer or image analysis call."""
from pathlib import Path
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image
from test_character_episode_automation import FakeVideo
from newsflow.character.kling import DEFAULTS,O3

def test_image_topic_direct_mode_requires_no_text_key_and_never_calls_writer(app,browser,tmp_path):
    app.state.api_keys={}
    class NoText:
        def generate(self,*a,**kw):raise AssertionError('Direct mode cannot call a story provider')
        def analyze(self,*a,**kw):raise AssertionError('Direct mode cannot analyze an image')
    app.state.character_authoring=NoText()
    fake=FakeVideo({**DEFAULTS,'video_model':O3,'native_resolution':'std'},tmp_path,Path('not-executed'))
    app.state.character.video_override=fake;app.state.character.video=fake
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page=ctx.new_page();posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters')
        page.get_by_role('button',name='이미지·주제 제작',exact=True).click()
        expect(page.get_by_role('heading',name='2. 주제 입력',exact=True)).to_be_visible()
        expect(page.get_by_role('button',name='스토리 자동 생성하기',exact=False)).to_have_count(0)
        expect(page.get_by_label('대본 AI',exact=True)).to_have_count(0)
        expect(page.get_by_label('영상 길이',exact=True)).to_have_value('15')
        page.get_by_label('영상 길이',exact=True).select_option('30')
        png=tmp_path/'original.png';png.write_bytes(image('purple'))
        page.get_by_label('캐릭터 참조 이미지 업로드',exact=True).set_input_files(str(png))
        page.get_by_label('영상 주제',exact=True).fill('바람에 날린 모자를 찾는 캐릭터')
        page.get_by_role('button',name='영상 견적 확인',exact=True).click()
        expect(page.get_by_role('button',name='영상 생성하기',exact=True)).to_be_enabled(timeout=15000)
        jobs=app.state.character.listing();assert len(jobs)==1
        assert jobs[0]['direct_video'] and jobs[0]['text_provider_calls']==0 and jobs[0]['state']=='quoted'
        expect(page.get_by_role('heading',name='한글 스토리',exact=False)).to_have_count(0)
        expect(page.get_by_text('장면 연출·자막·효과음 검토',exact=True)).to_have_count(0)
        assert jobs[0]['duration']==30 and jobs[0]['direct_extension']
        assert len(jobs[0]['scenes'])==2 and fake.uploads and not fake.sent
        assert all('/auto-story' not in p and '/analyze' not in p for p in posts)
        captures=Path(r'C:/Codex/NewsFlowAI/character_automation_operating')
        for w,h in ((1366,768),(1920,1080)):
            page.set_viewport_size({'width':w,'height':h})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(captures/f'direct-video-{w}x{h}.png'),full_page=True)
        ctx.close()
