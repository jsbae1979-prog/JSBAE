"""Single workspace contracts; synthetic records and bytes, no real API or media claim."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from conftest import csrf
from sqlalchemy import func, select

from newsflow.db.models import (
    AppSetting,
    AutopilotArtifact,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    RenderJob,
    Scene,
    VideoProject,
)
from newsflow.intelligence.provider import FakeProvider
from newsflow.intelligence.settings import write_studio_settings
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS


@pytest.fixture(autouse=True)
def isolated_voice_catalog(monkeypatch):
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: [])


def stored_values(app):
    with app.state.sessions() as session:
        return dict(session.execute(select(AppSetting.key, AppSetting.value)).all())


def save_values(app, **values):
    with app.state.sessions.begin() as session:
        for key, value in values.items():
            row = session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))


def draft_fixture(app, title):
    with app.state.sessions.begin() as session:
        run = IntelligenceRun(kind="script", status="success", provider="offline",
                              options={"model": "offline"}, evidence={"articles": []}, result={}, message="합성 fixture")
        session.add(run)
        session.flush()
        draft = ContentDraft(run_id=run.id, duration=45, sources={"articles": []},
                             content={"title": title, "hook": "합성", "summary": "검증용", "scenes": []})
        session.add(draft)
        session.flush()
        return draft.id


def video_fixture(app, title, *, status="success", playable=True, exists=True):
    """Mark fixture bytes playable only to test UI/path contracts, never MP4 validity."""
    draft_id = draft_fixture(app, title)
    with app.state.sessions.begin() as session:
        project = VideoProject(draft_id=draft_id, title=title, duration=45,
                               snapshot={"title": title, "scenes": []}, sources={"articles": []})
        session.add(project)
        session.flush()
        job = RenderJob(project_id=project.id, status=status, progress=100,
                        output_name=f"video-{uuid4().hex}.mp4", message="합성 UI fixture",
                        metadata_json={"playable": playable, "adapter": "synthetic-ui-only"})
        session.add(job)
        session.flush()
        result = {"id": job.id, "draft_id": draft_id, "project_id": project.id, "output_name": job.output_name}
    if exists:
        app.state.video.outputs.mkdir(parents=True, exist_ok=True)
        (app.state.video.outputs / result["output_name"]).write_bytes(b"SYNTHETIC_UI_BYTES_NOT_REAL_MP4")
    return result


def start_workspace(client, app):
    save_values(app, video_default_voice="offline-silence")
    response = client.post("/autopilot/quick-start", data={
        "csrf_token": csrf(client), "source": "sample", "duration": 45, "workspace": "true",
    }, follow_redirects=False)
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    assert location.path == "/" and location.fragment == "workspace-detail"
    identifier = parse_qs(location.query)["task"][0]
    app.state.autopilot.future.result(timeout=15)
    return identifier, app.state.autopilot.snapshot(identifier)


def test_workspace_has_creator_destinations_one_start_and_no_eager_player(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    navigation = re.search(r'<nav[^>]*aria-label="주 메뉴"[^>]*>(.*?)</nav>', html, re.DOTALL).group(1)
    primary = navigation.split('<details class="sidebar-tools"', 1)[0]
    assert re.findall(r'href="([^"]+)"', primary) == ["/", "/create", "/news", "/?show=tasks", "/videos", "/queue", "/simple-settings"]
    assert all(label in primary for label in ("홈", "쇼츠 만들기", "뉴스 선택", "작업 현황", "내 영상", "게시", "설정"))
    assert all(f'href="{path}"' in navigation for path in ("/ai", "/analytics", "/character", "/image-posts", "/voices", "/schedules"))
    assert not re.search(r'<aside[^>]*class="[^"]*\bsidebar\b', html)
    assert html.count('action="/autopilot/quick-start"') == 0
    assert client.get("/create").text.count('action="/autopilot/quick-start"') == 1
    for marker in ("data-workspace-create", 'id="workspace-tasks"', "data-workspace-videos"):
        assert marker in html
    assert '<video ' not in html and '<iframe' not in html
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "script-src 'self'" in response.headers["content-security-policy"]


def test_workspace_limits_cards_and_manual_completed_render_is_not_a_second_task(client, app):
    for index in range(7):
        draft_fixture(app, f"대본 검토 fixture {index}")
        video_fixture(app, f"완성 영상 fixture {index}")
    response = client.get("/")
    assert len(response.context["active_jobs"]) == 5
    assert len(response.context["completed"]) == 5
    assert response.context["active_task_count"] == 7 and response.context["video_count"] == 7
    assert response.context["task_count"] == 14  # expanded history retains completed manual tasks
    assert all("대본 검토 fixture" in row["title"] for row in response.context["active_jobs"])
    assert all("완성 영상 fixture" in row["title"] for row in response.context["completed"])
    assert 'href="/?show=tasks"' in response.text
    assert 'href="/videos"' in response.text
    assert len(client.get("/?show=tasks").context["workspace_tasks"]) == 14
    assert len(client.get("/?show=videos").context["workspace_videos"]) == 7
    assert "대본 검토 fixture 0" not in response.text
    assert "완성 영상 fixture 0" not in response.text
    assert response.text.count('<video ') == 1  # One explicit player; never eagerly load every MP4.
    assert 'preload="none"' in response.text and 'autoplay' not in response.text


def test_selected_video_uses_existing_guarded_player_and_download(client, app):
    video = video_fixture(app, "선택한 합성 영상")
    response = client.get(f'/?video={video["id"]}')
    assert response.status_code == 200 and "선택한 합성 영상" in response.text
    assert 'data-workspace-detail' in response.text
    player = re.search(r'<video\b[^>]*data-workspace-player[^>]*>', response.text).group(0)
    assert 'controls' in player and 'preload="none"' in player and 'autoplay' not in player
    assert response.text.count('<video ') == 1
    assert f'/video/jobs/{video["id"]}/file' in response.text
    assert f'/video/jobs/{video["id"]}/file?download=true' in response.text
    assert f'/video?job_id={video["id"]}' in response.text
    download = client.get(f'/video/jobs/{video["id"]}/file?download=true')
    assert download.status_code == 200 and "attachment" in download.headers["content-disposition"]
    assert download.content == b"SYNTHETIC_UI_BYTES_NOT_REAL_MP4"
    assert client.get(f'/video/jobs/{video["id"]}/file').headers["content-disposition"].startswith("inline")
    with app.state.sessions() as session:
        assert session.get(ContentDraft, video["draft_id"]).review_status == "review_required"


def test_workspace_preserves_ai_scene_and_preview_disclosures(client, app):
    video = video_fixture(app, "AI 장면 표시 fixture")
    with app.state.sessions.begin() as session:
        session.get(VideoProject, video["project_id"]).preview_only = True
        session.add(Scene(project_id=video["project_id"], position=0, start_ms=0, end_ms=45000,
                          narration="합성", caption="합성", material="AI 장면 fixture", ai_generated=True))
    for path in ("/", f'/?video={video["id"]}', "/videos"):
        html = client.get(path).text
        assert "AI 생성 장면 포함" in html
        assert "검토용 초안" in html


@pytest.mark.parametrize("status,playable,exists", [
    ("simulated", False, True), ("success", False, True), ("success", True, False),
])
def test_unverified_or_missing_media_never_appears_playable(client, app, status, playable, exists):
    video = video_fixture(app, "재생 불가 fixture", status=status, playable=playable, exists=exists)
    assert client.get("/").context["completed"] == []
    assert client.get(f'/?video={video["id"]}').status_code == 404
    assert client.get(f'/video/jobs/{video["id"]}/file').status_code == 404


def test_missing_manual_media_keeps_recovery_link_without_enabling_player(client, app):
    video = video_fixture(app, "누락 영상 복구 fixture", exists=False)
    for path in ("/", "/?show=tasks"):
        response = client.get(path)
        card = next(row for row in response.context["workspace_tasks"] if row["render_job_id"] == video["id"])
        assert card["workspace_href"] == f'/video?job_id={video["id"]}&draft_id={video["draft_id"]}'
        assert f'href="/video?job_id={video["id"]}&amp;draft_id={video["draft_id"]}"' in response.text
        assert '<video ' not in response.text
    assert client.get(f'/?video={video["id"]}').status_code == 404


def test_workspace_review_resume_preserves_gates_and_legacy_redirect(client, app):
    identifier, selected = start_workspace(client, app)
    assert selected["status"] == "waiting_review" and selected["current_stage"] == "select"
    page = client.get(f"/?task={identifier}")
    assert page.status_code == 200 and 'data-workspace-detail' in page.text
    assert f'action="/autopilot/jobs/{identifier}/resume"' in page.text
    assert 'name="workspace" value="true"' in page.text
    assert f'name="revision" value="{selected["revision"]}"' in page.text
    assert app.state.autopilot.snapshot(identifier)["revision"] == selected["revision"]
    legacy = client.get(f"/autopilot/jobs/{identifier}")
    assert legacy.status_code == 200 and 'name="workspace"' not in legacy.text
    resumed = client.post(f"/autopilot/jobs/{identifier}/resume", data={
        "csrf_token": csrf(client), "revision": selected["revision"],
        "article_id": selected["article_id"], "workspace": "true",
    }, follow_redirects=False)
    assert resumed.headers["location"] == f"/?task={identifier}#workspace-detail"
    app.state.autopilot.future.result(timeout=15)
    scripted = app.state.autopilot.snapshot(identifier)
    assert scripted["status"] == "waiting_review" and scripted["current_stage"] == "script"
    assert 'id="job-script"' in client.get(resumed.headers["location"]).text
    with app.state.sessions() as session:
        assert session.get(ContentDraft, scripted["content_draft_id"]).review_status == "review_required"
    stale = client.post(f"/autopilot/jobs/{identifier}/resume", data={
        "csrf_token": csrf(client), "revision": selected["revision"], "workspace": "true",
    })
    assert stale.status_code == 409
    cancelled = client.post(f"/autopilot/jobs/{identifier}/cancel", data={
        "csrf_token": csrf(client), "revision": scripted["revision"],
    }, follow_redirects=False)
    assert cancelled.headers["location"] == f"/autopilot/jobs/{identifier}"
    assert app.state.autopilot.snapshot(identifier)["content_draft_id"] == scripted["content_draft_id"]


def test_pending_final_review_is_not_duplicated_in_completed_cards(client, app):
    video = video_fixture(app, "최종 검토 fixture")
    identifier = uuid4().hex
    with app.state.sessions.begin() as session:
        session.add(AutopilotJob(id=identifier, active_slot=1, mode="guided", source="sample", duration=45,
                                platform="youtube", status="waiting_review", current_stage="validate", progress=83,
                                stage_results={"render": {"render_job_id": video["id"]}}, voice="offline-silence"))
        session.flush()
        session.add_all([
            AutopilotArtifact(job_id=identifier, kind="content_draft_id", reference=str(video["draft_id"])),
            AutopilotArtifact(job_id=identifier, kind="render_job_id", reference=str(video["id"])),
        ])
    response = client.get("/")
    assert len(response.context["active_jobs"]) == 1
    assert response.context["active_jobs"][0]["status_label"] == "최종 확인 필요"
    assert response.context["completed"] == []
    assert f'/?task={identifier}#workspace-detail' in response.text
    assert "검토 중인 영상은 위 작업에서 확인해 주세요" in response.text
    assert 'href="/videos"' in response.text


@pytest.mark.parametrize("origin,include_token", [("https://foreign.example", True), ("null", True),
                                                  ("http://127.0.0.1", False)])
def test_workspace_marker_cannot_bypass_csrf_or_origin(client, app, origin, include_token):
    data = {"source": "sample", "duration": "45", "workspace": "true"}
    if include_token:
        data["csrf_token"] = csrf(client)
    assert client.post("/autopilot/quick-start", data=data, headers={"Origin": origin}).status_code == 403
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AutopilotJob)) == 0


@pytest.mark.parametrize("query,status", [("task=missing", 404), ("video=999999", 404),
                                          ("video=0", 422), ("task=missing&video=1", 422),
                                          ("show=https://foreign.example", 422)])
def test_workspace_rejects_invalid_or_missing_selection(client, query, status):
    assert client.get("/?" + query).status_code == status


def test_workspace_reads_never_change_provider_preferences_or_start_inference(client, app):
    write_studio_settings(app.state.sessions, "claude_code", "sonnet")
    save_values(app, video_default_voice="Missing Korean", autopilot_duration="60", autopilot_source="feeds")
    video = video_fixture(app, "보존 확인 fixture")
    app.state.ai_provider = fake = FakeProvider()
    before = stored_values(app)
    for path in ("/", f'/?video={video["id"]}', "/?show=tasks", "/?show=videos"):
        assert client.get(path).status_code == 200
    assert stored_values(app) == before and fake.calls == 0
    response = client.get("/")
    home = response.text
    assert response.context["ready"]["voice"]["name"] == "Missing Korean"
    assert response.context["ready"]["voice"]["installed"] is False
    assert "Claude Code" in home and "음성 준비 필요" in home
    creation = client.get("/create")
    assert 'value="60" selected' in creation.text and 'value="feeds" selected' in creation.text
    assert creation.context["production"]["policy_states"]["ai_web"]["supported"] is False
    assert "다른 음성으로 자동 전환하지 않습니다" in home
    rss_state = response.context["production"]["policy_states"]["rss"]
    assert rss_state["supported"] is False
    assert "선택한 음성의 설치·제작별 승인이 필요합니다" in rss_state["notice"]
    assert "다른 음성으로 자동 전환하지 않습니다" in rss_state["notice"]


@pytest.mark.parametrize("path", ["/autopilot/jobs", "/videos", "/ai", "/video", "/simple-settings"])
def test_legacy_pages_remain_reachable_with_security_headers(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
