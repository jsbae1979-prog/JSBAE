import io
import json
import urllib.error

import pytest
from test_voice_engines import Keys, Transport, config

from newsflow.video.elevenlabs_tts import ElevenLabsTTS, PaymentRequiredError, rejected_payment
from newsflow.video.tts import TTSError


def test_402_annotation_preserves_reservation_and_only_new_voice_can_proceed(tmp_path):
    base = Transport(tier="free", status="free")
    reject = True

    def transport(method, path, payload=None):
        if method == "POST" and reject:
            base.calls.append(method)
            raise PaymentRequiredError()
        return base(method, path, payload)

    cfg = {**config(), "commercial": False}
    tts = ElevenLabsTTS(tmp_path, cfg, consent=True, transport=transport, keys=Keys())
    with pytest.raises(PaymentRequiredError):
        tts.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30)
    path = tmp_path / "tts-elevenlabs/ledger.json"
    rejected = json.loads(path.read_text())
    assert len(rejected) == 1
    record = next(iter(rejected.values()))
    assert record["state"] == "reserved" and record["credits"] == 0
    assert record["accounting"] == "reported_usage" and record["reported_credits"] is None
    assert record["vendor_billing"] == "NOT VERIFIED"
    assert rejected_payment(record)
    reject = False
    # The rejected request is never automatically submitted again.
    with pytest.raises(TTSError):
        tts.synthesize_timed("시험.", tmp_path / "retry.wav", "elevenlabs", 30)
    assert base.calls == ["GET", "POST"]
    tts.config = {**cfg, "voice_id": "differentDefaultVoice"}
    tts.synthesize_timed("시험.", tmp_path / "new.wav", "elevenlabs", 30)
    now = json.loads(path.read_text())
    assert len(now) == 2 and all(now[k] == v for k, v in rejected.items())
    assert base.calls == ["GET", "POST", "GET", "POST"]


@pytest.mark.parametrize("marker", [None, {"http_status": 500, "code": "payment_required"},
                                  {"http_status": 402, "code": "unknown"}])
def test_unknown_outcomes_still_block_every_new_voice(tmp_path, marker):
    transport = Transport()
    tts = ElevenLabsTTS(tmp_path, config(), consent=True, transport=transport, keys=Keys())
    tts.root.mkdir()
    record = {"state": "reserved", "credits": 12, "month": "2026-10", "provider_rejection": marker}
    path = tts.root / "ledger.json"
    path.write_text(json.dumps({"prior": record}))
    with pytest.raises(TTSError, match="결과 불명"):
        tts.synthesize_timed("새 문장.", tmp_path / "no.wav", "elevenlabs", 30)
    assert transport.calls == []
    assert json.loads(path.read_text()) == {"prior": record}


def test_402_http_maps_to_safe_fixed_error_without_retry(tmp_path, monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.get_method())
            raise urllib.error.HTTPError("https://api.elevenlabs.io/", 402, "secret-message",
                                         {}, io.BytesIO(b"secret-body"))

    monkeypatch.setattr("urllib.request.build_opener", lambda *args: Opener())
    tts = ElevenLabsTTS(tmp_path, config(), consent=True, keys=Keys())
    with pytest.raises(PaymentRequiredError) as error:
        tts._http("POST", "/text-to-speech/syntheticVoice", {"text": "시험."})
    assert calls == ["POST"] and "402" in str(error.value) and "secret" not in str(error.value)


def test_legacy_402_credits_and_record_are_preserved_when_new_voice_is_used(tmp_path):
    transport = Transport(tier="free", status="free")
    cfg = {**config(), "commercial": False}
    tts = ElevenLabsTTS(tmp_path, cfg, consent=True, transport=transport, keys=Keys())
    tts.root.mkdir()
    legacy = {"state": "reserved", "credits": 6, "month": "2026-10",
              "provider_rejection": {"http_status": 402, "code": "payment_required"}}
    ledger = tts.root / "ledger.json"
    ledger.write_text(json.dumps({"legacy-request": legacy}), encoding="utf-8")
    assert rejected_payment(legacy)
    tts.synthesize_timed("새 문장.", tmp_path / "new.wav", "elevenlabs", 30)
    result = json.loads(ledger.read_text(encoding="utf-8"))
    assert result["legacy-request"] == legacy and len(result) == 2
    assert transport.calls == ["GET", "POST"]
