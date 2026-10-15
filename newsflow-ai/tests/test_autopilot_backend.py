"""Service integration with synthetic inputs; real MP4 proof is a separate CI/browser check."""

from __future__ import annotations

from threading import Event
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from newsflow.autopilot.backend import PipelineBackend
from newsflow.autopilot.contracts import BackendError
from newsflow.autopilot.samples import SAMPLE_TOPICS, SAMPLE_URL
from newsflow.db.models import (
    AuditLog,
    CollectionRun,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    PublishDraft,
    RenderJob,
    VideoProject,
)
from newsflow.intelligence.provider import FakeProvider
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import PublishingService
from newsflow.video.engine import FakeRenderAdapter, RenderError
from newsflow.video.service import VideoError


@pytest.fixture
def pipeline(app):
    backend = PipelineBackend(
        app.state.sessions, app.state.config.data_dir, app.state.coordinator, app.state.video
    )
    context = {
        "job_id": uuid4().hex,
        "source": "sample",
        "mode": "easy",
        "duration": 30,
        "platform": "youtube",
    }
    yield backend, context
    backend.close()
    app.state.coordinator.close()
    app.state.video.close()


def step(pipeline, stage, cancel=None):
    backend, ctx = pipeline
    result = backend.execute(
        stage, dict(ctx), cancel or Event(), lambda *_: None, lambda key, value: ctx.__setitem__(key, value)
    )
    ctx.update(result)
    return result


def script(pipeline):
    for stage in ("collect", "select", "script"):
        step(pipeline, stage)


def test_sample_collection_scoped_without_real_feeds_or_estimated_dates(pipeline, app, monkeypatch):
    backend, ctx = pipeline
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Do not fetch", url="https://example.com/user-feed", enabled=True))
    forbidden = Mock(side_effect=AssertionError("real collection invoked"))
    monkeypatch.setattr(backend.collection, "start", forbidden)
    result = step(pipeline, "collect")
    assert result["synthetic_news"] and result["added"] == len(SAMPLE_TOPICS)
    assert not forbidden.called
    with app.state.sessions() as session:
        articles = list(session.scalars(select(NewsArticle)))
        assert len(articles) == len(SAMPLE_TOPICS)
        assert all(a.published_at is None and "[합성]" in a.title for a in articles)
        sample = session.scalar(select(NewsSource).where(NewsSource.url == SAMPLE_URL))
        assert not sample.enabled
        assert session.scalar(select(NewsSource).where(NewsSource.url.endswith("user-feed"))).enabled
        assert session.get(CollectionRun, ctx["collection_run_id"]).succeeded == 1


def test_explicit_feeds_uses_existing_registered_adapter_and_excludes_sample(pipeline, app):
    _backend, ctx = pipeline
    step(pipeline, "collect")
    with app.state.sessions.begin() as session:
        sample = session.scalar(select(NewsSource).where(NewsSource.url == SAMPLE_URL))
        sample.enabled = True  # Even a user-enabled sample is never requested by the real adapter.
        source = NewsSource(name="Fixture", url="https://example.com/rss", enabled=True)
        session.add(source)
        session.flush()
        wanted = source.id
    ctx.pop("collection_run_id")
    ctx.pop("source_ids")
    ctx["source"] = "feeds"
    result = step(pipeline, "collect")
    assert result["source_ids"] == [wanted] and not result["synthetic_news"]


def test_feed_failure_preserves_collected_data_and_log_redacts(pipeline, app):
    _backend, ctx = pipeline
    step(pipeline, "collect")
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Broken fixture", url="https://example.com/broken", enabled=True))
    ctx.pop("collection_run_id")
    ctx.pop("source_ids")
    ctx["source"] = "feeds"
    with pytest.raises(BackendError):
        step(pipeline, "collect")
    with app.state.sessions() as session:
        assert session.scalar(select(func.count(NewsArticle.id))) == len(SAMPLE_TOPICS)
        assert session.get(CollectionRun, ctx["collection_run_id"]).status == "failed"
        assert session.scalar(select(AuditLog).where(AuditLog.level == "error"))


def test_analysis_and_draft_are_offline_unreviewed_with_sources_preserved(pipeline, app, monkeypatch):
    from newsflow.intelligence.provider import OpenAIProvider

    forbidden = Mock(side_effect=AssertionError("external AI"))
    monkeypatch.setattr(OpenAIProvider, "request", forbidden)
    monkeypatch.setenv("NEWSFLOW_AI_API_KEY", "SYNTHETIC-KEY-NOT-ACTUAL")
    script(pipeline)
    _backend, ctx = pipeline
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, ctx["content_draft_id"])
        assert draft.review_status == "review_required"
        assert draft.sources["articles"][0]["verification"] == "unverified"
        assert draft.sources["articles"][0]["sources"][0]["url"].startswith("https://example.com/")
        assert all(run.provider == "offline" for run in session.scalars(select(IntelligenceRun)))
    assert not forbidden.called


@pytest.mark.parametrize("error", [TimeoutError("SECRET"), RuntimeError("SECRET")], ids=["timeout", "error"])
def test_ai_failure_persisted_safe_and_retryable(pipeline, app, error):
    backend, ctx = pipeline
    step(pipeline, "collect")
    step(pipeline, "select")
    backend.intelligence = IntelligenceService(app.state.sessions, FakeProvider(error))
    with pytest.raises(BackendError) as failure:
        step(pipeline, "script")
    assert "SECRET" not in str(failure.value)
    with app.state.sessions() as session:
        run = session.get(IntelligenceRun, ctx["analysis_run_id"])
        assert run.status == "failed" and "SECRET" not in run.message
    assert backend.can_retry("script", ctx)
    backend.intelligence = IntelligenceService(app.state.sessions)
    step(pipeline, "script")
    assert ctx["content_draft_id"]


def test_durable_script_run_recovers_existing_draft_without_repeat(pipeline, app):
    script(pipeline)
    backend, ctx = pipeline
    identifier = ctx.pop("content_draft_id")
    backend.intelligence.generate = Mock(side_effect=AssertionError("must reuse"))
    step(pipeline, "script")
    assert ctx["content_draft_id"] == identifier
    assert not backend.intelligence.generate.called


def test_preview_is_distinct_from_review_approval_and_has_watermark(pipeline, app):
    script(pipeline)
    backend, ctx = pipeline

    class Capture(FakeRenderAdapter):
        title = None

        def render(self, plan, *args):
            self.title = plan.title
            return super().render(plan, *args)

    engine = Capture()
    backend.video.engine = engine
    with pytest.raises(VideoError):
        backend.video.start(ctx["content_draft_id"], 30, reviewed=False)
    identifier = backend.video.start_preview(ctx["content_draft_id"], 30)
    backend.video.future.result(timeout=10)
    with app.state.sessions() as session:
        job = session.get(RenderJob, identifier)
        assert session.get(VideoProject, job.project_id).preview_only
        assert session.get(ContentDraft, ctx["content_draft_id"]).review_status == "review_required"
    assert engine.title.startswith("검토용 초안 · ")


def test_fake_render_never_becomes_a_valid_local_queue_video(pipeline, app):
    script(pipeline)
    backend, ctx = pipeline
    backend.video.engine = FakeRenderAdapter()
    with pytest.raises(BackendError) as failure:
        step(pipeline, "render")
    assert not failure.value.retryable
    assert not backend.can_retry("render", ctx)
    with app.state.sessions() as session:
        assert session.get(RenderJob, ctx["render_job_id"]).status == "simulated"
        assert session.scalar(select(PublishDraft)) is None


def test_ffmpeg_failure_does_not_leave_success_and_retry_safe(pipeline, app):
    script(pipeline)
    backend, ctx = pipeline
    backend.video.engine = FakeRenderAdapter(RenderError("SECRET"))
    with pytest.raises(BackendError) as failure:
        step(pipeline, "render")
    assert "SECRET" not in str(failure.value)
    with app.state.sessions() as session:
        job = session.get(RenderJob, ctx["render_job_id"])
        assert job.status == "failed" and "SECRET" not in job.message
    assert backend.can_retry("render", ctx)


def test_render_cancel_is_scoped_and_next_start_uses_fresh_event(pipeline, app):
    script(pipeline)
    backend, ctx = pipeline
    entered = Event()

    class Waiting(FakeRenderAdapter):
        def render(self, plan, work, tts, progress, cancel):
            entered.set()
            assert cancel.wait(10)
            raise RenderError("cancelled")

    backend.video.engine = Waiting()
    first = backend.video.start_preview(ctx["content_draft_id"], 30)
    assert entered.wait(5)
    assert not backend.video.request_cancel(first + 1)
    assert backend.video.request_cancel(first)
    backend.video.future.result(timeout=10)
    assert not backend.video.cancel.is_set()
    backend.video.engine = FakeRenderAdapter()
    second = backend.video.start_preview(ctx["content_draft_id"], 30)
    backend.video.future.result(timeout=10)
    with app.state.sessions() as session:
        assert session.get(RenderJob, first).status == "interrupted"
        assert session.get(RenderJob, second).status == "simulated"


@pytest.mark.parametrize("stage", ["script", "render"])
def test_preallocation_failure_can_be_explicitly_retried(pipeline, stage):
    backend, ctx = pipeline
    assert backend.can_retry(stage, ctx)


def test_checkpoint_failure_stops_before_ai_provider(pipeline, app):
    step(pipeline, "collect")
    step(pipeline, "select")
    _backend, ctx = pipeline
    provider = FakeProvider()
    ai = IntelligenceService(app.state.sessions, provider)

    def fail(_):
        raise RuntimeError("SECRET")

    with pytest.raises(IntelligenceError):
        ai.analyze([ctx["article_id"]], on_run=fail)
    assert provider.calls == 0
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun))
        assert run.status == "failed" and "SECRET" not in run.message


def test_checkpoint_failure_stops_before_collection_and_releases_lock(pipeline, app):
    backend, _ = pipeline
    source_ids = backend._sources("sample")

    def fail(_):
        raise RuntimeError("SECRET")

    with pytest.raises(RuntimeError):
        backend.sample_collection.start(source_ids, fail)
    with app.state.sessions() as session:
        assert session.scalar(select(CollectionRun)).status == "failed"
        assert session.scalar(select(NewsArticle)) is None
    step(pipeline, "collect")


def test_checkpoint_failure_stops_before_renderer_and_allows_next_start(pipeline, app):
    script(pipeline)
    backend, ctx = pipeline
    engine = Mock(spec=FakeRenderAdapter)
    backend.video.engine = engine

    def fail(_):
        raise RuntimeError("SECRET")

    with pytest.raises(RuntimeError):
        backend.video.start_preview(ctx["content_draft_id"], 30, fail)
    assert not engine.render.called
    with app.state.sessions() as session:
        job = session.scalar(select(RenderJob))
        assert job.status == "failed" and "SECRET" not in job.message
    backend.video.engine = FakeRenderAdapter()
    backend.video.start_preview(ctx["content_draft_id"], 30)
    backend.video.future.result(timeout=10)


def test_queue_synthetic_workflow_is_idempotent_and_keeps_human_approval_blocked(pipeline, app):
    """Fake inspection verifies orchestration only, not actual MP4 bytes/quality."""
    script(pipeline)
    backend, ctx = pipeline
    backend.video.engine = FakeRenderAdapter()
    identifier = backend.video.start_preview(ctx["content_draft_id"], 30)
    backend.video.future.result(timeout=10)
    inspector = FakeMediaInspector()
    with app.state.sessions.begin() as session:
        job = session.get(RenderJob, identifier)
        job.status, job.metadata_json = "success", {**inspector.metadata, "fixture_only": True}
    ctx["render_job_id"] = identifier
    backend.inspector = inspector
    backend.publishing = PublishingService(app.state.sessions, backend.video.outputs, inspector)
    step(pipeline, "render")
    step(pipeline, "validate")
    step(pipeline, "queue")
    initial = ctx["publish_draft_id"]
    ctx.pop("publish_draft_id")  # Simulate loss of coordinator checkpoint after atomic draft creation.
    step(pipeline, "queue")
    assert ctx["publish_draft_id"] == initial and ctx["queue_state"] == "review_required"
    assert ctx["external_publishing_enabled"] is False
    with app.state.sessions() as session:
        assert session.scalar(select(func.count(PublishDraft.id))) == 1
        draft = session.get(PublishDraft, initial)
        assert draft.state == "blocked" and draft.account_id is None
        assert not any((draft.content_reviewed, draft.sources_confirmed, draft.copyright_confirmed))
        assert draft.ai_disclosure == "unreviewed" and "실제 보도 아님" in draft.description


def test_collection_completed_checkpoint_recovery_uses_original_source_journal(pipeline, app):
    backend, ctx = pipeline
    ctx["source"] = "feeds"
    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss", enabled=True))
    step(pipeline, "collect")
    run_id, source_ids = ctx["collection_run_id"], ctx.pop("source_ids")
    with app.state.sessions.begin() as session:
        for identifier in source_ids:
            session.get(NewsSource, identifier).enabled = False
    backend.collection.start = Mock(side_effect=AssertionError("must reuse completed run"))
    step(pipeline, "collect")
    assert ctx["collection_run_id"] == run_id and ctx["source_ids"] == source_ids
    assert not backend.collection.start.called
