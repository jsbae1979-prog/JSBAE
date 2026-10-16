"""Phase 5F.5 orchestration with synthetic RSS and injected AI; no account inference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select

from newsflow.autopilot.backend import PipelineBackend
from newsflow.autopilot.contracts import AutopilotConflict, AutopilotError, BackendError
from newsflow.autopilot.service import AutopilotCoordinator
from newsflow.db.models import (
    AIUsage,
    AppSetting,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
)
from newsflow.intelligence.provider import OfflineProvider, ProviderAuthError, ProviderTimeoutError
from newsflow.intelligence.service import IntelligenceService
from newsflow.news.collector import Collector
from newsflow.news.rss_adapter import FakeRSSAdapter
from newsflow.news.service import CollectionCoordinator, NewsService


class RecordingAI(OfflineProvider):
    def __init__(self):
        self.calls = []
        self.last_usage = {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50}
        self.error = None
        self.fail_kind = None

    def analyze(self, evidence, options):
        self.calls.append(("analysis", evidence, options))
        if self.error and self.fail_kind == "analysis":
            raise self.error
        result = super().analyze(evidence, options)
        return {**result, "recommended_article_id": evidence["articles"][-1]["id"],
                "selection_reason": "공공 영향과 설명할 근거를 비교한 검토 제안입니다."}

    def complete(self, evidence, duration, options):
        self.calls.append(("script", evidence, options))
        if self.error and self.fail_kind == "script":
            raise self.error
        return super().complete(evidence, duration, options)


@pytest.fixture
def automation(app):
    sessions = app.state.sessions
    when = format_datetime(datetime.now(UTC) - timedelta(hours=1))
    xml = ("<rss version='2.0'><channel><title>Fixture</title>"
           f"<item><title>경제 물가 조사 합성 자료</title><link>https://example.com/economy</link><pubDate>{when}</pubDate>"
           "<description>금리와 소비 물가의 관계를 설명하기 위한 합성 자료입니다. 실제 보도가 아닙니다.</description></item>"
           f"<item><title>우주 망원경 기술 실험 기록</title><link>https://example.com/science</link><pubDate>{when}</pubDate>"
           "<description>과학 관측 장비의 실험을 소개하기 위한 합성 자료입니다. 실제 보도가 아닙니다.</description></item>"
           "</channel></rss>").encode()
    adapter = FakeRSSAdapter({"https://example.com/rss": xml})
    collector = CollectionCoordinator(NewsService(sessions, Collector(adapter)), app.state.config.data_dir)
    ai = RecordingAI()
    backend = PipelineBackend(sessions, app.state.config.data_dir, collector, app.state.video,
                              intelligence=IntelligenceService(sessions, ai))
    coordinator = AutopilotCoordinator(sessions, app.state.config.data_dir, backend)
    with sessions.begin() as session:
        session.add(NewsSource(name="Synthetic RSS", url="https://example.com/rss", enabled=True))
    yield coordinator, backend, ai, sessions
    coordinator.close()
    backend.close()
    collector.close()
    app.state.coordinator.close()
    app.state.video.close()


def start(coordinator, provider="claude_code", duration=30, **changes):
    values = {"mode": "guided", "source": "feeds", "duration": duration, "content_mode": "real",
              "ai_mode": provider, "ai_model": {"claude_code": "sonnet", "codex": "default", "offline": "offline",
                                                 "openai": "gpt-4o-mini"}[provider],
              "voice": "supertonic:F1", "acquisition_policy": "rss", "category": "all", "period": "24h",
              "external_consent": provider != "offline"}
    return coordinator.start(**{**values, **changes})


def settled(coordinator, identifier):
    coordinator.future.result(timeout=15)
    return coordinator.snapshot(identifier)


@pytest.mark.parametrize("provider", ["claude_code", "codex"])
@pytest.mark.parametrize("duration", [30, 45, 60])
def test_same_provider_pipeline_preserves_selection_context_usage_and_review(automation, provider, duration):
    coordinator, backend, ai, sessions = automation
    identifier = start(coordinator, provider, duration)
    job = settled(coordinator, identifier)
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    assert job["review_pauses"] == ["script", "validate"]
    assert job["duration"] == duration and job["voice"] == "supertonic:F1"
    assert job["news_method"] == "rss" and job["stage_results"]["collect"]["web_search_performed"] is False
    assert job["stage_results"]["select"]["selection_method"] == "ai_recommendation"
    assert [call[0] for call in ai.calls] == ["analysis", "script"]
    assert len(ai.calls[0][1]["articles"]) == 2 and len(ai.calls[1][1]["articles"]) == 1
    assert ai.calls[0][2].model == ai.calls[1][2].model == job["ai_model"]
    assert ai.calls[0][2].timeout == 60
    with sessions() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        assert draft.duration == duration and draft.review_status == "review_required"
        assert [a["id"] for a in draft.sources["articles"]] == [job["article_id"]]
        assert draft.sources["articles"][0]["verification"] == "unverified"
        run = session.get(IntelligenceRun, job["script_run_id"])
        assert run.options["production_context"]["initial_voice"] == "supertonic:F1"
        assert run.options["consented_at"] == job["consented_at"]
        assert run.options["autopilot_job_id"] == identifier
        usage = list(session.scalars(select(AIUsage).order_by(AIUsage.id)))
        assert [(item.kind, item.provider) for item in usage] == [("analysis", provider), ("script", provider)]
        assert all(item.run_id in {job["analysis_run_id"], job["script_run_id"]} for item in usage)
    # Recover completed external output using the durable run ID, without another request.
    with sessions() as session:
        from newsflow.db.models import AutopilotJob

        context = coordinator._context(session, session.get(AutopilotJob, identifier))
    context.pop("content_draft_id")
    restored = backend.execute("script", context, Event(), lambda *_: None, lambda *_: None)
    assert restored["content_draft_id"] == job["content_draft_id"]
    assert len(ai.calls) == 2


@pytest.mark.parametrize("provider", ["claude_code", "codex", "openai"])
def test_consent_web_policy_and_trial_cannot_start_external_calls(automation, provider):
    coordinator, _, ai, _ = automation
    with pytest.raises(AutopilotError, match="동의"):
        start(coordinator, provider, external_consent=False)
    for policy in ("ai_web", "hybrid"):
        with pytest.raises(AutopilotError, match="웹 뉴스 검색"):
            start(coordinator, provider, acquisition_policy=policy)
    with pytest.raises(AutopilotError, match="체험"):
        start(coordinator, provider, source="sample", content_mode="trial")
    assert ai.calls == []


@pytest.mark.parametrize("kind", ["analysis", "script"])
@pytest.mark.parametrize("error", [ProviderAuthError(), ProviderTimeoutError(), RuntimeError("SECRET")])
def test_failed_and_unknown_external_requests_never_replay(automation, kind, error):
    coordinator, backend, ai, sessions = automation
    ai.fail_kind, ai.error = kind, error
    identifier = start(coordinator)
    job = settled(coordinator, identifier)
    assert job["status"] == "failed" and job["retryable"] is False
    assert "SECRET" not in job["message"]
    assert bool(job.get("analysis_run_id"))
    assert bool(job.get("script_run_id")) == (kind == "script")
    count = len(ai.calls)
    with pytest.raises(AutopilotConflict):
        coordinator.retry(identifier, job["revision"])
    assert len(ai.calls) == count
    with sessions() as session:
        from newsflow.db.models import AutopilotJob

        context = coordinator._context(session, session.get(AutopilotJob, identifier))
        assert not backend.can_retry(job["current_stage"], context)
        assert "SECRET" not in session.get(IntelligenceRun, job.get("script_run_id") or job["analysis_run_id"]).message


def test_category_and_unknown_old_future_dates_are_not_current_news(automation):
    coordinator, _, ai, sessions = automation
    identifier = start(coordinator, category="economy")
    job = settled(coordinator, identifier)
    assert len(ai.calls[0][1]["articles"]) == 1
    assert ai.calls[0][1]["articles"][0]["category"] == "경제"
    coordinator.cancel(identifier, job["revision"])
    with sessions.begin() as session:
        for article in session.scalars(select(NewsArticle)):
            article.published_at = None
    identifier = start(coordinator, category="economy")
    job = settled(coordinator, identifier)
    assert job["error_code"] == "no_eligible_articles"
    assert len(ai.calls) == 2
    with sessions.begin() as session:
        for article in session.scalars(select(NewsArticle)):
            article.published_at = datetime.now(UTC) + timedelta(days=1)
    identifier = start(coordinator, category="economy")
    assert settled(coordinator, identifier)["error_code"] == "no_eligible_articles"
    assert len(ai.calls) == 2


def test_openai_gate_and_usage_budget_remain_required(automation):
    coordinator, backend, ai, sessions = automation
    identifier = start(coordinator, "openai")
    assert settled(coordinator, identifier)["error_code"] == "ai_not_ready"
    assert ai.calls == []
    backend.ai_gate = lambda: {"ready": True}
    with sessions.begin() as session:
        session.add_all([AppSetting(key="ai_provider", value="openai"),
                         AppSetting(key="ai_approved_at", value=datetime.now(UTC).isoformat()),
                         AppSetting(key="ai_monthly_token_limit", value="1")])
    identifier = start(coordinator, "openai")
    assert settled(coordinator, identifier)["error_code"] == "ai_budget"
    assert ai.calls == []


def test_offline_keeps_local_flow_and_explicit_policy(automation):
    coordinator, _, ai, sessions = automation
    identifier = start(coordinator, "offline", duration=45)
    job = settled(coordinator, identifier)
    assert job["status"] == "waiting_review" and job["current_stage"] == "script"
    assert job["external_consent"] is False
    assert len(ai.calls) == 2
    with sessions() as session:
        assert session.scalar(select(AIUsage)) is None


def test_idempotency_refuses_changed_policy_or_model(automation):
    coordinator, _, ai, _ = automation
    identifier = uuid4().hex
    start(coordinator, request_id=identifier)
    settled(coordinator, identifier)
    assert start(coordinator, request_id=identifier) == identifier
    for change in ({"ai_model": "haiku"}, {"period": "7d"}, {"category": "world"}):
        with pytest.raises(AutopilotConflict):
            start(coordinator, request_id=identifier, **change)
    assert len(ai.calls) == 2


def test_cancel_is_delivered_to_only_operation_owned_provider(automation):
    coordinator, _, ai, _ = automation
    entered, cancelled = Event(), Event()

    def waiting(evidence, options):
        entered.set()
        assert cancelled.wait(5)
        from newsflow.intelligence.claude_code import ProviderCancelled

        raise ProviderCancelled()

    ai.analyze = waiting
    ai.cancel = lambda: (cancelled.set() or True)
    identifier = start(coordinator)
    assert entered.wait(5)
    job = coordinator.snapshot(identifier)
    coordinator.cancel(identifier, job["revision"])
    job = settled(coordinator, identifier)
    assert cancelled.is_set() and job["status"] == "cancelled"
    assert job["retryable"] is False and not job.get("script_run_id")


def test_resume_after_script_review_carries_voice_without_new_ai(automation, monkeypatch):
    coordinator, backend, ai, _ = automation
    identifier = start(coordinator, "codex", duration=60)
    job = settled(coordinator, identifier)
    captured = {}

    def render(context, *_args):
        captured.update(context)
        raise BackendError(code="render_failed", retryable=False)

    monkeypatch.setattr(backend, "_render", render)
    coordinator.resume(identifier, job["revision"])
    settled(coordinator, identifier)
    assert captured["duration"] == 60 and captured["voice"] == "supertonic:F1"
    assert captured["analysis_run_id"] == job["analysis_run_id"]
    assert captured["content_draft_id"] == job["content_draft_id"]
    assert len(ai.calls) == 2


def test_today_uses_korean_midnight_without_inventing_unknown_dates(automation):
    _, backend, ai, sessions = automation
    context = {"job_id": uuid4().hex, "source": "feeds", "mode": "guided", "duration": 30,
               "content_mode": "real", "ai_mode": "claude_code", "ai_model": "sonnet",
               "voice": "supertonic:F1", "acquisition_policy": "rss", "category": "all", "period": "today",
               "external_consent": True, "consented_at": "2026-10-16T06:00:00+00:00",
               "requested_at": "2026-10-16T06:00:00+00:00", "unified": True}
    save = lambda key, value: context.__setitem__(key, value)
    context.update(backend.execute("collect", context, Event(), lambda *_: None, save))
    with sessions.begin() as session:
        articles = list(session.scalars(select(NewsArticle).order_by(NewsArticle.id)))
        articles[0].published_at = datetime(2026, 10, 15, 15, tzinfo=UTC)  # KST 00:00 today
        articles[1].published_at = datetime(2026, 10, 15, 14, 59, 59, tzinfo=UTC)
        expected = articles[0].id
    result = backend.execute("select", context, Event(), lambda *_: None, save)
    assert result["candidate_article_ids"] == [expected]
    assert len(ai.calls) == 1


@pytest.mark.parametrize("state,expected,retryable", [
    ("running", "outcome_unknown", False), ("failed", "ai_request_stopped", False),
    ("success", "interrupted", True),
])
def test_restart_distinguishes_success_failure_and_unknown_without_replay(automation, state, expected, retryable):
    coordinator, _, ai, sessions = automation
    identifier = start(coordinator)
    job = settled(coordinator, identifier)
    with sessions.begin() as session:
        saved = session.get(AutopilotJob, identifier)
        saved.status = "running"
        session.get(IntelligenceRun, job["script_run_id"]).status = state
    assert coordinator.recover() == 1
    recovered = coordinator.snapshot(identifier)
    assert recovered["error_code"] == expected and recovered["retryable"] is retryable
    assert len(ai.calls) == 2
