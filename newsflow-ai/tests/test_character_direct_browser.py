"""Cancelled direct entry: story-only UI; historical data stays readable."""
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_story_feedback_browser import setup
from test_character_operating_authoring import connected
from test_character_automation_routes import gui
from test_api_settings import sessions


def test_character_studio_exposes_only_original_story_flow(app,browser):
    setup(app)
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page=ctx.new_page();posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters')
        expect(page.get_by_role('button',name='이미지·주제 제작',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='스토리로 제작',exact=True)).to_have_count(0)
        expect(page.get_by_role('button',name='스토리 자동 생성하기',exact=False)).to_be_visible()
        expect(page.get_by_label('대본 AI',exact=True)).to_be_visible()
        page.get_by_text('주제 자동 생성·기록',exact=True).click()
        expect(page.get_by_role('button',name='주제 자동 생성',exact=True)).to_be_visible()
        assert not posts
        ctx.close()


def test_cancelled_direct_creation_request_is_rejected_before_provider(connected):
    c=connected;before=c.service.listing()
    import json
    from uuid import uuid4
    from newsflow.character.kling import check
    result=c.post('/character',creation_mode='direct',topic='합성 주제',episode_limit='5',
        request_id=uuid4().hex,reference_asset=c.gui.asset,
        studio_settings=json.dumps(check(c.service.read(c.identifier)['studio_selection'])))
    assert result.status_code==410
    assert c.service.listing()==before and not c.state.calls and not c.state.decryptions
