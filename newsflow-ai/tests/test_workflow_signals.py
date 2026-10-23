"""Connection indicators and task progress are separate, read-only projections."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect
from test_blue_studio_browser import guarded_page
from test_blue_studio_browser import studio_ui as studio_ui_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import save_values, stored_values, video_fixture

from newsflow.db.models import AutopilotJob, ContentDraft, IntelligenceRun
from newsflow.gui.dashboard_view import dashboard_context, workflow_context
from newsflow.gui.production_picker import selection_lights

studio_ui = studio_ui_fixture
browser = browser_fixture


def view(provider='claude_api', policy='ai_web'):
    base = {'status_code': 'check', 'availability': '확인 필요', 'configuration': '설정 보관됨',
            'evidence': '실행 미검증'}
    return {'production_config': {'provider': provider, 'acquisition_policy': policy,
                                 'voice_engine': 'windows', 'voice': 'Synthetic Heami',
                                 'voice_available': True, 'video_provider': 'off'},
            'provider_statuses': {name: dict(base) for name in
                                 ('offline', 'claude_api', 'openai', 'claude_code', 'codex',
                                  'windows', 'elevenlabs', 'higgsfield', 'ffmpeg')},
            'rss_readiness': {'enabled': 1, 'passed': 1, 'failed': 0},
            'api_connections': {}}


def request():
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))


def gate(**updates):
    return {'key': {'configured': True}, 'ready': False, 'authentication_verified': False,
            'reasons': ['실제 연결 미확인'], 'connection_check': {'code': 'not_checked', 'message': '미확인'},
            **updates}


@pytest.mark.parametrize('mode,color', [('missing', 'red'), ('registered', 'yellow'),
                                     ('auth_error', 'red'), ('rate_limit', 'red'),
                                     ('ready', 'green'), ('stale', 'yellow')])
def test_api_key_registration_never_means_authentication(mode, color):
    data = view()
    status = gate()
    if mode == 'missing':
        status['key']['configured'] = False
    elif mode in {'auth_error', 'rate_limit'}:
        status['connection_check'] = {'code': mode, 'message': '합성 인증·한도 실패'}
    elif mode == 'ready':
        status.update(ready=True, authentication_verified=True, reasons=[])
    elif mode == 'stale':
        status.update(ready=True, authentication_verified=False)
    data['api_connections']['claude_api'] = status
    before = deepcopy(data)
    assert selection_lights(request(), data)['news']['color'] == color
    assert data == before


def test_rss_gate_uses_analysis_not_search_and_requires_rss_evidence(monkeypatch):
    from newsflow.gui import api_settings_routes

    calls = []
    def local_status(_request, provider, capability):
        calls.append((provider, capability))
        return gate(ready=True, authentication_verified=True, reasons=[])
    monkeypatch.setattr(api_settings_routes, 'connection_status', local_status)
    data = view(policy='rss')
    assert selection_lights(request(), data)['news']['color'] == 'green'
    assert calls == [('claude_api', 'analysis')]
    data['rss_readiness']['passed'] = 0
    assert selection_lights(request(), data)['news']['color'] == 'yellow'
    data['rss_readiness']['enabled'] = 0
    assert selection_lights(request(), data)['news']['color'] == 'red'


def test_cli_blocked_and_paid_media_never_claim_connected():
    data = view('codex')
    assert selection_lights(request(), data)['news']['color'] == 'red'
    data['production_config'].update(voice_engine='elevenlabs', voice='elevenlabs', video_provider='higgsfield')
    signals = selection_lights(request(), data)
    assert signals['voice']['color'] == 'yellow'  # Configured-only state is not account validation.
    assert signals['video']['color'] == 'red'
    data['provider_statuses']['higgsfield']['status_code'] = 'configured'
    assert selection_lights(request(), data)['video']['color'] == 'yellow'
    data['provider_statuses']['elevenlabs']['status_code'] = 'setup'
    assert selection_lights(request(), data)['voice']['color'] == 'red'


def test_local_checks_and_selected_voice_are_not_other_engine_success():
    data = view('offline', 'rss')
    for name in ('windows', 'ffmpeg'):
        data['provider_statuses'][name]['status_code'] = 'configured'
    assert selection_lights(request(), data)['voice']['color'] == 'green'
    assert selection_lights(request(), data)['video']['color'] == 'green'
    data['production_config']['voice_available'] = False
    assert selection_lights(request(), data)['voice']['color'] == 'red'
    data['production_config']['voice'] = 'offline-silence'
    assert selection_lights(request(), data)['voice']['color'] == 'yellow'


def test_dashboard_uses_recent_render_instead_of_old_failure(studio_ui, client):
    app = studio_ui
    result = video_fixture(app, '가장 최근 완성 영상')
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, result['draft_id'])
        script = session.get(IntelligenceRun, draft.run_id)
        analysis = IntelligenceRun(kind='analysis', provider='offline', status='success', options={},
                                   evidence={'articles': [{'title': '합성 자료'}]}, result={}, message='합성 검증 기록')
        session.add(analysis)
        session.flush()
        script.evidence = analysis.evidence
        script.options = {'production_context': {'source': 'feeds', 'initial_provider': 'offline',
                          'initial_model': 'offline', 'initial_voice': 'offline-silence',
                          'initial_duration': 45, 'analysis_id': analysis.id}}
        old = datetime.now(UTC) - timedelta(days=1)
        session.add(AutopilotJob(id='a' * 32, mode='guided', source='feeds', duration=30, platform='youtube',
                                ai_mode='offline', status='failed', current_stage='collect', stage_results={},
                                created_at=old, updated_at=old))
    before = stored_values(app)
    html = client.get('/').text
    # The old failed job stays in history but cannot take over the newer rendered work.
    import re
    steps = re.search(r'<ol class="workflow-steps".*?</ol>', html, re.DOTALL).group()
    assert steps.count('class="is-done"') == 4
    assert 'class="is-current"' in steps and 'class="is-error"' not in steps
    current = re.search(r'<a class="workflow-current".*?</a>', html, re.DOTALL).group()
    assert '가장 최근 완성 영상' in current and f'/?video={result["id"]}' in current
    assert stored_values(app) == before
    with app.state.sessions() as session:
        assert session.get(AutopilotJob, 'a' * 32).status == 'failed'
        assert session.get(ContentDraft, result['draft_id']).review_status == 'review_required'


def test_running_work_wins_but_cancelled_work_does_not_mask_newer_progress(app):
    now = datetime.now(UTC)
    recent = {'id': 'latest', 'status': 'waiting_review', 'updated_at': now.isoformat()}
    running = {'id': 'active', 'status': 'running', 'updated_at': (now - timedelta(hours=1)).isoformat()}
    cancelled = {'id': 'cancelled', 'status': 'cancelled', 'updated_at': (now + timedelta(hours=1)).isoformat()}
    with app.state.sessions() as session:
        assert dashboard_context(session, [recent, running])['focus']['id'] == 'active'
        assert dashboard_context(session, [cancelled, recent])['focus']['id'] == 'latest'


def test_analysis_only_workflow_points_to_analysis_and_never_invents_script(app):
    with app.state.sessions.begin() as session:
        analysis = IntelligenceRun(kind='analysis', provider='offline', status='success', options={},
                                   evidence={'articles': [{'title': '합성 자료'}]}, result={}, message='합성 검증 기록')
        session.add(analysis)
        session.flush()
        focus = {'status': 'waiting_review', 'analysis_run_id': analysis.id}
        states = [step['state'] for step in workflow_context(session, focus, None)['steps']]
        assert states == ['done', 'current', 'pending', 'pending', 'pending']


def test_older_api_script_links_analysis_without_new_ui_context(app):
    result = video_fixture(app, '기존 API 제작 기록')
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, result['draft_id'])
        run = session.get(IntelligenceRun, draft.run_id)
        analysis = IntelligenceRun(kind='analysis', provider='claude_api', status='success', options={},
                                   evidence={'articles': [{'title': '합성 자료'}]}, result={}, message='합성 검증 기록')
        session.add(analysis)
        session.flush()
        run.provider, run.options, run.evidence = 'claude_api', {'analysis_run_id': analysis.id}, analysis.evidence
        focus = {'status': 'waiting_review', 'draft_id': draft.id, 'render_job_id': result['id']}
        states = [step['state'] for step in workflow_context(session, focus, draft)['steps']]
        assert states == ['done', 'done', 'done', 'done', 'current']


def test_signal_colors_accessible_reasons_and_no_automatic_checks(studio_ui, browser, monkeypatch):
    from pathlib import Path

    from newsflow.gui import production_status

    app = studio_ui
    monkeypatch.setattr(production_status.FFmpegAdapter, 'executable', lambda *_: 'synthetic-existing-executable')
    app.state.production_checks = {'ffmpeg': {'ok': True}}
    save_values(app, autopilot_acquisition_policy='ai_web')
    before = stored_values(app)
    with local_server(app) as origin:
        context, page, external, errors = guarded_page(browser, origin, (1366, 900))
        posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        for width, height in [(1366, 900), (390, 844)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(origin + '/')
            for kind, color, meaning in [('news', 'red', '키 미등록'), ('voice', 'yellow', '무음 검토용'),
                                         ('video', 'green', '로컬 검사 통과 기록')]:
                option = page.locator(f'[data-production-kind={kind}]')
                expect(option.locator('summary [data-signal]')).to_have_attribute('data-signal', color)
                assert meaning in option.locator('summary').get_attribute('aria-label')
                option.locator('summary [data-signal]').click()
                expect(option.locator('[data-selection-status]')).to_contain_text(meaning)
                expect(option.locator('[data-selection-status]')).to_contain_text('실시간 검사 아님')
                notice = option.locator('[data-selection-status]')
                expect(notice.locator('[data-readiness-reason]')).not_to_be_empty()
                expect(notice.locator('[data-readiness-settings]')).to_have_attribute('href',
                    '/simple-settings#selected-ai' if kind == 'news' else
                    '/simple-settings#selected-voice' if kind == 'voice' else '/simple-settings#selected-video')
                assert notice.bounding_box()['y'] < option.locator('select').bounding_box()['y']
                page.keyboard.press('Escape')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            proof = Path('validation-output/workflow-signals-20261020')
            proof.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(proof / f'signals-{width}.png'))
        assert not posts and not external and not errors
        context.close()
    assert stored_values(app) == before
