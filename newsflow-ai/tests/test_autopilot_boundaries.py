"""Adversarial local orchestration checks; synthetic metadata is not MP4 proof."""

from __future__ import annotations

from threading import Event
from uuid import uuid4

import pytest
from filelock import FileLock
from sqlalchemy import func, select

from newsflow.autopilot.backend import PipelineBackend
from newsflow.autopilot.contracts import BackendError
from newsflow.db.models import (
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    PublishDraft,
    PublishJob,
    RenderJob,
)
from newsflow.intelligence.service import IntelligenceService
from newsflow.main import _recover_intelligence_runs, create_app
from newsflow.news.rss_adapter import FakeRSSAdapter
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import PublishingService
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS

MEDIA = {
    "format": "mp4",
    "playable": True,
    "video_codec": "h264",
    "audio_codec": "aac",
    "width": 1080,
    "height": 1920,
    "duration": 30.0,
    "fps": 30.0,
    "audio_channels": 2,
}


def execute(backend, stage, context):
    return backend.execute(stage, context, Event(), lambda *_: None, lambda *_: None)


@pytest.fixture
def boundary_pipeline(app):
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource))
        articles = [
            NewsArticle(
                title=f"합성 테스트 지역 소식 {index}",
                summary="테스트 전용 자료이며 실제 보도가 아닙니다.",
                url=f"https://example.com/boundary/{index}",
                canonical_url=f"https://example.com/boundary/{index}",
                source_id=source.id,
                publisher="합성 출처",
            )
            for index in (1, 2)
        ]
        session.add_all(articles)
        session.flush()
        article_ids = [article.id for article in articles]
    intelligence = IntelligenceService(app.state.sessions)
    analyses = [intelligence.analyze([identifier]) for identifier in article_ids]
    drafts = [intelligence.generate(identifier, 30) for identifier in analyses]
    video = app.state.video
    video.engine, video.tts = FakeRenderAdapter(), FakeTTS()
    render_id = video.start_preview(drafts[0], 30)
    video.future.result(timeout=10)
    with app.state.sessions.begin() as session:
        render = session.get(RenderJob, render_id)
        # Deliberately fabricated media for boundary tests only. Production backend
        # constructs FFprobeMediaInspector independently and does not do this.
        render.status, render.metadata_json = "success", {**MEDIA, "adapter": "test-fixture"}
        path = video.outputs / render.output_name
    publishing = PublishingService(app.state.sessions, video.outputs, FakeMediaInspector(MEDIA.copy()))
    backend = PipelineBackend(
        app.state.sessions, app.state.config.data_dir, app.state.coordinator,
        video, publishing=publishing,
    )
    backend.inspector = FakeMediaInspector(MEDIA.copy())
    context = {
        "job_id": uuid4().hex,
        "source": "sample",
        "mode": "easy",
        "duration": 30,
        "platform": "youtube",
        "article_id": article_ids[0],
        "content_draft_id": drafts[0],
        "render_job_id": render_id,
    }
    try:
        yield backend, context, path, analyses, drafts
    finally:
        backend.close()
        video.close()


@pytest.mark.parametrize("reference", ["content_draft_id", "script_run_id", "analysis_run_id"])
def test_recovered_reference_cannot_bind_a_different_article(boundary_pipeline, app, reference):
    backend, context, _, analyses, drafts = boundary_pipeline
    context = {key: value for key, value in context.items() if key != "content_draft_id"}
    with app.state.sessions() as session:
        other = session.get(ContentDraft, drafts[1])
        context[reference] = {
            "content_draft_id": other.id,
            "script_run_id": other.run_id,
            "analysis_run_id": analyses[1],
        }[reference]
        count_before = session.scalar(select(func.count()).select_from(ContentDraft))
    with pytest.raises(BackendError):
        execute(backend, "script", context)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(ContentDraft)) == count_before


@pytest.mark.parametrize("stage", ["render", "validate", "queue"])
def test_script_revision_change_cannot_relabel_existing_video(boundary_pipeline, app, stage):
    backend, context, _, _, _ = boundary_pipeline
    context.update(execute(backend, "validate", context))
    with app.state.sessions.begin() as session:
        script = session.get(ContentDraft, context["content_draft_id"])
        script.content = {**script.content, "title": "수정된 다른 내용"}
        script.revision += 1
    with pytest.raises(BackendError):
        execute(backend, stage, context)
    with app.state.sessions() as session:
        assert session.scalar(select(PublishDraft)) is None
        assert session.scalar(select(func.count()).select_from(RenderJob)) == 1


def test_changed_media_between_queue_check_and_create_cannot_finish(boundary_pipeline, app, monkeypatch):
    backend, context, path, _, _ = boundary_pipeline
    context.update(execute(backend, "validate", context))
    original_create = backend.publishing.create

    def changed_before_create(*args, **kwargs):
        path.write_bytes(b"DIFFERENT SYNTHETIC VIDEO BYTES")
        return original_create(*args, **kwargs)

    monkeypatch.setattr(backend.publishing, "create", changed_before_create)
    with pytest.raises(BackendError):
        execute(backend, "queue", context)
    with app.state.sessions() as session:
        draft = session.scalar(select(PublishDraft))
        assert draft is not None and draft.state == "blocked"
        assert draft.media_sha256 != context["media_sha256"]
        assert not draft.content_reviewed and not draft.copyright_confirmed
        assert not draft.sources_confirmed and draft.account_id is None
        assert session.scalar(select(PublishJob)) is None


@pytest.mark.parametrize("field", ["content_reviewed", "copyright_confirmed", "sources_confirmed", "account_id"])
def test_queue_retry_never_inherits_forged_review_or_account(boundary_pipeline, app, field):
    backend, context, _, _, _ = boundary_pipeline
    context.update(execute(backend, "validate", context))
    result = execute(backend, "queue", context)
    account_id = (
        backend.publishing.add_account("youtube", "합성 계정", "youtube_channel")
        if field == "account_id" else None
    )
    with app.state.sessions.begin() as session:
        draft = session.get(PublishDraft, result["publish_draft_id"])
        if field == "account_id":
            draft.account_id = account_id
        else:
            setattr(draft, field, True)
    with pytest.raises(BackendError):
        execute(backend, "queue", context)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublishDraft)) == 1
        assert session.scalar(select(PublishJob)) is None


def test_environment_configuration_does_not_select_external_ai(boundary_pipeline, app, monkeypatch):
    backend, context, _, _, _ = boundary_pipeline
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret-not-a-real-key")
    monkeypatch.setenv("NEWSFLOW_AI_PROVIDER", "openai")
    monkeypatch.setenv("NEWSFLOW_OAUTH_ENABLED", "1")
    monkeypatch.setenv("NEWSFLOW_PUBLISHING_ENABLED", "1")
    for key in ("content_draft_id", "render_job_id"):
        context.pop(key)
    import urllib.request

    from newsflow.intelligence.provider import OpenAIProvider

    def forbidden(*_args, **_kwargs):
        pytest.fail("An external service was selected by the offline workflow")

    monkeypatch.setattr(OpenAIProvider, "__init__", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    result = execute(backend, "script", context)
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, result["content_draft_id"])
        run = session.get(IntelligenceRun, draft.run_id)
        assert run.provider == "offline" and draft.review_status == "review_required"
        assert session.scalar(select(PublishJob)) is None


def test_second_app_does_not_interrupt_ai_while_workflow_lock_is_owned(app):
    with app.state.sessions.begin() as session:
        run = IntelligenceRun(
            kind="analysis", provider="offline", status="running", options={},
            evidence={}, result={}, message="합성 작업 진행 중",
        )
        session.add(run)
        session.flush()
        identifier = run.id
    with FileLock(str(app.state.config.data_dir / "autopilot.lock")).acquire(timeout=0):
        second = create_app(app.state.config, FakeRSSAdapter({}))
        try:
            with second.state.sessions() as session:
                still_running = session.get(IntelligenceRun, identifier)
                assert still_running.status == "running" and still_running.finished_at is None
        finally:
            second.state.autopilot.close()
            second.state.autopilot_backend.close()
            second.state.coordinator.close()
            second.state.video.close()
            second.state.engine.dispose()
    _recover_intelligence_runs(app.state.sessions, app.state.config.data_dir)
    with app.state.sessions() as session:
        interrupted = session.get(IntelligenceRun, identifier)
        assert interrupted.status == "interrupted" and interrupted.finished_at is not None
