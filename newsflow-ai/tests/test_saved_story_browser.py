"""Only local synthetic candidates and Fake providers; visible review has no paid calls."""
from copy import deepcopy
from pathlib import Path
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_episode_saved_candidate import failed
from test_character_story_feedback_browser import NoSecret


def ready(app,browser):
    service,authoring,adapter,budget,identifier=failed(app.state.config.data_dir)
    service.sessions=app.state.sessions
    app.state.character=service;app.state.character_authoring=authoring
    app.state.api_keys={'claude_api':NoSecret()}
    return service,adapter,budget,identifier


def test_saved_story_review_cancel_is_readonly_and_edited_recovery_is_free(app,browser,tmp_path):
    service,adapter,budget,identifier=ready(app,browser)
    original=service.read(identifier)
    source=service.folder(identifier)/original['script_responses'][0]['file'];raw=source.read_bytes()
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();posts=[]
        page.on('request',lambda req:posts.append(req.url) if req.method=='POST' else None)
        page.goto(origin+'/studio/characters?job_id='+identifier)
        trigger=page.get_by_role('button',name='직접 검토·편집',exact=True)
        expect(trigger).to_be_visible();trigger.click()
        dialog=page.get_by_role('dialog',name='보관된 스토리 검토',exact=True)
        expect(dialog).to_be_visible()
        field=dialog.get_by_role('textbox',name='장면 1 카메라',exact=True)
        expect(field).to_have_value('C'*121)
        expect(dialog).to_contain_text('121/120')
        assert len(adapter.bodies)==1 and not posts
        for width,height in ((1366,768),(1920,1080)):
            page.set_viewport_size({'width':width,'height':height})
            expect(dialog.get_by_role('button',name='편집본 검증·복구 · 추가 비용 없음',exact=True)).to_be_visible()
        dialog.get_by_role('button',name='닫기',exact=True).click()
        assert service.read(identifier)==original and source.read_bytes()==raw and not posts
        trigger.click();expect(dialog).to_be_visible()
        dialog.get_by_role('textbox',name='장면 1 카메라',exact=True).fill('Slow close-up')
        dialog.get_by_role('button',name='편집본 검증·복구 · 추가 비용 없음',exact=True).click()
        expect(dialog).to_have_count(0)
        expect(page.get_by_role('button',name='영상 견적 확인',exact=True)).to_be_visible()
        done=service.read(identifier)
        assert done['state']=='script_review' and len(adapter.bodies)==1 and len(posts)==1
        assert posts[0].endswith('/recover-story') and source.read_bytes()==raw
        context.close()
