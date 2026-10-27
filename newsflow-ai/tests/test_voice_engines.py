import base64
from threading import Event

import pytest
from conftest import csrf

from newsflow.video.elevenlabs_tts import ElevenLabsTTS, alignment_cues, save_settings, settings
from newsflow.video.supertonic_assets import verify_file
from newsflow.video.tts import TTSError, wav_duration
from newsflow.video.voice_engines import provider_for, provider_name


class Keys:
    def key(self):
        return "synthetic-key-not-real-0001"


def config():
    return {"enabled": True, "voice_id": "syntheticVoice", "model": "eleven_multilingual_v2",
            "job_limit": 1000, "monthly_limit": 10000, "commercial": True}


class Transport:
    def __init__(self, error=False, **subscription):
        self.calls, self.error = [], error
        self.info = {"tier": "starter", "status": "active", "character_count": 0,
                     "character_limit": 10000, "max_credit_limit_extension": 0, **subscription}

    def __call__(self, method, path, payload=None):
        self.calls.append(method)
        if method == "GET":
            return self.info
        if self.error:
            raise TimeoutError("private upstream error")
        text = payload["text"]
        return {"audio_base64": base64.b64encode(b"\xe8\x03" * 24000).decode(), "alignment": {
            "characters": list(text), "character_start_times_seconds": [i * .05 for i in range(len(text))],
            "character_end_times_seconds": [(i + 1) * .05 for i in range(len(text))]}}


def test_elevenlabs_fake_timing_cache_and_no_key_leak(tmp_path):
    transport = Transport()
    provider = ElevenLabsTTS(tmp_path, config(), consent=True, transport=transport, keys=Keys())
    cues = provider.synthesize_timed("시험. 확인.", tmp_path / "first.wav", "elevenlabs", 30)
    assert len(cues) == 2 and wav_duration(tmp_path / "first.wav") == 1
    assert transport.calls == ["GET", "POST"]
    provider.synthesize_timed("시험. 확인.", tmp_path / "second.wav", "elevenlabs", 30)
    assert transport.calls == ["GET", "POST"]
    ledger = (tmp_path / "tts-elevenlabs/ledger.json").read_text(encoding="utf-8")
    assert Keys().key() not in ledger and "completed" in ledger


@pytest.mark.parametrize("account", [{"tier": "free"}, {"max_credit_limit_extension": "unlimited"},
                                    {"max_credit_limit_extension": 100}, {"character_limit": 1, "character_count": 1},
                                    {"status": "unknown"}, {"character_count": "0"}])
def test_elevenlabs_blocks_unapproved_or_unknown_account(tmp_path, account):
    transport = Transport(**account)
    provider = ElevenLabsTTS(tmp_path, config(), consent=True, transport=transport, keys=Keys())
    with pytest.raises(TTSError):
        provider.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30)
    assert "POST" not in transport.calls


def test_elevenlabs_timeout_never_replays(tmp_path):
    transport = Transport(error=True)
    provider = ElevenLabsTTS(tmp_path, config(), consent=True, transport=transport, keys=Keys())
    for _ in range(2):
        with pytest.raises(TTSError) as caught:
            provider.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30)
        assert "private" not in str(caught.value)
    assert transport.calls == ["GET", "POST"]
    assert "reserved" in (tmp_path / "tts-elevenlabs/ledger.json").read_text()


def test_elevenlabs_consent_cancel_and_reported_usage_policy(tmp_path):
    transport = Transport()
    provider = ElevenLabsTTS(tmp_path, config(), transport=transport, keys=Keys())
    with pytest.raises(TTSError):
        provider.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30)
    provider.consent = True
    cancel = Event()
    cancel.set()
    with pytest.raises(TTSError):
        provider.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30, cancel=cancel)
    assert transport.calls == []
    provider.config["job_limit"] = 1
    provider.synthesize_timed("시험.", tmp_path / "yes.wav", "elevenlabs", 30)
    assert transport.calls == ["GET", "POST"]


def test_free_plan_only_explicit_noncommercial(tmp_path):
    value = config()
    value["commercial"] = False
    provider = ElevenLabsTTS(tmp_path, value, consent=True, transport=Transport(tier="free"), keys=Keys())
    provider.synthesize_timed("시험.", tmp_path / "yes.wav", "elevenlabs", 30)
    assert provider.attribution_required


@pytest.mark.parametrize("alignment", [None, {"characters": ["X"]}, {
    "characters": ["시", "험"], "character_start_times_seconds": [0, float("nan")],
    "character_end_times_seconds": [.1, .2]}])
def test_alignment_rejects_fabricated_or_invalid_offsets(alignment):
    with pytest.raises(TTSError):
        alignment_cues("시험", alignment, 1)


def test_optional_engine_gui_and_settings_are_local(app, client, tmp_path):
    assert provider_name("supertonic:F1") == "supertonic"
    with pytest.raises(TTSError, match="동의"):
        provider_for("elevenlabs", app.state.sessions, tmp_path)
    token = csrf(client)
    assert client.get("/video/tts").status_code == 200
    page = client.get("/video/tts").text
    assert "ElevenLabs" in page
    assert "무료 플랜은 비상업용" in page
    assert "AI로 생성한 음성" in page
    assert "OpenRAIL-M" in page
    assert client.post("/video/tts/check", data={"csrf_token": token}).status_code == 422
    save_settings(app.state.sessions, **config())
    assert settings(app.state.sessions)["voice_id"] == "syntheticVoice"


def test_pinned_model_integrity_rejects_changes(tmp_path):
    path = tmp_path / "model.onnx"
    path.write_bytes(b"changed")
    assert not verify_file(path, {"size": 3, "sha256": "0" * 64})
