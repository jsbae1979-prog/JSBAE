"""Automatic queue creation reuses metadata preparation without approving publication."""

import pytest
from sqlalchemy import func, select
from test_autopilot_boundaries import boundary_pipeline as boundary_fixture
from test_autopilot_boundaries import execute
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.autopilot.backend import PipelineBackend
from newsflow.autopilot.contracts import BackendError
from newsflow.db.models import ContentDraft, PublishDraft, RenderJob, VideoProject
from newsflow.publishing.metadata import suggest_metadata

boundary_pipeline = boundary_fixture


def ready(pipeline):
    backend, context, *_ = pipeline
    context.update(execute(backend, "validate", context))
    return backend, context


@pytest.mark.parametrize("platform", ["youtube", "instagram"])
@pytest.mark.parametrize("scheduled", [False, True])
def test_automatic_and_scheduled_queue_store_same_local_suggestions(boundary_pipeline, app, platform, scheduled):
    backend, context = ready(boundary_pipeline)
    context.update(platform=platform, scheduled=scheduled)
    with app.state.sessions() as session:
        project = session.get(VideoProject, session.get(RenderJob, context["render_job_id"]).project_id)
        suggested = suggest_metadata(project.title, project.snapshot, project.sources)
        source = project.sources["articles"][0]["sources"][0]["url"]
    result = execute(backend, "queue", context)
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, result["publish_draft_id"])
        assert draft.title == suggested["title"]
        assert suggested["description"] in draft.description and source in draft.description
        assert draft.hashtags == [t.removeprefix("#") for t in suggested["hashtags"].split()]
        assert "실제 보도 아님" in draft.description and "음성 없음" in draft.description
        assert draft.state == "blocked" and draft.account_id is None
        assert not any((draft.content_reviewed, draft.copyright_confirmed, draft.sources_confirmed))
        assert draft.ai_disclosure == "unreviewed"
    assert result["queue_state"] == "review_required" and not result["external_publishing_enabled"]


def test_queue_uses_video_snapshot_not_mutated_content_without_revision(boundary_pipeline, app):
    backend, context = ready(boundary_pipeline)
    with app.state.sessions.begin() as session:
        content = session.get(ContentDraft, context["content_draft_id"])
        content.content = {**content.content, "title": "나중 제목", "summary": "나중 요약"}
    result = execute(backend, "queue", context)
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, result["publish_draft_id"])
        assert draft.title != "나중 제목" and "나중 요약" not in draft.description


def test_restarted_backend_preserves_preexisting_legacy_and_user_edited_draft(boundary_pipeline, app):
    backend, context = ready(boundary_pipeline)
    identifier = backend.publishing.create(context["render_job_id"], "youtube", "예전 초안", "예전 설명",
                                           "뉴스 검토용", autopilot_task_id=context["job_id"])
    execute(backend, "queue", context)
    backend.publishing.edit(identifier, 1, "youtube", "직접 수정한 제목", "", "직접수정", youtube_category_id="27")
    replacement = PipelineBackend(app.state.sessions, app.state.config.data_dir, app.state.coordinator,
                                  app.state.video, publishing=backend.publishing)
    replacement.inspector = backend.inspector
    try:
        result = execute(replacement, "queue", context)
        assert result["publish_draft_id"] == identifier
        with app.state.sessions() as session:
            assert session.scalar(select(func.count(PublishDraft.id))) == 1
            draft = session.get(PublishDraft, identifier)
            assert (draft.title, draft.description, draft.hashtags, draft.revision, draft.youtube_category_id) == (
                "직접 수정한 제목", "", ["직접수정"], 2, "27")
    finally:
        replacement.close()


@pytest.mark.parametrize("summary", ["sk-" + "syntheticsecret" * 2, "x" * 501])
def test_invalid_or_sensitive_snapshot_stops_queue_without_fallback(boundary_pipeline, app, summary):
    backend, context = ready(boundary_pipeline)
    with app.state.sessions.begin() as session:
        project = session.get(VideoProject, session.get(RenderJob, context["render_job_id"]).project_id)
        project.snapshot = {**project.snapshot, "summary": summary}
    with pytest.raises(BackendError) as raised:
        execute(backend, "queue", context)
    assert not raised.value.retryable and summary not in str(raised.value)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count(PublishDraft.id))) == 0


def test_external_ai_and_silent_disclaimers_remain_local(boundary_pipeline, app):
    backend, context = ready(boundary_pipeline)
    context.update(source="feeds", ai_mode="openai")  # Queue-only; no API generation.
    result = execute(backend, "queue", context)
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, result["publish_draft_id"])
        assert "외부 AI 초안 · 사실 확인 미완료" in draft.description
        assert "무음 검토영상 · 음성 없음" in draft.description
