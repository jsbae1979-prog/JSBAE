"""First-run setup, failure recovery, data preservation and production boundaries."""
from pathlib import Path

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import AppSetting, NewsArticle, NewsSource, utcnow
from newsflow.easy_setup import SetupError, diagnostics, preview_preferences, read_state, save_step
from newsflow.video.engine import RenderError
from newsflow.video.tts import TTSError, WindowsTTS


@pytest.fixture
def ready(monkeypatch):
    result = {'ready': True, 'checks': [], 'voices': [], 'korean_voice': 'not_installed', 'external_calls': 0}
    monkeypatch.setattr('newsflow.gui.setup_routes.diagnostics', lambda *args: dict(result))
    return result


def advance(client, app, step, **values):
    return client.post('/setup/step', data={'csrf_token': csrf(client), 'step': step,
                       'revision': read_state(app.state.sessions)['revision'], **values}, follow_redirects=False)


def through_storage(client, app):
    for step, values in [(1, {}), (2, {'source': 'feeds'}), (3, {'ai': 'offline'}),
                         (4, {'duration': '60', 'platform': 'instagram'}),
                         (5, {'voice': 'offline-silence', 'font_size': '56', 'subtitle_y': '1280'}),
                         (6, {'storage_confirmed': 'yes'})]:
        assert advance(client, app, step, **values).status_code == 303


def test_wizard_is_optional_and_all_core_menus_remain(client):
    for path in ['/setup', '/videos', '/', '/news', '/simple-settings', '/dashboard', '/video', '/publishing']:
        result = client.get(path)
        assert result.status_code == 200
        assert "script-src 'self'" in result.headers['content-security-policy']
    home = client.get('/').text
    assert '처음 오셨나요' in home and '자동 제작 시작' in home
    for path in ['/news', '/videos', '/queue', '/simple-settings', '/autopilot/start']:
        assert f'href="{path}"' in home


def test_wizard_atomic_commit_and_existing_news_preserved(client, app, ready):
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key='autopilot_duration', value='30'))
        session.add(NewsArticle(title='보존할 뉴스', url='https://example.com/keep', canonical_url='https://example.com/keep',
                                source_id=session.scalar(select(NewsSource.id)), publisher='합성', published_at=None, collected_at=utcnow()))
    through_storage(client, app)
    with app.state.sessions() as session:
        assert session.get(AppSetting, 'autopilot_duration').value == '30'
    assert advance(client, app, 7).status_code == 303
    assert read_state(app.state.sessions)['completed'] is True
    assert preview_preferences(app.state.sessions) == ('offline-silence', 56, 1280)
    with app.state.sessions() as session:
        assert session.get(AppSetting, 'autopilot_duration').value == '60'
        assert session.scalar(select(NewsArticle)).title == '보존할 뉴스'
    assert '체험 영상 만들기' in client.get('/setup').text


def test_missing_dependency_does_not_complete_or_overwrite_preferences(client, app, ready):
    through_storage(client, app)
    ready['ready'] = False
    assert advance(client, app, 7).status_code == 422
    assert not read_state(app.state.sessions)['completed']
    assert preview_preferences(app.state.sessions) == ('offline-silence', 48, 1420)
    ready['ready'] = True
    assert advance(client, app, 7).status_code == 303


def test_step_skip_stale_revision_and_replay_rejected(client, app):
    assert advance(client, app, 4, duration='30', platform='youtube').status_code == 422
    assert advance(client, app, 1).status_code == 303
    response = client.post('/setup/step', data={'csrf_token': csrf(client), 'step': 1, 'revision': 0})
    assert response.status_code == 422
    assert read_state(app.state.sessions)['revision'] == 1
    assert client.get('/setup?step=7').status_code == 422


@pytest.mark.parametrize('path', ['/setup/step', '/setup/check', '/setup/test-production'])
def test_setup_csrf_and_cross_origin(client, path):
    assert client.post(path).status_code == 403
    assert client.post(path, data={'csrf_token': csrf(client)}, headers={'Origin': 'https://attacker.example'}).status_code == 403


@pytest.mark.parametrize('step,values', [(2, {'source': 'evil'}), (3, {'ai': 'external'}),
    (4, {'duration': '1', 'platform': 'youtube'}), (4, {'duration': '30', 'platform': 'evil'}),
    (5, {'voice': 'offline-silence', 'font_size': '999', 'subtitle_y': '1420'}),
    (5, {'voice': 'not-installed', 'font_size': '48', 'subtitle_y': '1420'}),
    (6, {'storage_confirmed': 'no'}), (1, {'api_key': 'do-not-store-secret'})])
def test_invalid_preferences_not_stored(app, step, values):
    with pytest.raises(SetupError):
        save_step(app.state.sessions, step, 0, values)
    assert read_state(app.state.sessions)['revision'] == 0
    with app.state.sessions() as session:
        assert all('do-not-store-secret' not in row.value for row in session.scalars(select(AppSetting)))


def test_explicit_test_is_always_synthetic_offline(client, app, ready, monkeypatch):
    assert client.post('/setup/test-production', data={'csrf_token': csrf(client)}).status_code == 409
    through_storage(client, app)
    assert advance(client, app, 7).status_code == 303
    calls = []
    monkeypatch.setattr(app.state.autopilot, 'start', lambda **kwargs: calls.append(kwargs) or 'a' * 32)
    response = client.post('/setup/test-production', data={'csrf_token': csrf(client)}, follow_redirects=False)
    assert response.status_code == 303
    assert calls == [{'mode': 'easy', 'source': 'sample', 'duration': 30}]
    safety = client.get('/api/oauth/safety')
    assert safety.status_code == 200 and safety.json()['mode'] == 'OFFLINE/BLOCKED'


def test_diagnostics_failure_is_redacted_and_recovers(app, monkeypatch):
    monkeypatch.setattr('newsflow.easy_setup.voice_catalog', list)
    def broken(*args):
        raise RenderError('SECRET-tool-error')
    monkeypatch.setattr('newsflow.easy_setup.FFmpegAdapter.check', broken)
    result = diagnostics(app.state.config.data_dir, app.state.sessions)
    assert not result['ready'] and result['external_calls'] == 0
    assert 'SECRET' not in str(result)
    assert next(c for c in result['checks'] if c['key'] == 'storage')['status'] == 'pass'
    monkeypatch.setattr('newsflow.easy_setup.FFmpegAdapter.check', lambda *args: ('ffmpeg', 'ffprobe', '1'))
    result = diagnostics(app.state.config.data_dir, app.state.sessions)
    assert next(c for c in result['checks'] if c['key'] == 'media')['status'] == 'pass'


def test_korean_voice_uses_culture_not_name(client, app, monkeypatch):
    monkeypatch.setattr('newsflow.easy_setup.voice_catalog', lambda: [{'name': 'Local Korean', 'culture': 'ko-KR'}])
    for step, v in [(1, {}), (2, {'source': 'sample'}), (3, {'ai': 'offline'}), (4, {'duration': '30', 'platform': 'youtube'})]:
        assert advance(client, app, step, **v).status_code == 303
    assert advance(client, app, 5, voice='Local Korean', font_size='48', subtitle_y='1420').status_code == 303
    assert read_state(app.state.sessions)['values']['voice'] == 'Local Korean'


@pytest.mark.parametrize('payload', [b'{}', b'["name"]', b'[{"name":"x"}]', b'not-json'])
def test_invalid_voice_metadata_rejected(monkeypatch, payload):
    monkeypatch.setattr(WindowsTTS, '_command', lambda *args: payload)
    with pytest.raises(TTSError):
        WindowsTTS().voice_details()


def test_voice_metadata_supported(monkeypatch):
    monkeypatch.setattr(WindowsTTS, '_command', lambda *args: b'[{"name":"voice","culture":"ko-KR"}]')
    assert WindowsTTS().voice_details() == [{'name': 'voice', 'culture': 'ko-KR'}]


def test_setup_script_preserves_launcher_and_safe_arguments():
    root = Path(__file__).parents[1]
    script = (root / 'setup.bat').read_text()
    assert '--setup-only' in script and 'py -3.12' in script
    assert 'START_HERE.html' in script
    assert 'powershell -Command' not in script
    assert '--setup-only' not in (root / 'run.bat').read_text()


def test_preview_reads_saved_settings_and_keeps_review_boundary(app, monkeypatch):
    with app.state.sessions.begin() as session:
        for k, v in [('voice', 'offline-silence'), ('font_size', '56'), ('subtitle_y', '1280')]:
            session.add(AppSetting(key='video_default_' + k, value=v))
    calls = []
    monkeypatch.setattr(app.state.video, '_start', lambda *args: calls.append(args) or 1)
    assert app.state.video.start_preview(2, 45) == 1
    assert calls[0] == (2, 45, 'offline-silence', 56, 1280, None, False, True, None)


def test_korean_subtitles_wrap_and_overflow_is_rejected(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    from newsflow.video.engine import RenderPlan, ScenePlan, card, font_path, text_lines
    font = ImageFont.truetype(str(font_path()), 56)
    draw = ImageDraw.Draw(Image.new('RGB', (1080, 1920)))
    caption = '한국어 자막이 안전 영역 안에서 자연스럽게 줄을 바꾸는지 확인합니다.'
    lines = text_lines(draw, caption, font, 900)
    assert len(lines) > 1 and all(draw.textlength(line, font=font) <= 900 for line in lines)
    assert ''.join(lines) == caption
    plan = RenderPlan('검토용 영상', [ScenePlan(30, '합성 대본', caption)], [], font_size=56, subtitle_y=1280)
    card(plan, plan.scenes[0], 0, tmp_path / '자막.png', font_path())
    assert Image.open(tmp_path / '자막.png').size == (1080, 1920)
    long = ScenePlan(30, '합성 대본', '한' * 150)
    with pytest.raises(RenderError):
        card(plan, long, 0, tmp_path / 'overflow.png', font_path())


def test_first_wizard_inherits_existing_installation_defaults(app):
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key='autopilot_duration', value='60'))
        session.add(AppSetting(key='autopilot_source', value='feeds'))
    values = read_state(app.state.sessions)['values']
    assert values['duration'] == '60' and values['source'] == 'feeds'
    save_step(app.state.sessions, 1, 0, {})
    assert read_state(app.state.sessions)['values'] == values
