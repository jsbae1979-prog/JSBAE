"""Stored top-three -> editable feeds, no live inference or publishing."""
from copy import deepcopy

import pytest
from conftest import csrf
from sqlalchemy import func, select
from test_image_posts import deny_live

from newsflow.db.models import (
    ContentDraft,
    ImagePost,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
)
from newsflow.news.lifecycle import used_article_ids
from newsflow.publishing.service import PublishingError

__all__ = ["deny_live"]


@pytest.fixture
def selected(app, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No inference, OAuth, media rendering or publishing")
    monkeypatch.setattr("newsflow.intelligence.service.IntelligenceService.analyze", forbidden)
    monkeypatch.setattr("newsflow.intelligence.service.IntelligenceService.generate", forbidden)
    monkeypatch.setattr("newsflow.oauth.instagram.InstagramConnectionService.access_for_upload", forbidden)
    with app.state.sessions.begin() as session:
        source = NewsSource(name="합성 출처", url="https://example.com/feed", enabled=False)
        session.add(source)
        session.flush()
        ids, evidence = [], []
        for number in range(4):
            article = NewsArticle(source_id=source.id, title=f"합성 주제 {number}",
                url=f"https://example.com/news/{number}", canonical_url=f"https://example.com/news/{number}",
                publisher=f"합성 출처 {number}", summary=f"기존 자료 {number}", published_at=None)
            session.add(article)
            session.flush()
            ids.append(article.id)
            evidence.append({"id": article.id, "title": article.title, "summary": article.summary,
                "published_at": "2026-10-20T01:00:00+00:00" if number == 0 else None,
                "sources": [{"url": article.url, "publisher": article.publisher}]})
        groups = [ids[:2], ids[2:3], ids[3:4]]
        analysis = IntelligenceRun(kind="analysis", status="success", provider="claude_api",
            options={"model": "fixture"}, message="synthetic",
            evidence={"curation_contract": {"top_k": 3}, "articles": evidence},
            result={"ranking": [{"rank": rank, "article_ids": group, "title": f"주제 {rank}",
                                "summary": f"저장된 평가 요약 {rank}", "score": 90-rank}
                               for rank, group in enumerate(groups, 1)]})
        session.add(analysis)
        session.flush()
        script = IntelligenceRun(kind="script", status="success", provider="claude_api",
            options={"analysis_run_id": analysis.id, "selected_article_ids": groups[0]},
            evidence={}, result={}, message="synthetic")
        session.add(script)
        session.flush()
        draft = ContentDraft(run_id=script.id, duration=30, content={
            "title": "기존 릴스 대본 제목", "scenes": [{"narration": "저장한 릴스 대본입니다."}]},
            sources={"articles": evidence[:2]})
        session.add(draft)
        session.flush()
        return analysis.id, ids, draft.id


def test_three_feed_previews_read_only_and_pinned_to_analysis(app, client, selected):
    analysis_id, _ids, draft_id = selected
    for _ in range(2):
        page = client.get(f"/image-posts/selection?analysis_id={analysis_id}")
        assert page.status_code == 200
        assert page.text.count('class="card feed-selection-item"') == 3
        assert "기존 릴스 대본 제목" in page.text and "저장한 릴스 대본입니다." in page.text
        assert "저장된 평가 요약 2" in page.text and "저장된 평가 요약 3" in page.text
        assert "다른 후보 2" in page.text and "대본 미생성" in page.text
        assert "2026-10-20T01:00:00+00:00" in page.text and "발행: 미확인" in page.text
    editor = client.get(f"/image-posts?analysis_id={analysis_id}&rank=1")
    assert f'name="draft_id" value="{draft_id}"' in editor.text
    assert "체크" not in editor.text
    assert 'name="reviewed" value="true" required' in editor.text
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(IntelligenceRun)) == 2
        assert session.scalar(select(func.count()).select_from(ImagePost)) == 0
        assert not used_article_ids(session)
    # Top-three feeds remain available inside image creation, without a third
    # duplicate creation choice on the dashboard.
    assert '/image-posts/selection' in client.get('/image-posts').text
    assert '/image-posts/selection' not in client.get('/').text


def test_save_three_feeds_preserves_sources_and_original_runs(app, client, selected):
    analysis_id, ids, draft_id = selected
    group = app.state.image_posts.selection(analysis_id)
    with app.state.sessions() as session:
        original = deepcopy(session.get(IntelligenceRun, analysis_id).result)
        original_script = deepcopy(session.get(ContentDraft, draft_id).content)
    for item in group["items"]:
        data = {"csrf_token": csrf(client), "article_id": item["article_id"],
                "analysis_id": analysis_id, "rank": item["rank"],
                "title": item["title"], "body": item["body"], "reviewed": "true",
                "sources_confirmed": "true", "rights": "true", "ai_disclosure": "not_required"}
        if item["draft"]:
            data["draft_id"] = item["draft"].id
        response = client.post("/image-posts/create", data=data)
        assert response.status_code == 200 and "다음 후보 만들기" in response.text
    with app.state.sessions() as session:
        posts = list(session.scalars(select(ImagePost).order_by(ImagePost.id)))
        assert len(posts) == 3
        assert [p.sources["selection"]["rank"] for p in posts] == [1, 2, 3]
        assert "https://example.com/news/1" in posts[0].caption
        assert posts[0].sources["selection"]["draft_id"] == draft_id
        assert set(ids).issubset(used_article_ids(session))
        assert session.get(IntelligenceRun, analysis_id).result == original
        assert session.get(ContentDraft, draft_id).content == original_script
    page = client.get(f"/image-posts/selection?analysis_id={analysis_id}").text
    assert page.count("저장한 피드 확인") == 3
    assert page.count("새 버전 편집") == 3


@pytest.mark.parametrize("change", ["failed", "missing", "overlap", "unknown_source"])
def test_incomplete_or_unlinked_selection_blocks_without_fallback(app, selected, change):
    analysis_id, ids, _ = selected
    with app.state.sessions.begin() as session:
        run = session.get(IntelligenceRun, analysis_id)
        if change == "failed":
            run.status = "failed"
        else:
            result = deepcopy(run.result)
            if change == "missing":
                result["ranking"].pop()
            elif change == "overlap":
                result["ranking"][1]["article_ids"] = [ids[0]]
            else:
                result["ranking"][2]["article_ids"] = [99999]
            run.result = result
    with pytest.raises(PublishingError):
        app.state.image_posts.selection(analysis_id)


def test_tampered_selection_and_unreviewed_save_rejected(app, client, selected):
    analysis_id, ids, draft_id = selected
    data = {"csrf_token": csrf(client), "article_id": ids[0], "analysis_id": analysis_id,
            "rank": 2, "draft_id": draft_id, "title": "제목", "body": "본문",
            "reviewed": "true", "sources_confirmed": "true", "rights": "true",
            "ai_disclosure": "not_required"}
    assert client.post("/image-posts/create", data=data).status_code == 422
    data["rank"] = 1
    data.pop("reviewed")
    assert client.post("/image-posts/create", data=data).status_code == 422
    assert not app.state.image_posts.recent()


def test_empty_selection_guides_to_existing_results_without_network(client):
    page = client.get("/image-posts/selection")
    assert page.status_code == 200 and "재평가는 자동 실행하지 않습니다" in page.text
