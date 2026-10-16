"""Easy UI HTTP flows with synthetic news; browser/real MP4 checks run separately."""

from __future__ import annotations

from uuid import uuid4

import pytest
from conftest import csrf
from sqlalchemy import func, select

from newsflow.autopilot.contracts import BackendError
from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.db.models import (
    AppSetting,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    PublishDraft,
    RenderJob,
)
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import PublishingService
from newsflow.video.engine import FakeRenderAdapter


def start_guided(client, app):
    response = client.post(
        "/autopilot/start", data={"csrf_token": csrf(client), "mode": "guided"}, follow_redirects=False,
    )
    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[1]
    app.state.autopilot.future.result(timeout=15)
    return job_id, app.state.autopilot.snapshot(job_id)


@pytest.mark.parametrize("path,title", [
    ("/", "오늘은 어떤 뉴스를 만들까요?"),
    ("/autopilot/start", "뉴스 영상 만들기"),
    ("/autopilot/jobs", "작업 현황"),
    ("/queue", "게시 대기함"),
    ("/simple-settings", "제작 단계별 연결 상태"),
    ("/dashboard", "뉴스 흐름을 한눈에"),
])
def test_easy_and_advanced_pages_keep_security_headers(client, path, title):
    response = client.get(path)
    assert response.status_code == 200 and title in response.text
    assert 'href="/simple-settings"' in response.text
    assert 'aria-label="주 메뉴"' in response.text
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert 'href="#main-content"' in response.text
    assert '<script src="/static/js/autopilot.js" defer>' in response.text


def test_easy_default_one_click_stops_with_actionable_real_render_failure(client, app, monkeypatch):
    execute = app.state.autopilot.backend.execute

    def fail_render(stage, *args, **kwargs):
        if stage == "render":
            raise BackendError("DO-NOT-EXPOSE-provider-secret", code="render_unavailable")
        return execute(stage, *args, **kwargs)

    monkeypatch.setattr(app.state.autopilot.backend, "execute", fail_render)
    response = client.post("/autopilot/start", data={"csrf_token": csrf(client)}, follow_redirects=False)
    app.state.autopilot.future.result(timeout=15)
    job_id = response.headers["location"].rsplit("/", 1)[1]
    data = client.get(f"/api/autopilot/jobs/{job_id}").json()
    assert (data["mode"], data["source"], data["duration"], data["platform"]) == ("easy", "sample", 30, "youtube")
    assert data["status"] == "failed" and data["current_stage"] == "render"
    screen = client.get(response.headers["location"])
    assert screen.status_code == 200
    assert 'id="error-title"' in screen.text and "이렇게 해 보세요" in screen.text
    assert "DO-NOT-EXPOSE" not in screen.text and "DO-NOT-EXPOSE" not in str(data)
    assert "대본 수정" in screen.text
    assert 'class="video-preview"' not in screen.text
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublishDraft)) == 0
        assert session.get(ContentDraft, data["content_draft_id"]).review_status == "review_required"


def test_guided_selection_changes_news_then_script_and_cancel_preserves_artifacts(client, app):
    job_id, selected = start_guided(client, app)
    assert selected["status"] == "waiting_review" and selected["current_stage"] == "select"
    page = client.get(f"/autopilot/jobs/{job_id}").text
    assert "이 뉴스로 만들어 볼까요?" in page and 'name="article_id"' in page
    changed = next(a["id"] for a in selected["candidates"] if a["id"] != selected["article_id"])
    response = client.post(f"/autopilot/jobs/{job_id}/resume", data={
        "csrf_token": csrf(client), "revision": selected["revision"], "article_id": changed,
    }, follow_redirects=False)
    assert response.status_code == 303
    app.state.autopilot.future.result(timeout=15)
    script = client.get(f"/api/autopilot/jobs/{job_id}").json()
    assert script["status"] == "waiting_review" and script["current_stage"] == "script"
    assert script["article_id"] == changed
    screen = client.get(f"/autopilot/jobs/{job_id}").text
    assert f'/ai?draft_id={script["content_draft_id"]}' in screen
    assert "게시 승인이나 저작권 확인으로 기록되지 않습니다" in screen
    stopped = client.post(f"/autopilot/jobs/{job_id}/cancel", data={
        "csrf_token": csrf(client), "revision": script["revision"],
    })
    assert stopped.status_code == 200 and "제작을 취소했습니다" in stopped.text
    cancelled = app.state.autopilot.snapshot(job_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["content_draft_id"] == script["content_draft_id"]
    with app.state.sessions() as session:
        assert session.get(ContentDraft, script["content_draft_id"]).review_status == "review_required"


def test_stale_revision_and_duplicate_start_have_no_new_task_or_script(client, app):
    job_id, selected = start_guided(client, app)
    duplicate = client.post("/autopilot/start", data={"csrf_token": csrf(client)})
    assert duplicate.status_code == 409
    stale = client.post(f"/autopilot/jobs/{job_id}/resume", data={
        "csrf_token": csrf(client), "revision": selected["revision"] + 100,
    })
    assert stale.status_code == 409
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 1
        assert session.scalar(select(func.count()).select_from(ContentDraft)) == 0


@pytest.mark.parametrize("origin,token", [
    ("http://127.0.0.1", False), ("https://attacker.example", True), ("null", True),
])
def test_easy_start_rejects_csrf_and_foreign_origin(client, app, origin, token):
    data = {"csrf_token": csrf(client)} if token else {}
    assert client.post("/autopilot/start", data=data, headers={"Origin": origin}).status_code == 403
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 0


@pytest.mark.parametrize("field,value", [
    ("duration", "31"), ("platform", "external"), ("source", "http://127.0.0.1"), ("mode", "automatic-publish"),
])
def test_invalid_simple_settings_are_atomic(client, app, field, value):
    data = {"duration": "45", "platform": "youtube", "source": "sample", "mode": "easy", field: value}
    response = client.post("/simple-settings", data={**data, "csrf_token": csrf(client)})
    assert response.status_code == 422
    with app.state.sessions() as session:
        assert not session.scalar(select(AppSetting).where(AppSetting.key.startswith("autopilot_")))


def test_saved_simple_defaults_are_applied_by_home_button_and_remain_local(client, app):
    data = {"duration": "45", "platform": "instagram", "source": "sample", "mode": "guided"}
    response = client.post("/simple-settings", data={**data, "csrf_token": csrf(client)})
    assert response.status_code == 200 and "제작 구성을 저장했습니다" in response.text
    home = client.get("/").text
    assert 'value="45" selected' in home and 'value="sample" selected' in home
    # Detailed defaults remain in the advanced setup, while the home shows two choices.
    advanced = client.get("/autopilot/start?advanced=true").text
    assert 'value="guided" selected' in advanced and 'value="instagram" selected' in advanced
    started = client.post("/autopilot/start", data={"csrf_token": csrf(client)}, follow_redirects=False)
    app.state.autopilot.future.result(timeout=15)
    job_id = started.headers["location"].rsplit("/", 1)[1]
    job = app.state.autopilot.snapshot(job_id)
    assert (job["mode"], job["duration"], job["platform"]) == ("guided", 45, "instagram")
    assert job["status"] == "waiting_review"
    with app.state.sessions() as session:
        assert session.get(AppSetting, "autopilot_duration").value == "45"


def test_corrupt_saved_settings_fall_back_to_offline_defaults(client, app):
    with app.state.sessions.begin() as session:
        session.add_all([AppSetting(key="autopilot_" + name, value="invalid") for name in (
            "duration", "platform", "source", "mode",
        )])
    response = client.get("/")
    assert response.status_code == 200
    assert 'value="30" selected' in response.text and 'value="sample" selected' in response.text
    advanced = client.get("/autopilot/start?advanced=true").text
    assert 'value="easy" selected' in advanced and 'value="youtube" selected' in advanced


def test_user_news_titles_are_escaped_and_source_count_excludes_sample(client, app):
    with app.state.sessions.begin() as session:
        sample = NewsSource(name="Synthetic", url=SAMPLE_URL, enabled=True)
        session.add(sample)
        session.flush()
        article = NewsArticle(
            title='<script>alert("title")</script>', url="https://example.com/escaped", canonical_url="https://example.com/escaped",
            publisher="<b>출처</b>", source_id=sample.id,
        )
        session.add(article)
        session.flush()
        article_id = article.id
        # Stored text is untrusted on task cards as well as the legacy article page.
        run = IntelligenceRun(kind="script", status="success", provider="offline", options={"model": "offline"},
                              evidence={"articles": []}, result={}, message="UI escaping fixture")
        session.add(run)
        session.flush()
        session.add(ContentDraft(run_id=run.id, duration=30, content={"title": article.title, "scenes": []},
                                 sources={"articles": []}))
    response = client.get(f"/news/{article_id}")
    assert "&lt;script&gt;" in response.text and "&lt;b&gt;출처&lt;/b&gt;" in response.text
    assert '<script>alert("title")</script>' not in response.text
    for path in ("/", "/autopilot/jobs"):
        task_page = client.get(path).text
        assert "&lt;script&gt;" in task_page and '<script>alert("title")</script>' not in task_page
    assert client.get("/autopilot/start").context["enabled_sources"] == 0


def test_fake_render_cannot_appear_as_completed_video(client, app):
    job_id, selected = start_guided(client, app)
    client.post(f"/autopilot/jobs/{job_id}/resume", data={"csrf_token": csrf(client), "revision": selected["revision"]})
    app.state.autopilot.future.result(timeout=15)
    script = app.state.autopilot.snapshot(job_id)
    app.state.video.engine = FakeRenderAdapter()
    render_id = app.state.video.start(script["content_draft_id"], 30, reviewed=True)
    app.state.video.future.result(timeout=15)
    with app.state.sessions() as session:
        assert session.get(RenderJob, render_id).status == "simulated"
    assert "완성한 영상이 여기에 모입니다" in client.get("/").text
    assert client.get(f"/video/jobs/{render_id}/file").status_code == 404


def test_queue_synthetic_media_fixture_detects_file_change_and_keeps_human_review(client, app):
    # Explicit fake bytes and metadata exercise queue presentation, not MP4 validity.
    job_id, selected = start_guided(client, app)
    client.post(f"/autopilot/jobs/{job_id}/resume", data={"csrf_token": csrf(client), "revision": selected["revision"]})
    app.state.autopilot.future.result(timeout=15)
    script = app.state.autopilot.snapshot(job_id)
    app.state.video.engine = FakeRenderAdapter()
    render_id = app.state.video.start(script["content_draft_id"], 30, reviewed=True)
    app.state.video.future.result(timeout=15)
    with app.state.sessions.begin() as session:
        render = session.get(RenderJob, render_id)
        render.status = "success"
        render.metadata_json = {"playable": True, "adapter": "ui-synthetic-fixture"}
        output = app.state.video.outputs / render.output_name
    service = PublishingService(app.state.sessions, app.state.video.outputs, FakeMediaInspector())
    draft_id = service.create(render_id, "youtube", "합성 초안", "연습용", "", ai_disclosure="unreviewed")
    page = client.get("/queue")
    assert page.status_code == 200 and f'id="draft-{draft_id}"' in page.text
    assert "SNS에 전송되거나 게시되지 않습니다" in page.text
    assert "내용 확인 필요" in page.text and "권리 확인 필요" in page.text
    assert 'class="queue-video"' in page.text
    output.write_bytes(b"CHANGED-SYNTHETIC-FILE")
    changed = client.get("/queue")
    assert "영상 파일을 다시 확인해 주세요" in changed.text
    assert 'class="queue-video"' not in changed.text


@pytest.mark.parametrize("path", [
    "/autopilot/jobs/not-a-task", "/api/autopilot/jobs/not-a-task", f"/autopilot/jobs/{uuid4().hex}",
])
def test_missing_or_malformed_task_is_not_found(client, path):
    assert client.get(path).status_code == 404
