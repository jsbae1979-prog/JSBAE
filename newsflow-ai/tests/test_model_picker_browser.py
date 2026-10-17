"""Narrow, offline Chrome checks for the provider/model selection interaction."""

import html
import json
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

JS = Path(__file__).resolve().parents[1] / "src" / "newsflow" / "static" / "js"
MODELS = {"claude_api": "claude-sonnet-4-6", "openai": "gpt-4.1-mini", "offline": "offline"}
CHOICES = {
    "claude_api": [
        {"value": "claude-sonnet-4-6", "label": "Sonnet"},
        {"value": "claude-haiku-4-5-20251001", "label": "Haiku"},
    ],
    "openai": [{"value": "gpt-4.1-mini", "label": "GPT 4.1 mini"}],
    "offline": [{"value": "offline", "label": "Offline"}],
}


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(channel="chrome", headless=True)
        yield instance
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    requests = []
    context.route("**/*", lambda route: (requests.append(route.request.url), route.abort()))
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    context.close()
    assert not requests, "Changing models must not make a network request"
    assert not errors


def load_settings(page, *, stored="claude-sonnet-4-6"):
    models = dict(MODELS, claude_api=stored)
    page.set_content(f"""
        <form id="production-preferences" data-settings-watch
          data-studio-models='{html.escape(json.dumps(models), quote=True)}'
          data-studio-model-choices='{html.escape(json.dumps(CHOICES), quote=True)}'></form>
        <label>AI<select name="provider" form="production-preferences">
          <option value="claude_api" selected>Claude API</option>
          <option value="openai">OpenAI API</option><option value="offline">Offline</option>
        </select></label>
        <label>모델<select data-model-choice form="production-preferences"></select></label>
        <label data-custom-model>직접 입력<input name="model" form="production-preferences"
          value="{html.escape(stored, quote=True)}" required></label>
        <select name="voice" form="production-preferences">
          <option value="offline-silence" data-engine="offline">무음</option></select>
        <select name="video_provider" form="production-preferences"><option value="off">FFmpeg</option></select>
        <p id="production-unsaved" hidden>저장하지 않은 변경</p>
        <p data-settings-saved-label>저장됨</p>
        <button type="button" data-settings-reset hidden>변경 취소</button>
    """)
    page.add_script_tag(content=(JS / "claude_connection.js").read_text(encoding="utf-8"))
    page.add_script_tag(content=(JS / "production_settings.js").read_text(encoding="utf-8"))


def test_known_choices_preserve_each_provider_edits_and_submit_only_canonical_model(page):
    load_settings(page)
    picker = page.locator("[data-model-choice]")
    provider = page.locator("[name=provider]")
    model = page.locator("[name=model]")
    expect(picker).to_have_value("claude-sonnet-4-6")
    expect(page.locator("[data-custom-model]")).to_be_hidden()
    expect(page.locator("#production-unsaved")).to_be_hidden()
    picker.select_option("claude-haiku-4-5-20251001")
    expect(model).to_have_value("claude-haiku-4-5-20251001")
    expect(page.locator("#production-unsaved")).to_be_visible()
    assert page.evaluate("new FormData(document.getElementById('production-preferences')).getAll('model')") == [
        "claude-haiku-4-5-20251001"]
    provider.select_option("openai")
    expect(picker).to_have_value("gpt-4.1-mini")
    picker.select_option("__custom__")
    expect(model).to_have_value("gpt-4.1-mini")
    model.fill("my-existing-model")
    provider.select_option("claude_api")
    expect(picker).to_have_value("claude-haiku-4-5-20251001")
    provider.select_option("openai")
    expect(picker).to_have_value("__custom__")
    expect(model).to_be_visible()
    expect(model).to_have_value("my-existing-model")


def test_unknown_saved_model_stays_visible_and_is_never_replaced(page):
    load_settings(page, stored="claude-existing-custom-model")
    picker = page.locator("[data-model-choice]")
    model = page.locator("[name=model]")
    expect(picker).to_have_value("__custom__")
    expect(model).to_be_visible()
    expect(model).to_have_value("claude-existing-custom-model")
    expect(page.locator("#production-unsaved")).to_be_hidden()
    page.locator("[name=provider]").select_option("offline")
    page.locator("[name=provider]").select_option("claude_api")
    expect(picker).to_have_value("__custom__")
    expect(model).to_have_value("claude-existing-custom-model")


def test_settings_reset_restores_picker_and_provider_cache(page):
    load_settings(page)
    provider = page.locator("[name=provider]")
    picker = page.locator("[data-model-choice]")
    picker.select_option("claude-haiku-4-5-20251001")
    provider.select_option("openai")
    page.locator("[data-settings-reset]").click()
    expect(provider).to_have_value("claude_api")
    expect(picker).to_have_value("claude-sonnet-4-6")
    expect(page.locator("[name=model]")).to_have_value("claude-sonnet-4-6")
    expect(page.locator("#production-unsaved")).to_be_hidden()
    provider.select_option("openai")
    provider.select_option("claude_api")
    expect(picker).to_have_value("claude-sonnet-4-6")


def test_legacy_ai_studio_direct_input_still_works(page):
    page.set_content(f"""
        <form data-studio-models='{html.escape(json.dumps(MODELS), quote=True)}'>
          <select name="provider"><option value="claude_api">Claude API</option>
          <option value="openai">OpenAI API</option></select>
          <input name="model" value="claude-sonnet-4-6"><span data-studio-provider-label>Claude API</span>
        </form>
    """)
    page.add_script_tag(content=(JS / "claude_connection.js").read_text(encoding="utf-8"))
    page.locator("[name=model]").fill("legacy-custom")
    page.locator("[name=provider]").select_option("openai")
    expect(page.locator("[name=model]")).to_have_value("gpt-4.1-mini")
    page.locator("[name=provider]").select_option("claude_api")
    expect(page.locator("[name=model]")).to_have_value("legacy-custom")
