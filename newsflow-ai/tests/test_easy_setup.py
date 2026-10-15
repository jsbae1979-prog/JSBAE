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
    monkeypatch.setattr(app.state.video, '_start', lambda *args, **kwargs: calls.append((args, kwargs)) or 1)
    assert app.state.video.start_preview(2, 45) == 1
    assert calls[0][0] == (2, 45, 'offline-silence', 56, 1280, None, False, True, None)
    assert calls[0][1]['fit_audio'] is False and calls[0][1]['speech'].rate == 0


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


def test_readonly_database_not_reported_ready(app, monkeypatch):
    from contextlib import contextmanager

    monkeypatch.setattr('newsflow.easy_setup.voice_catalog', list)
    @contextmanager
    def readonly():
        with app.state.sessions() as session:
            session.connection().exec_driver_sql('PRAGMA query_only=ON')
            try:
                yield session
            finally:
                session.rollback()
                session.connection().exec_driver_sql('PRAGMA query_only=OFF')
    result = diagnostics(app.state.config.data_dir, readonly)
    assert next(c for c in result['checks'] if c['key'] == 'storage')['status'] == 'needs_attention'
    assert not result['ready'] and 'OperationalError' not in str(result)
    with app.state.sessions() as session:
        assert session.get(AppSetting, 'request_timeout').value == '10'
    assert next(c for c in diagnostics(app.state.config.data_dir, app.state.sessions)['checks'] if c['key']=='storage')['status'] == 'pass'


# --- Phase 5C.1 package C: canonical voice guidance, policy state, listening record service ---

from types import SimpleNamespace

from newsflow.easy_setup import (
    LISTENING_ITEMS,
    LISTENING_NAME,
    VOICE_INSTALL_GUIDE,
    listening_summary,
    record_listening,
)
from newsflow.video.tts import TTSPolicyError

CANONICAL = ('Windows 설정 → 시간 및 언어 → 언어 및 지역 → 한국어 → 언어 옵션에서 음성(텍스트 음성 변환)을 설치한 뒤 '
             'NewsFlow를 종료하고 run.bat를 다시 실행하세요.')


def test_diagnostics_voice_guidance_and_policy_state(app, monkeypatch):
    assert VOICE_INSTALL_GUIDE == CANONICAL
    monkeypatch.setattr('newsflow.easy_setup.voice_catalog', list)
    result = diagnostics(app.state.config.data_dir, app.state.sessions)
    check = next(c for c in result['checks'] if c['key'] == 'korean_voice')
    assert check['status'] == 'needs_attention' and not check['required'] and CANONICAL in check['guidance']
    assert result['korean_voice'] == 'not_installed'
    assert result['quality'] == '사람의 청취·시청 평가는 아직 하지 않았습니다.'

    def blocked():
        raise TTSPolicyError('SECRET stderr text')

    monkeypatch.setattr('newsflow.easy_setup.voice_catalog', blocked)
    result = diagnostics(app.state.config.data_dir, app.state.sessions)
    check = next(c for c in result['checks'] if c['key'] == 'korean_voice')
    assert result['korean_voice'] == 'blocked_policy' and 'SECRET' not in str(result)
    assert 'Get-ExecutionPolicy -List' in check['guidance'] and '정책을 바꾸지 않' in check['guidance']


def test_listening_record_service_rules_retention_and_summary(app):
    data_dir, sessions = app.state.config.data_dir, app.state.sessions
    values = {'listener': ' 홍길동 ', 'voice': 'Local Korean', 'rate': '0', 'pause_ms': '250', 'verdict': 'pass',
              **{key: 'ok' for key in LISTENING_ITEMS}}
    record = record_listening(data_dir, sessions, values)
    assert record['verdict'] == 'pass' and record['listener'] == '홍길동' and record['preview_sha256'] == ''
    assert LISTENING_NAME.fullmatch(record['file']) and (data_dir / 'voice-listening' / record['file']).is_file()
    date = record['created_at'][:10]
    assert listening_summary(sessions) == {'verdict': 'pass', 'label': 'PASS', 'date': date,
                                           'listener': '홍길동', 'voice': 'Local Korean'}
    assert diagnostics(data_dir, sessions)['quality'] == f'사람 청취 결과: PASS ({date}, 홍길동)'
    for bad in [{'numbers': 'bad'}, {'listener': ''}, {'listener': 'a\tb'}, {'clarity': 'x'}, {'verdict': 'ok'},
                {'preview': 'preview-zz.wav'}, {'notes': 'n' * 501}, {'rate': '5'}, {'pause_ms': '999'}]:
        with pytest.raises(SetupError):
            record_listening(data_dir, sessions, {**values, **bad})
    assert listening_summary(sessions)['verdict'] == 'pass'  # rejected forms change nothing
    record_listening(data_dir, sessions, {**values, 'numbers': 'bad', 'verdict': 'fail', 'notes': '줄\n바꿈 허용'})
    assert listening_summary(sessions)['verdict'] == 'fail'
    for _ in range(55):
        record_listening(data_dir, sessions, {**values, 'verdict': 'not_verified'})
    kept = list((data_dir / 'voice-listening').glob('listening-*.json'))
    assert len(kept) == 50 and record['file'] not in {p.name for p in kept}
    assert listening_summary(sessions)['label'] == 'NOT VERIFIED'
    record_listening(data_dir, sessions, {**values, 'voice': 'v' * 200, 'verdict': 'not_verified'})
    with sessions() as session:
        assert len(session.get(AppSetting, 'voice_listening_last').value) <= 200
    summary = listening_summary(sessions)
    assert summary['listener'] == '홍길동' and summary['voice'].startswith('vvv')


def test_setup_wizard_links_sources_and_uses_canonical_voice_guidance(client, app, monkeypatch):
    assert advance(client, app, 1).status_code == 303
    assert '<a href="/sources">뉴스 메뉴에서 뉴스 출처 관리 →</a>' in client.get('/setup?step=2').text
    for step, v in [(2, {'source': 'sample'}), (3, {'ai': 'offline'}), (4, {'duration': '30', 'platform': 'youtube'})]:
        assert advance(client, app, step, **v).status_code == 303
    monkeypatch.setattr('newsflow.gui.setup_routes.voice_catalog', list)
    text = client.get('/setup?step=5').text
    assert '<select id="setup-voice" name="voice"><option value="offline-silence">무음 검토영상</option></select>' in text
    assert 'id="setup-voice-guide"' in text and CANONICAL in text and 'SAPI 엔진' in text

    def blocked():
        raise TTSPolicyError('정책')

    monkeypatch.setattr('newsflow.gui.setup_routes.voice_catalog', blocked)
    text = client.get('/setup?step=5').text
    assert 'Get-ExecutionPolicy -List' in text and '이 앱은 정책을 바꾸지 않습니다' in text
    monkeypatch.setattr('newsflow.gui.setup_routes.voice_catalog', list)
    monkeypatch.setattr('newsflow.gui.setup_routes.sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(WindowsTTS, 'korean_voice_report', lambda self, sapi=None: {
        'state': 'onecore_only', 'sapi': [], 'onecore_only': ['Microsoft Heami'], 'registry_read': 'ok'})
    text = client.get('/setup?step=5').text
    assert '한국어 음성 1개(Microsoft Heami)' in text and 'SAPI에는 보이지 않아요' in text and CANONICAL in text
    assert 'value="Microsoft Heami"' not in text and '레지스트리를 수정하지 않습니다' in text
