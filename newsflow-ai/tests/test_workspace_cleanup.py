"""Collection replacement, archived sources, reversible removal; no live network or media render."""

from conftest import csrf
from sqlalchemy import select
from test_google_news_trends import no_external_calls
from test_single_workspace import video_fixture

from newsflow.db.models import (
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsListState,
    NewsSource,
    VideoProject,
    WorkspaceRemoval,
)
from newsflow.news.collector import CollectedArticle
from newsflow.news.lifecycle import replace_collection, used_article_ids, visible_news
from newsflow.news.service import NewsService

__all__ = ["no_external_calls"]


def articles(app):
    with app.state.sessions.begin() as session:
        source = NewsSource(name="Fixture", url="https://example.com/cleanup", enabled=False)
        session.add(source)
        session.flush()
        ids = []
        for i in range(3):
            row = NewsArticle(source_id=source.id, title=f"Synthetic topic {i}", summary="Stored summary",
                              url=f"https://example.com/cleanup/{i}", canonical_url=f"https://example.com/cleanup/{i}",
                              publisher="Fixture")
            session.add(row)
            session.flush()
            ids.append(row.id)
        return ids


def test_replace_collection_deletes_unused_hides_used_sources_and_reactivates(app, client):
    old, used, new = articles(app)
    fixture = video_fixture(app, "Archive fixture")
    with app.state.sessions.begin() as session:
        project = session.get(VideoProject, fixture["project_id"])
        project.sources = {"articles": [{"id": used, "title": "Used source"}]}
        replace_collection(session, [new])
    with app.state.sessions() as session:
        assert set(session.scalars(select(NewsArticle.id).where(visible_news()))) == {new}
        assert used_article_ids(session) == {used}
        # The unused old article is deleted; the video source row is kept but hidden.
        assert set(session.scalars(select(NewsArticle.id))) == {used, new}
        assert session.get(NewsArticle, old) is None and session.get(NewsListState, old) is None
        assert session.get(NewsArticle, used).summary == "Stored summary"
        assert session.get(NewsListState, used).hidden and session.get(NewsListState, used).used
    assert "Synthetic topic 2" in client.get("/news").text
    assert "Synthetic topic 1" not in client.get("/news").text
    assert "Synthetic topic 1" in client.get("/news?view=used").text
    with app.state.sessions.begin() as session:
        replace_collection(session, [used])
        assert session.get(NewsListState, used).used and not session.get(NewsListState, used).hidden
        assert session.get(NewsArticle, new) is None
    assert "Synthetic topic 1" in client.get("/").text
    assert "Synthetic topic 2" not in client.get("/dashboard/news").text


def test_replace_collection_keeps_articles_referenced_by_drafts_images_and_autopilot(app):
    from newsflow.db.models import ArticleThumbnail, AutopilotJob, ImagePost

    draft_ref, image_ref, autopilot_ref = articles(app)
    with app.state.sessions.begin() as session:
        source_id = session.get(NewsArticle, draft_ref).source_id
        removed, current = (NewsArticle(source_id=source_id, title=f"Synthetic extra {i}", summary="Stored summary",
                                        url=f"https://example.com/cleanup/x{i}",
                                        canonical_url=f"https://example.com/cleanup/x{i}", publisher="Fixture")
                            for i in range(2))
        session.add_all([removed, current])
        session.flush()
        removed, current = removed.id, current.id
        session.add(ArticleThumbnail(article_id=removed, url="https://images.example.org/x.png",
                                     source_article_url="https://example.com/cleanup/x0", publisher="Fixture"))
        run = IntelligenceRun(kind="script", status="success", provider="offline", options={}, evidence={},
                              result={}, message="")
        session.add(run)
        session.flush()
        session.add(ContentDraft(run_id=run.id, duration=30, content={},
                                 sources={"articles": [{"article_id": draft_ref}]}))
        session.add(ImagePost(article_id=image_ref, title="t", caption="c", sources={}, filename="synthetic.jpg",
                              sha256="0" * 64, ai_disclosure="none"))
        session.add(AutopilotJob(id="d" * 32, mode="guided", source="sample", duration=30, platform="youtube",
                                 status="failed", current_stage="script", article_id=autopilot_ref))
    with app.state.sessions.begin() as session:
        replace_collection(session, [current])
    with app.state.sessions() as session:
        assert set(session.scalars(select(NewsArticle.id))) == {draft_ref, image_ref, autopilot_ref, current}
        assert set(session.scalars(select(NewsArticle.id).where(visible_news()))) == {current}
        assert session.get(ArticleThumbnail, removed) is None


def test_empty_collection_does_not_clear_existing(app):
    ids = articles(app)
    with app.state.sessions.begin() as session:
        replace_collection(session, [])
    with app.state.sessions() as session:
        assert set(session.scalars(select(NewsArticle.id).where(visible_news()))) == set(ids)


def test_rss_success_replaces_list_but_failure_hides_previous_round_and_keeps_originals(app):
    from newsflow.db.models import CollectionRun

    ids = articles(app)
    with app.state.sessions.begin() as session:
        source = session.get(NewsSource, 1)
        source.enabled = True
        run = CollectionRun()
        session.add(run)
        session.flush()
        run_id = run.id
    class Collector:
        def collect(self, *_args):
            return [CollectedArticle("New distinct discovery", "https://example.com/fresh", "Fixture", "Fresh", None)]
    service = NewsService(app.state.sessions, Collector())
    result = service.collect(run_id)
    with app.state.sessions() as session:
        assert list(session.scalars(select(NewsArticle.id).where(visible_news()))) == result["article_ids"]
        # Unreferenced articles from the earlier collection are deleted on a successful replace.
        assert not any(session.get(NewsArticle, i) for i in ids)
    class Failed:
        def collect(self, *_args):
            raise RuntimeError("Do not log raw transport text")
    service.collector = Failed()
    service.collect(run_id)
    with app.state.sessions() as session:
        assert list(session.scalars(select(NewsArticle.id).where(visible_news()))) == []
        assert all(session.get(NewsArticle, identifier) is not None for identifier in result["article_ids"])


def test_video_delete_and_restore_preserve_bytes_and_sources(client, app):
    ids = articles(app)
    fixture = video_fixture(app, "Video to remove")
    with app.state.sessions.begin() as session:
        session.get(VideoProject, fixture["project_id"]).sources = {"articles": [{"id": ids[1]}]}
    path = app.state.video.outputs / fixture["output_name"]
    original = path.read_bytes()
    url = f"/workspace/videos/{fixture['id']}/remove"
    assert client.post(url, data={"csrf_token": csrf(client)}, follow_redirects=False).status_code == 422
    assert path.read_bytes() == original
    response = client.post(url, data={"csrf_token": csrf(client), "confirm": "true"}, follow_redirects=False)
    assert response.status_code == 303
    assert not path.exists()
    assert (app.state.video.root / "trash/videos" / path.name).read_bytes() == original
    assert client.get(f"/video/jobs/{fixture['id']}/file").status_code == 404
    assert "Video to remove" not in client.get("/videos").text
    assert "Video to remove" in client.get("/workspace/trash").text
    with app.state.sessions() as session:
        assert session.get(NewsListState, ids[1]).used
        assert session.get(ContentDraft, fixture["draft_id"])
    assert client.post(url, data={"csrf_token": csrf(client), "confirm": "true"}, follow_redirects=False).status_code == 303
    response = client.post("/workspace/trash/restore", data={"csrf_token": csrf(client), "confirm": "true",
                                                            "item": f"video:{fixture['id']}"}, follow_redirects=False)
    assert response.status_code == 303 and path.read_bytes() == original


def test_activity_delete_hides_card_not_draft_or_api_history(client, app):
    fixture = video_fixture(app, "Activity fixture", status="failed", exists=False)
    token = csrf(client)
    item = f"draft:{fixture['draft_id']}"
    assert client.post("/workspace/activity/remove", data={"csrf_token": token, "item": item,
                                                         "confirm": "true"}, follow_redirects=False).status_code == 303
    assert "Activity fixture" not in client.get("/").text
    with app.state.sessions() as session:
        assert session.get(ContentDraft, fixture["draft_id"])
        assert session.scalar(select(IntelligenceRun))
        assert session.get(WorkspaceRemoval, "activity:" + item)
    assert client.post("/workspace/trash/restore", data={"csrf_token": token, "confirm": "true",
                                                         "item": "activity:" + item}, follow_redirects=False).status_code == 303


def test_running_activity_and_missing_csrf_cannot_remove(client, app):
    fixture = video_fixture(app, "Running fixture", status="running")
    item = f"draft:{fixture['draft_id']}"
    assert client.post("/workspace/activity/remove", data={"item": item, "confirm": "true"}).status_code == 403
    assert client.post("/workspace/activity/remove", data={"csrf_token": csrf(client), "item": item,
                                                         "confirm": "true"}).status_code == 409
    assert client.post(f"/workspace/videos/{fixture['id']}/remove", data={"csrf_token": csrf(client),
                       "confirm": "true"}).status_code == 409


def test_compact_collection_ui_names_both_sources_and_preserves_consent(client):
    html = client.get("/news").text
    assert "Google News + Trends 수집" in html and "Google News 수집 1회" not in html
    assert "collection-status-grid" in html and "영상에 사용한 뉴스" in html
    assert 'name="consent" value="true" required' in html and 'name="maximum_requests" value="5"' in html
    assert 'name="consent" value="true" checked' not in html


def test_publish_link_blocks_video_removal(client, app):
    from newsflow.db.models import PublishDraft

    fixture = video_fixture(app, "Publication fixture")
    with app.state.sessions.begin() as session:
        session.add(PublishDraft(render_job_id=fixture["id"], platform="youtube", title="Fixture",
                    description="Fixture", hashtags=[], sources={}, media_sha256="0" * 64))
    response = client.post(f"/workspace/videos/{fixture['id']}/remove", data={"csrf_token": csrf(client),
                           "confirm": "true"})
    assert response.status_code == 409
    assert (app.state.video.outputs / fixture["output_name"]).is_file()
    with app.state.sessions() as session:
        assert session.get(WorkspaceRemoval, f"video:{fixture['id']}") is None


def test_failed_move_keeps_original_and_unknown_journal_without_replay(client, app, monkeypatch):
    from pathlib import Path

    fixture = video_fixture(app, "Move failure fixture")
    path = app.state.video.outputs / fixture["output_name"]
    original = path.read_bytes()
    def fail(*_args):
        raise OSError("Synthetic file in use")
    monkeypatch.setattr(Path, "rename", fail)
    data = {"csrf_token": csrf(client), "confirm": "true"}
    response = client.post(f"/workspace/videos/{fixture['id']}/remove", data=data)
    assert response.status_code == 409 and path.read_bytes() == original
    with app.state.sessions() as session:
        assert session.get(WorkspaceRemoval, f"video:{fixture['id']}").detail["state"] == "pending"
    assert client.post(f"/workspace/videos/{fixture['id']}/remove", data=data, follow_redirects=False).status_code == 303
    assert path.read_bytes() == original


def test_restore_rejects_tampered_mp4(client, app):
    fixture = video_fixture(app, "Tamper fixture")
    token = csrf(client)
    client.post(f"/workspace/videos/{fixture['id']}/remove", data={"csrf_token": token, "confirm": "true"})
    path = app.state.video.root / "trash/videos" / fixture["output_name"]
    path.write_bytes(b"altered synthetic file")
    response = client.post("/workspace/trash/restore", data={"csrf_token": token, "confirm": "true",
                           "item": f"video:{fixture['id']}"})
    assert response.status_code == 409 and path.is_file()
