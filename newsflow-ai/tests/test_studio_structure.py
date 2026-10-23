"""Mixed content projections and explicit, read-only continuation links."""
from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import select

from newsflow.db.models import (
    ImagePost,
    ImagePostDelivery,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    PlatformAccount,
)
from newsflow.gui.navigation import CONTENT_TYPES, navigation_context
from newsflow.gui.studio_overview import overview

NOW = datetime(2026, 10, 23, 10, tzinfo=UTC)


def news_task(**values):
    return {'id': 'draft:3', 'title': '뉴스 대본', 'completed': False, 'status': 'waiting_review',
            'status_label': '대본 검토 필요', 'next_action': '대본 검토', 'updated_at': NOW.isoformat(),
            'href': '/ai?draft_id=3', **values}


def character(**values):
    return {'id': 'a' * 32, 'topic': '퇴근 직전의 합성 예시', 'state': 'script_review',
            'created_at': NOW.isoformat(), 'script': None, **values}


def image_records(app):
    with app.state.sessions.begin() as session:
        source = NewsSource(name='구조 검증 출처', url='https://example.com/structure', enabled=False)
        session.add(source)
        session.flush()
        article = NewsArticle(title='합성 기사', url='https://example.com/structure/1',
            canonical_url='https://example.com/structure/1', source_id=source.id, publisher='합성')
        session.add(article)
        session.flush()
        post = ImagePost(article_id=article.id, title='저장한 합성 이미지', caption='합성 본문', sources={},
                         filename='image-' + 'b' * 32 + '.jpg', sha256='c' * 64, ai_disclosure='disclose')
        session.add(post)
        session.flush()
        return article.id, post.id


def test_content_catalogue_and_creation_sidebar_share_destinations():
    menu = navigation_context('/', {})
    creation = next(group for group in menu['groups'] if group['label'] == '콘텐츠 스튜디오')['items']
    assert [row['href'] for row in creation] == [row['href'] for row in CONTENT_TYPES]
    assert len({row['id'] for group in menu['groups'] for row in group['items']}) == 13


def test_mixed_types_keep_independent_states_and_do_not_mutate_records(app):
    _article, post = image_records(app)
    jobs = [character()]
    original = deepcopy(jobs)
    with app.state.sessions() as session:
        result = overview(session, [news_task()], [], jobs)
        assert {row['type'] for row in result['rows']} == {'news', 'character', 'image'}
        assert result['counts'] == {'active': 2, 'review': 2, 'running': 0, 'outputs': 1}
        assert next(row for row in result['rows'] if row['type'] == 'image')['href'] == f'/image-posts?post_id={post}#image-result'
    assert jobs == original
    with app.state.sessions() as session:
        assert session.get(ImagePost, post).caption == '합성 본문'


def test_running_character_focus_is_not_replaced_by_newer_news(app):
    with app.state.sessions() as session:
        result = overview(session, [news_task(updated_at='2026-10-24T10:00:00+00:00')], [],
                          [character(state='generating')])
    assert result['focus']['type'] == 'character'
    assert result['focus']['next_action'] == '생성 상태 확인'


def test_unknown_character_is_attention_and_never_becomes_saved_or_retried(app):
    job = character(state='submission_unknown')
    before = deepcopy(job)
    with app.state.sessions() as session:
        result = overview(session, [], [], [job])
    assert result['focus']['category'] == 'attention'
    assert result['focus']['label'] == '제출 결과 불명'
    assert result['counts']['outputs'] == 0
    assert result['focus']['href'] == '/character?job_id=' + job['id']
    assert job == before


def test_saved_image_does_not_hide_other_account_unknown_publication(app):
    _article, post = image_records(app)
    with app.state.sessions.begin() as session:
        accounts = [PlatformAccount(platform='instagram', label=f'합성 계정 {n}', account_type='instagram_business',
                                    status='not_connected', scopes=[], api_ready=False) for n in range(2)]
        session.add_all(accounts)
        session.flush()
        for account, state in zip(accounts, ['unknown', 'published']):
            session.add(ImagePostDelivery(post_id=post, account_id=account.id, media_sha256='c' * 64,
                                          status=state, detail={'synthetic': True}))
    with app.state.sessions() as session:
        result = overview(session, [], [], [])
        assert result['rows'][0]['category'] == 'attention'
        assert '결과 불명' in result['rows'][0]['label']
        assert {row.status for row in session.scalars(select(ImagePostDelivery))} == {'unknown', 'published'}


def test_saved_card_reuses_its_origin_and_does_not_duplicate_a_finished_run(app):
    article, post = image_records(app)
    with app.state.sessions.begin() as session:
        run = IntelligenceRun(kind='feed_card', provider='claude_api', status='success',
            options={'article_id': article, 'purpose': 'svg_card'}, result={'plan': {'title': '합성 카드'}}, evidence={}, message='합성')
        session.add(run)
        session.flush()
        session.get(ImagePost, post).sources = {'claude_card_run_id': run.id}
    with app.state.sessions() as session:
        result = overview(session, [], [], [])
    assert len(result['rows']) == 1
    assert result['rows'][0]['category'] == 'saved'


def test_image_prompt_success_is_review_not_an_image_output(app):
    article, _post = image_records(app)
    with app.state.sessions.begin() as session:
        run = IntelligenceRun(kind='feed_card', provider='claude_api', status='success',
            options={'article_id': article, 'purpose': 'full_image'}, result={'plan': {'title': '이미지 지시문'}}, evidence={}, message='합성')
        session.add(run)
        session.flush()
        identifier = run.id
    with app.state.sessions() as session:
        result = overview(session, [], [], [])
    row = next(row for row in result['rows'] if row['id'] == f'image-run:{identifier}')
    assert row['category'] == 'review'
    assert f'card_id={identifier}' in row['href']
    assert all(row['title'] != '이미지 지시문' for row in result['outputs'])


def test_untrusted_record_identifiers_cannot_become_external_links(app):
    with app.state.sessions.begin() as session:
        session.add(IntelligenceRun(kind='feed_image', provider='openai', status='unknown',
            options={'article_id': 'https://evil.example'}, result={}, evidence={}, message='합성'))
    with app.state.sessions() as session:
        result = overview(session, [], [], [character(id='https://evil.example')])
    assert len(result['rows']) == 1
    assert result['rows'][0]['href'] == '/image-posts'


def test_dashboard_retains_archive_search_topics_and_links_to_one_news_form_without_running(client, app):
    html = client.get('/').text
    assert '아이디어를,' in html
    for item in CONTENT_TYPES:
        assert f'class="studio-format-card format-{item["id"]}"' in html
    assert 'action="/news" method="get"' in html and 'name="q"' in html
    for category in ('정치', '경제', '사회', 'IT·과학', '문화', '스포츠', '국제', '미분류'):
        assert f'data-dash-news-category="{category}"' in html
    assert '/static/css/dashboard.css' in html
    assert client.get('/static/images/newsflow-earth-generated.png').status_code == 200
    assert 'id="quick-production"' not in html
    creation = client.get('/create').text
    assert 'id="quick-production"' in creation
    assert 'name="script_review" value="true"' in creation
    assert not app.state.character.root.exists()
