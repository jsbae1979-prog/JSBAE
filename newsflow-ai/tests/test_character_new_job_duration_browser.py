"""New-job duration uses current catalog, never the last completed job; no paid requests."""
from uuid import uuid4
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_story_feedback_browser import setup
from test_character_episode_schema import image
from test_character_topics_simple_browser import context_for
from newsflow.character.kling import DEFAULTS


def test_new_job_uses_twenty_without_changing_saved_thirty(app, browser):
    saved = setup(app)
    identifier, _ = app.state.character.create_episode(
        '합성 기존 작업', '5', reference=image(),
        settings={**DEFAULTS, 'duration': 30}, request_id=uuid4().hex, profile=saved)
    before = app.state.character.read(identifier)
    with local_server(app) as origin:
        context = context_for(browser, origin)
        def restored_defaults(route):
            response = route.fetch()
            data = response.json()
            data['catalog']['characterStudio']['defaults']['duration'] = 30
            data['catalog']['characterStudio']['character']['target_duration']['default'] = 20
            route.fulfill(response=response, json=data)
        context.route('**/api/studio/modules/characters', restored_defaults)
        page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.goto(origin + '/studio/characters?job_id=' + identifier)
        expect(page.get_by_label('영상 길이', exact=True)).to_have_value('30')
        page.get_by_role('button', name='작업 이력', exact=True).click()
        page.get_by_role('dialog').get_by_role('button', name='새 작업', exact=True).click()
        expect(page.get_by_label('영상 길이', exact=True)).to_have_value('20')
        page.get_by_label('영상 길이', exact=True).select_option('35')
        expect(page.get_by_label('영상 길이', exact=True)).to_have_value('35')
        page.goto(origin + '/studio/characters?job_id=' + identifier)
        expect(page.get_by_label('영상 길이', exact=True)).to_have_value('30')
        assert not posts and app.state.character.read(identifier) == before
        context.close()
