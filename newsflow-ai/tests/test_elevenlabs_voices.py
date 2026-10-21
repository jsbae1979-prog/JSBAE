"""Fake-only voice catalog, named selection and pre-existing sample playback."""

import copy
import io
import json
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest
import test_elevenlabs_settings_links as settings_links
from conftest import csrf
from test_elevenlabs_settings_links import saved_values

from newsflow.intelligence.credentials import FakeCipher
from newsflow.news.rss_adapter import FeedError, PublicTransport, Response
from newsflow.video import elevenlabs_tts
from newsflow.video.elevenlabs_voices import ElevenLabsVoices, sample_url
from newsflow.video.tts import TTSError

KEY = "synthetic-elevenlabs-voice-list-key-0123456789"
URL = "https://storage.googleapis.com/eleven-public-prod/premade/voices/voiceA/sample.mp3"
KOREAN = URL.replace("sample.mp3", "korean.mp3")
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00"  # Transport fixture, not a playable or generated human voice.
isolated_store = settings_links.isolated_store


def payload(name="지민", voice_id="voiceA", **kwargs):
    voice = {"voice_id": voice_id, "name": name, "preview_url": URL,
             "sharing": {"owner_id": "do-not-cache", "email": "private@example.test"},
             "samples": [{"file_name": "private-sample.wav"}]}
    voice.update(kwargs)
    return {"voices": [voice], "has_more": False, "next_page_token": None}


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No real account, synthesis, CDN or HTTP requests in voice-picker tests")

    monkeypatch.delenv("NEWSFLOW_ELEVENLABS_KEY", raising=False)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(PublicTransport, "get", forbidden)
    monkeypatch.setattr(elevenlabs_tts.ElevenLabsTTS, "subscription", forbidden)
    monkeypatch.setattr(elevenlabs_tts.ElevenLabsTTS, "synthesize_timed", forbidden)


@pytest.fixture
def catalog(tmp_path):
    keys = elevenlabs_tts.ElevenLabsKeys(tmp_path, FakeCipher())
    keys.save(KEY)
    return ElevenLabsVoices(tmp_path, keys)


def test_explicit_single_page_lookup_filters_private_data_and_prefers_korean(catalog):
    calls = []
    data = payload(verified_languages=[{"language": "ko", "preview_url": KOREAN}])
    catalog.transport = lambda token: calls.append(token) or data
    assert catalog.cached()["voices"] == [] and calls == []
    result = catalog.load()
    assert calls == [None]
    assert result["voices"][0] == {"voice_id": "voiceA", "name": "지민", "preview_url": KOREAN,
                                    "sample_label": "한국어 샘플"}
    raw = (catalog.root / "voices.json").read_text(encoding="utf-8")
    assert all(private not in raw for private in (KEY, "do-not-cache", "private@example.test",
                                                 "private-sample.wav"))
    assert catalog.cached() == result and calls == [None]


def test_manual_pagination_one_call_per_action_and_no_automatic_retry(catalog):
    calls = []
    pages = [payload(), payload("다른 음성", "voiceB")]
    pages[0].update(has_more=True, next_page_token="cursor_2")
    catalog.transport = lambda token: calls.append(token) or pages[len(calls) - 1]
    catalog.load()
    assert calls == [None]  # Never follows has_more automatically.
    assert len(catalog.load(more=True)["voices"]) == 2
    assert calls == [None, "cursor_2"]
    with pytest.raises(TTSError, match="더 불러올"):
        catalog.load(more=True)
    assert calls == [None, "cursor_2"]


@pytest.mark.parametrize("bad", [{}, {"voices": [], "has_more": "false"},
    {"voices": [], "has_more": True},
    {"voices": [{"voice_id": "../bad", "name": "a"}], "has_more": False},
    {"voices": [{"voice_id": 123, "name": "a"}], "has_more": False},
    {"voices": [{"voice_id": "a", "name": ""}], "has_more": False}])
def test_invalid_response_preserves_last_catalog(catalog, bad):
    catalog.transport = lambda token: payload()
    before = catalog.load()
    catalog.transport = lambda token: bad
    with pytest.raises(TTSError):
        catalog.load()
    assert catalog.cached() == before


@pytest.mark.parametrize("url", ["http://storage.googleapis.com/eleven-public-prod/a.mp3",
    "https://127.0.0.1/a.mp3", "https://evil.test/eleven-public-prod/a.mp3",
    "https://storage.googleapis.com/other-bucket/a.mp3", URL + "?token=secret", URL + "#x",
    URL.replace("https://", "https://user:pass@"), URL.replace(".com/", ".com:444/"),
    URL.replace("sample", "../secret"), URL.replace("sample", "%2e%2e%2fsecret"),
    URL.replace("sample", "\\secret"), "//storage.googleapis.com/eleven-public-prod/a.mp3"])
def test_preview_allowlist_rejects_unsafe_urls_without_network(url):
    assert sample_url(url) is None


def test_unknown_sample_host_does_not_prevent_selection_but_never_fetches(catalog):
    catalog.transport = lambda token: payload(preview_url="https://unknown.test/sample.mp3")
    assert catalog.load()["voices"][0]["preview_url"] is None
    with pytest.raises(TTSError, match="공개 샘플"):
        catalog.prepare_sample("voiceA")


def test_cached_account_list_hidden_on_key_change_without_decryption(catalog, monkeypatch):
    catalog.transport = lambda token: payload()
    catalog.load()
    monkeypatch.setattr(catalog.keys, "key", lambda: pytest.fail("Page load must not decrypt a key"))
    assert catalog.cached()["voices"]
    catalog.keys.save("synthetic-replaced-elevenlabs-key-0123456789")
    assert not catalog.cached()["voices"]


def test_http_uses_v2_account_get_and_does_not_send_key_to_url(catalog, monkeypatch):
    calls = []

    def fake_open(self, request, timeout):
        calls.append((request, timeout))
        return io.BytesIO(json.dumps(payload()).encode())

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    catalog.load()
    request, timeout = calls[0]
    assert len(calls) == 1 and timeout == 30 and request.get_method() == "GET" and request.data is None
    assert urlsplit(request.full_url).path == "/v2/voices"
    assert parse_qs(urlsplit(request.full_url).query) == {"page_size": ["100"], "voice_type": ["saved"]}
    assert KEY not in request.full_url and request.get_header("Xi-api-key") == KEY


@pytest.mark.parametrize(("code", "message"), [(401, "인증 실패"), (403, "권한·플랜"),
                                               (429, "사용량·요청 제한"), (500, "조회 실패")])
def test_auth_permission_usage_errors_are_distinct_and_safe(catalog, monkeypatch, code, message):
    calls = []

    def fake_open(*args, **kwargs):
        calls.append(1)
        raise urllib.error.HTTPError("https://api.elevenlabs.io", code, KEY, {}, io.BytesIO(KEY.encode()))

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    with pytest.raises(TTSError, match=message) as exc:
        catalog.load()
    assert KEY not in str(exc.value) and calls == [1]


@pytest.mark.parametrize("response", [b"not-json", (KEY + "{}").encode(), b"x" * 4_000_001,
    json.dumps(payload(name=KEY)).replace("synthetic", "\\u0073ynthetic").encode()],
    ids=["not-json", "secret-echo", "oversize", "escaped-secret-echo"])
def test_bad_or_secret_echo_response_not_cached(catalog, monkeypatch, response):
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *a, **kw: io.BytesIO(response))
    with pytest.raises(TTSError):
        catalog.load()
    assert not (catalog.root / "voices.json").exists()


def test_timeout_one_attempt_and_no_secret_in_error(catalog, monkeypatch):
    calls = []

    def fake_open(*args, **kwargs):
        calls.append(1)
        raise TimeoutError(KEY)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    with pytest.raises(TTSError, match="시간 초과") as exc:
        catalog.load()
    assert calls == [1] and KEY not in str(exc.value)


@pytest.mark.parametrize("response", [Response(302, MP3, "https://127.0.0.1/"), Response(403, MP3),
    Response(200, b"<html>error</html>"), Response(200, b"ID3" + b"x" * (2 * 1024 * 1024))])
def test_bad_sample_fails_closed_without_changing_catalog(catalog, response, monkeypatch):
    catalog.transport = lambda token: payload()
    before = catalog.load()
    calls = []
    monkeypatch.setattr(PublicTransport, "get", lambda self, url, timeout: calls.append(url) or response)
    with pytest.raises(TTSError):
        catalog.prepare_sample("voiceA")
    assert calls == [URL] and catalog.cached() == before and not catalog.sample_path("voiceA").exists()


@pytest.fixture
def gui_catalog(app, isolated_store, monkeypatch):
    isolated_store.save(KEY)
    elevenlabs_tts.save_settings(app.state.sessions, enabled=True, voice_id="old-manual-id",
                               model="eleven_flash_v2_5", job_limit=777, monthly_limit=7777, commercial=False)
    calls = []
    monkeypatch.setattr(ElevenLabsVoices, "_http", lambda self, token: calls.append(token) or payload())
    return calls


def test_gui_get_load_and_named_save_keep_other_settings(client, app, gui_catalog, isolated_store):
    before, key_before = saved_values(app), isolated_store.path.read_bytes()
    response = client.get("/video/tts")
    assert response.status_code == 200 and gui_catalog == []
    assert 'value="old-manual-id"' in response.text
    token = csrf(client)
    assert client.post("/video/tts/voices/load", data={"csrf_token": token}).status_code == 422
    assert gui_catalog == []
    response = client.post("/video/tts/voices/load", data={"csrf_token": token, "consent": "true"})
    assert response.status_code == 200 and "지민" in response.text and gui_catalog == [None]
    assert saved_values(app) == before
    assert 'value="old-manual-id"' in response.text
    response = client.post("/video/tts/voices/select", data={"csrf_token": token, "voice_id": "voiceA"})
    assert response.status_code == 200 and "음성 선택을 저장했습니다" in response.text
    after = saved_values(app)
    assert after.pop("tts_el_voice_id") == '"voiceA"'
    expected = copy.copy(before)
    expected.pop("tts_el_voice_id")
    assert after == expected and isolated_store.path.read_bytes() == key_before and gui_catalog == [None]
    assert KEY not in response.text


def test_preview_only_downloads_after_explicit_post_and_get_is_local_only(
    client, app, gui_catalog, monkeypatch,
):
    token = csrf(client)
    client.post("/video/tts/voices/load", data={"csrf_token": token, "consent": "true"})
    before = saved_values(app)
    calls = []
    monkeypatch.setattr(PublicTransport, "get", lambda self, url, timeout:
                        calls.append((url, timeout)) or Response(200, MP3))
    assert client.get("/video/tts?sample=voiceA").status_code == 200
    assert client.get("/video/tts/voices/voiceA/sample").status_code == 404 and calls == []
    assert client.post("/video/tts/voices/preview", data={"csrf_token": token, "voice_id": "voiceA"}
                       ).status_code == 422 and calls == []
    response = client.post("/video/tts/voices/preview", data={"csrf_token": token, "voice_id": "voiceA",
                                                            "sample_consent": "true"})
    assert response.status_code == 200 and '<audio controls preload="none"' in response.text
    assert "autoplay" not in response.text and calls == [(URL, 15)]
    assert "media-src https:" not in response.headers["content-security-policy"]
    assert client.get("/video/tts/voices/voiceA/sample").content == MP3
    assert client.get("/video/tts/voices/voiceA/sample", headers={"sec-fetch-site": "cross-site"}
                      ).status_code == 403
    client.post("/video/tts/voices/preview", data={"csrf_token": token, "voice_id": "voiceA",
                                                "sample_consent": "true"})
    assert calls == [(URL, 15)] and saved_values(app) == before and gui_catalog == [None]


def test_gui_errors_keep_selection_and_csrf_origin_are_required(client, app, gui_catalog, monkeypatch):
    token, before = csrf(client), saved_values(app)
    for route in ("load", "select", "preview"):
        assert client.post("/video/tts/voices/" + route, data={"consent": "true"}).status_code == 403
        assert client.post("/video/tts/voices/" + route, headers={"origin": "https://evil.test"},
                           data={"csrf_token": token, "consent": "true"}).status_code == 403
    assert gui_catalog == []
    assert client.post("/video/tts/voices/select", data={"csrf_token": token, "voice_id": "unknown"}
                       ).status_code == 422

    def failed(self, token):
        raise TTSError("ElevenLabs API Key 인증 실패 · 자동 재시도 없음")

    monkeypatch.setattr(ElevenLabsVoices, "_http", failed)
    response = client.post("/video/tts/voices/load", data={"csrf_token": token, "consent": "true"})
    assert response.status_code == 422 and "인증 실패" in response.text and KEY not in response.text
    assert saved_values(app) == before


def test_missing_key_and_public_sample_network_errors_are_safe(catalog, monkeypatch):
    catalog.transport = lambda token: payload()
    catalog.load()

    def failed(*args, **kwargs):
        raise FeedError(KEY)

    monkeypatch.setattr(PublicTransport, "get", failed)
    with pytest.raises(TTSError, match="안전 검사") as exc:
        catalog.prepare_sample("voiceA")
    assert KEY not in str(exc.value)
    catalog.keys.clear()
    with pytest.raises(TTSError, match="미등록"):
        catalog.load()


def test_voice_name_is_escaped_and_saved_selection_survives_catalog_failure(client, gui_catalog, monkeypatch):
    monkeypatch.setattr(ElevenLabsVoices, "_http", lambda self, token: payload(name='<img src=x onerror=bad()>'))
    token = csrf(client)
    response = client.post("/video/tts/voices/load", data={"csrf_token": token, "consent": "true"})
    assert response.status_code == 200 and "&lt;img" in response.text and "<img src=x" not in response.text
    client.post("/video/tts/voices/select", data={"csrf_token": token, "voice_id": "voiceA"})

    def failed(self, token):
        raise TTSError("ElevenLabs 사용량·요청 제한 · 자동 재시도 없음")

    monkeypatch.setattr(ElevenLabsVoices, "_http", failed)
    response = client.post("/video/tts/voices/load", data={"csrf_token": token, "consent": "true"})
    assert response.status_code == 422 and "&lt;img" in response.text
    assert 'value="voiceA" selected' in response.text


def test_template_remains_compatible_with_running_pre_restart_route(client, app, gui_catalog, monkeypatch):
    from newsflow.gui import video_routes
    from newsflow.gui.routes import page

    # The existing server can read an updated template before its route code is restarted.
    def old_page(request, **kwargs):
        return page(request, "tts_settings.html", active="video", models=elevenlabs_tts.MODELS,
                    config=elevenlabs_tts.settings(app.state.sessions),
                    key={"configured": True}, supertonic_ready=False)

    monkeypatch.setattr(video_routes, "_tts_page", old_page)
    response = client.get("/video/tts")
    assert response.status_code == 200 and 'action="/video/tts/key"' in response.text
    assert 'action="/video/tts/voices/load"' not in response.text and gui_catalog == []
