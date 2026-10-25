"""Phase 5D GUI: AI 고품질 제작 pages, settings, CSRF, refusal details and the full Fake-provider flow."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

import pytest
from conftest import csrf
from fastapi.testclient import TestClient
from sqlalchemy import select

from newsflow.config import Settings
from newsflow.db.models import (
    AIVideoPlan,
    AIVideoScene,
    NewsArticle,
    RenderJob,
    Scene,
    VideoAIUsage,
    VideoProject,
)
from newsflow.gui.routes import kst, kst_day
from newsflow.intelligence.credentials import FakeCipher
from newsflow.intelligence.service import IntelligenceService
from newsflow.main import create_app
from newsflow.video.ai.fake import FakeVideoProvider
from newsflow.video.ai.policy import SCENE_LABEL, STYLE_GUARD
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe not installed")


@pytest.fixture
def studio(tmp_path, fake, monkeypatch):
    provider = FakeVideoProvider(steps=1)
    app = create_app(Settings(data_dir=tmp_path / "data"), fake, video_provider=provider)
    service = app.state.video_ai
    monkeypatch.setattr(service, "wake", lambda: None)  # tests drive the worker with tick()
    with app.state.sessions.begin() as session:
        session.add(NewsArticle(
            title="AI 영상 화면 테스트 뉴스", summary="합성 요약", url="https://example.com/news/1",
            canonical_url="https://example.com/news/1", source_id=1, publisher="합성 언론",
        ))
    ai = IntelligenceService(app.state.sessions)
    draft_id = ai.generate(ai.analyze([1]), 30)
    app.state.video.engine, app.state.video.tts = FakeRenderAdapter(), FakeTTS()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield app, client, provider, draft_id
    app.state.video.close()


def post(client, path: str, data: dict | None = None):
    token = csrf(client)
    return client.post(path, data={"csrf_token": token, **(data or {})}, follow_redirects=False)


def configure(client) -> None:
    assert post(client, "/video-ai-settings", {
        "provider": "higgsfield", "host": "api.higgsfield.ai", "approved": "true", "monthly_limit": "20",
        "job_limit": "5", "currency": "USD", "max_active": "2", "timeout_minutes": "30", "poll_seconds": "10",
    }).status_code == 303
    assert post(client, "/video-ai-settings/models", {
        "path": "vendor/model/text-to-video", "label": "시험 모델", "price_per_second": "0.1", "durations": "5,10",
        "resolution": "720p", "confirmed": "true",
    }).status_code == 303


def plan_id_for(client, draft_id: int) -> int:
    response = post(client, "/video/ai/plans", {"draft_id": draft_id, "duration": 30})
    assert response.status_code == 303
    return int(response.headers["location"].rsplit("/", 1)[-1])


def revision(app, plan_id: int) -> int:
    with app.state.sessions() as session:
        return session.get(AIVideoPlan, plan_id).revision


def test_pages_render_default_off_and_keep_six_main_menus(studio):
    _app, client, _provider, draft_id = studio
    home = client.get("/video/ai")
    assert home.status_code == 200 and "기본 FFmpeg 제작" in home.text and "전체 AI 영상 · 모든 시각 장면" in home.text
    assert "AI 영상 유료 생성 승인이 저장되지 않았습니다." in home.text and "테스트 전용 Fake 공급자" in home.text
    nav = home.text.split('aria-label="주 메뉴"', 1)[1].split("</nav>", 1)[0]
    assert nav.count('data-nav-id=') == 13
    assert 'data-sidebar-tools' in nav
    for href in ("/", "/news", "/ai", "/videos", "/queue", "/analytics", "/simple-settings"):
        assert f'href="{href}"' in nav
    settings = client.get("/video-ai-settings")
    assert settings.status_code == 200 and 'name="provider" value="off"' in settings.text
    assert 'href="/simple-settings#selected-video"' in settings.text
    assert "모델 등록·가격 확인 (고급 관리)" in settings.text
    assert "공급사에서 확인한 값만 입력하세요" in settings.text
    assert "Authorization: Key" not in settings.text and "video.url" not in settings.text
    assert "kling-video/v3.0-turbo/text-to-video" in settings.text and "KEY_ID" not in settings.text
    studio_page = client.get(f"/video?draft_id={draft_id}")
    assert f'href="/video/ai?draft_id={draft_id}"' in studio_page.text and 'action="/video/render"' in studio_page.text
    assert 'href="/video-ai-settings"' in client.get("/simple-settings").text


def test_post_requires_csrf_and_refusals_carry_the_fixed_detail(studio):
    _app, client, _provider, draft_id = studio
    assert client.post("/video-ai-settings", data={"provider": "higgsfield"}).status_code == 403
    refused = post(client, "/video-ai-settings", {"provider": "higgsfield", "approved": "true", "monthly_limit": "", "job_limit": ""})
    assert refused.status_code == 303
    with _app.state.sessions() as session:
        assert session.scalar(select(VideoAIUsage)) is None
    assert _provider.calls == []
    bad_model = post(client, "/video-ai-settings/models", {"path": "../etc/passwd", "label": "x", "durations": "5"})
    assert bad_model.status_code == 422 and "모델 경로" in bad_model.json()["detail"]
    plan_id = plan_id_for(client, draft_id)
    configure(client)
    blocked = post(client, f"/video/ai/plans/{plan_id}/scenes", {
        "revision": 1, "source_0": "generated", "prompt_0": "사고 현장 영상처럼 cctv 화면", "model_0": "vendor/model/text-to-video",
    })
    assert blocked.status_code == 422 and "실제 뉴스 현장" in blocked.json()["detail"]
    stale = post(client, f"/video/ai/plans/{plan_id}/scenes", {"revision": 99, "source_0": "card"})
    assert stale.status_code == 409


def test_key_form_stores_through_dpapi_store_and_never_renders_the_key(studio, monkeypatch):
    app, client, _provider, _draft = studio
    app.state.video_ai.keys._cipher = FakeCipher()
    from types import SimpleNamespace

    # Isolate the key-store platform branch; never change stdlib sys.platform on Linux.
    monkeypatch.setattr("newsflow.intelligence.credentials.sys", SimpleNamespace(platform="win32"))
    secret = "hf-test-key-ABCDEFGH12345678"
    refused = post(client, "/video-ai-settings/key", {"api_key": "has space key value"})
    assert refused.status_code == 422 and "open.higgsfield.ai" in refused.json()["detail"]
    assert post(client, "/video-ai-settings/key", {"api_key": secret}).status_code == 303
    page = client.get("/video-ai-settings").text
    assert secret not in page and "저장됨 (비밀값 비표시)" in page
    assert (app.state.config.data_dir / "video-ai-key.dpapi").is_file()
    assert not (app.state.config.data_dir / "ai-key.dpapi").exists()
    assert post(client, "/video-ai-settings/key/clear").status_code == 303


@needs_ffmpeg
def test_full_flow_plan_confirm_generate_review_and_compose(studio, monkeypatch):
    app, client, provider, draft_id = studio
    configure(client)
    plan_id = plan_id_for(client, draft_id)
    page = client.get(f"/video/ai/plans/{plan_id}").text
    assert SCENE_LABEL in page and STYLE_GUARD in page and "생성할 AI 장면이 없습니다" in page
    saved = post(client, f"/video/ai/plans/{plan_id}/scenes", {
        "revision": revision(app, plan_id), "source_0": "generated", "prompt_0": "도시 경제를 상징하는 추상 그래픽",
        "model_0": "vendor/model/text-to-video", "source_1": "card", "source_2": "card",
    })
    assert saved.status_code == 303
    estimate = app.state.video_ai.estimate(plan_id)
    assert estimate["can_submit"] and estimate["total"] == "1"  # 10 s scene -> 10 s clip x 0.1
    unchecked = post(client, f"/video/ai/plans/{plan_id}/confirm", {"revision": revision(app, plan_id), "shown_total": "1"})
    assert unchecked.status_code == 422 and "체크하세요" in unchecked.json()["detail"]
    wrong_total = post(client, f"/video/ai/plans/{plan_id}/confirm", {
        "revision": revision(app, plan_id), "shown_total": "0.5", "confirmed": "true"})
    assert wrong_total.status_code == 409
    confirmed = post(client, f"/video/ai/plans/{plan_id}/confirm", {
        "revision": revision(app, plan_id), "shown_total": "1", "confirmed": "true"})
    assert confirmed.status_code == 303
    assert client.get(f"/api/video/ai/plans/{plan_id}").json()["scenes"][0]["status"] == "waiting"
    app.state.video_ai.tick()  # submit
    app.state.video_ai.tick()  # poll -> completed -> download -> validate
    status = client.get(f"/api/video/ai/plans/{plan_id}").json()
    assert status["status"] == "review" and status["scenes"][0]["status"] == "ready"
    page = client.get(f"/video/ai/plans/{plan_id}").text
    with app.state.sessions() as session:
        scene = session.scalar(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id, AIVideoScene.position == 0))
        usage = session.scalar(select(VideoAIUsage).where(VideoAIUsage.scene_id == scene.id))
    assert f"/video/ai/scenes/{scene.id}/clip" in page and usage.status == "completed" and usage.estimated_cost == "1"
    media = client.get(f"/video/ai/scenes/{scene.id}/clip")
    assert media.status_code == 200 and media.headers["content-type"] == "video/mp4" and len(media.content) > 1000
    early = post(client, f"/video/ai/plans/{plan_id}/approve", {"revision": revision(app, plan_id), "approved": "true"})
    assert early.status_code == 422 and "검토" in early.json()["detail"]
    reviewed = post(client, f"/video/ai/plans/{plan_id}/review", {
        "revision": revision(app, plan_id), "reviewed_0": "true", "statement": "true"})
    assert reviewed.status_code == 303
    approved = post(client, f"/video/ai/plans/{plan_id}/approve", {"revision": revision(app, plan_id), "approved": "true"})
    assert approved.status_code == 303 and approved.headers["location"].startswith("/video?job_id=")
    job_id = int(approved.headers["location"].split("=")[1])
    app.state.video.future.result(timeout=30)
    with app.state.sessions() as session:
        job = session.get(RenderJob, job_id)
        project = session.get(VideoProject, job.project_id)
        scenes = list(session.scalars(select(Scene).where(Scene.project_id == project.id).order_by(Scene.position)))
        plan = session.get(AIVideoPlan, plan_id)
    assert job.status == "simulated" and project.ai_plan_id == plan_id and plan.render_job_id == job_id
    assert scenes[0].ai_generated and scenes[0].clip_name == scene.clip_name and not scenes[1].ai_generated
    assert app.state.video.engine.calls[-1].scenes[0].clip is not None
    assert [call[0] for call in provider.calls].count("submit") == 1
    job_page = client.get(f"/video?job_id={job_id}").text
    assert 'id="job-ai-notice"' in job_page and f'href="/video/ai/plans/{plan_id}"' in job_page
    assert job_page.count('<span class="scene-source">AI 생성</span>') == 1
    assert "AI 생성 장면 포함" in client.get("/videos").text
    assert client.get(f"/api/video/ai/plans/{plan_id}").json()["status"] == "composed"
    again = post(client, f"/video/ai/plans/{plan_id}/approve", {"revision": revision(app, plan_id), "approved": "true"})
    assert again.status_code == 409


def test_clip_route_404_for_unready_scenes_and_status_api(studio):
    app, client, _provider, draft_id = studio
    plan_id = plan_id_for(client, draft_id)
    with app.state.sessions() as session:
        scene_id = session.scalar(select(AIVideoScene.id).where(AIVideoScene.plan_id == plan_id))
    assert client.get(f"/video/ai/scenes/{scene_id}/clip").status_code == 404
    assert client.get("/api/video/ai/plans/9999").status_code == 404
    assert client.get(f"/api/video/ai/plans/{plan_id}").json()["status"] == "draft"


def test_screen_times_are_kst():
    assert kst(datetime(2026, 10, 15, 12, 39, tzinfo=UTC)) == "2026-10-15 21:39 KST"
    assert kst(datetime(2026, 10, 15, 15, 0)) == "2026-10-16 00:00 KST"
    assert kst(None) == "미확인"


def test_approval_day_and_news_date_filter_use_kst(client, app):
    assert kst_day("2026-10-15T20:30:00+00:00") == "2026-10-16" and kst_day("") == "" and kst_day("garbage") == ""
    with app.state.sessions.begin() as session:
        session.add(NewsArticle(
            title="KST 자정 넘긴 합성 뉴스", summary="합성 요약", url="https://example.com/news/kst",
            canonical_url="https://example.com/news/kst", source_id=1, publisher="합성 언론",
            published_at=datetime(2026, 10, 13, 16, 0, tzinfo=UTC),  # 2026-10-14 01:00 KST
        ))
    assert "KST 자정 넘긴 합성 뉴스" in client.get("/news?start=2026-10-14&end=2026-10-14").text
    assert "KST 자정 넘긴 합성 뉴스" not in client.get("/news?start=2026-10-13&end=2026-10-13").text
    assert "발행일 시작 · KST" in client.get("/news").text


def test_news_filter_rejects_the_first_calendar_day_instead_of_failing(client):
    assert client.get("/news?start=0001-01-01").status_code == 422
    assert client.get("/news?start=0001-01-02").status_code == 200


def test_plan_page_shows_current_prices_and_flags_an_unusable_model(studio):
    app, client, _provider, draft_id = studio
    configure(client)
    plan_id = plan_id_for(client, draft_id)
    assert post(client, f"/video/ai/plans/{plan_id}/scenes", {
        "revision": revision(app, plan_id), "source_0": "generated", "prompt_0": "도시 경제를 상징하는 추상 그래픽",
        "model_0": "vendor/model/text-to-video", "source_1": "card", "source_2": "card",
    }).status_code == 303
    page = client.get(f"/video/ai/plans/{plan_id}").text
    assert "현재 단가 기준 생성 길이 10초 · 예상 1 USD" in page
    with app.state.sessions.begin() as session:
        from newsflow.db.models import VideoAIModel

        session.scalar(select(VideoAIModel)).confirmed_at = None
    page = client.get(f"/video/ai/plans/{plan_id}").text
    assert "모델을 다시 고르세요(공식 문서 확인·단가가 필요합니다)" in page and "현재 단가 기준" not in page
    # The scene's model stays selected (and so is posted back unchanged) even though it left the usable list.
    assert '<option value="vendor/model/text-to-video" selected>vendor/model/text-to-video (현재 사용 불가)</option>' in page


@needs_ffmpeg
def test_paid_clip_needs_discard_and_a_new_script_can_be_taken_in(studio):
    app, client, _provider, draft_id = studio
    configure(client)
    plan_id = plan_id_for(client, draft_id)
    form = {"source_0": "generated", "prompt_0": "도시 경제를 상징하는 추상 그래픽", "model_0": "vendor/model/text-to-video",
            "source_1": "card", "source_2": "card"}
    assert post(client, f"/video/ai/plans/{plan_id}/scenes", {"revision": revision(app, plan_id), **form}).status_code == 303
    assert post(client, f"/video/ai/plans/{plan_id}/confirm", {
        "revision": revision(app, plan_id), "shown_total": "1", "confirmed": "true"}).status_code == 303
    app.state.video_ai.tick()
    app.state.video_ai.tick()
    page = client.get(f"/video/ai/plans/{plan_id}").text
    assert 'name="discard_0"' in page and 'name="discard_1"' not in page and 'id="rebase-form"' not in page
    with app.state.sessions.begin() as session:
        from newsflow.db.models import ContentDraft, VideoAIModel

        session.scalar(select(VideoAIModel)).confirmed_at = None
    # Posting the page back as shown keeps the paid clip although its model is no longer usable.
    assert post(client, f"/video/ai/plans/{plan_id}/scenes", {"revision": revision(app, plan_id), **form}).status_code == 303
    changed = {**form, "prompt_0": "다른 추상 그래픽"}
    refused = post(client, f"/video/ai/plans/{plan_id}/scenes", {"revision": revision(app, plan_id), **changed})
    assert refused.status_code == 409 and "'받아 둔 유료 AI 영상 버리기'에 체크" in refused.json()["detail"]
    with app.state.sessions() as session:
        scene = session.scalar(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id, AIVideoScene.position == 0))
    assert scene.status == "ready" and scene.clip_name

    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, draft_id)
        items = [dict(item) for item in draft.content["scenes"]]
        items[1]["caption"] = "바뀐 둘째 자막"
        draft.content = {**draft.content, "scenes": items}
        draft.revision += 1
    page = client.get(f"/video/ai/plans/{plan_id}").text
    assert 'id="rebase-form"' in page and "바뀐 대본 반영" in page
    rebased = post(client, f"/video/ai/plans/{plan_id}/rebase", {"revision": revision(app, plan_id)})
    assert rebased.status_code == 303 and rebased.headers["location"].endswith("saved=rebased")
    page = client.get(rebased.headers["location"]).text
    assert "바뀐 대본의 내레이션·자막을 반영했습니다." in page and "바뀐 둘째 자막" in page and 'id="rebase-form"' not in page
    assert post(client, f"/video/ai/plans/{plan_id}/rebase", {"revision": revision(app, plan_id)}).status_code == 409
    with app.state.sessions() as session:
        kept = session.get(AIVideoScene, scene.id)
    assert (kept.status, kept.clip_name) == ("ready", scene.clip_name)


@needs_ffmpeg
def test_an_unreadable_clip_offers_a_free_refetch_on_the_plan_page(studio, monkeypatch):
    from pathlib import Path

    app, client, provider, draft_id = studio
    configure(client)
    plan_id = plan_id_for(client, draft_id)
    form = {"source_0": "generated", "prompt_0": "도시 경제를 상징하는 추상 그래픽", "model_0": "vendor/model/text-to-video",
            "source_1": "card", "source_2": "card"}
    assert post(client, f"/video/ai/plans/{plan_id}/scenes", {"revision": revision(app, plan_id), **form}).status_code == 303
    assert post(client, f"/video/ai/plans/{plan_id}/confirm", {
        "revision": revision(app, plan_id), "shown_total": "1", "confirmed": "true"}).status_code == 303
    app.state.video_ai.tick()
    app.state.video_ai.tick()
    assert post(client, f"/video/ai/plans/{plan_id}/review", {
        "revision": revision(app, plan_id), "reviewed_0": "true", "statement": "true"}).status_code == 303
    refetch_action = f'action="/video/ai/plans/{plan_id}/scenes/0/refetch"'
    assert refetch_action not in client.get(f"/video/ai/plans/{plan_id}").text
    with app.state.sessions() as session:
        scene = session.scalar(select(AIVideoScene).where(AIVideoScene.plan_id == plan_id, AIVideoScene.position == 0))
    clip = app.state.video_ai.clip_path(scene.id)
    real_open = Path.open

    def locked(self, *args, **kwargs):
        if self == clip:
            raise PermissionError(13, "denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)
    refused = post(client, f"/video/ai/plans/{plan_id}/approve", {"revision": revision(app, plan_id), "approved": "true"})
    assert refused.status_code == 409 and "결과 다시 받기" in refused.json()["detail"]
    assert refetch_action in client.get(f"/video/ai/plans/{plan_id}").text
    assert post(client, f"/video/ai/plans/{plan_id}/scenes/0/refetch", {"revision": revision(app, plan_id)}).status_code == 303
    app.state.video_ai.tick()
    status = client.get(f"/api/video/ai/plans/{plan_id}").json()
    assert status["scenes"][0]["status"] == "ready"
    assert [call[0] for call in provider.calls].count("submit") == 1
