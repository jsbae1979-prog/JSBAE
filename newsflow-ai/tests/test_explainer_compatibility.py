"""Saved versions, existing editor and simulated rendering; isolated app/DB only."""

import json
from copy import deepcopy
from threading import Event

import pytest
from conftest import csrf
from test_api_news_pipeline import api_pipeline as api_pipeline  # noqa: PLC0414
from test_api_news_pipeline import settled, start
from test_explainer_prompts import evidence, interpretive

from newsflow.autopilot.contracts import BackendError
from newsflow.db.models import AutopilotJob, ContentDraft, IntelligenceRun, RenderJob, VideoProject
from newsflow.intelligence.provider import OfflineProvider, Options, prompt_instruction
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_existing_job_keeps_version_across_environment_change_and_reopen(api_pipeline, monkeypatch, version):
    coordinator, backend, provider, sessions, _mode, _rss = api_pipeline
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', version)
    original = provider.analyze
    seen = []

    def analyze(source, options):
        seen.append(deepcopy(source))
        monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', 'v2' if version == 'v1' else 'v1')
        return original(source, options)

    monkeypatch.setattr(provider, 'analyze', analyze)
    identifier = start(api_pipeline)
    job = settled(api_pipeline, identifier)
    assert job['status'] == 'waiting_review' and job['script_method'] == 'api_grounded_' + version
    assert seen[0]['script_prompt_version'] == version
    with sessions() as session:
        draft = session.get(ContentDraft, job['content_draft_id'])
        assert draft.sources['script_prompt_version'] == version
        assert session.get(IntelligenceRun, draft.run_id).options['script_prompt_version'] == version
        context = coordinator._context(session, session.get(AutopilotJob, identifier))
    restored = backend.execute('script', context, Event(), lambda *_: None, lambda *_: None)
    assert restored['content_draft_id'] == draft.id
    assert restored['script_method'] == 'api_grounded_' + version
    assert start(api_pipeline, request_id=identifier) == identifier
    assert coordinator.recover() == 0
    assert provider.calls == ['search', 'analysis', 'script']
    # A different version cannot borrow the previous result or trigger a fresh call.
    wrong = {**context, 'script_method': 'api_grounded_' + ('v1' if version == 'v2' else 'v2')}
    with pytest.raises(BackendError):
        backend.execute('script', wrong, Event(), lambda *_: None, lambda *_: None)
    assert provider.calls == ['search', 'analysis', 'script']


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_old_and_new_editor_keep_metadata_and_render_only_scene_narration(api_pipeline, client, app, monkeypatch, version):
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', version)
    _coordinator, _backend, provider, sessions, _mode, _rss = api_pipeline
    job = settled(api_pipeline, start(api_pipeline))
    source_article = evidence()['articles'][0]
    with sessions.begin() as session:
        draft = session.get(ContentDraft, job['content_draft_id'])
        source = deepcopy(draft.sources)
        source['articles'][0].update(title=source_article['title'], summary=source_article['summary'])
        value = interpretive() if version == 'v2' else OfflineProvider().complete(source, 30, Options())
        draft.content, draft.sources = value, source
        draft.review_notes = []
        session.get(IntelligenceRun, draft.run_id).evidence = source
        draft_id = draft.id
    calls = list(provider.calls)
    page = client.get(f'/ai?draft_id={draft_id}')
    assert page.status_code == 200
    assert page.text.count('data-script-read-scene=') == len(value['scenes'])
    assert '실제 처리: 주제 설명 템플릿' not in page.text
    assert 'AI 초안 · 원문·출처 검토 필요' in page.text
    fields = {'csrf_token': csrf(client), 'revision': '1', 'title': value['title'], 'hook': value['hook'],
              'summary': value['summary'], 'closing': value['closing'],
              'seconds': [str(s['seconds']) for s in value['scenes']],
              'narration': [s['narration'] for s in value['scenes']],
              'caption': [s['caption'] for s in value['scenes']],
              'material': [s['material'] for s in value['scenes']]}
    saved = client.post(f'/ai/drafts/{draft_id}', data=fields, follow_redirects=False)
    assert saved.status_code == 303
    with sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.content == value and draft.revision == 2 and draft.review_status == 'review_required'
    video = client.get(f'/video?draft_id={draft_id}')
    assert video.status_code == 200
    engine, voice = FakeRenderAdapter(), FakeTTS()
    app.state.video.engine, app.state.video.tts = engine, voice
    render = app.state.video.start_preview(draft_id, 30)
    app.state.video.future.result(timeout=15)
    assert voice.calls == [s['narration'] for s in value['scenes']]
    assert all('viewer_action' not in text and 'misconception' not in text for text in voice.calls)
    assert len(engine.calls) == 1 and engine.calls[0].strict_audio_fit
    with sessions() as session:
        row = session.get(RenderJob, render)
        assert row.status == 'simulated' and row.metadata_json['playable'] is False
        project = session.get(VideoProject, row.project_id)
        assert project.snapshot.get('analysis') == value.get('analysis')
        assert project.sources['script_method'] == 'api_grounded_' + version
    assert provider.calls == calls


def test_v2_shortform_specialized_hook_guard_stays_enabled():
    from dataclasses import asdict

    from newsflow.shortform import Shortform

    source = evidence()
    source['shortform'] = asdict(Shortform(enabled=True))
    value = interpretive()
    with pytest.raises(IntelligenceError, match='숏폼'):
        IntelligenceService.check_news_usage(value, source)
    system = prompt_instruction('script', source)
    assert 'shortform_contract' in system and 'subscription' in system


def test_review_skip_is_not_fact_approval_or_publication():
    value = interpretive()
    value['scenes'][0].pop('role')
    notes = IntelligenceService.__new__(IntelligenceService)
    notes.speech = {'rate': 0, 'pause_ms': 250}
    findings = notes._review_notes(value, evidence(), 30)
    assert any(item['code'] == 'explainer_roles' and item['level'] == 'info' for item in findings)
    assert evidence().get('facts_verified') is None
    assert 'facts_verified' not in json.dumps(value)

