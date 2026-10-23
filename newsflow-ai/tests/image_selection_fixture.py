import pytest

from newsflow.db.models import ContentDraft, IntelligenceRun, NewsArticle, NewsSource


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
