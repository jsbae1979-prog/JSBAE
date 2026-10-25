"""State-machine tests use synthetic stage results; they do not prove media quality."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from newsflow.autopilot.contracts import (
    STAGES,
    AutopilotBusy,
    AutopilotConflict,
    AutopilotError,
    AutopilotNotFound,
    BackendError,
)
from newsflow.autopilot.service import AutopilotCoordinator
from newsflow.db.models import (
    AutopilotArticleClaim,
    AutopilotArtifact,
    AutopilotAttempt,
    AutopilotJob,
    NewsArticle,
    NewsSource,
)
from newsflow.db.session import make_engine, migrate, session_factory


class SyntheticStages:
    def __init__(self, article_ids):
        self.article_ids = article_ids
        self.calls = []
        self.block_stage = None
        self.entered = Event()
        self.release = Event()
        self.failure = None
        self.fail_stage = None
        self.retry_safe = True
        self.on_execute = None
        self.ignore_cancel = False

    def can_retry(self, _stage, _context):
        return self.retry_safe

    def execute(self, stage, context, cancel, progress, save):
        self.calls.append((stage, dict(context)))
        if self.on_execute:
            self.on_execute(stage, context, cancel, progress, save)
        if stage == self.block_stage:
            self.entered.set()
            while not self.release.wait(0.01):
                if cancel.is_set() and not self.ignore_cancel:
                    raise BackendError(code="cancelled")
        if stage == self.fail_stage:
            raise self.failure
        progress(50, "untrusted provider text must not become an event")
        result = {
            "collect": {"collection_run_id": 101, "collection_status": "success"},
            "select": {"article_id": self.article_ids[0], "candidate_article_ids": self.article_ids},
            "script": {"content_draft_id": 201, "script_revision": 1},
            "render": {"render_job_id": 301, "video_project_id": 401, "preview_only": True},
            "validate": {"media_sha256": "a" * 64, "preview_only": True, "human_review_required": True},
            "queue": {"publish_draft_id": 501, "queue_state": "review_required", "external_publishing_enabled": False},
        }[stage]
        return result


@pytest.fixture
def harness(tmp_path):
    root = tmp_path / "한글 사용자" / "NewsFlow AI"
    engine = make_engine(root / "newsflow.db")
    migrate(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        source = NewsSource(name="Synthetic", url="https://example.test/rss", enabled=False)
        session.add(source)
        session.flush()
        articles = [NewsArticle(title=f"합성 뉴스 {index}", url=f"https://example.test/{index}", canonical_url=f"https://example.test/{index}", source_id=source.id, publisher="Synthetic") for index in (1, 2)]
        session.add_all(articles)
        session.flush()
        identifiers = [article.id for article in articles]
    backend = SyntheticStages(identifiers)
    coordinator = AutopilotCoordinator(sessions, root, backend)
    yield coordinator, backend, sessions, root
    backend.release.set()
    coordinator.close()
    engine.dispose()


def settled(coordinator, identifier):
    if coordinator.future is not None:
        coordinator.future.result(timeout=10)
    return coordinator.snapshot(identifier)


def test_easy_synthetic_stages_are_durable_and_ordered(harness):
    coordinator, backend, sessions, _ = harness
    identifier = coordinator.start()
    result = settled(coordinator, identifier)
    assert len(identifier) == 32
    assert result["status"] == "completed" and result["progress"] == 100
    assert [stage for stage, _ in backend.calls] == list(STAGES)
    assert result["stage_results"]["request"]["news_usage"] == "STANDARD"
    assert [key for key in result["stage_results"] if key != "request"] == list(STAGES)
    assert [attempt["status"] for attempt in result["attempts"]] == ["completed"] * 6
    assert result["publish_draft_id"] == 501
    assert result["preview_playable"] is False  # Synthetic state fixture is not a rendered MP4.
    with sessions() as session:
        assert session.get(AutopilotJob, identifier).active_slot is None
        assert session.get(AutopilotArticleClaim, backend.article_ids[0]).job_id == identifier
    assert "untrusted provider text" not in json.dumps(result, ensure_ascii=False)


def test_guided_requires_each_review_and_can_choose_another_article(harness):
    coordinator, backend, sessions, _ = harness
    identifier = coordinator.start(mode="guided")
    result = settled(coordinator, identifier)
    assert (result["status"], result["current_stage"]) == ("waiting_review", "select")
    coordinator.resume(identifier, result["revision"], backend.article_ids[1])
    result = settled(coordinator, identifier)
    assert (result["status"], result["current_stage"]) == ("waiting_review", "script")
    assert backend.calls[-1][1]["article_id"] == backend.article_ids[1]
    with sessions() as session:
        assert session.get(AutopilotArticleClaim, backend.article_ids[0]) is None
    coordinator.resume(identifier, result["revision"])
    result = settled(coordinator, identifier)
    assert (result["status"], result["current_stage"]) == ("waiting_review", "validate")
    assert "queue" not in [stage for stage, _ in backend.calls]
    coordinator.resume(identifier, result["revision"])
    assert settled(coordinator, identifier)["status"] == "completed"


@pytest.mark.parametrize("pause", ["select", "script", "validate"])
def test_cancelled_guided_review_is_restored_without_skipping_review(harness, pause):
    coordinator, backend, _, _ = harness
    identifier = coordinator.start(mode="guided")
    result = settled(coordinator, identifier)
    while result["current_stage"] != pause:
        coordinator.resume(identifier, result["revision"])
        result = settled(coordinator, identifier)
    calls = len(backend.calls)
    cancelled = coordinator.cancel(identifier, result["revision"])
    assert cancelled["current_stage"] == pause
    restored = coordinator.retry(identifier, cancelled["revision"])
    assert restored["status"] == "waiting_review"
    assert restored["current_stage"] == pause
    assert len(backend.calls) == calls
    assert not restored["cancel_requested"]


def test_invalid_or_stale_review_does_not_change_article_claim(harness):
    coordinator, backend, sessions, _ = harness
    identifier = coordinator.start(mode="guided")
    result = settled(coordinator, identifier)
    for revision, article_id in ((result["revision"] - 1, backend.article_ids[1]), (result["revision"], 99999)):
        with pytest.raises(AutopilotError):
            coordinator.resume(identifier, revision, article_id)
    assert coordinator.snapshot(identifier)["article_id"] == backend.article_ids[0]
    with sessions() as session:
        assert session.get(AutopilotArticleClaim, backend.article_ids[1]) is None


def test_review_pause_occupies_database_slot_across_coordinators(harness):
    coordinator, backend, sessions, root = harness
    identifier = coordinator.start(mode="guided")
    settled(coordinator, identifier)
    second = AutopilotCoordinator(sessions, root, backend)
    try:
        with pytest.raises(AutopilotBusy):
            second.start()
        assert second.recover() == 0
        assert second.snapshot(identifier)["status"] == "waiting_review"
    finally:
        second.close()


def test_active_worker_blocks_second_start_and_recovery(harness):
    coordinator, backend, sessions, root = harness
    backend.block_stage = "collect"
    identifier = coordinator.start()
    assert backend.entered.wait(5)
    second = AutopilotCoordinator(sessions, root, backend)
    try:
        with pytest.raises(AutopilotBusy):
            second.start()
        with pytest.raises(AutopilotBusy):
            coordinator.start()
        assert second.recover() == 0
        second.cancel(identifier, second.snapshot(identifier)["revision"])
        assert settled(coordinator, identifier)["status"] == "cancelled"
    finally:
        second.close()


def test_independent_process_lock_blocks_without_creating_job(harness):
    coordinator, _, sessions, root = harness
    script = "from filelock import FileLock; import sys; lock=FileLock(sys.argv[1]); lock.acquire(); print('ready', flush=True); sys.stdin.readline(); lock.release()"
    child = subprocess.Popen([sys.executable, "-c", script, str(root / "autopilot.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(AutopilotBusy):
            coordinator.start()
        with sessions() as session:
            assert session.scalar(select(AutopilotJob.id)) is None
    finally:
        child.communicate("stop\n", timeout=10)
    assert child.returncode == 0


def test_concurrent_cancel_has_only_one_revision_winner(harness):
    coordinator, _, _, _ = harness
    identifier = coordinator.start(mode="guided")
    result = settled(coordinator, identifier)
    def cancel():
        try:
            coordinator.cancel(identifier, result["revision"])
            return "accepted"
        except AutopilotConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: cancel(), range(2)))
    assert sorted(outcomes) == ["accepted", "conflict"]
    assert coordinator.snapshot(identifier)["revision"] == result["revision"] + 1


def test_midstage_failure_preserves_artifacts_and_safe_retry_reuses_job(harness):
    coordinator, backend, _, _ = harness
    backend.fail_stage, backend.failure = "render", BackendError()
    def checkpoint(stage, _ctx, _cancel, _progress, save):
        if stage == "render":
            save("render_job_id", 300)
    backend.on_execute = checkpoint
    identifier = coordinator.start()
    result = settled(coordinator, identifier)
    assert result["status"] == "failed" and result["error_code"] == "render_failed"
    assert result["render_job_id"] == 300
    backend.fail_stage = None
    coordinator.retry(identifier, result["revision"])
    result = settled(coordinator, identifier)
    assert result["status"] == "completed"
    assert [stage for stage, _ in backend.calls] == ["collect", "select", "script", "render", "render", "validate", "queue"]
    assert backend.calls[4][1]["render_job_id"] == 300
    assert [a["number"] for a in result["attempts"] if a["stage"] == "render"] == [1, 2]


def test_same_article_cannot_make_second_automatic_video(harness):
    coordinator, backend, _, _ = harness
    assert settled(coordinator, coordinator.start())["status"] == "completed"
    second = settled(coordinator, coordinator.start())
    assert second["status"] == "failed"
    assert second["error_code"] == "duplicate_article"
    assert [stage for stage, _ in backend.calls].count("render") == 1


def test_cancel_during_render_keeps_checkpoint_and_stops_queue(harness):
    coordinator, backend, _, _ = harness
    backend.block_stage = "render"
    backend.on_execute = lambda stage, _ctx, _cancel, _progress, save: save("render_job_id", 300) if stage == "render" else None
    identifier = coordinator.start()
    assert backend.entered.wait(5)
    result = coordinator.snapshot(identifier)
    coordinator.cancel(identifier, result["revision"])
    result = settled(coordinator, identifier)
    assert result["status"] == "cancelled"
    assert result["render_job_id"] == 300
    assert "queue" not in [stage for stage, _ in backend.calls]
    assert result["attempts"][-1]["status"] == "cancelled"


def test_cancel_after_effect_keeps_completed_stage_and_retries_next(harness):
    coordinator, backend, _, _ = harness
    backend.block_stage, backend.ignore_cancel = "render", True
    identifier = coordinator.start()
    assert backend.entered.wait(5)
    coordinator.cancel(identifier, coordinator.snapshot(identifier)["revision"])
    backend.release.set()
    result = settled(coordinator, identifier)
    assert result["status"] == "cancelled" and result["current_stage"] == "validate"
    assert result["stage_results"]["render"]["render_job_id"] == 301
    coordinator.retry(identifier, result["revision"])
    assert settled(coordinator, identifier)["status"] == "completed"
    assert [stage for stage, _ in backend.calls].count("render") == 1


def test_unknown_result_is_never_automatically_successful(harness):
    coordinator, backend, _, _ = harness
    backend.fail_stage = "render"
    backend.failure = BackendError(outcome_unknown=True)
    backend.retry_safe = False
    identifier = coordinator.start()
    result = settled(coordinator, identifier)
    assert result["status"] == "failed" and result["error_code"] == "outcome_unknown"
    assert result["attempts"][-1]["status"] == "unknown"
    with pytest.raises(AutopilotConflict):
        coordinator.retry(identifier, result["revision"])
    assert coordinator.snapshot(identifier)["status"] == "failed"


def test_unexpected_error_does_not_expose_secret_or_allow_blind_retry(harness):
    coordinator, backend, _, _ = harness
    backend.fail_stage = "script"
    backend.failure = RuntimeError("Bearer super-secret-token and full provider response")
    identifier = coordinator.start()
    result = settled(coordinator, identifier)
    assert result["error_code"] == "outcome_unknown" and not result["retryable"]
    assert "super-secret" not in json.dumps(result)
    with pytest.raises(AutopilotConflict):
        coordinator.retry(identifier, result["revision"])


def test_restart_quarantines_running_job_and_preserves_checkpoint(harness):
    coordinator, backend, sessions, root = harness
    identifier = "a" * 32
    with sessions.begin() as session:
        session.add(AutopilotJob(id=identifier, active_slot=1, mode="easy", source="sample", duration=30, platform="youtube", status="running", current_stage="render", stage_results={}, article_id=backend.article_ids[0]))
        session.flush()
        session.add(AutopilotAttempt(job_id=identifier, stage="render", number=1, status="running"))
        session.add(AutopilotArtifact(job_id=identifier, kind="render_job_id", reference="300"))
    coordinator.close()
    reopened = AutopilotCoordinator(sessions, root, backend)
    try:
        assert reopened.recover() == 1
        result = reopened.snapshot(identifier)
        assert result["status"] == "interrupted" and result["render_job_id"] == 300
        assert result["attempts"][-1]["status"] == "unknown"
        assert backend.calls == []
        assert reopened.recover() == 0
        backend.retry_safe = False
        with pytest.raises(AutopilotConflict):
            reopened.retry(identifier, result["revision"])
    finally:
        reopened.close()


def test_close_requests_interruption_without_marking_completion(harness):
    coordinator, backend, _, _ = harness
    backend.block_stage = "collect"
    identifier = coordinator.start()
    assert backend.entered.wait(5)
    coordinator.close()
    result = coordinator.snapshot(identifier)
    assert result["status"] == "interrupted"
    assert result["progress"] < 100
    with pytest.raises(AutopilotBusy):
        coordinator.start()


@pytest.mark.parametrize("kwargs", [{"mode": "auto-publish"}, {"source": "external"}, {"duration": True}, {"duration": 31}, {"platform": "other"}])
def test_start_rejects_invalid_configuration(harness, kwargs):
    coordinator, _, _, _ = harness
    with pytest.raises(AutopilotError):
        coordinator.start(**kwargs)


@pytest.mark.parametrize("identifier", ["../x", "A" * 32, "", 1, "a" * 31])
def test_job_identifiers_reject_paths_and_invalid_types(harness, identifier):
    with pytest.raises(AutopilotNotFound):
        harness[0].snapshot(identifier)


@pytest.mark.parametrize("stage,result", [("collect", {}), ("script", {"content_draft_id": True}), ("render", {"render_job_id": 1, "video_project_id": 1, "preview_only": False}), ("validate", {"media_sha256": "a" * 64, "human_review_required": False, "preview_only": True}), ("queue", {"publish_draft_id": 1, "queue_state": "success", "external_publishing_enabled": True}), ("script", {"content_draft_id": 1, "nested": {"access_token": "synthetic"}})], ids=["missing", "boolean-id", "unreviewed-render", "forged-review", "published", "secret-field"])
def test_backend_success_contract_cannot_forge_completion(stage, result):
    with pytest.raises(BackendError):
        AutopilotCoordinator._validated_result(result, stage)


def test_migration_0008_is_additive_and_retains_legacy_data(tmp_path):
    engine = make_engine(tmp_path / "legacy.sqlite")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "src/newsflow/db/migrations"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0007")
            connection.execute(text("INSERT INTO news_sources(name,url,enabled,created_at) VALUES ('legacy','https://example.test/legacy',0,'2026-01-01 00:00:00')"))
        migrate(engine)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0018"
            assert connection.scalar(text("SELECT name FROM news_sources")) == "legacy"
        schema = inspect(engine)
        assert "autopilot_jobs" in schema.get_table_names()
        assert "preview_only" in {column["name"] for column in schema.get_columns("video_projects")}
        assert "autopilot_task_id" in {column["name"] for column in schema.get_columns("publish_drafts")}
    finally:
        engine.dispose()
