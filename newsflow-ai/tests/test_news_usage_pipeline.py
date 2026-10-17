"""Preserved legacy local jobs on isolated SQLite; new API jobs use test_api_shorts_pipeline."""

from copy import deepcopy
from threading import Event
from uuid import uuid4

import pytest
import test_api_news_pipeline
from sqlalchemy import select
from test_api_news_pipeline import MODELS, settled, start

from newsflow.autopilot.contracts import AutopilotConflict, AutopilotError, BackendError
from newsflow.db.models import (
    APIRequestReservation,
    AppSetting,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    RenderJob,
    utcnow,
)
from newsflow.intelligence.api_search import SearchRequest, SourceEvidence
from newsflow.intelligence.news_usage import safe_topic_script
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError
from newsflow.video.service import VideoError

new_api_pipeline = test_api_news_pipeline.api_pipeline


@pytest.fixture
def api_pipeline(new_api_pipeline, monkeypatch):
    """Model a saved pre-upgrade job, without the new paid-stage creation marker."""
    coordinator, _, _, sessions, _, _ = new_api_pipeline
    run = coordinator._run

    def legacy_run(identifier):
        with sessions.begin() as session:
            row = session.get(AutopilotJob, identifier)
            request = dict(row.stage_results["request"])
            request.pop("script_method", None)
            row.stage_results = {**row.stage_results, "request": request}
        run(identifier)

    monkeypatch.setattr(coordinator, "_run", legacy_run)
    return new_api_pipeline

LISTING = "https://www.cnbc.com/technology/"
ARTICLE = "https://www.cnbc.com/2026/10/17/technology-explainer.html"
UNVERIFIED_CLAIM = "오늘 신제품 매출이 9876억 원을 돌파했다고 대표가 발표했습니다."


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: pytest.fail("No live HTTP"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI or render processes"))


def search_fixture(pipeline, *, include_article=False):
    """Keep tool-observed URLs separate from unverified generated claims."""
    _, _, provider, _, mode, _ = pipeline
    original = provider.search(SearchRequest(), Options(model=MODELS[mode], max_tokens=3000))
    listing = original.articles[0].model_copy(update={
        "title": "[합성 테스트] Technology News 목록", "url": LISTING, "publisher": "www.cnbc.com",
        "claimed_title": "합성 모델 주장", "published_at": None, "eligible": False,
        "metadata_status": "needs_source_review", "summary": UNVERIFIED_CLAIM,
        "key_facts": [UNVERIFIED_CLAIM],
    })
    articles = [listing]
    if include_article:
        articles.append(listing.model_copy(update={
            "title": "[합성 테스트] 데이터 보관 방식 설명", "url": ARTICLE,
        }))
    provider.result = original.model_copy(update={
        "articles": articles,
        "tool_evidence": original.tool_evidence.model_copy(update={
            "sources": [SourceEvidence(url=article.url, title=article.title) for article in articles],
        }),
    })
    provider.calls.clear()


def settings_snapshot(sessions):
    with sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


@pytest.mark.parametrize("mode", [None, "QUICK", "STANDARD"])
@pytest.mark.parametrize("duration", [30, 45, 60])
def test_listing_is_topic_material_with_one_search_and_no_invented_script(api_pipeline, mode, duration):
    _, _, provider, sessions, selected_provider, rss = api_pipeline
    search_fixture(api_pipeline)
    before = settings_snapshot(sessions)
    changes = {"duration": duration, **({"news_usage": mode} if mode else {})}
    identifier = start(api_pipeline, **changes)
    job = settled(api_pipeline, identifier)
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    assert job["news_usage"] == (mode or "STANDARD")
    assert job["news_usage_result"]["source_kind"] == "listing"
    assert job["news_usage_result"]["verification_status"] == "NOT VERIFIED"
    assert job["news_usage_result"]["approach"] == "topic"
    assert job["ai_mode"] == job["search_provider"] == selected_provider
    assert job["analysis_provider"] == job["script_provider"] == "local_topic_template"
    assert job["script_method"] == "local_topic_template"
    assert job["review_pauses"] == ["script", "validate"]
    assert provider.calls == ["search"] and rss.calls == []
    with sessions() as session:
        article = session.get(NewsArticle, job["article_id"])
        assert article.url == LISTING and article.published_at is None
        draft = session.get(ContentDraft, job["content_draft_id"])
        assert draft.content == safe_topic_script(draft.sources, duration)
        assert draft.review_status == "review_required"
        assert "9876" not in str(draft.content) and UNVERIFIED_CLAIM not in str(draft.content)
        assert draft.sources["articles"][0]["sources"][0]["url"] == LISTING
        rows = list(session.scalars(select(APIRequestReservation)))
        assert len(rows) == 1 and rows[0].bounds["search_calls"] == 1
        assert rows[0].status == "success" and rows[0].test_only
    assert settings_snapshot(sessions) == before


@pytest.mark.parametrize("include_article", [False, True])
def test_verified_stops_even_for_individual_article_candidate_without_original_verification(api_pipeline, include_article):
    coordinator, _, provider, sessions, _, rss = api_pipeline
    search_fixture(api_pipeline, include_article=include_article)
    identifier = start(api_pipeline, news_usage="VERIFIED")
    job = settled(api_pipeline, identifier)
    assert job["status"] == "failed" and job["error_code"] == "news_evidence_required"
    assert job["news_usage"] == "VERIFIED" and job["retryable"] is False
    assert provider.calls == ["search"] and rss.calls == []
    with sessions() as session:
        runs = list(session.scalars(select(IntelligenceRun)))
        assert len(runs) == 1 and runs[0].kind == "search" and runs[0].status == "success"
        assert session.scalar(select(ContentDraft)) is None
        row = session.scalar(select(APIRequestReservation))
        assert row.status == "success" and row.bounds["search_calls"] == 1
    with pytest.raises(AutopilotConflict):
        coordinator.retry(identifier, job["revision"])
    assert provider.calls == ["search"]


def test_standard_prefers_individual_article_candidate_without_claiming_verified(api_pipeline):
    _, _, provider, sessions, _, rss = api_pipeline
    search_fixture(api_pipeline, include_article=True)
    identifier = start(api_pipeline, news_usage="STANDARD")
    job = settled(api_pipeline, identifier)
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script")
    with sessions() as session:
        chosen = session.get(NewsArticle, job["article_id"])
        assert chosen.url == ARTICLE and chosen.published_at is None
    assert job["news_usage_result"]["verification_status"] == "NOT VERIFIED"
    assert provider.calls == ["search"] and rss.calls == []


def test_news_usage_is_durable_and_recovery_never_repeats_search(api_pipeline):
    coordinator, backend, provider, sessions, _, rss = api_pipeline
    search_fixture(api_pipeline)
    identity = uuid4().hex
    start(api_pipeline, request_id=identity, news_usage="QUICK")
    job = settled(api_pipeline, identity)
    # Reusing an old request ID cannot upgrade its policy into new paid API stages.
    with pytest.raises(AutopilotConflict):
        start(api_pipeline, request_id=identity, news_usage="QUICK")
    with pytest.raises(AutopilotConflict):
        start(api_pipeline, request_id=identity, news_usage="STANDARD")
    assert coordinator.recover() == 0
    with sessions() as session:
        row = session.get(AutopilotJob, identity)
        assert row.stage_results["request"]["news_usage"] == "QUICK"
        context = coordinator._context(session, row)
    restored = backend.execute("collect", context, Event(), lambda *_: None, lambda *_: None)
    assert restored["search_run_id"] == job["search_run_id"]
    context.pop("content_draft_id")
    draft = backend.execute("script", context, Event(), lambda *_: None, lambda *_: None)
    assert draft["content_draft_id"] == job["content_draft_id"]
    assert coordinator.snapshot(identity)["news_usage"] == "QUICK"
    assert provider.calls == ["search"] and rss.calls == []


def test_unsupported_fact_edit_is_blocked_without_revising_draft_or_researching(api_pipeline):
    _, backend, provider, sessions, _, rss = api_pipeline
    search_fixture(api_pipeline)
    identifier = start(api_pipeline, news_usage="STANDARD")
    job = settled(api_pipeline, identifier)
    with sessions() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        original, revision = deepcopy(draft.content), draft.revision
    changed = deepcopy(original)
    changed["scenes"][0]["narration"] = UNVERIFIED_CLAIM
    with pytest.raises(IntelligenceError):
        backend.intelligence.edit(job["content_draft_id"], revision, changed)
    with sessions() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        assert draft.content == original and draft.revision == revision
        assert draft.review_status == "review_required"
    assert provider.calls == ["search"] and rss.calls == []


def test_tampered_draft_cannot_reach_voice_or_render(api_pipeline, monkeypatch):
    coordinator, backend, provider, sessions, _, rss = api_pipeline
    search_fixture(api_pipeline)
    identifier = start(api_pipeline, news_usage="QUICK")
    job = settled(api_pipeline, identifier)
    with sessions.begin() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        content = deepcopy(draft.content)
        content["scenes"][0]["narration"] = UNVERIFIED_CLAIM
        draft.content = content
    with sessions() as session:
        context = coordinator._context(session, session.get(AutopilotJob, identifier))
    rendered = []

    def unexpected_render(*_args, **_kwargs):
        rendered.append(True)
        pytest.fail("Unsupported facts must be blocked before voice/render")

    monkeypatch.setattr(backend.video, "start_preview", unexpected_render)
    with pytest.raises(BackendError) as failed:
        backend.execute("render", context, Event(), lambda *_: None, lambda *_: None)
    assert failed.value.code == "news_usage_script"
    assert rendered == [] and provider.calls == ["search"] and rss.calls == []


def test_previous_failure_reservation_and_settings_are_preserved(api_pipeline):
    _, backend, provider, sessions, mode, rss = api_pipeline
    search_fixture(api_pipeline)
    with sessions.begin() as session:
        session.add(APIRequestReservation(
            id="prior-failed", request_id="prior:failed-search", provider=mode, kind="search", model=MODELS[mode],
            status="failed", reserved_usd="3.055000", estimated_usd="0.059278",
            bounds={"prompt_tokens": 1000000, "completion_tokens": 3000, "search_calls": 1},
            prices={"input": "3", "output": "15", "search": "10"},
            usage={"prompt_tokens": 100, "completion_tokens": 100, "search_calls": 1}, test_only=True,
        ))
    before_settings = settings_snapshot(sessions)
    with sessions() as session:
        row = session.get(APIRequestReservation, "prior-failed")
        before_record = {column.name: deepcopy(getattr(row, column.name)) for column in row.__table__.columns}
    identifier = start(api_pipeline, news_usage="QUICK")
    assert settled(api_pipeline, identifier)["status"] == "waiting_review"
    with sessions() as session:
        row = session.get(APIRequestReservation, "prior-failed")
        assert {column.name: getattr(row, column.name) for column in row.__table__.columns} == before_record
        rows = list(session.scalars(select(APIRequestReservation)))
        assert len(rows) == 2 and all(row.bounds["search_calls"] == 1 for row in rows)
    assert settings_snapshot(sessions) == before_settings
    assert backend.intelligence.api_budget.test_only
    assert provider.calls == ["search"] and rss.calls == []


@pytest.mark.parametrize("mode", ["UNSAFE", "", True])
def test_invalid_news_usage_never_starts_search(api_pipeline, mode):
    _, _, provider, _, _, rss = api_pipeline
    with pytest.raises(AutopilotError):
        start(api_pipeline, news_usage=mode)
    assert provider.calls == [] and rss.calls == []


def test_legacy_context_without_news_usage_keeps_existing_selected_provider_flow(api_pipeline):
    _, backend, provider, sessions, mode, rss = api_pipeline
    stamp = utcnow().isoformat()
    context = {
        "job_id": uuid4().hex, "mode": "guided", "source": "feeds", "content_mode": "real",
        "duration": 30, "platform": "youtube", "ai_mode": mode, "ai_model": MODELS[mode],
        "voice": "offline-silence", "unified": True, "acquisition_policy": "ai_web",
        "category": "all", "period": "24h", "requested_at": stamp,
        "external_consent": True, "consented_at": stamp,
    }
    for stage in ("collect", "select", "script"):
        result = backend.execute(stage, context, Event(), lambda *_: None, context.__setitem__)
        context.update(result)
    assert provider.calls == ["search", "analysis", "script"] and rss.calls == []
    assert context["analysis_provider"] == context["script_provider"] == mode
    with sessions() as session:
        draft = session.get(ContentDraft, context["content_draft_id"])
        assert "news_usage" not in draft.sources
        assert draft.review_status == "review_required"
        assert session.get(IntelligenceRun, context["analysis_run_id"]).provider == mode
        assert session.get(IntelligenceRun, context["script_run_id"]).provider == mode


def test_standalone_video_start_rejects_malformed_topic_draft_before_render(api_pipeline):
    _, backend, provider, sessions, _, rss = api_pipeline
    search_fixture(api_pipeline)
    job = settled(api_pipeline, start(api_pipeline, news_usage="STANDARD"))
    with sessions.begin() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        content = deepcopy(draft.content)
        content["scenes"][0]["narration"] = UNVERIFIED_CLAIM
        draft.content = content
    with pytest.raises(VideoError, match="미확인 사실"):
        backend.video.start_preview(job["content_draft_id"], 30, voice="offline-silence")
    assert backend.video.future is None
    with sessions() as session:
        assert session.scalar(select(RenderJob)) is None
    assert provider.calls == ["search"] and rss.calls == []


def test_ai_studio_cannot_bypass_topic_policy_with_selected_external_provider(api_pipeline):
    _, backend, provider, sessions, mode, rss = api_pipeline
    search_fixture(api_pipeline)
    job = settled(api_pipeline, start(api_pipeline, news_usage="QUICK"))
    with sessions() as session:
        existing_ids = list(session.scalars(select(IntelligenceRun.id).order_by(IntelligenceRun.id)))
    with pytest.raises(IntelligenceError) as failed:
        backend.intelligence.generate(
            job["analysis_run_id"], 30, mode=mode, consent=True,
            options=Options(model=MODELS[mode], max_tokens=1800),
        )
    assert failed.value.code == "news_usage_blocked"
    with sessions() as session:
        assert list(session.scalars(select(IntelligenceRun.id).order_by(IntelligenceRun.id))) == existing_ids
    assert provider.calls == ["search"] and rss.calls == []
