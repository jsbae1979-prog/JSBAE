"""Dashboard projections must describe stored events without inventing activity or approvals."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from test_single_workspace import stored_values, video_fixture

from newsflow.db.models import NewsArticle, NewsSource, RenderJob, VideoProject
from newsflow.gui.dashboard_view import dashboard_context


def test_kst_buckets_exclude_future_failed_and_unknown_finish_times(app):
    now = datetime(2026, 10, 19, 1, tzinfo=UTC)
    first = video_fixture(app, 'completed')
    unknown = video_fixture(app, 'unknown finish')
    failed = video_fixture(app, 'failed', status='failed')
    with app.state.sessions.begin() as session:
        source = NewsSource(name='Synthetic', url='https://example.com/fixture', enabled=False)
        session.add(source)
        session.flush()
        for i, at in enumerate([datetime(2026, 10, 18, 14, 59, tzinfo=UTC),
                                datetime(2026, 10, 18, 15, tzinfo=UTC), now + timedelta(hours=1),
                                now - timedelta(days=8)]):
            session.add(NewsArticle(source_id=source.id, title='fixture', url=f'https://example.com/{i}',
                                   canonical_url=f'https://example.com/{i}', publisher='Fixture', collected_at=at))
        session.get(RenderJob, first['id']).finished_at = datetime(2026, 10, 18, 15, tzinfo=UTC)
        session.get(RenderJob, unknown['id']).finished_at = None
        session.get(RenderJob, failed['id']).finished_at = now
    before = stored_values(app)
    with app.state.sessions() as session:
        data = dashboard_context(session, [], now=now)
        assert data['news_count'] == 4
        assert [d['news'] for d in data['days']] == [0, 0, 0, 0, 0, 1, 1]
        assert [d['videos'] for d in data['days']] == [0, 0, 0, 0, 0, 0, 1]
        assert data['days'][-1]['date'] == '2026-10-19'
        assert data['unknown_finished'] == 1
        assert data['maximum'] == 1
        assert session.get(RenderJob, unknown['id']).finished_at is None
    assert stored_values(app) == before


def test_empty_dashboard_never_fabricates_history_or_draft(app):
    with app.state.sessions() as session:
        data = dashboard_context(session, [], now=datetime(2026, 10, 19, tzinfo=UTC))
        assert data['news_count'] == 0 and not data['has_activity']
        assert data['spark_totals'] == [0, 0, 0, 0]
        assert data['focus'] is None and data['excerpt'] == ''
        assert all(d['news'] == d['videos'] == 0 for d in data['days'])


def test_video_selection_attributes_preserve_disclosures_and_escape_html(client, app):
    first = video_fixture(app, '<img src=x onerror=alert(1)>')
    with app.state.sessions.begin() as session:
        session.get(VideoProject, first['project_id']).preview_only = True
    html = client.get('/').text
    assert '&lt;img src=x onerror=alert(1)&gt;' in html
    assert '<img src=x onerror=' not in html
    assert 'data-preview-only="true"' in html
    assert 'data-dash-preview-warning' in html and '검토용 초안' in html
    assert html.count('<video ') == 1 and 'preload="none"' in html and 'autoplay' not in html
    with app.state.sessions() as session:
        assert session.scalar(select(VideoProject.preview_only)) is True


def test_legacy_dashboard_and_new_creator_routes_remain_separate(client):
    import re

    home = client.get('/')
    legacy = client.get('/dashboard')
    assert home.status_code == legacy.status_code == 200
    assert 'mockup-dashboard' in home.text
    assert '뉴스 흐름을 한눈에' in legacy.text
    assert 'mockup-dashboard' not in legacy.text
    assert client.get('/create').status_code == 200
    assert re.findall(r'<a class="button" href="([^\"]+)"', re.search(r'<nav class="workflow-formats".*?</nav>', home.text, re.DOTALL).group()) == [
        '/create', '/image-posts', '/character']
    assert 'id="quick-production"' not in home.text
    assert 'id="production-title"' in client.get('/create').text
    assert 'workflow-record-scope' not in home.text
    assert 'workflow-formats-label' not in home.text
    assert client.get('/image-posts').status_code == 200


def test_dashboard_category_links_stay_on_dashboard(client):
    import re
    from urllib.parse import parse_qs, urlparse

    html = client.get('/').text
    category_nav = re.search(r'<nav class="dash-categories".*?</nav>', html).group()
    links = re.findall(r'href="([^"]+)"', category_nav)
    assert len(links) == 9
    categories = []
    for link in links:
        assert urlparse(link).path == '/'
        response = client.get(link)
        assert response.status_code == 200, link
        categories.extend(parse_qs(urlparse(link).query).get('news_category', []))
    assert categories == ['정치', '경제', '사회', 'IT·과학', '문화', '스포츠', '국제', '미분류']
