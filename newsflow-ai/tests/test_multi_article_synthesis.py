"""Multi-article contracts: synthetic API/RSS fixtures, no supplier calls."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import select
from test_api_news_pipeline import api_pipeline as pipeline_fixture
from test_api_news_pipeline import settled, start
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.autopilot.contracts import BackendError
from newsflow.autopilot.synthesis import CLAIM_KIND, POLICY, choose_articles
from newsflow.db.models import (
    AutopilotArticleClaim,
    AutopilotArtifact,
    AutopilotJob,
    ContentDraft,
    NewsArticle,
    NewsSource,
    PublishDraft,
    RenderJob,
    VideoProject,
)
from newsflow.intelligence.api_search import SearchArticle, SearchResult, SourceEvidence, ToolEvidence
from newsflow.intelligence.provider import SCRIPT_INSTRUCTION, ProviderTimeoutError
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import PublishingService
from newsflow.video.engine import FakeRenderAdapter

api_pipeline = pipeline_fixture
TITLES = ["도시 태양광 발전 실증 사업 참여 6곳 발표", "도시 태양광 발전 실증 사업 참여 8곳 보도", "프로 야구 선수 이적 계약과 구단 운영 소식"]
SUMMARIES = ["자료는 실증 사업 참여 규모를 6곳으로 설명합니다. 합성 자료이며 서로 다른 보도의 차이를 확인하는 검증용입니다.",
             "자료는 실증 사업 참여 규모를 8곳으로 설명합니다. 합성 자료이며 다른 자료와 수치가 달라 원문 확인이 필요합니다.",
             "구단 선수 이적 내용을 다루는 별개의 합성 스포츠 자료입니다. 태양광 사업과는 관련 없는 내용입니다."]


@pytest.fixture
def grouped(api_pipeline, monkeypatch):
    _coordinator, _backend, provider, _sessions, mode, rss = api_pipeline
    when = datetime.now(UTC) - timedelta(hours=1)
    urls = [f"https://www.bbc.com/korean/articles/synthetic-synthesis-{i}" for i in range(3)]
    items = [f"<item><title>{t}</title><link>{u}</link><description>{s}</description><pubDate>{format_datetime(when)}</pubDate></item>"
             for t,u,s in zip(TITLES, urls, SUMMARIES)]
    rss.feeds["https://example.com/step3-rss"] = ("<rss version='2.0'><channel><title>합성</title>" + "".join(items) + "</channel></rss>").encode()
    provider.result = SearchResult(provider=mode, model="gpt-4.1-mini" if mode == "openai" else "claude-sonnet-4-6",
        searched_at=datetime.now(UTC), articles=[SearchArticle(title=t, claimed_title=t, url=u, publisher="합성 자료",
            summary=s, published_at=when, metadata_status="test_fixture", eligible=True,
            key_facts=["검증용 자료"], uncertainties=["사실 확인 미완료"]) for t,u,s in zip(TITLES, urls, SUMMARIES)],
        tool_evidence=ToolEvidence(tool_name="web_search" if mode == "openai" else "web_search_20250305",
            completed_tool_ids=["synthetic-1"], sources=[SourceEvidence(url=u, title=t) for u,t in zip(urls,TITLES)],
            provenance="test_fixture"), usage=provider.last_usage)
    original_analysis, original_script = provider.analyze, provider.complete
    recorded = []
    def analyze(evidence, options):
        result = original_analysis(evidence, options)
        chosen = next(a["id"] for a in evidence["articles"] if a["title"] == TITLES[0])
        return {**result, "recommended_article_id": chosen, "selection_reason": "두 합성 보도의 차이를 비교할 주제"}
    def complete(evidence, duration, options):
        recorded.append(deepcopy(evidence))
        result = original_script(evidence, duration, options)
        return {**result, "summary": "제공된 자료는 참여 규모를 다르게 설명합니다. 사실관계 확인이 필요합니다."}
    monkeypatch.setattr(provider, "analyze", analyze)
    monkeypatch.setattr(provider, "complete", complete)
    return api_pipeline, recorded


@pytest.mark.parametrize("policy", ["rss", "ai_web"])
@pytest.mark.parametrize("duration", [30, 45, 60])
def test_multiple_sources_one_script_preserved_and_recovered(grouped, policy, duration):
    pipeline, recorded = grouped
    coordinator, backend, provider, sessions, _mode, _ = pipeline
    identifier = start(pipeline, acquisition_policy=policy, duration=duration)
    job = settled(pipeline, identifier)
    assert (job["status"], job["current_stage"]) == ("waiting_review", "script"), job
    assert provider.calls == (["search"] if policy == "ai_web" else []) + ["analysis", "script"]
    assert len(recorded) == 1
    evidence = recorded[0]
    assert {a["title"] for a in evidence["articles"]} == set(TITLES[:2])
    assert {a["summary"] for a in evidence["articles"]} == set(SUMMARIES[:2])
    assert evidence["synthesis"]["facts_verified"] is False
    assert "다수결" in evidence["synthesis"]["instruction"]
    assert "never resolve a conflict" in SCRIPT_INSTRUCTION
    ids = set(job["stage_results"]["select"]["script_article_ids"])
    with sessions() as session:
        draft = session.get(ContentDraft, job["content_draft_id"])
        assert {a["id"] for a in draft.sources["articles"]} == ids
        assert sum(s["seconds"] for s in draft.content["scenes"]) == duration
        assert draft.review_status == "review_required"
        claims = list(session.scalars(select(AutopilotArtifact).where(AutopilotArtifact.job_id == identifier,
                                                                    AutopilotArtifact.kind == CLAIM_KIND)))
        assert {int(c.reference) for c in claims} == ids
        context = coordinator._context(session, session.get(AutopilotJob, identifier))
    context.pop("content_draft_id")
    assert backend.execute("script", context, Event(), lambda *_: None, lambda *_: None)["content_draft_id"] == draft.id
    assert len(recorded) == 1


def test_sources_survive_fake_render_and_queue(grouped):
    pipeline, _ = grouped
    coordinator, backend, _, sessions, _, _ = pipeline
    job = settled(pipeline, start(pipeline, acquisition_policy="rss"))
    backend.video.engine = FakeRenderAdapter()
    render_id = backend.video.start_preview(job["content_draft_id"], 30)
    backend.video.future.result(timeout=10)
    inspector = FakeMediaInspector()
    with sessions.begin() as session:
        render = session.get(RenderJob, render_id)
        render.status, render.metadata_json = "success", {**inspector.metadata, "fixture_only": True}
        assert len(session.get(VideoProject, render.project_id).sources["articles"]) == 2
        context = coordinator._context(session, session.get(AutopilotJob, job["id"]))
    context["render_job_id"] = render_id
    backend.inspector = inspector
    backend.publishing = PublishingService(sessions, backend.video.outputs, inspector)
    context.update(backend.execute("validate", context, Event(), lambda *_: None, lambda *_: None))
    result = backend.execute("queue", context, Event(), lambda *_: None, lambda *_: None)
    with sessions() as session:
        draft = session.get(PublishDraft, result["publish_draft_id"])
        assert len(draft.sources["articles"]) == 2 and draft.description.count("https://www.bbc.com/") == 2
        assert not draft.content_reviewed and not draft.sources_confirmed and draft.account_id is None


def test_forged_group_is_blocked_before_request(grouped):
    pipeline, recorded = grouped
    coordinator, backend, _, sessions, _, _ = pipeline
    job = settled(pipeline, start(pipeline, acquisition_policy="rss"))
    with sessions() as session:
        context = coordinator._context(session, session.get(AutopilotJob, job["id"]))
    for ids in ([context["article_id"]], [context["article_id"], 99999], [True], []):
        with pytest.raises(BackendError):
            backend.execute("script", {**context, "script_article_ids": ids}, Event(), lambda *_: None, lambda *_: None)
    assert len(recorded) == 1


def test_all_members_prevent_another_job_claim(grouped):
    pipeline, _ = grouped
    coordinator, _, _, sessions, _, _ = pipeline
    job = settled(pipeline, start(pipeline, acquisition_policy="rss"))
    other = AutopilotJob(id=uuid4().hex, mode="easy", source="feeds", duration=30, platform="youtube",
        active_slot=None, status="cancelled", current_stage="select", stage_results={"request": {"article_grouping": POLICY,
                                                                       "script_method": "api_grounded_v1"}})
    with sessions.begin() as session:
        session.add(other)
    for article_id in job["stage_results"]["select"]["script_article_ids"]:
        with pytest.raises(BackendError), coordinator._transaction() as session:
            coordinator._claim(session, session.get(AutopilotJob, other.id), article_id)


def test_old_unmarked_job_keeps_one_article(grouped, monkeypatch):
    pipeline, recorded = grouped
    coordinator, _, _, sessions, _, _ = pipeline
    run = coordinator._run
    def legacy(identifier):
        with sessions.begin() as session:
            job = session.get(AutopilotJob, identifier)
            request = dict(job.stage_results["request"])
            request.pop("article_grouping")
            job.stage_results = {**job.stage_results, "request": request}
        run(identifier)
    monkeypatch.setattr(coordinator, "_run", legacy)
    identifier = start(pipeline, acquisition_policy="rss")
    assert settled(pipeline, identifier)["status"] == "waiting_review"
    assert len(recorded[0]["articles"]) == 1 and "synthesis" not in recorded[0]
    assert start(pipeline, acquisition_policy="rss", request_id=identifier) == identifier
    with sessions() as session:
        assert "article_grouping" not in session.get(AutopilotJob, identifier).stage_results["request"]
    assert len(recorded) == 1


def test_grouped_timeout_is_not_replayed(grouped, monkeypatch):
    pipeline, _ = grouped
    coordinator, backend, provider, sessions, _, _ = pipeline
    def timeout(*_):
        provider.calls.append("script")
        raise ProviderTimeoutError()
    monkeypatch.setattr(provider, "complete", timeout)
    job = settled(pipeline, start(pipeline, acquisition_policy="rss"))
    assert job["status"] == "failed"
    with sessions() as session:
        context = coordinator._context(session, session.get(AutopilotJob, job["id"]))
    assert not backend.can_retry("script", context)
    with pytest.raises(BackendError):
        backend.execute("script", context, Event(), lambda *_: None, lambda *_: None)
    assert provider.calls == ["analysis", "script"]


def test_groups_are_bounded_and_exclude_category_or_old_events():
    now = datetime.now(UTC)
    articles = [{"id": i, "title": f"도시 태양광 발전 실증 사업 참여 {i}곳 발표", "category": "사회",
                 "published_at": now.isoformat()} for i in range(1, 10)]
    articles[1]["category"] = "스포츠"
    articles[2]["published_at"] = (now - timedelta(days=5)).isoformat()
    result = choose_articles({"articles": articles, "groups": [list(range(1,10))]}, 1)
    assert result == [1, 4, 5, 6, 7]
    assert choose_articles({"articles": articles, "groups": [[1], list(range(2,10))]}, 1) == [1]


def test_competing_group_claims_are_atomic(app):
    coordinator = app.state.autopilot
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource))
        articles = [NewsArticle(title=f"합성 경합 기사 {i}", url=f"https://example.com/race/{i}",
                               canonical_url=f"https://example.com/race/{i}", source_id=source.id, publisher="합성") for i in range(3)]
        jobs = [AutopilotJob(id=uuid4().hex, mode="easy", source="feeds", duration=30, platform="youtube",
            active_slot=None, status="cancelled", current_stage="select", stage_results={"request": {
                "article_grouping": POLICY, "script_method": "api_grounded_v1"}}) for _ in range(2)]
        session.add_all([*articles, *jobs])
        session.flush()
        ids, job_ids = [a.id for a in articles], [j.id for j in jobs]
    def claim(index):
        try:
            with coordinator._transaction() as session:
                job = session.get(AutopilotJob, job_ids[index])
                coordinator._claim(session, job, ids[index])
                coordinator._claim_sources(session, job, {"script_article_ids": [ids[index], ids[2]], "candidate_article_ids": ids})
            return "claimed"
        except BackendError:
            return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(claim, range(2))) == ["blocked", "claimed"]
    with app.state.sessions() as session:
        primary = list(session.scalars(select(AutopilotArticleClaim)))
        group = list(session.scalars(select(AutopilotArtifact).where(AutopilotArtifact.kind == CLAIM_KIND)))
        assert len(primary) == 1 and len(group) == 2
        assert {item.job_id for item in group} == {primary[0].job_id}

