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
    assert "무음 검토영상" in page.text and "다른 언어 음성으로 몰래 대체하지 않습니다" in page.text
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
