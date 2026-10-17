"""Real upload orchestration with local DB/media and explicitly injected Fake adapters."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from newsflow.db.models import (
    Base,
    ContentDraft,
    IntelligenceRun,
    PublishAttempt,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    RenderJob,
    VideoProject,
)
from newsflow.db.session import make_engine, session_factory
from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE
from newsflow.publishing.auth import TokenBundle
from newsflow.publishing.live import LivePublishingService
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import ConflictError, PublishingError, PublishingService
from newsflow.publishing.youtube import YouTubeUploadError, YouTubeUploadResult

CHANNEL = "UC" + "a" * 22
VIDEO = "abcDEF_1234"


class Connections:
    def __init__(self):
        self.calls = []

    def access_for_upload(self, account_id, *, consent=False):
        assert consent is True
        self.calls.append(account_id)
        return TokenBundle(access_token=SecretStr("nf-synthetic-never-sent"),
                           expires_at=datetime.now(UTC) + timedelta(hours=1), scopes=(YOUTUBE_UPLOAD_SCOPE,)), CHANNEL


class Adapter:
    def __init__(self, outcome=None):
        self.calls, self.outcome = [], outcome

    def upload(self, *args):
        self.calls.append(args)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome or YouTubeUploadResult(VIDEO, "https://www.youtube.com/watch?v=" + VIDEO, "private")


@pytest.fixture
def environment(tmp_path):
    engine = make_engine(tmp_path / "test.sqlite3")
    Base.metadata.create_all(engine)
    sessions = session_factory(engine)
    outputs = tmp_path / "videos"
    outputs.mkdir()
    inspector, connections, adapter = FakeMediaInspector(), Connections(), Adapter()
    local = PublishingService(sessions, outputs, inspector)
    sources = {"articles": [{"sources": [{"url": "https://example.com/fixture"}]}]}
    with sessions.begin() as session:
        run = IntelligenceRun(kind="script", status="success", provider="offline", options={"model": "fixture"},
                              evidence={}, result={}, message="synthetic")
        session.add(run)
        session.flush()
        content = ContentDraft(run_id=run.id, duration=30, content={}, sources=sources)
        session.add(content)
        session.flush()
        project = VideoProject(draft_id=content.id, title="합성 검토용", duration=30, snapshot={}, sources=sources)
        session.add(project)
        session.flush()
        video = RenderJob(project_id=project.id, status="success", output_name="video-" + "a" * 32 + ".mp4",
                          metadata_json={"playable": True})
        session.add(video)
        session.flush()
        render_id = video.id
        output = outputs / video.output_name
        output.write_bytes(b"synthetic local video fixture")
    account = local.add_account("youtube", "테스트 채널", "youtube_channel")
    draft_id = local.create(render_id, "youtube", "합성 검토용", "설명", "뉴스", account_id=account,
                            content_reviewed=True, copyright_confirmed=True, sources_confirmed=True,
                            ai_disclosure="not_required")
    service = LivePublishingService(sessions, outputs, connections, inspector, lambda: adapter)
    yield service, sessions, draft_id, output, connections, adapter
    engine.dispose()


def test_success_persists_id_link_and_approved_snapshot(environment):
    service, sessions, draft_id, _output, connections, adapter = environment
    job_id = service.execute(draft_id, 1, consent=True)
    with sessions() as session:
        assert session.get(PublishJob, job_id).status == "uploaded"
        result = session.scalar(select(PublishEvidence).where(PublishEvidence.kind == "youtube_upload_result"))
        assert result.payload["video_id"] == VIDEO
        assert result.payload["url"] == "https://www.youtube.com/watch?v=" + VIDEO
        request = session.scalar(select(PublishEvidence).where(PublishEvidence.kind == "youtube_upload_request"))
        assert request.payload["privacy"] == "private" and request.payload["user_approved"] is True
        assert "token" not in str(result.payload) + str(request.payload)
    assert len(adapter.calls) == len(connections.calls) == 1
    assert service.results()[0]["draft_id"] == draft_id


@pytest.mark.parametrize("arguments", [{}, {"privacy": "public", "consent": True},
                                      {"privacy": "unlisted", "consent": True}])
def test_missing_upload_or_visibility_consent_never_calls_connections(environment, arguments):
    service, _sessions, draft_id, _output, connections, adapter = environment
    with pytest.raises(PublishingError):
        service.execute(draft_id, 1, **arguments)
    assert connections.calls == adapter.calls == []


@pytest.mark.parametrize("field", ["content_reviewed", "copyright_confirmed", "sources_confirmed"])
def test_missing_review_blocks_before_oauth_and_upload(environment, field):
    service, sessions, draft_id, _output, connections, adapter = environment
    with sessions.begin() as session:
        setattr(session.get(PublishDraft, draft_id), field, False)
    with pytest.raises(PublishingError):
        service.execute(draft_id, 1, consent=True)
    assert connections.calls == adapter.calls == []


def test_stale_revision_or_changed_file_cannot_upload(environment):
    service, _sessions, draft_id, output, connections, adapter = environment
    with pytest.raises(ConflictError):
        service.execute(draft_id, 2, consent=True)
    output.write_bytes(b"changed")
    with pytest.raises(PublishingError):
        service.execute(draft_id, 1, consent=True)
    assert connections.calls == adapter.calls == []


@pytest.mark.parametrize("outcome,status", [(YouTubeUploadError("unknown"), "unknown"),
    (TimeoutError("sensitive provider body"), "unknown"), (YouTubeUploadError("permission"), "failed")])
def test_failure_and_unknown_never_replay_after_service_restart(environment, outcome, status):
    service, sessions, draft_id, _output, connections, adapter = environment
    adapter.outcome = outcome
    first = service.execute(draft_id, 1, consent=True)
    recreated = LivePublishingService(sessions, service.outputs, connections, FakeMediaInspector(), lambda: adapter)
    assert recreated.execute(draft_id, 1, consent=True) == first
    with sessions() as session:
        job = session.get(PublishJob, first)
        assert job.status == status and "sensitive" not in job.message
    assert len(adapter.calls) == len(connections.calls) == 1


def test_same_channel_video_different_draft_cannot_duplicate_upload(environment):
    service, sessions, draft_id, _output, _connections, adapter = environment
    first = service.execute(draft_id, 1, consent=True)
    with sessions() as session:
        original = session.get(PublishDraft, draft_id)
        second = service.local.create(original.render_job_id, "youtube", "다른 제목", "다른 설명", "검토",
            account_id=original.account_id, content_reviewed=True, copyright_confirmed=True,
            sources_confirmed=True, ai_disclosure="not_required")
    assert service.execute(second, 1, consent=True) == first and len(adapter.calls) == 1


def test_metadata_edit_does_not_allow_second_upload(environment):
    service, sessions, draft_id, _output, _connections, adapter = environment
    first = service.execute(draft_id, 1, consent=True)
    with sessions.begin() as session:
        draft = session.get(PublishDraft, draft_id)
        draft.title, draft.revision = "수정 제목", 2
    assert service.execute(draft_id, 2, consent=True) == first and len(adapter.calls) == 1


def test_restart_quarantines_incomplete_upload_without_network(environment):
    service, sessions, draft_id, _output, connections, adapter = environment
    first = service.execute(draft_id, 1, consent=True)
    with sessions.begin() as session:
        session.get(PublishJob, first).status = "uploading"
        session.scalar(select(PublishAttempt)).status = "uploading"
    assert service.recover() == 1 and service.recover() == 0
    assert service.execute(draft_id, 1, consent=True) == first
    with sessions() as session:
        assert session.get(PublishJob, first).status == "unknown"
    assert len(adapter.calls) == len(connections.calls) == 1


def test_channel_reconnect_cannot_rebind_pending_review(environment):
    service, sessions, draft_id, _output, connections, adapter = environment
    original = connections.access_for_upload
    def changed(account_id, *, consent=False):
        with sessions.begin() as session:
            session.get(PublishDraft, draft_id).revision += 1
        return original(account_id, consent=consent)
    connections.access_for_upload = changed
    with pytest.raises(ConflictError):
        service.execute(draft_id, 1, consent=True)
    assert adapter.calls == []


def test_legacy_simulation_does_not_count_as_live_upload(environment):
    from newsflow.publishing.service import identity
    service, sessions, draft_id, _output, _connections, adapter = environment
    with sessions.begin() as session:
        draft = session.get(PublishDraft, draft_id)
        session.add(PublishJob(draft_id=draft_id, platform="youtube", status="simulated",
                               message="historical fake", idempotency_key=identity(draft)))
    job_id = service.execute(draft_id, 1, consent=True)
    with sessions() as session:
        assert session.get(PublishJob, job_id).status == "uploaded"
        assert len(list(session.scalars(select(PublishJob)))) == 2
    assert len(adapter.calls) == 1


def test_result_listing_never_authenticates_or_uploads(environment):
    service, _sessions, _draft_id, _output, connections, adapter = environment
    assert service.results() == [] and connections.calls == adapter.calls == []


def test_concurrent_clicks_reserve_only_one_real_upload(environment):
    service, sessions, draft_id, _output, _connections, adapter = environment
    with ThreadPoolExecutor(max_workers=2) as workers:
        jobs = list(workers.map(lambda _: service.execute(draft_id, 1, consent=True), range(2)))
    assert jobs[0] == jobs[1] and len(adapter.calls) == 1
    with sessions() as session:
        assert len(list(session.scalars(select(PublishJob)))) == 1


def test_results_include_workspace_fields(environment):
    service, _sessions, draft_id, _output, _connections, _adapter = environment
    identifier = service.execute(draft_id, 1, consent=True)
    item = service.results()[0]
    assert item["id"] == item["job_id"] == identifier
    assert item["render_job_id"] == 1 and item["status"] == "uploaded"
    assert item["video_url"] == "https://www.youtube.com/watch?v=" + VIDEO and item["message"]


def test_wrong_platform_cannot_enter_youtube_upload(environment):
    service, sessions, draft_id, _output, connections, adapter = environment
    with sessions.begin() as session:
        session.get(PublishDraft, draft_id).platform = "instagram"
    with pytest.raises(PublishingError):
        service.execute(draft_id, 1, consent=True)
    assert connections.calls == adapter.calls == []
