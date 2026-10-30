"""Synthetic Chrome rendering only; no live provider requests or operating writes."""
from pathlib import Path
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_automation import setup_episode
from test_character_story_feedback_browser import NoSecret
from newsflow.video.engine import FFmpegAdapter

def test_quote_refresh_is_separate_and_notsent_has_clear_status(app,browser,monkeypatch):
    monkeypatch.setattr(FFmpegAdapter,'executable',staticmethod(lambda *a:Path('synthetic-tool.exe')))
    service,video,i,_,_=setup_episode(app.state.config.data_dir,15)
    service.sessions=app.state.sessions
    service.write(i,consent=True);service.prepare(i,consent=True,script_reviewed=True)
    app.state.character=service;app.state.character_authoring=service.authoring
    app.state.api_keys={'claude_api':NoSecret()}
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?job_id='+i)
        refresh=page.get_by_role('button',name='견적 다시 확인',exact=True)
        production=page.get_by_role('region',name='영상 비용 및 제작',exact=True)
        # Section has no implicit region role in every engine; stable accessible label is used below.
        production=page.locator('section[aria-label="영상 비용 및 제작"]')
        expect(refresh).to_be_visible()
        expect(page.locator('.kling-settings-footer').get_by_role('button',name='견적 다시 확인',exact=True)).to_have_count(1)
        expect(production.get_by_role('button')).to_have_count(1)
        expect(production.get_by_role('button',name='영상 생성하기',exact=True)).to_be_visible()
        for width,height in ((1366,768),(1920,1080)):
            page.set_viewport_size({'width':width,'height':height})
            refresh.scroll_into_view_if_needed()
            box=refresh.bounding_box();assert box and box['height']<=40 and box['width']<220
            path=Path(r'C:/Codex/NewsFlowAI/character_automation_operating')/f'submit-layout-{width}x{height}.png'
            page.screenshot(path=str(path),full_page=True)
        job=service.read(i);job['state']='submission_not_sent'
        job['scenes'][0]['state']='not_sent';service.save(job)
        page.reload();expect(page.get_by_text('전송 전 중단',exact=True)).to_be_visible()
        expect(production).to_contain_text('미전송 1')
        assert not posts and not video.sent
        context.close()
