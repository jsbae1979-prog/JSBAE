"""Real HTTP/Chrome + existing services; injected APIs/accounts/TTS, no vendor calls.

This is test wiring, never a selectable application mode. All state lives in tmp_path.
Synthetic WAV silence proves timing/streams only, not speech or listening quality.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import time
import urllib.request
import wave
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlsplit

import uvicorn
from playwright.sync_api import expect
from sqlalchemy import select
from test_api_news_pipeline import FixtureKey
from test_api_news_pipeline import api_pipeline as pipeline_fixture
from test_instagram_live import Adapter as InstagramAdapter
from test_instagram_live import Connections as InstagramConnections
from test_live_publishing import Adapter as YouTubeAdapter
from test_live_publishing import Connections as YouTubeConnections
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import save_values

from newsflow.db.models import APIRequestReservation, ContentDraft, IntelligenceRun, PublishDraft
from newsflow.gui import production_status
from newsflow.gui.routes import templates
from newsflow.intelligence.settings import write_studio_settings
from newsflow.publishing.instagram_live import InstagramPublishingService
from newsflow.publishing.live import LivePublishingService
from newsflow.publishing.media import FFprobeMediaInspector
from newsflow.publishing.unified import UnifiedPublishingService

api_pipeline = pipeline_fixture
browser = browser_fixture


class SyntheticTTS:
    def __init__(self):
        self.calls = []

    def voices(self):
        return ["supertonic:F1"]

    def synthesize(self, text, target, voice, seconds, speech=None):
        self.calls.append((text, voice))
        with wave.open(str(target), "wb") as wav:
            wav.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\0\0" * round(8000 * 9.2))


@contextmanager
def local_server(app):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        config = uvicorn.Config(app, log_level="error", access_log=False, lifespan="off")
        server = uvicorn.Server(config)
        thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 15
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(.02)
            yield f"http://127.0.0.1:{sock.getsockname()[1]}"
        finally:
            server.should_exit = True
            thread.join(timeout=15)
            assert not thread.is_alive()


def test_api_to_render_review_and_existing_publish_services(app, api_pipeline, browser, monkeypatch, tmp_path):
    coordinator, backend, provider, sessions, mode, rss = api_pipeline
    # The original factories/engines stay intact; only test dependencies are injected.
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    monkeypatch.setattr(app.state, "autopilot_backend", backend)
    monkeypatch.setattr(app.state, "api_keys", {mode: FixtureKey(),
        ("claude_api" if mode == "openai" else "openai"): FixtureKey()})
    if mode == "openai":
        monkeypatch.setattr(app.state, "ai_keys", FixtureKey())
    write_studio_settings(sessions, mode, "gpt-4.1-mini" if mode == "openai" else "claude-sonnet-4-6")
    save_values(app, video_default_voice="supertonic:F1", autopilot_source="feeds",
                autopilot_acquisition_policy="ai_web", autopilot_duration="30")
    tts = SyntheticTTS()
    monkeypatch.setattr(app.state.video, "tts", tts)
    monkeypatch.setattr(production_status, "voice_choice_catalog", lambda: [{
        "name": "supertonic:F1", "label": "합성 측정 음성 · 사람 음성 아님", "engine": "supertonic", "available": True}])
    monkeypatch.setitem(templates.env.globals, "ui_demo", True)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("No external API/OAuth/SNS/CLI authentication allowed")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    # Ignore no assertions: a fallback to a real network adapter fails immediately.
    yt_connections, ig_connections = YouTubeConnections(), InstagramConnections()
    yt_adapter, ig_adapter = YouTubeAdapter(), InstagramAdapter()
    inspector = FFprobeMediaInspector()
    youtube = LivePublishingService(sessions, app.state.video.outputs, yt_connections, inspector, lambda: yt_adapter)
    instagram = InstagramPublishingService(sessions, app.state.video.outputs, ig_connections, inspector, lambda: ig_adapter)
    unified = UnifiedPublishingService(sessions, app.state.video.outputs, youtube, instagram, inspector)
    accounts = {"youtube": unified.local.add_account("youtube", "합성 YouTube · 실계정 아님", "youtube_channel"),
                "instagram": unified.local.add_account("instagram", "합성 Instagram · 실계정 아님", "professional_business")}
    monkeypatch.setattr(yt_connections, "status", lambda: {"client_configured": True, "storage_supported": True,
        "pending": False, "accounts": [{"id": accounts["youtube"], "label": "합성 YouTube · 실계정 아님", "ready": True}]}, raising=False)
    monkeypatch.setattr(ig_connections, "status", lambda: {"configured": True, "connection_supported": True,
        "accounts": [{"id": accounts["instagram"], "label": "합성 Instagram · 실계정 아님", "ready": True}]}, raising=False)
    monkeypatch.setattr(app.state, "youtube", yt_connections)
    monkeypatch.setattr(app.state, "instagram", ig_connections)
    monkeypatch.setattr(app.state, "unified_publishing", unified)
    output = Path(os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path / "evidence"))) / mode
    output.mkdir(parents=True, exist_ok=True)
    errors, external = [], []
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ko-KR")
        def guard(route):
            if urlsplit(route.request.url).netloc == urlsplit(origin).netloc:
                route.continue_()
            else:
                external.append(urlsplit(route.request.url).hostname)
                route.abort()
        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        response = page.goto(origin + "/")
        assert "script-src 'self'" in response.headers["content-security-policy"]
        expect(page.locator(".demo-banner")).to_be_visible()
        page.get_by_role("link", name="새 뉴스로 쇼츠 만들기 →", exact=True).click()
        assert urlsplit(page.url).path == "/create"
        page.get_by_role("button", name="쇼츠 만들기", exact=True).click()
        page.wait_for_url(lambda u: "guide=consent" in u)
        assert provider.calls == []
        form = page.locator('form[action="/autopilot/confirm-start"]')
        token = form.locator('[name="csrf_token"]').input_value()
        flow = form.locator('[name="flow"]').input_value()
        rejected = context.request.post(origin + "/autopilot/confirm-start", form={"csrf_token":token,"flow":flow,"workspace":"true"})
        assert rejected.status == 422 and provider.calls == []
        form.locator('[name="consent"]').check()
        form.get_by_role("button", name="동의하고 제작 준비").click()
        page.wait_for_url(lambda u: "task=" in u)
        identifier = parse_qs(urlsplit(page.url).query)["task"][0]
        coordinator.future.result(timeout=30)
        job = coordinator.snapshot(identifier)
        assert (job["status"],job["current_stage"]) == ("waiting_review","script"), job
        assert provider.calls == ["search","analysis","script"] and rss.calls == []
        page.reload()
        expect(page.locator("#job-script")).to_be_visible()
        page.screenshot(path=str(output / "api-script-review.png"), full_page=True)
        # Use the real editor POST and return to the same work item, with no new inference.
        page.goto(origin + f'/ai?draft_id={job["content_draft_id"]}')
        expect(page.locator('textarea[name="narration"]').first).not_to_have_attribute("readonly", "")
        with page.expect_response(lambda r:r.request.method=="POST" and "/ai/drafts/" in r.url) as saved:
            page.get_by_role("button",name="수정 초안 저장").click()
        assert saved.value.status == 303
        page.wait_for_url(lambda u:"draft_id=" in u)
        page.get_by_role("link", name="작업실에서 대본 검토 계속하기 →", exact=True).click()
        with page.expect_response(lambda r:r.request.method=="POST" and r.url.endswith("/resume")) as resumed:
            page.get_by_role("button", name="이 대본으로 영상 만들기", exact=False).click()
        assert resumed.value.status == 303
        coordinator.future.result(timeout=240)
        job = coordinator.snapshot(identifier)
        assert (job["status"],job["current_stage"]) == ("waiting_review","validate"), job
        assert len(tts.calls) == 3
        page.reload()
        video = page.locator('[data-workspace-detail] video').first
        expect(video).to_be_visible()
        video.evaluate("async v=>{v.muted=true;await v.play()}")
        page.wait_for_function("()=>document.querySelector('[data-workspace-detail] video').currentTime>0")
        video.evaluate("v=>v.pause()")
        render_id = job["render_job_id"]
        media = context.request.get(origin + f"/video/jobs/{render_id}/file?download=true")
        assert media.status == 200 and "attachment" in media.headers["content-disposition"]
        digest = hashlib.sha256(media.body()).hexdigest()
        path = backend.video.outputs / job["output_name"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        metadata = inspector.inspect(path)
        assert (metadata["width"],metadata["height"],metadata["video_codec"],metadata["audio_codec"]) == (1080,1920,"h264","aac")
        with page.expect_response(lambda r:r.request.method=="POST" and r.url.endswith("/resume")) as queued:
            page.get_by_role("button", name="게시 대기함에 보관하기", exact=False).click()
        assert queued.value.status == 303
        coordinator.future.result(timeout=30)
        job = coordinator.snapshot(identifier)
        assert job["status"] == "completed" and job["publish_draft_id"]
        with sessions() as s:
            draft = s.get(PublishDraft, job["publish_draft_id"])
            assert not draft.content_reviewed and not draft.copyright_confirmed and not draft.sources_confirmed
            assert draft.account_id is None
        page.goto(origin+f"/?video={render_id}&publish_platform=unified#publish-workspace")
        review = page.locator('form[action="/publishing/unified/review"]')
        target = "both" if mode == "openai" else "youtube"
        review.locator('[name="target"]').select_option(target)
        for field in ("content_reviewed","copyright_confirmed","sources_confirmed"):
            review.locator(f'[name="{field}"]').check()
        review.locator('[name="ai_disclosure"]').select_option("disclose")
        review.get_by_role("button",name="검토 저장·파일 확인").click()
        page.wait_for_load_state("networkidle")
        execute = page.locator('form[action$="/execute"]')
        expect(execute).to_be_visible()
        cohort = unified.for_video(render_id)
        with sessions() as s:
            assert {s.get(PublishDraft,row["draft_id"]).media_sha256 for row in cohort["targets"]} == {digest}
        approval = execute.locator('[name="approval_token"]').input_value()
        denied = context.request.post(origin + f'/publishing/unified/{cohort["id"]}/execute', form={
            "csrf_token":token,"approval_token":approval,"consent":"true","privacy":"public","made_for_kids":"no"})
        assert denied.status==422 and yt_adapter.calls==ig_adapter.calls==[]
        execute.locator('[name="made_for_kids"]').select_option("no")
        execute.locator('[name="consent"]').check()
        if target=="both":
            ig_adapter.processing="IN_PROGRESS"
            execute.locator('[name="instagram_public_consent"]').check()
        with page.expect_response(lambda r:r.request.method=="POST" and r.url.endswith("/execute")) as dispatched:
            execute.get_by_role("button", name="선택한 곳에 게시",exact=True).click()
        assert dispatched.value.status == 303, dispatched.value.text()
        page.wait_for_load_state("networkidle")
        states = [row["status"] for row in unified.for_video(render_id)["targets"]]
        assert states == (["complete","waiting"] if target=="both" else ["complete"])
        if target=="both":
            page.screenshot(path=str(output/'synthetic-partial-result.png'),full_page=True)
            # Recreate the existing coordinator from durable SQLite evidence.
            unified = UnifiedPublishingService(sessions, backend.video.outputs, youtube, instagram, inspector)
            monkeypatch.setattr(app.state,"unified_publishing",unified)
            assert unified.recover()==0
            ig_adapter.processing="FINISHED"
            page.reload()
            execute=page.locator('form[action$="/execute"]')
            assert execute.locator('[name="made_for_kids"]').count()==0
            execute.locator('[name="consent"]').check()
            execute.locator('[name="instagram_public_consent"]').check()
            with page.expect_response(lambda r:r.request.method=="POST" and r.url.endswith("/execute")) as continued:
                execute.get_by_role("button",name="게시 계속",exact=True).click()
            assert continued.value.status == 303, continued.value.text()
            page.wait_for_load_state("networkidle")
        assert all(row["status"]=="complete" for row in unified.for_video(render_id)["targets"])
        assert len(yt_adapter.calls)==1
        assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
        expect(page.locator('form[action$="/execute"]')).to_have_count(0)
        expect(page.locator('[data-outcome="success"]')).to_have_count(2 if target=="both" else 1)
        assert provider.calls == ["search","analysis","script"]
        assert not errors and not external
        for route in ('/create','/news','/videos',f'/ai?draft_id={job["content_draft_id"]}','/queue','/simple-settings'):
            assert page.goto(origin+route).status==200
            assert "synthetic-key-not-a-real-credential" not in page.content()
            assert "nf-synthetic-never-sent" not in page.content()
        with sessions() as s:
            assert all(r.test_only for r in s.scalars(select(APIRequestReservation)))
            assert {r.provider for r in s.scalars(select(IntelligenceRun))}=={mode}
            assert s.get(ContentDraft,job['content_draft_id']).revision==2
        context.close()
    result={"status":"PASS","provider":mode,"api_calls":provider.calls,"target":target,
            "youtube_fake_uploads":len(yt_adapter.calls),"instagram_fake_calls":ig_adapter.calls,
            "media":metadata,"media_sha256":digest,"tts":"synthetic timed WAV silence, not speech",
            "human_quality":"NOT VERIFIED","actual_external_api_oauth_sns":0,
            "javascript_errors":errors,"external_browser_requests":external,
            "restart":"publisher coordinator reconstructed; same SQLite evidence, no successful-platform replay"}
    (output/'flow-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
