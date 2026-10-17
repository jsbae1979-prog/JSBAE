"""Instagram publication orchestration, isolated SQLite/media and Fake-only transports."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from newsflow.db.models import (
    Base,
    ContentDraft,
    IntelligenceRun,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    RenderJob,
    VideoProject,
)
from newsflow.db.session import make_engine, session_factory
from newsflow.publishing.auth import TokenBundle
from newsflow.publishing.instagram import InstagramPublishResult, InstagramUploadError
from newsflow.publishing.instagram_live import InstagramPublishingService
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import ConflictError, PublishingError, PublishingService

IG_ID, PAGE_ID, APP_ID = "17841400000001", "12340001", "56780001"
CONTAINER, MEDIA = "1800000000001", "1810000000001"
LINK = "https://www.instagram.com/reel/Fixture_123/"


class Connections:
    def __init__(self):
        self.calls = []
        self.instagram_id = IG_ID

    def access_for_upload(self, account_id, *, consent=False):
        assert consent is True
        self.calls.append(account_id)
        return SimpleNamespace(
            bundle=TokenBundle(access_token=SecretStr("nf-synthetic-never-sent"),
                               expires_at=datetime.now(UTC) + timedelta(hours=1),
                               scopes=("instagram_basic", "instagram_content_publish", "pages_read_engagement")),
            instagram_id=self.instagram_id, page_id=PAGE_ID, app_id=APP_ID,
        )


class Adapter:
    def __init__(self):
        self.calls, self.failure = [], {}
        self.processing = "FINISHED"
        self.inspect = lambda _stage: None

    def _call(self, name):
        self.calls.append(name)
        self.inspect(name)
        if name in self.failure:
            raise self.failure[name]

    def create_container(self, payload, _bundle, account_id):
        self._call("create")
        assert payload["upload_approved"] is True and account_id == IG_ID
        return SimpleNamespace(container_id=CONTAINER)

    def upload(self, _path, _bundle, container_id, _hash):
        self._call("upload")
        assert container_id == CONTAINER

    def status(self, _bundle, container_id):
        self._call("status")
        assert container_id == CONTAINER
        return self.processing

    def publish(self, _bundle, account_id, container_id, *, public_approved):
        self._call("publish")
        assert account_id == IG_ID and container_id == CONTAINER and public_approved is True
        return MEDIA

    def result(self, _bundle, media_id, account_id):
        self._call("result")
        return InstagramPublishResult(media_id, LINK, account_id)


@pytest.fixture
def environment(tmp_path):
    engine = make_engine(tmp_path / "isolated.sqlite3")
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
        project = VideoProject(draft_id=content.id, title="합성 게시 검토", duration=30, snapshot={}, sources=sources)
        session.add(project)
        session.flush()
        video = RenderJob(project_id=project.id, status="success", output_name="video-" + "b" * 32 + ".mp4",
                          metadata_json={"playable": True})
        session.add(video)
        session.flush()
        render_id = video.id
        output = outputs / video.output_name
        output.write_bytes(b"synthetic video fixture")
    account = local.add_account("instagram", "합성 프로페셔널 계정", "professional_business")
    draft_id = local.create(render_id, "instagram", "합성 게시 검토", "설명", "뉴스", account_id=account,
                            content_reviewed=True, copyright_confirmed=True, sources_confirmed=True,
                            ai_disclosure="not_required")
    service = InstagramPublishingService(sessions, outputs, connections, inspector, lambda: adapter)
    yield service, sessions, draft_id, output, connections, adapter
    engine.dispose()


def approved(service, job_id):
    item = next(item for item in service.results() if item["id"] == job_id)
    return {"consent": True, "public_consent": True, "account_id": item["account_id"],
            "media_sha256": item["media_sha256"]}


def prepared(environment, *, ready=True):
    service, _sessions, draft_id, _output, _connections, _adapter = environment
    job_id = service.prepare(draft_id, 1, consent=True)
    if ready:
        service.check(job_id, consent=True)
    return job_id


def test_prepare_process_and_publication_are_separate_explicit_actions(environment):
    service, sessions, draft_id, _output, _connections, adapter = environment
    job = service.prepare(draft_id, 1, consent=True)
    assert adapter.calls == ["create", "upload"]
    assert service.results()[0]["status"] == "ig_processing"
    service.publish(job, **approved(service, job))  # Processing is not ready to publish.
    assert adapter.calls == ["create", "upload"]
    service.check(job, consent=True)
    assert service.results()[0]["status"] == "ig_ready"
    service.publish(job, **approved(service, job))
    result = service.results()[0]
    assert result["status"] == "ig_published" and result["media_id"] == MEDIA and result["url"] == LINK
    assert result["instagram_id"] == IG_ID and result["render_job_id"] == 1
    with sessions() as session:
        assert session.get(PublishJob, job).platform == "instagram"
        evidence = list(session.scalars(select(PublishEvidence)))
        assert all("nf-synthetic" not in str(row.payload) for row in evidence)
    assert adapter.calls == ["create", "upload", "status", "publish", "result"]


def test_every_mutation_and_returned_id_is_durable_before_next_request(environment):
    service, sessions, _draft_id, _output, _connections, adapter = environment
    states = {"create": "ig_creating", "upload": "ig_uploading", "status": "ig_checking",
              "publish": "ig_publishing", "result": "ig_linking"}
    def inspect(stage):
        item = service.results()[0]
        assert item["status"] == states[stage]
        if stage in {"upload", "status", "publish", "result"}:
            assert item["container_id"] == CONTAINER
        if stage == "publish":
            assert item["public_approved"] is True
        if stage == "result":
            assert item["media_id"] == MEDIA
    adapter.inspect = inspect
    job = prepared(environment)
    service.publish(job, **approved(service, job))
    with sessions() as session:
        assert session.get(PublishJob, job).status == "ig_published"


def test_missing_transfer_consent_does_not_access_credentials(environment):
    service, _sessions, draft_id, _output, connections, adapter = environment
    with pytest.raises(PublishingError):
        service.prepare(draft_id, 1)
    assert connections.calls == adapter.calls == []


@pytest.mark.parametrize("arguments", [{}, {"consent": True}, {"consent": True, "public_consent": True},
    {"consent": True, "public_consent": True, "account_id": 999, "media_sha256": "wrong"}])
def test_publication_requires_explicit_account_file_and_public_consent(environment, arguments):
    service, _sessions, _draft_id, _output, connections, adapter = environment
    job = prepared(environment)
    before = len(connections.calls)
    with pytest.raises(PublishingError):
        service.publish(job, **arguments)
    assert "publish" not in adapter.calls and len(connections.calls) == before


@pytest.mark.parametrize("field", ["content_reviewed", "copyright_confirmed", "sources_confirmed"])
def test_media_review_is_required_before_external_calls(environment, field):
    service, sessions, draft_id, _output, connections, adapter = environment
    with sessions.begin() as session:
        setattr(session.get(PublishDraft, draft_id), field, False)
    with pytest.raises(PublishingError):
        service.prepare(draft_id, 1, consent=True)
    assert connections.calls == adapter.calls == []


def test_changed_file_or_revision_blocks_transfer(environment):
    service, _sessions, draft_id, output, connections, adapter = environment
    with pytest.raises(ConflictError):
        service.prepare(draft_id, 2, consent=True)
    output.write_bytes(b"changed fixture")
    with pytest.raises(PublishingError):
        service.prepare(draft_id, 1, consent=True)
    assert connections.calls == adapter.calls == []


@pytest.mark.parametrize("stage", ["create", "upload", "publish"])
@pytest.mark.parametrize("error,status", [(TimeoutError("must never persist provider secret"), "ig_unknown"),
                                        (InstagramUploadError("permission"), "ig_failed")])
def test_failed_and_unknown_mutations_are_never_replayed(environment, stage, error, status):
    service, sessions, draft_id, _output, connections, adapter = environment
    adapter.failure[stage] = error
    job = prepared(environment)
    service.publish(job, **approved(service, job))
    before = list(adapter.calls), list(connections.calls)
    service.recover()
    assert service.prepare(draft_id, 1, consent=True) == job
    service.check(job, consent=True)
    service.publish(job, **approved(service, job))
    assert (adapter.calls, connections.calls) == before
    with sessions() as session:
        record = session.get(PublishJob, job)
        assert record.status == status and "secret" not in record.message


def test_known_publication_survives_link_lookup_failure_and_restart(environment):
    service, sessions, _draft_id, _output, _connections, adapter = environment
    job = prepared(environment)
    adapter.failure["result"] = TimeoutError()
    service.publish(job, **approved(service, job))
    item = service.results()[0]
    assert item["status"] == "ig_published_no_link" and item["media_id"] == MEDIA and item["url"] is None
    with sessions.begin() as session:
        session.get(PublishJob, job).status = "ig_linking"
    assert service.recover() == 1
    service.publish(job, **approved(service, job))
    assert adapter.calls.count("publish") == 1


@pytest.mark.parametrize("state", ["ig_creating", "ig_uploading", "ig_checking", "ig_publishing"])
def test_restart_never_replays_incomplete_request(environment, state):
    service, sessions, draft_id, _output, connections, adapter = environment
    job = prepared(environment)
    with sessions.begin() as session:
        session.get(PublishJob, job).status = state
    before = list(connections.calls), list(adapter.calls)
    assert service.recover() == 1 and service.recover() == 0
    service.prepare(draft_id, 1, consent=True)
    service.check(job, consent=True)
    service.publish(job, **approved(service, job))
    assert service.results()[0]["status"] == "ig_unknown"
    assert (connections.calls, adapter.calls) == before


def test_explicit_status_check_can_repeat_but_never_uploads_or_publishes(environment):
    service, _sessions, _draft_id, _output, connections, adapter = environment
    job = prepared(environment, ready=False)
    adapter.failure["status"] = TimeoutError()
    service.check(job, consent=True)
    assert service.results()[0]["status"] == "ig_status_failed"
    before = list(connections.calls), list(adapter.calls)
    service.results()
    service.recover()
    assert (connections.calls, adapter.calls) == before
    del adapter.failure["status"]
    service.check(job, consent=True)
    assert service.results()[0]["can_publish"] is True
    assert adapter.calls == ["create", "upload", "status", "status"]


@pytest.mark.parametrize("processing,expected", [("IN_PROGRESS", "ig_processing"), ("ERROR", "ig_failed"),
    ("EXPIRED", "ig_failed"), ("PUBLISHED", "ig_unknown"), ("malformed", "ig_status_failed")])
def test_processing_states_never_claim_publication_success(environment, processing, expected):
    service, _sessions, _draft_id, _output, _connections, adapter = environment
    job = prepared(environment, ready=False)
    adapter.processing = processing
    service.check(job, consent=True)
    assert service.results()[0]["status"] == expected
    assert "publish" not in adapter.calls


def test_draft_edit_after_upload_cannot_publish_stale_caption(environment):
    service, sessions, draft_id, _output, _connections, adapter = environment
    job = prepared(environment)
    with sessions.begin() as session:
        draft = session.get(PublishDraft, draft_id)
        draft.title, draft.revision = "새 제목", 2
    with pytest.raises(ConflictError):
        service.publish(job, **approved(service, job))
    assert "publish" not in adapter.calls


def test_changed_account_binding_cannot_publish(environment):
    service, _sessions, _draft_id, _output, connections, adapter = environment
    job = prepared(environment)
    connections.instagram_id = "17841400000002"
    service.publish(job, **approved(service, job))
    assert "publish" not in adapter.calls and service.results()[0]["status"] == "ig_unknown"


def test_processing_recheck_before_publish_cannot_turn_into_automatic_post(environment):
    service, _sessions, _draft_id, _output, _connections, adapter = environment
    job = prepared(environment)
    adapter.failure["publish"] = InstagramUploadError("not_ready")
    service.publish(job, **approved(service, job))
    assert service.results()[0]["status"] == "ig_processing"
    assert service.results()[0]["can_publish"] is False
    assert "result" not in adapter.calls
    # A repeated publish click while processing cannot enter the adapter again.
    service.publish(job, **approved(service, job))
    assert adapter.calls.count("publish") == 1


def test_same_video_different_draft_and_concurrent_clicks_only_transfer_once(environment):
    service, sessions, draft_id, _output, _connections, adapter = environment
    with ThreadPoolExecutor(max_workers=2) as workers:
        ids = list(workers.map(lambda _: service.prepare(draft_id, 1, consent=True), range(2)))
    assert ids[0] == ids[1]
    with sessions() as session:
        draft = session.get(PublishDraft, draft_id)
        second = service.local.create(draft.render_job_id, "instagram", "다른 제목", "설명", "뉴스",
            account_id=draft.account_id, content_reviewed=True, copyright_confirmed=True, sources_confirmed=True,
            ai_disclosure="not_required")
    assert service.prepare(second, 1, consent=True) == ids[0]
    assert adapter.calls == ["create", "upload"]


def test_concurrent_publication_clicks_send_one_post(environment):
    service, _sessions, _draft_id, _output, _connections, adapter = environment
    job = prepared(environment)
    arguments = approved(service, job)
    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(lambda _: service.publish(job, **arguments), range(2))) == [job, job]
    assert adapter.calls.count("publish") == 1


def test_youtube_jobs_same_mp4_are_independent_and_never_recovered(environment):
    service, sessions, draft_id, _output, _connections, adapter = environment
    with sessions.begin() as session:
        session.add(PublishJob(draft_id=draft_id, platform="youtube", status="uploading",
                              message="preserved YouTube", idempotency_key="y" * 64))
    job = prepared(environment)
    assert service.recover() == 0
    with sessions() as session:
        assert session.get(PublishJob, job).platform == "instagram"
        assert session.scalar(select(PublishJob).where(PublishJob.platform == "youtube")).status == "uploading"
    assert adapter.calls == ["create", "upload", "status"]


def test_listing_and_recovery_without_work_never_calls_providers(environment):
    service, _sessions, _draft_id, _output, connections, adapter = environment
    assert service.results() == [] and service.recover() == 0
    assert connections.calls == adapter.calls == []
