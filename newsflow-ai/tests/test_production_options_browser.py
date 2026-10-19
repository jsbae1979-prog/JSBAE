"""Real FFmpeg/Chrome with the existing ElevenLabs adapter and synthetic transport."""

import base64
import json
import os
import urllib.request
from pathlib import Path

from playwright.sync_api import expect
from test_api_news_pipeline import MODELS, FixtureKey
from test_api_news_pipeline import api_pipeline as pipeline_fixture
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import save_values
from test_voice_engines import Keys, config

from newsflow.db.models import ContentDraft, PublishDraft
from newsflow.gui import production_status
from newsflow.gui.routes import templates
from newsflow.intelligence.korean import speech_plan
from newsflow.intelligence.settings import write_studio_settings
from newsflow.publishing.media import FFprobeMediaInspector
from newsflow.video.elevenlabs_tts import ElevenLabsTTS, save_settings

api_pipeline = pipeline_fixture
browser = browser_fixture


def test_skip_review_elevenlabs_fake_to_real_mp4_final_review(app, api_pipeline, browser, monkeypatch, tmp_path):
    coordinator, backend, api, sessions, mode, rss = api_pipeline
    monkeypatch.setattr(app.state, "autopilot", coordinator)
    monkeypatch.setattr(app.state, "autopilot_backend", backend)
    monkeypatch.setattr(app.state, "api_keys", {"openai": FixtureKey(), "claude_api": FixtureKey()})
    monkeypatch.setattr(app.state, "ai_keys", FixtureKey())
    write_studio_settings(sessions, mode, MODELS[mode])
    save_values(app, video_default_voice="elevenlabs", video_ai_provider="off", autopilot_source="feeds",
                autopilot_acquisition_policy="ai_web")
    cfg = {**config(), "job_limit": 10000, "monthly_limit": 100000}
    save_settings(sessions, **cfg)
    complete = api.complete

    def sufficient_synthetic_script(evidence, seconds, options):
        result = complete(evidence, seconds, options)
        # The shared legacy Fake is deliberately short (20s). Supply a well-formed
        # synthetic 30s contract here; never weaken the product's short-script check.
        while speech_plan(result, seconds)["estimated_total_seconds"] < seconds * .90:
            plan = speech_plan(result, seconds)
            index = min(range(len(plan["scenes"])), key=lambda i: plan["scenes"][i]["estimated_seconds"])
            result["scenes"][index]["narration"] += " 살펴봅니다."
        assert speech_plan(result, seconds)["fits"]
        return result

    monkeypatch.setattr(api, "complete", sufficient_synthetic_script)
    calls, sent = [], []

    def transport(method, path, payload=None):
        calls.append((method, path))
        if method == "GET":
            return {"tier": "starter", "status": "active", "character_count": 0,
                    "character_limit": 100000, "max_credit_limit_extension": 0}
        text = payload["text"]
        sent.append(text)
        assert payload["model_id"] == cfg["model"]
        return {"audio_base64": base64.b64encode(b"\0\0" * 220800).decode(), "alignment": {
            "characters": list(text), "character_start_times_seconds": [i * 9.2 / len(text) for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) * 9.2 / len(text) for i in range(len(text))]}}

    # Existing adapter runs fully, including consent, account permissions, timed WAV and ledger.
    fake_tts = ElevenLabsTTS(backend.video.root, cfg, consent=True, transport=transport, keys=Keys())
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsTTS", lambda root, config, consent, **_kw: fake_tts)
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsKeys.key", lambda _: Keys().key())
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsKeys.status", lambda _: {"configured": True})
    monkeypatch.setattr(production_status, "voice_choice_catalog", lambda: [{
        "name": "elevenlabs", "label": "ElevenLabs · 합성 API 응답", "engine": "elevenlabs", "available": False}])
    monkeypatch.setitem(templates.env.globals, "ui_demo", True)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("No external HTTP")))
    output = Path(os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path / "evidence"))) / f"options-{mode}"
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ko-KR")
        context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + "/") else route.abort())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        assert page.goto(origin + "/create").status == 200
        expect(page.locator('[name="script_review"]')).to_be_checked()
        expect(page.locator('#quick-voice-method')).to_have_value("elevenlabs")
        page.locator('[name="script_review"]').uncheck()
        for width, height in ((1366, 768), (1920, 1080), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            for selector in ("#quick-voice-method", "#quick-video-method"):
                box = page.locator(selector).bounding_box()
                assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
        page.set_viewport_size({"width": 1366, "height": 768})
        page.locator('[data-workspace-create]').screenshot(path=str(output / "production-options.png"))
        expect(page.locator('form[action="/autopilot/quick-start"]')).to_have_attribute("data-easy-wired", "true")
        page.get_by_role("button", name="쇼츠 만들기", exact=True).click()
        page.wait_for_url(lambda url: "guide=consent" in url)
        form = page.locator('form[action="/autopilot/confirm-start"]')
        expect(form.locator('[name="external_tts_consent"]')).not_to_be_checked()
        # API-analysis consent alone cannot authorize paid voice synthesis.
        rejected = context.request.post(origin + "/autopilot/confirm-start", form={
            "csrf_token": form.locator('[name="csrf_token"]').input_value(),
            "flow": form.locator('[name="flow"]').input_value(), "consent": "true", "workspace": "true"})
        assert rejected.status == 422 and api.calls == calls == []
        form.locator('[name="consent"]').check()
        form.locator('[name="external_tts_consent"]').check()
        expect(form).to_have_attribute("data-easy-wired", "true")
        form.get_by_role("button", name="동의하고 제작 준비").click()
        page.wait_for_url(lambda url: "task=" in url)
        coordinator.future.result(timeout=240)
        identifier = page.url.split("task=", 1)[1].split("#", 1)[0]
        job = coordinator.snapshot(identifier)
        assert (job["status"], job["current_stage"]) == ("waiting_review", "validate"), job
        assert job["production_options"]["script_review"] is False and job["review_pauses"] == ["validate"]
        assert {k:v for k,v in job["production_options"]["elevenlabs"].items() if k != "credential_fingerprint"} == cfg
        assert api.calls == ["search", "analysis", "script"] and rss.calls == []
        assert len(sent) == 3 and [method for method, _ in calls] == ["GET", "POST"] * 3
        expect(page.locator('[data-autopilot-job]')).to_have_attribute("data-job-stage", "validate", timeout=15000)
        expect(page.locator('.creator-flow [aria-current="step"]')).to_contain_text('미리보기·최종 검토')
        expect(page.locator('[data-production-history] .progress-panel')).to_be_hidden()
        assert page.locator('[data-ai-production-history]').count() == 0
        player = page.locator('[data-workspace-detail] video').first
        player.evaluate("async v=>{v.muted=true;await v.play()}")
        page.wait_for_function("document.querySelector('[data-workspace-detail] video').currentTime > 0")
        player.evaluate("v=>v.pause()")
        expect(page.locator('[data-production-choices]')).to_contain_text("ElevenLabs")
        expect(page.locator('[data-production-choices]')).to_contain_text("생략")
        with sessions() as session:
            assert session.get(ContentDraft, job["content_draft_id"]).review_status == "review_required"
            assert session.query(PublishDraft).count() == 0  # Final human review still blocks queue creation.
        metadata = FFprobeMediaInspector().inspect(backend.video.outputs / job["output_name"])
        assert (metadata["width"], metadata["height"], metadata["video_codec"], metadata["audio_codec"]) == (1080, 1920, "h264", "aac")
        assert Keys().key() not in page.content() and not errors
        context.close()
    (output / "options-result.json").write_text(json.dumps({"status": "PASS", "provider": mode,
        "analysis_script_calls": api.calls, "voice": "ElevenLabs adapter + synthetic silent PCM transport",
        "voice_fake_posts": len(sent), "script_review": "skipped; automatic checks passed; not human verified",
        "final_review": "waiting; no publish draft", "media": metadata, "actual_external_calls": 0,
        "human_voice_quality": "NOT VERIFIED", "javascript_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
