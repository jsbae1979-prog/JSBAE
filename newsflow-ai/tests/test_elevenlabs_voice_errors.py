"""Safe list diagnostics and real JS error display with fake providers/temporary data only."""

import io
import json
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import test_elevenlabs_voices as voices_tests
from conftest import csrf
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_elevenlabs_settings_links import saved_values
from test_model_picker_browser import browser as browser_fixture

from newsflow.intelligence.credentials import CredentialError
from newsflow.video.elevenlabs_voices import ElevenLabsVoices, VoiceListError
from newsflow.video.tts import TTSError

browser = browser_fixture
catalog = voices_tests.catalog
isolated_store = voices_tests.isolated_store
no_real_network = voices_tests.no_real_network
KEY = voices_tests.KEY
EVIDENCE = Path(__file__).resolve().parents[1] / "validation-output/elevenlabs-401-subcodes-20261020"


@pytest.mark.parametrize(("failure", "code", "status", "message"), [
    (401, "http", 401, "API Key 인증 실패"),
    (403, "http", 403, "음성 조회 권한·플랜 확인 필요"),
    (429, "http", 429, "사용량·요청 제한"),
    (500, "http", 500, "음성 조회 실패"),
    ("timeout", "timeout", None, "시간 초과"),
    ("network", "network", None, "연결·TLS 오류"),
    ("key", "key_store", None, "API Key 읽기 실패"),
    ("json", "response", None, "응답 형식·안전 검사 실패"),
])
def test_safe_failure_classification_retention_and_no_retry(catalog, monkeypatch, failure, code, status, message):
    calls = []

    def fake_open(*args, **kwargs):
        calls.append(1)
        if isinstance(failure, int):
            raise urllib.error.HTTPError("https://api.elevenlabs.io", failure, KEY, {}, io.BytesIO(KEY.encode()))
        if failure == "timeout":
            raise urllib.error.URLError(TimeoutError(KEY))
        if failure == "network":
            raise urllib.error.URLError(KEY)
        return io.BytesIO(b"invalid-json " + KEY.encode())

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    if failure == "key":
        def broken_key():
            raise CredentialError(KEY)
        monkeypatch.setattr(catalog.keys, "key", broken_key)
    with pytest.raises(VoiceListError, match=message) as exc:
        catalog.load()
    assert exc.value.code == code and exc.value.http_status == status and KEY not in str(exc.value)
    assert calls == ([] if failure == "key" else [1])
    catalog.record_failure(exc.value)
    catalog.record_failure(TTSError("untrusted text must never be recorded: " + KEY))
    records = [json.loads(p.read_text()) for p in (catalog.root / "diagnostics").glob("*.json")]
    assert len(records) == 2  # An older diagnostic is retained, not replaced.
    assert any(r["failure_code"] == code and r["provider_http_status"] == status for r in records)
    assert all(set(r) == {"operation", "failure_code", "provider_http_status", "provider_error_code",
                          "recorded_at"} for r in records)
    assert KEY not in json.dumps(records) and "untrusted" not in json.dumps(records)
    assert not (catalog.root / "voices.json").exists()


def test_list_route_returns_identifiable_safe_html_and_retains_diagnostic(client, app, isolated_store, monkeypatch):
    isolated_store.save(KEY)
    before, key_bytes = saved_values(app), isolated_store.path.read_bytes()

    def failed(self, token):
        raise VoiceListError("http", 403)

    monkeypatch.setattr(ElevenLabsVoices, "_http", failed)
    response = client.post("/video/tts/voices/load", data={"csrf_token": csrf(client), "consent": "true"})
    assert response.status_code == 422 and 'id="elevenlabs-voice-error"' in response.text
    assert "공급사 HTTP 403" in response.text and "권한·플랜" in response.text and KEY not in response.text
    records = list((app.state.video.root / "tts-elevenlabs/diagnostics").glob("*.json"))
    assert len(records) == 1 and json.loads(records[0].read_text())["provider_http_status"] == 403
    assert saved_values(app) == before and isolated_store.path.read_bytes() == key_bytes


@pytest.mark.parametrize(("failure", "expected"), [
    (401, "API Key 인증 실패"), (403, "음성 조회 권한·플랜 확인 필요"),
    (429, "사용량·요청 제한"), ("timeout", "시간 초과"),
    ("json", "응답 형식·안전 검사 실패"),
    ("validation_json", "음성 목록 요청을 확인하지 못했습니다"),
    ("invalid_key", "오류 코드 invalid_api_key"),
    ("permission", "오류 코드 insufficient_permissions"),
])
def test_chrome_displays_safe_list_error_once_and_keeps_settings(
    app, browser, isolated_store, monkeypatch, failure, expected,
):
    isolated_store.save(KEY)
    before, key_bytes = saved_values(app), isolated_store.path.read_bytes()
    calls, posts, external, errors = [], [], [], []

    def fake_open(*args, **kwargs):
        calls.append(1)
        if isinstance(failure, int):
            raise urllib.error.HTTPError("https://api.elevenlabs.io", failure, KEY, {}, io.BytesIO(KEY.encode()))
        if failure in ("invalid_key", "permission"):
            detail = ({"status": "invalid_api_key"} if failure == "invalid_key"
                      else {"code": "insufficient_permissions", "status": "invalid_api_key"})
            detail["message"] = "Secret must not be displayed: " + KEY
            raise urllib.error.HTTPError("https://api.elevenlabs.io", 401, KEY, {},
                                         io.BytesIO(json.dumps({"detail": detail}).encode()))
        if failure == "timeout":
            raise TimeoutError(KEY)
        return io.BytesIO(b"invalid-json " + KEY.encode())

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    with local_server(app) as origin:
        context = browser.new_context(viewport={"width": 1366, "height": 900}, locale="ko-KR")

        def guard(route):
            url = urlsplit(route.request.url)
            if url.netloc != urlsplit(origin).netloc:
                external.append(route.request.url)
                route.abort()
            elif route.request.method == "POST":
                assert url.path == "/video/tts/voices/load"
                posts.append(url.path)
                if failure == "validation_json":
                    route.fulfill(status=422, content_type="application/json",
                                  body=json.dumps({"detail": [{"input": KEY}]}))
                else:
                    route.continue_()
            else:
                route.continue_()

        context.route("**/*", guard)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        try:
            assert page.goto(origin + "/video/tts").status == 200
            form = page.locator('form[action="/video/tts/voices/load"]')
            form.locator('[name="consent"]').check()
            submit = form.get_by_role("button", name="음성 목록 불러오기", exact=True)
            submit.click()
            alert = form.locator('[data-submit-error]')
            expect(alert).to_contain_text(expected)
            expect(alert).to_be_focused()
            expect(submit).to_be_enabled()
            expect(form.locator('[name="consent"]')).to_be_checked()
            assert "입력값과 필수 확인 항목" not in alert.inner_text()
            assert KEY not in page.locator("body").inner_text()
            assert posts == ["/video/tts/voices/load"] and calls == ([] if failure == "validation_json" else [1])
            assert external == [] and errors == []
            if failure == "permission":
                EVIDENCE.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(EVIDENCE / "fake-401-permission-chrome.png"), full_page=True)
        finally:
            context.close()
    assert saved_values(app) == before and isolated_store.path.read_bytes() == key_bytes
    assert not (app.state.video.root / "tts-elevenlabs/voices.json").exists()
