"""Windows Chrome design and local-only workflow evidence. No operating app."""
import io
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from jinja2 import FileSystemLoader
from PIL import Image
from playwright.sync_api import expect
from test_blue_studio_browser import studio_ui as studio_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import stored_values
from test_unified_publishing_gui import instagram_ui as instagram_fixture
from test_unified_publishing_gui import unified as unified_fixture
from test_unified_publishing_gui import youtube_media as media_fixture
from test_unified_publishing_gui import youtube_ui as youtube_fixture
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.db.models import AudioTrack, ContentDraft, RenderJob, SubtitleTrack, VideoProject
from newsflow.gui.routes import templates
from newsflow.intelligence.provider import FakeProvider, Options

studio_ui = studio_fixture
browser = browser_fixture
instagram_ui = instagram_fixture
unified = unified_fixture
youtube_media = media_fixture
youtube_ui = youtube_fixture


@pytest.fixture
def visual(studio_ui, unified, youtube_media, youtube_ui, instagram_ui, monkeypatch):
    app = studio_ui
    youtube_ui[0].channel['ready'] = False
    instagram_ui[0].account['ready'] = False
    script = FakeProvider().complete({'articles': [{'title': '도시의 새로운 안전 설계', 'summary': '합성 자료'}]}, 30, Options(model='offline'))
    script['scenes'][1]['review_notes'] = ['관련 용어와 기사 근거를 확인하세요.']
    with app.state.sessions.begin() as session:
        job = session.get(RenderJob, youtube_media)
        project = session.get(VideoProject, job.project_id)
        draft = session.get(ContentDraft, project.draft_id)
        draft.content = script
        project.snapshot = script
        session.add(AudioTrack(project_id=project.id, provider='offline', voice='offline-silence', status='success'))
        session.add(SubtitleTrack(project_id=project.id, font_size=48, position_y=1280, cues=[]))
        failure = RenderJob(project_id=project.id, status='failed', output_name='video-' + 'f'*32 + '.mp4',
            metadata_json={'failure_stage': 'voice'}, message='음성 생성 실패. 해당 단계 설정을 확인하세요.')
        session.add(failure)
        session.flush()
        ids = (draft.id, job.id, failure.id)
    image = io.BytesIO()
    Image.new('RGB', (108, 192), '#15304d').save(image, 'PNG')
    monkeypatch.setattr('newsflow.video.thumbnails.thumbnail', lambda *a, **k: image.getvalue())
    return app, ids


def test_local_workflow_and_all_screen_design(visual, browser):
    app, (draft, render, failure) = visual
    evidence = Path(os.environ['NEWSFLOW_USABILITY_EVIDENCE'])
    evidence.mkdir(parents=True, exist_ok=True)
    before_settings = stored_values(app)
    original = Path('C:/Codex/NewsFlowAI/newsflow-ai/src/newsflow')
    external, posts, errors = [], [], []
    with local_server(app) as origin:
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='ko-KR')
        phase = {'before': False}
        def guard(route):
            path = urlsplit(route.request.url)
            if path.netloc != urlsplit(origin).netloc:
                external.append(route.request.url)
                route.abort()
            elif phase['before'] and path.path.startswith('/static/'):
                source = original / path.path.lstrip('/')
                if source.is_file():
                    route.fulfill(body=source.read_bytes(), content_type=mimetypes.guess_type(source.name)[0] or 'application/octet-stream')
                else:
                    route.fulfill(status=404)
            else:
                route.continue_()
        context.route('**/*', guard)
        page = context.new_page()
        page.on('request', lambda request: posts.append(urlsplit(request.url).path) if request.method == 'POST' else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        captures = [('dashboard', '/'), ('script', f'/ai?draft_id={draft}'),
                    ('voice', '/voices'), ('failed-video', f'/video?job_id={failure}'),
                    ('video-layout', f'/video?draft_id={draft}'),
                    ('publish', f'/?video={render}&publish_platform=unified#publish-workspace')]
        old_loader = templates.env.loader
        try:
            phase['before'] = True
            templates.env.loader = FileSystemLoader(str(original / 'gui' / 'templates'))
            templates.env.cache.clear()
            for name, url in captures:
                assert page.goto(origin + url).status == 200
                page.screenshot(path=str(evidence / f'before-{name}.png'), full_page=True)
        finally:
            phase['before'] = False
            templates.env.loader = old_loader
            templates.env.cache.clear()
        for name, url in captures:
            assert page.goto(origin + url).status == 200
            page.screenshot(path=str(evidence / f'after-{name}.png'), full_page=True)
        # This is an editor/layout check, not a real media playback or publishing claim.
        page.goto(origin + f'/ai?draft_id={draft}')
        expect(page.get_by_role('region', name='장면별 보완 필요')).to_contain_text('보완 필요 1건')
        page.get_by_role('link', name='장면 2 확인').click()
        expect(page.locator('#script-scene-2')).to_be_in_viewport()
        page.get_by_role('link', name='이 대본으로 영상 구성', exact=False).click()
        expect(page.locator('.composition-preview')).to_be_visible()
        expect(page.locator('.composition-preview')).to_contain_text('음성·타이밍 미검증')
        frame = page.locator('.composition-preview').bounding_box()
        monitor = page.locator('.workstation-monitor').bounding_box()
        assert abs(frame['height'] / frame['width'] - 16/9) < .02
        assert frame['y'] >= monitor['y'] and frame['y'] + frame['height'] <= monitor['y'] + monitor['height']
        expect(page.locator('[data-composition-caption]')).to_be_visible()
        # Existing render is selected, no new synthesis or upload.
        page.goto(origin + f'/?video={render}&publish_platform=unified#publish-workspace')
        expect(page.locator('[data-publish-save]')).to_be_disabled()
        expect(page.locator('[data-publish-local-save]')).to_be_enabled()
        page.locator('[data-publish-target]').select_option('both')
        page.locator('[data-publish-review] input[name=title]').fill('')
        page.locator('[data-publish-review] textarea[name=description]').fill('내 PC에 보관할 합성 초안')
        page.locator('[data-publish-review] input[name=hashtags]').fill('#합성 #초안')
        page.locator('[data-publish-local-save]').click()
        expect(page.get_by_text('내 PC에 초안 저장됨 · 검토·게시 승인 전')).to_be_visible()
        page.reload()
        expect(page.locator('[data-publish-review] textarea[name=description]')).to_have_value('내 PC에 보관할 합성 초안')
        expect(page.locator('[data-publish-target]')).to_have_value('both')
        # Scan auxiliary pages too: no missing navigation, overflow, implicit calls or account checks.
        urls = ['/', '/news', '/sources', '/ai', f'/ai?draft_id={draft}', '/videos',
                f'/video?job_id={failure}', f'/video?draft_id={draft}', '/queue', '/analytics',
                '/simple-settings', '/voices', '/video/tts', '/video/ai',
                f'/video-ai-settings?return_draft={draft}', '/schedules', '/workspace/trash', '/settings']
        for width in [1440, 390]:
            page.set_viewport_size({'width': width, 'height': 1000})
            for index, url in enumerate(urls):
                response = page.goto(origin + url)
                assert response.status == 200, url
                assert page.locator('h1').count() > 0, url
                assert page.locator('link[href="/static/css/usability.css"]').count() == 1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), (width, url)
                if width == 390 or url in ['/news', '/queue', '/simple-settings', '/schedules', '/workspace/trash', '/settings']:
                    page.screenshot(path=str(evidence / f'screen-{width}-{index}.png'), full_page=True)
        page.goto(origin + '/voices')
        assert page.locator('#listening-voice').input_value() == ''
        expect(page.get_by_role('button', name='청취 결과 저장')).to_be_disabled()
        page.goto(origin + '/video-ai-settings?return_draft=' + str(draft))
        expect(page.get_by_role('link', name=f'4 대본 #{draft} 작업 복귀 →')).to_have_attribute('href', f'/video/ai?draft_id={draft}')
        page.goto(origin + '/')
        page.keyboard.press('Tab')
        expect(page.get_by_role('link', name='본문으로 이동')).to_be_focused()
        page.keyboard.press('Enter')
        expect(page.locator('#main-content')).to_be_focused()
        assert posts == ['/publishing/unified/local-draft']
        assert not external and not errors
        (evidence / 'browser-results.json').write_text(__import__('json').dumps({
            'screens': urls, 'widths': [1440, 390], 'chrome': browser.version,
            'posts': posts, 'external_requests': len(external), 'page_errors': errors,
            'operating_app_used': False, 'synthetic_media_only': True}, ensure_ascii=False, indent=2), encoding='utf-8')
        assert stored_values(app) == before_settings
        context.close()
