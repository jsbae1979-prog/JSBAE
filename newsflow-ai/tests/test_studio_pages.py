"""Studio presentation reuses existing routes, local records and approval contracts."""
import re

import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from test_blue_studio_browser import guarded_page
from test_blue_studio_browser import studio_ui as studio_ui_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import draft_fixture, stored_values, video_fixture

from newsflow.db.models import AutopilotJob, ContentDraft, NewsArticle, NewsSource, PublishDraft

browser = browser_fixture
studio_ui = studio_ui_fixture


@pytest.mark.parametrize('url,title', [('/news','뉴스 수집'),('/ai','AI 대본'),('/videos','영상 제작'),
    ('/video','영상 구성'),('/queue','게시 허브'),('/?show=tasks','제작 활동'),
    ('/simple-settings','설정 · 자동화'),('/schedules','자동 제작 예약')])
def test_suite_empty_routes_and_security(client, app, url, title):
    before = stored_values(app)
    response = client.get(url)
    assert response.status_code == 200
    assert f'<h1>{title}</h1>' in response.text
    assert 'studio-pages.css' in response.text
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert stored_values(app) == before
    if url == '/?show=tasks':
        assert 'form action="/autopilot/quick-start"' not in response.text
        assert 'data-activity-filter' in response.text
        assert response.text.count('aria-current="page"') == 1


def seed_suite(app):
    draft_id = draft_fixture(app, '긴 한글 대본 · ' + '검토할 이야기 ' * 8)
    with app.state.sessions.begin() as session:
        source = NewsSource(name='합성 출처',url='https://example.com/suite',enabled=False)
        session.add(source);session.flush()
        for index,category in enumerate(['IT·과학','경제']):
            session.add(NewsArticle(source_id=source.id,title=f'합성 뉴스 {index} — '+ '긴 한글 제목 ' * 8,
                url=f'https://example.com/{index}',canonical_url=f'https://example.com/{index}',
                publisher='합성 출처',category=category,summary='화면 검증 자료입니다.'))
        session.add(AutopilotJob(id='a'*32,mode='guided',source='sample',duration=30,platform='youtube',
            status='failed',current_stage='render',message='합성 실패',error_code='voice_unavailable'))
    return draft_id


def test_suite_browser_navigation_filters_and_record_preservation(studio_ui, browser):
    app = studio_ui
    draft_id = seed_suite(app)
    before = stored_values(app)
    with local_server(app) as origin:
        context,page,external,errors = guarded_page(browser,origin,(1366,768))
        posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        for width,height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width':width,'height':height})
            for url,title in [('/news','뉴스 수집'),('/ai','AI 대본'),('/videos','영상 제작'),
                              ('/queue','게시 허브'),('/?show=tasks','제작 활동'),('/simple-settings','설정 · 자동화')]:
                assert page.goto(origin+url).status == 200
                expect(page.get_by_role('heading',name=title,exact=True,level=1)).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width,url)
            expect(page.get_by_role('navigation',name='설정 항목')).to_have_count(1)
            expect(page.locator('form[action="/production/preferences"]')).to_have_count(1)
            page.goto(origin+'/news')
            page.locator('.news-filter-options > summary').click()
            page.locator('[name="category"]').select_option('경제')
            page.get_by_role('button',name='필터 적용',exact=True).click()
            page.wait_for_url('**/news?**')
            expect(page.locator('.suite-news-article')).to_have_count(1)
            expect(page.locator('.suite-news-article')).to_contain_text('합성 뉴스 1')
            page.locator('.suite-extra-filters summary').click()
            expect(page.locator('[name="start"]')).to_be_visible()
            page.goto(origin+'/?show=tasks')
            expect(page.locator('[data-workspace-task]:visible')).to_have_count(2)
            page.get_by_role('button',name='확인 필요',exact=True).focus();page.keyboard.press('Enter')
            expect(page.locator('[data-workspace-task]:visible')).to_have_count(1)
            expect(page.locator('[data-workspace-task]:visible')).to_have_attribute('data-task-status','failed')
            page.get_by_role('button',name='완료',exact=True).click()
            expect(page.locator('[data-activity-empty]')).to_be_visible()
            page.get_by_role('button',name='검토 대기',exact=True).click()
            expect(page.locator('[data-workspace-task]:visible')).to_have_count(1)
            expect(page.locator('[data-activity-result]')).to_contain_text('1개 기록')
            page.locator('[data-workspace-task]:visible').click()
            page.wait_for_url(f'**/ai?draft_id={draft_id}')
        assert not posts and not external and not errors
        context.close()
    assert stored_values(app) == before
    with app.state.sessions() as session:
        assert session.get(ContentDraft,draft_id).review_status == 'review_required'
        assert session.get(AutopilotJob,'a'*32).status == 'failed'


def test_publish_queue_retains_unapproved_draft_and_original_targets(client, app):
    item = video_fixture(app,'<script>synthetic</script>',status='failed')
    with app.state.sessions.begin() as session:
        draft = PublishDraft(render_job_id=item['id'],platform='youtube',title='승인 전 합성 초안',
            description='전송하지 않습니다',hashtags=[],sources={},media_sha256='0'*64)
        session.add(draft);session.flush();draft_id=draft.id
    response=client.get('/queue')
    assert response.status_code==200
    assert '승인 전 합성 초안' in response.text
    assert f'/publishing?draft_id={draft_id}' in response.text
    assert '영상 파일을 다시 확인' in response.text
    assert not re.search('<video',response.text)
    with app.state.sessions() as session:
        draft=session.get(PublishDraft,draft_id)
        assert not draft.content_reviewed and draft.state=='unvalidated'
        assert len(list(session.scalars(select(PublishDraft))))==1


def test_workstation_scene_selection_filters_and_chart_are_read_only(studio_ui, browser):
    app = studio_ui
    draft_id = seed_suite(app)
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        draft.content = {**draft.content, 'scenes': [
            {'seconds': 20, 'narration': '합성 첫 문장입니다.', 'caption': '첫 장면', 'material': '배경'},
            {'seconds': 25, 'narration': '합성 두 번째 문장입니다.', 'caption': '두 번째 장면', 'material': '도형'},
        ]}
        before_content = draft.content.copy()
    before = stored_values(app)
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366,768))
        posts = []
        page.on('request', lambda request: posts.append(request.url) if request.method == 'POST' else None)
        for width, height in [(1366,768),(1920,1080),(390,844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(origin + '/news')
            page.get_by_role('button', name='경제', exact=True).click()
            page.wait_for_url('**/news?**')
            expect(page.locator('.suite-news-article')).to_have_count(1)
            expect(page.locator('[name=category]')).to_have_value('경제')
            page.goto(origin + f'/video?draft_id={draft_id}')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            expect(page.locator('[data-video-scene]:visible')).to_have_count(1)
            page.get_by_role('button', name='자막 장면 2 · 25초', exact=True).focus()
            page.keyboard.press('Enter')
            expect(page.locator('[data-video-scene="1"]')).to_be_visible()
            expect(page.locator('[data-video-scene="0"]')).to_be_hidden()
            expect(page.locator('[data-video-scene-select="1"]')).to_have_count(4)
            assert all(value == 'true' for value in page.locator('[data-video-scene-select="1"]').evaluate_all(
                "elements => elements.map(element => element.getAttribute('aria-pressed'))"))
            # All scene image selectors remain successful controls of the unchanged protected form.
            assert page.locator('form[action="/video/render"]').evaluate(
                "form => new FormData(form).getAll('images').length") == 2
            expect(page.locator('[name=reviewed]')).not_to_be_checked()
            expect(page.locator('[name=external_tts_consent]')).not_to_be_checked()
            page.goto(origin + '/?show=tasks')
            page.locator('[data-activity-day]').first.click()
            expect(page.locator('[data-activity-day-result]')).to_contain_text('생성 완료 0건')
            page.goto(origin + f'/ai?draft_id={draft_id}')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.get_by_role('button', name='장면 2', exact=True).click()
            expect(page.locator('[data-topic-scene]:visible textarea[name=narration]')).to_have_value('합성 두 번째 문장입니다.')
            expect(page.locator('[data-workspace-return]')).to_have_count(1)
        assert not posts and not external and not errors
        context.close()
    assert stored_values(app) == before
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.content == before_content and draft.review_status == 'review_required'


@pytest.mark.parametrize('status,playable,exists,shown', [
    ('success',True,True,True), ('failed',True,True,False),
    ('success',False,True,False), ('success',True,False,False),
])
def test_video_studio_previous_preview_requires_existing_completed_output(client, app, status, playable, exists, shown):
    item = video_fixture(app, '이전 합성 영상', status=status, playable=playable, exists=exists)
    response = client.get(f'/video?draft_id={item["draft_id"]}')
    assert response.status_code == 200
    assert ('aria-label="이 대본으로 만든 이전 영상"' in response.text) is shown
    if shown:
        assert '이전에 제작된 영상입니다' in response.text
        assert f'/video/jobs/{item["id"]}/file?download=true' in response.text
    # This is the stored-output UI contract, not a claim that fixture bytes are a valid MP4.
