"""Subscription policy regression: fake responses only, never real credentials."""
import base64
import json

import pytest

from newsflow.db.models import NewsArticle, RenderJob
from newsflow.intelligence.service import IntelligenceService
from newsflow.video.elevenlabs_tts import ElevenLabsTTS, SubscriptionError
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS, TTSError


class Keys:
    def key(self):
        return "synthetic-key-not-real"


class Transport:
    def __init__(self, **changes):
        # Exact nonsecret field values from the failed free-account preflight.
        self.info = {"tier": "free", "status": "free", "character_count": 518,
                     "character_limit": 10000, "max_credit_limit_extension": 0, **changes}
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path))
        if method == "GET":
            assert path == "/user/subscription"
            return self.info
        text = payload["text"]
        return {"audio_base64": base64.b64encode(b"\xe8\x03" * 24000).decode(),
                "alignment": {"characters": list(text),
                              "character_start_times_seconds": [i * .05 for i in range(len(text))],
                              "character_end_times_seconds": [(i + 1) * .05 for i in range(len(text))]}}


@pytest.fixture(autouse=True)
def no_live_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Real ElevenLabs HTTP is forbidden")
    monkeypatch.setattr(ElevenLabsTTS, "_http", forbidden)


def provider(root, transport, *, commercial=False, consent=True):
    config = {"enabled": True, "voice_id": "syntheticVoice", "model": "eleven_multilingual_v2",
              "job_limit": 1000, "monthly_limit": 10000, "commercial": commercial}
    return ElevenLabsTTS(root, config, consent=consent, transport=transport, keys=Keys())


@pytest.mark.parametrize("status", ["free", "active"])
def test_free_noncommercial_synthesis_and_cache(tmp_path, status):
    transport = Transport(status=status)
    tts = provider(tmp_path, transport)
    tts.synthesize_timed("시험.", tmp_path / "first.wav", "elevenlabs", 30)
    tts.synthesize_timed("시험.", tmp_path / "cached.wav", "elevenlabs", 30)
    assert [m for m, _ in transport.calls] == ["GET", "POST"]
    assert tts.attribution_required
    ledger = json.loads((tmp_path / "tts-elevenlabs/ledger.json").read_text())
    assert len(ledger) == 1 and all(r["state"] == "completed" for r in ledger.values())
    assert all(r["attribution_required"] for r in ledger.values())


@pytest.mark.parametrize("tier", ["starter", "creator", "pro", "scale", "business", "enterprise"])
def test_paid_active_still_allowed(tmp_path, tier):
    result = provider(tmp_path, Transport(tier=tier, status="active"), commercial=True).subscription(176)
    assert result["remaining"] == 9482 and not result["attribution_required"]


@pytest.mark.parametrize("changes,commercial,code", [
    ({}, True, "free_commercial"),
    ({"status": "free_disabled"}, False, "inactive"),
    ({"status": "trialing"}, False, "inactive"),
    ({"status": "past_due"}, False, "inactive"),
    ({"status": "incomplete"}, False, "inactive"),
    ({"status": None}, False, "inactive"),
    ({"status": "unexpected-secret-value"}, False, "inactive"),
    ({"tier": "starter"}, False, "inactive"),
    ({"tier": "unexpected-secret-value"}, False, "unknown_plan"),
    ({"character_count": "518"}, False, "invalid_usage"),
    ({"character_count": True}, False, "invalid_usage"),
    ({"character_count": -1}, False, "invalid_usage"),
    ({"character_limit": 500}, False, "invalid_usage"),
    ({"character_count": 10000}, False, "insufficient_credits"),
    ({"max_credit_limit_extension": 1}, False, "overage_enabled"),
    ({"max_credit_limit_extension": "unlimited"}, False, "overage_enabled"),
    ({"max_credit_limit_extension": None}, False, "overage_unknown"),
    ({"max_credit_limit_extension": False}, False, "overage_unknown"),
    ({"max_credit_limit_extension": -1}, False, "overage_unknown"),
])
def test_policy_failure_is_specific_and_never_synthesizes(tmp_path, changes, commercial, code):
    transport = Transport(**changes)
    tts = provider(tmp_path, transport, commercial=commercial)
    with pytest.raises(SubscriptionError) as error:
        tts.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30)
    assert error.value.code == code
    assert "unexpected-secret-value" not in str(error.value)
    assert transport.calls == [("GET", "/user/subscription")]
    assert not (tmp_path / "tts-elevenlabs/ledger.json").exists()
    assert not (tmp_path / "no.wav").exists()


def test_unknown_ledger_and_missing_consent_still_block_before_network(tmp_path):
    transport = Transport()
    tts = provider(tmp_path, transport, consent=False)
    with pytest.raises(TTSError):
        tts.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30)
    tts.consent = True
    tts.root.mkdir(parents=True)
    path = tts.root / "ledger.json"
    original = '{"prior": {"state": "reserved", "credits": 6, "month": "2026-10"}}'
    path.write_text(original)
    with pytest.raises(TTSError, match="결과 불명"):
        tts.synthesize_timed("시험.", tmp_path / "no.wav", "elevenlabs", 30)
    assert transport.calls == [] and path.read_text() == original


def test_render_record_keeps_safe_actionable_policy_error(app):
    class PolicyFailure(FakeRenderAdapter):
        def render(self, *args):
            error = SubscriptionError("inactive")
            error.args = ("secret-upstream-response",)
            raise error

    with app.state.sessions.begin() as session:
        article = NewsArticle(title="합성 뉴스", summary="테스트용 합성 요약",
                              url="https://example.com/test", canonical_url="https://example.com/test",
                              source_id=1, publisher="합성 출처")
        session.add(article)
        session.flush()
        article_id = article.id
    ai = IntelligenceService(app.state.sessions)
    draft_id = ai.generate(ai.analyze([article_id]), 30)
    video = app.state.video
    video.engine, video.tts = PolicyFailure(), FakeTTS()
    try:
        identifier = video.start(draft_id, 30, reviewed=True)
        video.future.result(timeout=10)
        with app.state.sessions() as session:
            row = session.get(RenderJob, identifier)
            assert row.status == "failed"
            assert row.message == SubscriptionError.MESSAGES["inactive"] + " · 자동 재시도 없음"
            assert "secret" not in row.message
    finally:
        video.close()
