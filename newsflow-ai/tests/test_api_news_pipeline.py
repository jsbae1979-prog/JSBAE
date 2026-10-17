"""STEP 3 integration: injected fixtures only; no CLI, paid API, or live RSS calls."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from newsflow.autopilot.backend import PipelineBackend
from newsflow.autopilot.contracts import AutopilotConflict, AutopilotError, BackendError
from newsflow.autopilot.service import AutopilotCoordinator
from newsflow.db.models import (
    APIRequestReservation,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
)
from newsflow.intelligence.api_providers import APICancelled, FakeAPIProvider
from newsflow.intelligence.api_search import SearchRequest
from newsflow.intelligence.api_settings import FakeAPIBudgetService, save_api_settings
from newsflow.intelligence.provider import Options, ProviderTimeoutError
from newsflow.intelligence.service import IntelligenceService
from newsflow.intelligence.settings import write_settings
from newsflow.news.collector import Collector
from newsflow.news.rss_adapter import FakeRSSAdapter
from newsflow.news.service import CollectionCoordinator, NewsService

MODELS = {"openai": "gpt-4.1-mini", "claude_api": "claude-sonnet-4-6"}


class FixtureKey:
    def status(self):
        return {"configured": True, "source": "test"}

    def key(self):
        return "synthetic-key-not-a-real-credential"


@pytest.fixture(params=["openai", "claude_api"])
def api_pipeline(app, request):
    mode, sessions = request.param, app.state.sessions
    model = MODELS[mode]
    save_api_settings(sessions, mode, model=model, approved=True, search_enabled=True, search_approved=True,
                      request_limit_usd="10", monthly_limit_usd="100", input_price_per_1m="3",
                      output_price_per_1m="15", search_price_per_1k="10", billing_confirmed=True,
                      account_remaining_usd="100")
    if mode == "openai":
        write_settings(sessions, "openai", model, True, 2_000_000, 20)
    provider = FakeAPIProvider(mode)
    ai = IntelligenceService(sessions, api_key_stores={mode: FixtureKey()}, api_providers={mode: provider},
                             api_budget=FakeAPIBudgetService(sessions))
    date = format_datetime(datetime.now(UTC) - timedelta(hours=1))
    xml = (f"<rss version='2.0'><channel><title>Fixture</title><item><title>[합성 테스트] 공개 뉴스 자료 검토</title>"
           f"<link>https://www.bbc.com/korean/articles/newsflow-contract-fixture</link><pubDate>{date}</pubDate>"
           "<description>실제 보도가 아닌 계약 테스트 자료입니다. 출처와 내용을 검토하는 과정을 확인합니다.</description>"
           "</item></channel></rss>").encode()
    adapter = FakeRSSAdapter({"https://example.com/step3-rss": xml})
    collection = CollectionCoordinator(NewsService(sessions, Collector(adapter)), app.state.config.data_dir)
    with sessions.begin() as session:
        session.add(NewsSource(name="합성 RSS", url="https://example.com/step3-rss", enabled=True))
    backend = PipelineBackend(sessions, app.state.config.data_dir, collection, app.state.video,
                              intelligence=ai, ai_gate=lambda: {"ready": True})
    coordinator = AutopilotCoordinator(sessions, app.state.config.data_dir, backend)
    yield coordinator, backend, provider, sessions, mode, adapter
    coordinator.close()
    backend.close()
    collection.close()
    app.state.coordinator.close()
    app.state.video.close()


def start(pipeline, **changes):
    coordinator, _, _, _, mode, _ = pipeline
    params = {"mode": "guided", "source": "feeds", "content_mode": "real", "duration": 30, "ai_mode": mode,
              "ai_model": MODELS[mode], "acquisition_policy": "ai_web", "category": "all", "period": "24h",
              "voice": "supertonic:F1", "external_consent": True}
    return coordinator.start(**{**params, **changes})


def settled(pipeline, identifier):
    coordinator = pipeline[0]
    coordinator.future.result(timeout=20)
    return coordinator.snapshot(identifier)


@pytest.mark.parametrize("duration", [30, 45, 60])
def test_search_analysis_script_same_api_and_length_pause_once(api_pipeline, duration, monkeypatch):
    coordinator, backend, provider, sessions, mode, rss = api_pipeline
    identity = uuid4().hex
    identifier = start(api_pipeline, duration=duration, request_id=identity)
    job = settled(api_pipeline, identifier)
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    assert provider.calls == ["search"] and rss.calls == []
    assert job["ai_mode"] == job["search_provider"] == mode
    assert job["analysis_provider"] == job["script_provider"] == "local_topic_template"
    assert job["news_method"] == "ai_web" and job["duration"] == duration
    assert job["review_pauses"] == ["script", "validate"]
    assert job["stage_results"]["collect"]["web_search_performed"] is False
    assert job["stage_results"]["collect"]["simulated_search"] is True
    with sessions() as session:
        rows = list(session.scalars(select(IntelligenceRun).order_by(IntelligenceRun.id)))
        assert [(row.kind, row.provider, row.status) for row in rows] == [
            ("search", mode, "success"),
            ("analysis", "local_topic_template", "success"),
            ("script", "local_topic_template", "success"),
        ]
        assert all(row.options["autopilot_job_id"] == identity for row in rows)
        draft = session.get(ContentDraft, job["content_draft_id"])
        assert draft.duration == duration and draft.review_status == "review_required"
        assert sum(scene["seconds"] for scene in draft.content["scenes"]) == duration
        assert draft.sources["articles"][0]["search_provenance"]["facts_verified"] is False
        reservations = list(session.scalars(select(APIRequestReservation)))
        assert len(reservations) == 1 and all(row.test_only and row.status == "success" for row in reservations)
    # Reopening, restarting and repeated start preserve IDs and never rerun inference.
    assert start(api_pipeline, duration=duration, request_id=identity) == identity
    assert coordinator.recover() == 0
    assert coordinator.snapshot(identity)["search_run_id"] == job["search_run_id"]
    captured = {}

    def stop_at_render(context, *_):
        captured.update(context)
        raise BackendError(code="render_failed", retryable=False)

    monkeypatch.setattr(backend, "_render", stop_at_render)
    coordinator.resume(identifier, job["revision"])
    coordinator.future.result(timeout=15)
    assert captured["duration"] == duration and captured["voice"] == "supertonic:F1"
    assert captured["analysis_run_id"] == job["analysis_run_id"]
    assert provider.calls == ["search"]


def test_hybrid_runs_explicit_rss_after_search_and_deduplicates(api_pipeline):
    _, _, provider, sessions, _, rss = api_pipeline
    identifier = start(api_pipeline, acquisition_policy="hybrid")
    job = settled(api_pipeline, identifier)
    assert job["status"] == "waiting_review"
    assert job["news_method"] == "ai_web+rss" and rss.calls == ["https://example.com/step3-rss"]
    assert provider.calls == ["search"]
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(NewsArticle)) == 1


def test_unknown_search_stops_without_rss_fallback_or_replay(api_pipeline):
    coordinator, backend, provider, sessions, _, rss = api_pipeline
    provider.result = ProviderTimeoutError()
    identifier = start(api_pipeline, acquisition_policy="hybrid")
    job = settled(api_pipeline, identifier)
    assert job["status"] == "failed" and job["retryable"] is False
    assert provider.calls == ["search"] and rss.calls == []
    assert job["search_run_id"]
    with pytest.raises(AutopilotConflict):
        coordinator.retry(identifier, job["revision"])
    # Simulate process loss before the collect-stage result was persisted.
    with sessions.begin() as session:
        row = session.get(AutopilotJob, identifier)
        row.status, row.current_stage = "running", "collect"
    assert coordinator.recover() == 1
    job = coordinator.snapshot(identifier)
    assert job["status"] == "failed" and job["retryable"] is False
    assert not backend.can_retry("collect", job)
    assert provider.calls == ["search"]
    with sessions() as session:
        record = session.scalar(select(APIRequestReservation))
        assert record.status == "unknown"
        assert session.scalar(select(func.count()).select_from(NewsArticle)) == 0


def test_real_api_readiness_never_inherits_fake_or_configuration_as_success(api_pipeline):
    _, backend, provider, _, _, rss = api_pipeline
    backend.intelligence.api_budget = None
    with pytest.raises(AutopilotError):
        start(api_pipeline)
    assert provider.calls == [] and rss.calls == []


@pytest.mark.parametrize("acquisition_policy", ["ai_web", "hybrid"])
def test_unknown_source_date_allows_topic_only_and_rss_is_explicit(api_pipeline, acquisition_policy):
    _, _, provider, sessions, mode, rss = api_pipeline
    result = provider.search(SearchRequest(), Options(model=MODELS[mode], max_tokens=3000))
    article = result.articles[0].model_copy(update={"published_at": None, "eligible": False,
                                                 "metadata_status": "needs_source_review"})
    provider.result = result.model_copy(update={"articles": [article]})
    provider.calls.clear()
    identifier = start(api_pipeline, acquisition_policy=acquisition_policy)
    job = settled(api_pipeline, identifier)
    assert job["status"] == "waiting_review" and job["current_stage"] == "script"
    assert job["news_usage"] == "STANDARD"
    assert job["news_usage_result"]["verification_status"] == "NOT VERIFIED"
    assert job["analysis_provider"] == job["script_provider"] == "local_topic_template"
    assert provider.calls == ["search"]
    assert rss.calls == (["https://example.com/step3-rss"] if acquisition_policy == "hybrid" else [])
    with sessions() as session:
        article = session.scalar(select(NewsArticle))
        assert (article.published_at is not None) == (acquisition_policy == "hybrid")
        draft = session.get(ContentDraft, job["content_draft_id"])
        assert draft.sources["articles"][0]["verification"] == "unverified"


def test_successful_search_artifact_reused_after_restart_without_new_search(api_pipeline):
    coordinator, backend, provider, sessions, _, rss = api_pipeline
    identifier = start(api_pipeline)
    job = settled(api_pipeline, identifier)
    with sessions() as session:
        context = coordinator._context(session, session.get(AutopilotJob, identifier))
    restored = backend.execute("collect", context, Event(), lambda *_: None, lambda *_: None)
    assert restored["search_run_id"] == job["search_run_id"]
    assert provider.calls == ["search"] and rss.calls == []


def test_cancel_search_keeps_reservation_unknown_and_never_starts_analysis(api_pipeline, monkeypatch):
    coordinator, _, provider, sessions, _, rss = api_pipeline
    started, cancelled = Event(), Event()

    def search(*_):
        provider.calls.append("search")
        started.set()
        assert cancelled.wait(5)
        raise APICancelled()

    monkeypatch.setattr(provider, "search", search)
    monkeypatch.setattr(provider, "cancel", cancelled.set, raising=False)
    identifier = start(api_pipeline)
    assert started.wait(5)
    coordinator.cancel(identifier, coordinator.snapshot(identifier)["revision"])
    job = settled(api_pipeline, identifier)
    assert job["status"] == "cancelled" and job["retryable"] is False
    assert provider.calls == ["search"] and rss.calls == []
    with sessions() as session:
        assert session.scalar(select(APIRequestReservation)).status == "unknown"
        assert session.scalar(select(func.count()).select_from(NewsArticle)) == 0


def test_workspace_script_review_shows_search_evidence_and_separate_usage(api_pipeline, client, app, monkeypatch):
    monkeypatch.setattr("newsflow.video.tts.WindowsTTS.voice_details", lambda self: [])
    monkeypatch.setattr("newsflow.video.supertonic_tts.SupertonicTTS.voices", lambda self: [])
    coordinator, backend, provider, _, _, rss = api_pipeline
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    monkeypatch.setattr(app.state, "autopilot_backend", backend)
    identifier = start(api_pipeline)
    job = settled(api_pipeline, identifier)
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    response = client.get(f"/?task={identifier}#workspace-detail")
    assert response.status_code == 200
    assert "뉴스 검색 근거" in response.text
    assert "Fake 응답 검증 · 실제 웹 검색 아님" in response.text
    assert "뉴스 검색: 1회" in response.text
    assert "주제" in response.text and "NOT VERIFIED" in response.text
    assert "원문 본문·사실·권리 확인은 사용자 검토가 필요합니다." in response.text
    assert 'href="https://www.bbc.com/korean/articles/newsflow-contract-fixture"' in response.text
    assert "RSS 수집·보완을 선택할 때만 출처 등록이 필요합니다." not in response.text  # fixture has a registered RSS
    assert "RSS 선택 시 사용합니다." in response.text
    assert provider.calls == ["search"] and rss.calls == []
