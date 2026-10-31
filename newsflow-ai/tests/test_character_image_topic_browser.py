"""User-visible image/topic path, no registration or paid analysis. Local Fake only."""
from pathlib import Path
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_story_feedback_browser import setup,open_story
from test_character_episode_schema import image

def test_uploaded_image_and_topic_enable_single_story_without_profile_registration(app,browser,tmp_path):
    saved=setup(app)
    with local_server(app) as origin:
        ctx,page,posts=open_story(browser,origin,saved)
        page.get_by_role('button',name='참조 이미지 업로드',exact=True).click()
        sample=tmp_path/'original.png';sample.write_bytes(image('teal'))
        page.get_by_label('캐릭터 참조 이미지 업로드',exact=True).set_input_files(str(sample))
        page.get_by_label('스토리 주제',exact=True).fill('주어진 이미지의 캐릭터가 우산을 찾아요')
        trigger=page.get_by_role('button',name='스토리 자동 생성하기',exact=False)
        expect(trigger).to_be_enabled()
        assert page.get_by_text('특징 등록 완료',exact=True).count()==0
        sent=[]
        def refuse(route):
            sent.append(route.request.url)
            route.fulfill(status=409,json={'error':'Synthetic stop after explicit button; no paid call.'})
        ctx.route('**/api/studio/characters/auto-story',refuse)
        trigger.click()
        expect(page.get_by_role('alert')).to_contain_text('Synthetic stop after explicit button')
        expect(page.get_by_label('스토리 주제',exact=True)).to_have_value('주어진 이미지의 캐릭터가 우산을 찾아요')
        expect(page.get_by_role('img',name='선택한 캐릭터 로컬 미리보기',exact=True)).to_be_visible()
        expect(page.get_by_text('선택한 작업을 찾을 수 없습니다. 작업 이력에서 다른 작업을 선택하세요.',exact=True)).to_have_count(0)
        jobs=app.state.character.listing();assert len(jobs)==1 and jobs[0]['character_reference_mode']=='image_topic'
        assert len(sent)==1 and not any('/analyze' in p or '/profiles/save' in p or '/library' in p for p in posts)
        expect(page.get_by_role('dialog')).to_have_count(0)
        captures=Path(r'C:/Codex/NewsFlowAI/character_automation_operating')
        for w,h in ((1366,768),(1920,1080)):
            page.set_viewport_size({'width':w,'height':h})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(captures/f'image-topic-{w}x{h}.png'),full_page=True)
        ctx.close()
