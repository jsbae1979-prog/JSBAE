"""Focused P1/P2 contracts; synthetic data, Fake transports, never operating storage."""
import hashlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from conftest import csrf
from sqlalchemy import func, select
from test_unified_publishing_gui import instagram_ui as instagram_fixture
from test_unified_publishing_gui import unified as unified_fixture
from test_unified_publishing_gui import youtube_media as media_fixture
from test_unified_publishing_gui import youtube_ui as youtube_fixture
from test_video import video as video_fixture
from test_voices_gui import korean as korean_fixture
from test_voices_gui import listening_form
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.db.models import AppSetting, ContentDraft, PublishDraft, PublishJob, RenderJob, Scene
from newsflow.easy_setup import listening_summary
from newsflow.gui.video_presentation import video_presentation
from newsflow.intelligence.korean import speech_plan
from newsflow.intelligence.provider import FakeProvider, Options
from newsflow.intelligence.review import scene_findings
from newsflow.intelligence.schema import Script
from newsflow.intelligence.service import IntelligenceService
from newsflow.publishing.service import PublishingError
from newsflow.publishing.unified import UnifiedPublishingService

instagram_ui = instagram_fixture
unified = unified_fixture
youtube_media = media_fixture
youtube_ui = youtube_fixture
korean = korean_fixture
video = video_fixture


@pytest.fixture(autouse=True)
def no_background_timers(monkeypatch):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self: None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start', lambda self: None)


def test_unconnected_incomplete_local_draft_survives_reopen_without_approval(
    unified, client, app, youtube_media, youtube_ui, instagram_ui,
):
    youtube_ui[0].channel['ready'] = False
    instagram_ui[0].account['ready'] = False
    before = app.state.unified_publishing.for_video(youtube_media)
    response = client.post('/publishing/unified/local-draft', data={
        'csrf_token': csrf(client), 'render_job_id': youtube_media, 'target': 'both',
        'title': '', 'description': '연결 전 작성 중 <script>not executable</script>',
        'hashtags': '#합성 #보관', 'youtube_category_id': '',
        # A local save must never imply these reviews, even if submitted by a client.
        'content_reviewed': 'true', 'copyright_confirmed': 'true', 'sources_confirmed': 'true',
    })
    assert response.status_code == 200 and '내 PC에 초안 저장됨' in response.text
    assert '&lt;script&gt;not executable&lt;/script&gt;' in response.text
    reopened = UnifiedPublishingService(app.state.sessions, unified.outputs, unified.youtube, unified.instagram)
    local = reopened.local_draft(youtube_media)
    assert local['target'] == 'both' and local['metadata']['title'] == ''
    assert local['metadata']['hashtags'] == ['#합성', '#보관'] and local['approval'] is False
    assert reopened.for_video(youtube_media) == before
    with app.state.sessions() as session:
        row = session.scalar(select(PublishDraft).where(PublishDraft.state == 'local_draft'))
        assert not row.content_reviewed and not row.account_id and not row.media_sha256
        assert session.scalar(select(func.count()).select_from(PublishJob)) == 0
    with pytest.raises(PublishingError):
        reopened.get(local['id'])
    assert not youtube_ui[0].calls and not instagram_ui[0].calls
    assert not youtube_ui[1].calls and not instagram_ui[1].calls


def test_local_save_does_not_rewrite_review_history(unified, client, youtube_media, youtube_ui, instagram_ui):
    from test_unified_publishing_gui import values
    client.post('/publishing/unified/review', data=values(client, youtube_media, youtube_ui, instagram_ui))
    previous = deepcopy(unified.for_video(youtube_media))
    unified.save_local_draft(youtube_media, target='youtube', title='새 로컬 문구', youtube_category_id='28')
    assert unified.for_video(youtube_media) == previous
    assert '새 로컬 문구' in client.get(f'/?video={youtube_media}&publish_platform=unified').text
    assert not youtube_ui[1].calls and not instagram_ui[1].calls


def test_listening_is_bound_to_sample_not_saved_provider(client, app, korean):
    response = client.post('/voices/preview', data={'csrf_token': csrf(client), 'voice': 'Fake Korean Voice'})
    name = response.url.params['preview']
    with app.state.sessions.begin() as session:
        row = session.get(AppSetting, 'video_default_voice')
        if row:
            row.value = 'elevenlabs'
        else:
            session.add(AppSetting(key='video_default_voice', value='elevenlabs'))
    page = client.get('/voices', params={'preview': name})
    assert page.status_code == 200 and 'elevenlabs · 이 PC에서 찾지 못함' not in page.text
    assert 'value="Fake Korean Voice" readonly' in page.text
    for changed in ({'voice': 'elevenlabs'}, {'rate': '2'}, {'pause_ms': '400'}):
        assert client.post('/voices/listening', data=listening_form(client, preview=name, **changed)).status_code == 422
    assert client.post('/voices/listening', data=listening_form(client)).status_code == 422
    # A human FAIL verdict is stored as submitted, never computed by the app.
    assert client.post('/voices/listening', data=listening_form(client, preview=name, verdict='fail')).status_code == 200
    assert listening_summary(app.state.sessions)['sample_linked']
    record = json.loads(next((app.state.config.data_dir / 'voice-listening').glob('*.json')).read_text('utf-8'))
    assert record['provider'] == 'windows' and record['voice'] == 'Fake Korean Voice'
    assert record['rate'] == 0 and record['pause_ms'] == 250
    # Do not delete the old sample when a new preview is made.
    client.post('/voices/preview', data={'csrf_token': csrf(client), 'voice': 'Fake Korean Voice'})
    path = app.state.config.data_dir / 'voice-preview' / name
    assert path.is_file()
    path.write_bytes(b'tampered synthetic sample')
    assert client.post('/voices/listening', data=listening_form(client, preview=name)).status_code == 422


def test_legacy_listening_record_and_unlinked_sample_remain_unverified(client, app, korean):
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key='voice_listening_last', value='fail · 2020-01-01 · 이전 청취자 · Heami'))
    directory = app.state.config.data_dir / 'voice-preview'
    directory.mkdir()
    name = 'preview-' + 'a' * 32 + '.wav'
    path = directory / name
    path.write_bytes(b'old sample')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    page = client.get('/voices', params={'preview': name})
    assert page.status_code == 200 and '샘플 연결 확인 필요 · 기존 기록' in page.text
    assert 'id="listening-voice" name="voice" maxlength="200" value="" readonly' in page.text
    assert not listening_summary(app.state.sessions)['sample_linked']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize('status,stage,label,action', [
    ('queued', None, '제작 대기', '/simple-settings#quality'),
    ('running', None, '영상 제작 중', '/simple-settings#quality'),
    ('failed', 'voice', '제작 실패', '/simple-settings#selected-voice'),
    ('failed', 'subtitle', '제작 실패', '/video'),
    ('failed', None, '제작 실패', '/simple-settings#quality'),
    ('unknown', None, '결과 불명', '/simple-settings#quality'),
    ('interrupted', None, '제작 중단', '/simple-settings#quality'),
    ('success', None, '영상 생성 완료 · 검토 필요', '/simple-settings#quality'),
])
def test_video_status_uses_only_confirmed_stage(status, stage, label, action):
    job = SimpleNamespace(status=status, metadata_json={'failure_stage': stage}, message='제작 기록')
    display = video_presentation(job, playable=status == 'success')
    assert display['label'] == label and display['action'] == action
    if status == 'failed' and not stage:
        assert display['stage'] == '원인 확인 필요'
    assert '준비 중' not in display['label']


def script_with_notes():
    script = FakeProvider().complete({'articles': [{'title': '합성 뉴스', 'summary': '화면 검증용'}]}, 30, Options(model='offline'))
    script['scenes'][0]['review_notes'] = ['원문에서 용어 정의 확인']
    return script


def test_structured_notes_and_legacy_notice_are_distinct_from_intentional_copy():
    script = script_with_notes()
    validated = Script.model_validate(script).model_dump()
    assert validated['scenes'][0]['review_notes'] == ['원문에서 용어 정의 확인']
    assert len(scene_findings(validated)) == 1
    old = deepcopy(script)
    old['scenes'][1]['narration'] = '제공된 요약에는 구체적인 배경이 없어, 자세한 내용은 원문 확인이 필요합니다.'
    assert len(scene_findings(old)) == 2 and old['scenes'][1]['narration'].startswith('제공된 요약에는')
    old['scenes'][1]['narration'] = '이 법은 원문 확인 절차를 개선합니다.'
    assert len(scene_findings(old)) == 1
    clean = deepcopy(script)
    del clean['scenes'][0]['review_notes']
    assert speech_plan(script, 30) == speech_plan(clean, 30)
    assert Script.model_validate(clean).model_dump() == clean  # No forced rewrite of old JSON.


def test_scene_notes_never_enter_render_narration_and_legacy_editor_preserves_them(video, app):
    coordinator, draft_id = video
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        content = deepcopy(draft.content)
        content['scenes'][0]['review_notes'] = ['검토자 전용 메모 절대 음성 금지']
        draft.content = content
    edited = deepcopy(content)
    for scene in edited['scenes']:
        scene.pop('review_notes', None)
    IntelligenceService(app.state.sessions).edit(draft_id, 1, edited)
    job_id = coordinator.start(draft_id, 30, reviewed=True)
    coordinator.future.result(timeout=10)
    with app.state.sessions() as session:
        saved = session.get(ContentDraft, draft_id)
        assert saved.content['scenes'][0]['review_notes'] == ['검토자 전용 메모 절대 음성 금지']
        assert session.get(RenderJob, job_id).status == 'simulated'
        assert all('검토자 전용' not in row.narration for row in session.scalars(select(Scene)))
    assert all('검토자 전용' not in text for text in coordinator.tts.calls)


def test_readiness_displays_scope_and_timestamp_without_claiming_inference(monkeypatch):
    from test_workflow_signals import gate, request, view

    from newsflow.gui.production_picker import selection_lights
    data = view()
    data['api_connections']['claude_api'] = gate(connection_check={
        'code': 'success', 'message': '모의 인증 확인', 'checked_at': '2026-10-20T00:00:00+00:00'})
    signals = selection_lights(request(), data)
    assert signals['news']['state'] == '미검증'
    assert signals['news']['checked_at'].year == 2026
    assert '인증·모델 조회 기록' in signals['news']['scope']
    assert signals['news']['action_url'] == '/simple-settings#selected-ai'
    assert signals['voice']['scope'] == '음성 설치·설정'


def test_ai_video_setup_save_keeps_validated_return_context_only(client):
    response = client.post('/video-ai-settings', data={
        'csrf_token': csrf(client), 'provider': 'off', 'currency': 'USD', 'return_draft': '7'},
        follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'].endswith('&return_draft=7')
    html = client.get(response.headers['location']).text
    assert '/video/ai?draft_id=7' in html
    assert '설정 저장·로컬 점검은 유료 생성이 아닙니다' in html
    assert client.post('/video-ai-settings', data={
        'csrf_token': csrf(client), 'provider': 'off', 'return_draft': 'https://external.invalid'},
        follow_redirects=False).status_code == 422
