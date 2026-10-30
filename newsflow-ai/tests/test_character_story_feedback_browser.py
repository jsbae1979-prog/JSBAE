"""One story error region across local failure, persisted diagnosis and refresh; Fake only."""
from copy import deepcopy

from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile
from newsflow.character.registry import CharacterRegistry
from newsflow.character.schema import CharacterError


class NoSecret:
    def status(self): return {'configured': True}
    def key(self): raise AssertionError('Synthetic feedback checks cannot read credentials')


class FakePreflight:
    response_received = False
    last_reserved_usd = '0'
    last_failure = {'stage': 'budget', 'reason': 'authentication_required', 'dispatched': False}
    def __init__(self): self.calls = 0
    def generate(self, *args, **kwargs):
        assert kwargs['consent'] is True
        self.calls += 1
        raise CharacterError('provider')


def setup(app):
    registry = CharacterRegistry(app.state.config.data_dir, app.state.image_studio)
    saved = registry.save(profile('합성 안내 토끼'), app.state.image_studio.asset_bytes(image()))
    app.state.api_keys = {'claude_api': NoSecret()}
    return saved


def open_story(browser, origin, saved):
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    page = context.new_page(); posts = []
    page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
    page.goto(origin + '/studio/characters')
    page.get_by_role('button', name='내 캐릭터', exact=True).click()
    page.get_by_label('저장된 캐릭터', exact=True).select_option('profile:' + saved['id'])
    page.get_by_label('스토리 주제', exact=True).fill('정원의 느긋한 아침')
    return context, page, posts


def assert_one_story_message(page, message):
    story = page.locator('.kling-character-story')
    error = story.locator(':scope > .kling-character-error')
    expect(error).to_have_count(1)
    expect(error).to_contain_text(message)
    expect(story.get_by_role('alert')).to_have_count(1)
    assert story.inner_text().count(message) == 1
    assert story.locator('.kling-character-story-generate').evaluate(
        '(e)=>e.nextElementSibling.classList.contains("kling-character-error")')
    assert story.locator('.character-topic-tools').evaluate(
        '(e)=>Boolean(e.compareDocumentPosition(e.parentElement.querySelector(":scope > .kling-character-error")) & Node.DOCUMENT_POSITION_PRECEDING)')


def assert_new_story_keeps_reference(page, saved):
    page.get_by_role('button', name='새 스토리 입력', exact=True).click()
    expect(page.get_by_label('스토리 주제', exact=True)).to_have_value('')
    expect(page.locator('.kling-character-story > .kling-character-error')).to_have_count(0)
    expect(page.get_by_role('img', name='선택한 캐릭터 참조 이미지', exact=True)).to_have_attribute(
        'src', '/image-studio/assets/' + saved['asset'])
    expect(page.get_by_label('저장된 캐릭터', exact=True)).to_have_value('profile:' + saved['id'])


def test_persisted_preflight_message_appears_once_after_request_and_refresh(app, browser):
    saved = setup(app); fake = FakePreflight(); app.state.character_authoring = fake
    message = '설정에서 선택한 AI의 연결 상태를 다시 확인하세요. 유료 요청은 전송되지 않았습니다.'
    with local_server(app) as origin:
        context, page, posts = open_story(browser, origin, saved)
        page.get_by_role('button', name='스토리 자동 생성하기', exact=False).click()
        assert_one_story_message(page, message)
        jobs = app.state.character.listing()
        assert len(jobs) == 1 and fake.calls == 1
        job = deepcopy(jobs[0])
        assert job['state'] == 'needs_script' and job['script_failure']['dispatched'] is False
        assert job['script_attempts'] == 0 and not job.get('text_reservations')
        assert len(posts) == 2 and posts[0].endswith('/character') and posts[1].endswith('/auto-story')
        assert_new_story_keeps_reference(page, saved)
        page.goto(origin + '/studio/characters?job_id=' + job['id'])
        assert_one_story_message(page, message)
        page.reload()
        assert_one_story_message(page, message)
        assert fake.calls == 1 and len(posts) == 2 and app.state.character.read(job['id']) == job
        context.close()


def test_generic_request_error_remains_visible_once_and_new_story_keeps_reference(app, browser):
    saved = setup(app)
    message = '합성 스토리 전송을 완료하지 못했습니다.'
    with local_server(app) as origin:
        context, page, posts = open_story(browser, origin, saved)
        context.route('**/api/studio/characters/auto-story',
            lambda route: route.fulfill(status=409, json={'error': message}))
        page.get_by_role('button', name='스토리 자동 생성하기', exact=False).click()
        assert_one_story_message(page, message)
        assert len(posts) == 2 and posts[0].endswith('/character') and posts[1].endswith('/auto-story')
        jobs = app.state.character.listing()
        assert len(jobs) == 1 and jobs[0]['state'] == 'needs_script' and jobs[0]['script'] is None
        assert_new_story_keeps_reference(page, saved)
        assert len(posts) == 2
        context.close()
