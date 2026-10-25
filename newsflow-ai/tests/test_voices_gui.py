"""Korean voice settings page, preview synthesis boundaries and saved speech preferences."""

from __future__ import annotations

import wave

import pytest
from conftest import csrf

from newsflow.db.models import AppSetting
from newsflow.easy_setup import speech_preferences
from newsflow.video.tts import PREVIEW_TEXT, SpeechSettings, TTSError


class KoreanFakeTTS:
    def __init__(self) -> None:
        self.calls = []

    def voices(self):
        return ["Fake Korean Voice"]

    def preview(self, target, voice, speech=None):
        self.calls.append((voice, speech))
        with wave.open(str(target), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x10\x10" * 16000)
        return 1.0


@pytest.fixture
def korean(monkeypatch, app):
    monkeypatch.setattr("newsflow.gui.voice_routes.voice_catalog", lambda: [{"name": "Fake Korean Voice", "culture": "ko-KR"}, {"name": "English", "culture": "en-US"}])
    monkeypatch.setattr("newsflow.easy_setup.voice_catalog", lambda: [{"name": "Fake Korean Voice", "culture": "ko-KR"}])
    app.state.video.tts = KoreanFakeTTS()
    return app.state.video.tts


def test_page_without_voices_explains_install_and_keeps_silent_default(client, monkeypatch):
    monkeypatch.setattr("newsflow.gui.voice_routes.voice_catalog", list)
    page = client.get("/voices")
    assert page.status_code == 200 and 'id="voice-install-guide"' in page.text
    assert "무음 검토영상" in page.text and "선택한 음성이 없으면 제작을 멈춥니다" in page.text
    assert client.post("/voices/preview", data={"csrf_token": csrf(client), "voice": "offline-silence"}).status_code == 422


def test_save_preferences_validates_voice_rate_and_pause(client, app, korean):
    token = csrf(client)
    assert client.post("/voices", data={"csrf_token": token, "voice": "English", "rate": "0", "pause_ms": "250"}).status_code == 422
    assert client.post("/voices", data={"csrf_token": token, "voice": "Fake Korean Voice", "rate": "9", "pause_ms": "250"}).status_code == 422
    saved = client.post("/voices", data={"csrf_token": token, "voice": "Fake Korean Voice", "rate": "2", "pause_ms": "400"})
    assert saved.status_code == 200 and "음성 설정을 저장했습니다" in saved.text
    assert speech_preferences(app.state.sessions) == SpeechSettings(2, 400)
    with app.state.sessions() as session:
        assert session.get(AppSetting, "video_default_voice").value == "Fake Korean Voice"
    assert "현재 선택: Fake Korean Voice" in client.get("/voices").text


def test_preview_uses_fixed_sample_text_and_serves_only_generated_file(client, app, korean):
    token = csrf(client)
    response = client.post("/voices/preview", data={"csrf_token": token, "voice": "Fake Korean Voice", "rate": "-1", "pause_ms": "150"})
    assert response.status_code == 200 and "<audio" in response.text
    assert korean.calls == [("Fake Korean Voice", SpeechSettings(-1, 150))]
    name = response.url.params["preview"]
    audio = client.get(f"/voices/preview/{name}")
    assert audio.status_code == 200 and audio.headers["content-type"].startswith("audio/wav")
    assert client.get("/voices/preview/../newsflow.db").status_code in {404, 422}
    assert client.get("/voices/preview/preview-notahex.wav").status_code == 404
    assert client.post("/voices/preview", data={"csrf_token": token, "voice": "English"}).status_code == 422
    assert PREVIEW_TEXT.startswith("안녕하세요")


def test_preview_failure_is_safe(client, app, korean):
    def broken(*args, **kwargs):
        raise TTSError("음성이 생성되지 않았습니다. 선택한 음성이 한국어 문장을 읽는지 확인하세요.")

    korean.preview = broken
    response = client.post("/voices/preview", data={"csrf_token": csrf(client), "voice": "Fake Korean Voice"})
    assert response.status_code == 422 and "음성이 생성되지 않았습니다" in response.text


# --- Phase 5C.1 package C: detection states, spoken sample and the human listening record ---

import hashlib
import json
import re

from newsflow.easy_setup import LISTENING_ITEMS, diagnostics
from newsflow.gui import voice_routes
from newsflow.video.speech_text import normalize_for_speech
from newsflow.video.tts import TTSPolicyError, WindowsTTS

ONECORE = {"state": "onecore_only", "sapi": [], "onecore_only": ["Microsoft Heami"], "registry_read": "ok"}
BLOCKED = {"state": "blocked_policy", "sapi": [], "onecore_only": [], "registry_read": "unavailable"}


def test_page_shows_raw_and_spoken_sample_and_default_listening_status(client, monkeypatch):
    monkeypatch.setattr("newsflow.gui.voice_routes.voice_catalog", list)
    text = client.get("/voices").text
    assert 'id="sample-text"' in text and 'id="sample-spoken"' in text and "읽기 형태 (음성에 전달되는 문장)" in text
    assert PREVIEW_TEXT in text and normalize_for_speech(PREVIEW_TEXT) in text
    assert "2026년 10월 15일 14시 30분 기준 코스피는 3.5퍼센트" in text and "125만 달러입니다" in text
    assert 'id="listening-status"' in text and "사람 청취 결과: NOT VERIFIED" in text
    assert 'action="/voices/listening"' in text and "청취 결과 기록" in text


def test_onecore_only_shows_pending_chip_and_guide(client, monkeypatch):
    monkeypatch.setattr("newsflow.gui.voice_routes._voices", lambda: ([], [], "onecore_only", ONECORE))
    text = client.get("/voices").text
    assert 'class="status-chip pending">한국어 음성 1개 설치됨 · SAPI 미노출</span>' in text
    assert 'status-chip ready">한국어' not in text
    assert 'id="voice-onecore-guide"' in text and "Microsoft Heami" in text and "UNCERTAIN" in text
    assert "절대 수정하지 않" in text and "무음 검토영상 유지" in text and "한국어 음성 팩 재설치" in text
    assert 'id="voice-install-guide"' in text and "run.bat를 다시 실행하세요" in text
    assert "선택한 음성이 없으면 제작을 멈춥니다" in text
    assert text.count("<option") >= 1 and 'value="Microsoft Heami"' not in text  # never offered for selection


def test_blocked_policy_shows_policy_guide_and_app_changes_nothing(client, monkeypatch):
    monkeypatch.setattr("newsflow.gui.voice_routes._voices", lambda: ([], [], "blocked_policy", BLOCKED))
    text = client.get("/voices").text
    assert 'id="voice-policy-guide"' in text and "Get-ExecutionPolicy -List" in text
    assert "Set-ExecutionPolicy -Scope CurrentUser RemoteSigned" in text and "읽지도 바꾸지도 않" in text
    assert "한국어 음성 0개 확인 불가" in text and 'id="voice-onecore-guide"' not in text


def test_voices_composition_consults_registry_only_on_windows_without_korean_sapi(monkeypatch):
    monkeypatch.setattr(voice_routes, "voice_catalog", lambda: [{"name": "English", "culture": "en-US"}])
    monkeypatch.setattr(voice_routes, "_windows", lambda: True)
    monkeypatch.setattr(WindowsTTS, "korean_voice_report", lambda self, sapi=None: dict(ONECORE))
    _catalog, korean, state, report = voice_routes._voices()
    assert state == "onecore_only" and korean == [] and report["onecore_only"] == ["Microsoft Heami"]
    calls = []
    monkeypatch.setattr(voice_routes, "voice_catalog", lambda: [{"name": "Fake Korean Voice", "culture": "ko-KR"}])
    monkeypatch.setattr(WindowsTTS, "korean_voice_report", lambda self, sapi=None: calls.append(1) or dict(ONECORE))
    assert voice_routes._voices()[2] == "available" and not calls
    monkeypatch.setattr(voice_routes, "_windows", lambda: False)
    monkeypatch.setattr(voice_routes, "voice_catalog", list)
    assert voice_routes._voices()[2] == "not_installed" and not calls

    def blocked():
        raise TTSPolicyError("정책")

    monkeypatch.setattr(voice_routes, "voice_catalog", blocked)
    assert voice_routes._voices()[2:] == ("blocked_policy", BLOCKED)


def listening_form(client, **overrides):
    data = {"csrf_token": csrf(client), "listener": "홍길동", "voice": "Fake Korean Voice", "rate": "0",
            "pause_ms": "250", "verdict": "pass", "notes": "또렷하게 들림"}
    data.update({key: "ok" for key in LISTENING_ITEMS})
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


@pytest.mark.parametrize("overrides", [
    {"listener": ""}, {"listener": "   "}, {"listener": "a\x00b"}, {"listener": "가" * 41},
    {"clarity": "maybe"}, {"numbers": None}, {"subtitle_sync": ""},
    {"verdict": "pass", "numbers": "bad"}, {"verdict": "pass", "english": "bad", "notes": "그래도 통과?"},
    {"verdict": "pass", "dates": "unknown"}, {"listener": "김 · 철수"}, {"voice": "가 · 나"},
    {"verdict": "excellent"}, {"verdict": None}, {"rate": "9"}, {"pause_ms": "1"},
    {"preview": "../newsflow.db"}, {"preview": "preview-notahex.wav"}, {"notes": "x" * 501}, {"voice": "v" * 201},
])
def test_listening_record_rejected(client, app, korean, overrides):
    assert client.post("/voices/listening", data=listening_form(client, **overrides)).status_code == 422
    directory = app.state.config.data_dir / "voice-listening"
    assert not directory.exists() or not list(directory.glob("listening-*.json"))
    with app.state.sessions() as session:
        assert session.get(AppSetting, "voice_listening_last") is None
    assert "사람 청취 결과: NOT VERIFIED" in client.get("/voices").text


def test_listening_record_requires_csrf(client, korean):
    assert client.post("/voices/listening", data={"listener": "홍길동"}).status_code == 403


def test_listening_record_persists_file_setting_and_summary(client, app, korean):
    response = client.post("/voices/preview", data={"csrf_token": csrf(client), "voice": "Fake Korean Voice", "rate": "0", "pause_ms": "250"})
    name = response.url.params["preview"]
    result = client.post("/voices/listening", data=listening_form(client, preview=name, verdict="fail", numbers="bad"))
    assert result.status_code == 200 and "청취 결과를 기록했습니다" in result.text
    assert "사람 청취 결과: FAIL (" in result.text and "홍길동)" in result.text
    files = list((app.state.config.data_dir / "voice-listening").glob("listening-*.json"))
    assert len(files) == 1 and re.fullmatch(r"listening-[0-9a-f]{32}\.json", files[0].name)
    record = json.loads(files[0].read_text(encoding="utf-8"))
    assert record["verdict"] == "fail" and record["items"]["numbers"] == "bad" and record["listener"] == "홍길동"
    assert record["voice"] == "Fake Korean Voice" and record["rate"] == 0 and record["pause_ms"] == 250
    assert record["preview"] == name and record["recorded_by"] == "human"
    wav = app.state.config.data_dir / "voice-preview" / name
    assert record["preview_sha256"] == hashlib.sha256(wav.read_bytes()).hexdigest()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", record["created_at"])
    with app.state.sessions() as session:
        value = session.get(AppSetting, "voice_listening_last").value
    assert value == f"fail · {record['created_at'][:10]} · 홍길동 · Fake Korean Voice"
    quality = diagnostics(app.state.config.data_dir, app.state.sessions)["quality"]
    assert quality == f"사람 청취 결과: FAIL ({record['created_at'][:10]}, 홍길동)"
    # a later PASS record (all items accurate) replaces the summary; the app never derives it
    passed = client.post("/voices/listening", data=listening_form(client, preview=name))
    assert passed.status_code == 200 and "사람 청취 결과: PASS (" in passed.text
    assert len(list((app.state.config.data_dir / "voice-listening").glob("listening-*.json"))) == 2
