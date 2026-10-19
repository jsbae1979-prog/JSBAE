"""Existing workspace and approval screens, no API keys/accounts outside test fixtures."""

import os
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import test_all_scene_production as flows
from playwright.sync_api import expect
from test_api_news_pipeline import MODELS, FixtureKey
from test_cloud_workspace_flow import local_server
from test_model_picker_browser import browser as browser_fixture
from test_single_workspace import save_values

from newsflow.gui import production_status
from newsflow.gui.routes import templates
from newsflow.intelligence.settings import write_studio_settings

api_pipeline = flows.api_pipeline
production = flows.production
browser = browser_fixture


def test_workspace_all_ai_voice_approval_to_original_task_preview(production, browser, monkeypatch, tmp_path):
    p = production
    app, coordinator = p["app"], p["coordinator"]
    monkeypatch.setattr(app.state, "api_keys", {"openai": FixtureKey(), "claude_api": FixtureKey()})
    monkeypatch.setattr(app.state, "ai_keys", FixtureKey())
    monkeypatch.setattr("newsflow.video.elevenlabs_tts.ElevenLabsKeys.status", lambda _: {"configured": True})
    monkeypatch.setattr(production_status, "voice_choice_catalog", lambda: [{
        "name": "supertonic:F1", "label": "Supertonic · 합성 응답", "engine": "supertonic", "available": True}])
    monkeypatch.setitem(templates.env.globals, "ui_demo", True)
    write_studio_settings(p["sessions"], p["mode"], MODELS[p["mode"]])
    save_values(app, autopilot_source="feeds", autopilot_acquisition_policy="ai_web")
    output = Path(os.environ.get("NEWSFLOW_VALIDATION_OUTPUT", str(tmp_path)))
    output.mkdir(parents=True, exist_ok=True)
    with local_server(app) as origin:
        ctx = browser.new_context(viewport={"width": 1366, "height": 768}, locale="ko-KR")
        external, errors = [], []
        def guard(route):
            if urlsplit(route.request.url).netloc == urlsplit(origin).netloc:
                route.continue_()
            else:
                external.append(route.request.url)
                route.abort()
        ctx.route("**/*", guard)
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        assert page.goto(origin + "/create").status == 200
        expect(page.locator('[name="script_review"]')).to_be_checked()
        page.locator('[name="script_review"]').uncheck()
        page.locator('#quick-voice-method').select_option("elevenlabs")
        page.locator('#quick-video-method').select_option("higgsfield")
        for width, height in ((1366, 768), (1920, 1080), (390, 844)):
            page.set_viewport_size({"width": width, "height": height})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.set_viewport_size({"width": 1366, "height": 768})
        expect(page.locator('form[action="/autopilot/quick-start"]')).to_have_attribute("data-easy-wired", "true")
        page.get_by_role("button", name="쇼츠 만들기", exact=True).click()
        page.wait_for_url(lambda u: "guide=consent" in u)
        form = page.locator('form[action="/autopilot/confirm-start"]')
        expect(form).to_have_attribute("data-easy-wired", "true")
        form.locator('[name="consent"]').check()
        form.locator('[name="external_tts_consent"]').check()
        form.get_by_role("button", name="동의하고 제작 준비").click()
        page.wait_for_url(lambda u: "task=" in u)
        identifier = parse_qs(urlsplit(page.url).query)["task"][0]
        job = flows.settle(p, identifier)
        assert (job["status"], job["current_stage"]) == ("waiting_review", "render"), job
        assert p["fake"].calls == [] and p["voice_calls"] == []
        page.goto(origin + f'/?task={identifier}#workspace-detail')
        page.get_by_role("link", name="AI 장면 계획·승인 열기 →", exact=True).click()
        plan_id = job["ai_plan_id"]
        page.wait_for_url(f"**/video/ai/plans/{plan_id}")
        for index in range(3):
            assert page.locator(f'#source-{index} option').count() == 1
            page.locator(f'#model-{index}').select_option(flows.MODEL)
        with page.expect_navigation(wait_until="load"):
            page.get_by_role("button", name="장면 설정 저장", exact=True).click()
        expect(page.locator('#cost-form')).to_be_visible()
        page.locator('#cost-form input[name="confirmed"]').check()
        with page.expect_navigation(wait_until="load"):
            page.get_by_role("button", name="유료 생성 요청", exact=True).click()
        for _ in range(8):
            p["service"].tick()
        page.goto(origin + f'/video/ai/plans/{plan_id}')
        for index in range(3):
            page.locator(f'[name="reviewed_{index}"]').check()
        page.locator('#relation-review [name="statement"]').check()
        with page.expect_navigation(wait_until="load"):
            page.get_by_role("button", name="관계 검토 저장", exact=True).click()
        expect(page.locator('#compose-voice-context')).to_contain_text("elevenlabs")
        assert "동시 합성은 지원하지 않습니다" not in page.locator('#compose-voice-context').inner_text()
        page.locator('#compose-voice-context').screenshot(path=str(output / f'ai-voice-scope-{p["mode"]}.png'))
        page.locator('#compose-form [name="approved"]').check()
        with page.expect_navigation(wait_until="load"):
            page.get_by_role("button", name="최종 합성 시작", exact=True).click()
        p["backend"].video.future.result(timeout=240)
        p["service"].sync()
        coordinator.future.result(timeout=60)
        job = coordinator.snapshot(identifier)
        assert (job["status"], job["current_stage"]) == ("waiting_review", "validate"), job
        page.goto(origin + f'/?task={identifier}#workspace-detail')
        video = page.locator('[data-workspace-player]').first
        expect(video).to_be_visible()
        video.evaluate("async v=>{v.muted=true;await v.play()}")
        page.wait_for_function("document.querySelector('[data-workspace-player]').currentTime > 0")
        video.evaluate("v=>v.pause()")
        page.locator('#workspace-detail').screenshot(path=str(output / f'ai-final-review-{p["mode"]}.png'))
        assert not errors and not external
        assert len([c for c in p["voice_calls"] if c[0] == "POST"]) == 3
        assert len([c for c in p["fake"].calls if c[0] == "submit"]) == 3
        ctx.close()
