"""Navigation and preserved input/consent contracts, using only temporary data."""
import re

import pytest
from sqlalchemy import select

from newsflow.db.models import AppSetting, NewsArticle, NewsSource

DESTINATIONS = [
    ('/', '/'), ('/news', '/news'), ('/sources', '/news'), ('/ai', '/ai'),
    ('/videos', '/videos'), ('/video', '/create'), ('/create', '/create'),
    ('/character', '/character'), ('/video/ai', '/create'), ('/workspace/trash', '/?show=tasks'),
    ('/queue', '/queue'), ('/image-posts', '/image-posts'), ('/analytics', '/analytics'),
    ('/?show=tasks', '/?show=tasks'), ('/simple-settings', '/simple-settings'),
    ('/voices', '/voices'), ('/video/tts', '/voices'),
    ('/video-ai-settings', '/simple-settings'), ('/publishing/platforms', '/simple-settings'),
    ('/schedules', '/schedules'), ('/operations', '/simple-settings'),
]


@pytest.mark.parametrize('path,selected', DESTINATIONS)
def test_all_categories_have_one_correct_current_menu_and_safe_finder(client, path, selected):
    response = client.get(path)
    assert response.status_code == 200
    primary = re.search(r'<nav aria-label="주 메뉴"[^>]*>(.*?)</nav>', response.text, re.DOTALL).group(1)
    anchors = re.findall(r'<a\b[^>]*>', primary)
    current = [tag for tag in anchors if 'aria-current="page"' in tag]
    assert len(current) == 1
    assert f'href="{selected}"' in current[0]
    assert len(anchors) == 14
    assert any('href="/image-studio"' in tag for tag in anchors)
    dialog = re.search(r'<dialog id="access-dialog".*?</dialog>', response.text, re.DOTALL).group(0)
    assert '<form' not in dialog and 'method="post"' not in dialog
    assert 'aria-labelledby="access-title"' in dialog
    assert 'data-access-search' in dialog
    for link in ('/character', '/image-posts', '/sources', '/voices', '/schedules'):
        assert f'href="{link}"' in dialog
    assert '/static/js/workspace-access.js' in response.text
    assert "script-src 'self'" in response.headers['content-security-policy']


def test_navigation_does_not_change_saved_settings_or_news(client, app):
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key='workspace_access_preservation', value='synthetic-saved-value'))
        source = NewsSource(name='합성 출처', url='https://example.com/access-test.xml', enabled=False)
        session.add(source)
        session.flush()
        session.add(NewsArticle(title='지워지면 안 되는 합성 기사', url='https://example.com/access-article',
                                canonical_url='https://example.com/access-article', source_id=source.id,
                                publisher='합성 출처', category='it'))
    for path in ('/', '/news', '/ai', '/video', '/queue', '/analytics', '/simple-settings', '/character'):
        assert client.get(path).status_code == 200
    with app.state.sessions() as session:
        assert session.get(AppSetting, 'workspace_access_preservation').value == 'synthetic-saved-value'
        assert session.scalar(select(NewsArticle).where(NewsArticle.title == '지워지면 안 되는 합성 기사'))
        assert session.scalar(select(NewsSource).where(NewsSource.name == '합성 출처')).enabled is False
    assert not app.state.character.root.exists()  # Viewing never creates a character job.


def test_character_simplification_keeps_upload_budget_and_csrf_requirements(client, app):
    from test_creation_models import png
    app.state.image_studio.asset_bytes(png())  # Saved-reference selector exists only with a verified local asset.
    html = client.get('/character').text
    assert '주제·원본 저장' in html and 'data-character-reference' in html
    form = re.search(r'<form\b[^>]*class="[^"]*\bcharacter-form\b[^"]*".*?</form>', html, re.DOTALL).group(0)
    for name in ('topic', 'reference', 'episode_limit', 'csrf_token'):
        assert f'name="{name}"' in form
    assert 'enctype="multipart/form-data"' in form
    assert len(re.findall(r'\brequired\b', form)) == 2
    assert 'name="day_limit"' not in form
    assert 'name="reference_asset"' in form
    assert 'data-character-preview hidden' in html
    assert client.post('/character', data={'topic': 'test'}).status_code in (403, 422)

    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    response = client.post('/character', data={'csrf_token': token, 'topic': '참조 없는 합성 입력',
        'episode_limit': '5', 'day_limit': '20'})
    assert response.status_code == 422
    assert '참조 이미지와 스토리 주제' in response.json()['error']
    assert not app.state.character.root.exists()  # Neither upload nor saved reference: no job is created.
