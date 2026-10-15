"""Pure logic of the Phase 5C.1 CI tools: voice probe shape, docs link check, zero-token AI check."""

from __future__ import annotations

import importlib.util
import json
import wave
from pathlib import Path

import pytest

from newsflow.intelligence.provider import ProviderAuthError
from newsflow.video.tts import TTSError

TOOLS = Path(__file__).resolve().parents[1] / "tools"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeKoreanTTS:
    """Windows-like provider for the probe: Korean and English voices, signal-bearing previews."""

    preview_text = "안녕하세요. 미리 듣기입니다."

    def __init__(self, fail_policy: bool = False) -> None:
        self.fail_policy = fail_policy
        self.calls: list[tuple[str, int, int]] = []

    def voice_details(self):
        if self.fail_policy:
            raise TTSError("PowerShell 스크립트 실행 정책 때문에 Windows 음성 기능을 사용할 수 없습니다.")
        return [{"name": "English Voice", "culture": "en-US"}, {"name": "Korean Voice", "culture": "ko-KR"}]

    def registry_voices(self):
        return [{"hive": "onecore", "token": "MSTTS_V110_koKR_HeamiM", "name": "Microsoft Heami", "language": "412", "gender": "Female"},
                {"hive": "sapi", "token": "TTS_MS_EN-US_ZIRA_11.0", "name": "Microsoft Zira Desktop", "language": "409", "gender": "Female"}]

    def _wav(self, target: Path, seconds: float) -> None:
        with wave.open(str(target), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\x10\x10" * int(16000 * seconds))

    def preview(self, target, voice, speech=None):
        assert voice == "Korean Voice", "a non-Korean voice must never be used"
        self.calls.append((voice, speech.rate, speech.pause_ms))
        self._wav(target, 2.0 + speech.pause_ms / 1000 - speech.rate * 0.2)
        return 2.0

    def synthesize(self, text, target, voice, seconds, speech=None):
        assert voice == "Korean Voice" and "2026년" in text
        self._wav(target, 4.0)


def test_voice_probe_non_windows_is_not_verified(tmp_path):
    probe = load("ci_korean_voice_probe")
    result = probe.probe(tmp_path, tts=None, platform="linux")
    assert result["korean_tts"].startswith("NOT VERIFIED") and result["korean_voice_count"] == 0
    assert result["korean_pronunciation"] == "NOT VERIFIED (requires human listening)"
    assert "2026년" in result["sample_text"]


def test_voice_probe_measures_only_korean_voices_and_never_claims_quality(tmp_path):
    probe = load("ci_korean_voice_probe")
    tts = FakeKoreanTTS()
    result = probe.probe(tmp_path, tts=tts, platform="win32")
    assert result["korean_voice_count"] == 1 and result["state"] == "available"
    assert all(call[0] == "Korean Voice" for call in tts.calls) and len(tts.calls) == 5
    row = result["measurements"][0]
    assert {(p["rate"], p["pause_ms"]) for p in row["previews"]} == {(-3, 250), (0, 250), (3, 250), (0, 0), (0, 600)}
    assert all(p["signal"] for p in row["previews"]) and row["sample"]["signal"]
    del FakeKoreanTTS.preview_text  # the real WindowsTTS has no such attribute: the probe uses PREVIEW_TEXT
    try:
        again = probe.probe(tmp_path / "again", tts=FakeKoreanTTS(), platform="win32")
    finally:
        FakeKoreanTTS.preview_text = "안녕하세요. 미리 듣기입니다."
    assert all(p["estimated_seconds"] and p["estimated_seconds"] > 5 for p in again["measurements"][0]["previews"])
    assert result["registry"]["hive_counts"] == {"onecore": 1, "sapi": 1} and result["registry"]["korean_names"] == ["Microsoft Heami"]
    assert result["korean_tts"].startswith("PASS (non-silent Korean WAV") and "NOT VERIFIED" in result["korean_tts"]
    assert result["korean_pronunciation"] == "NOT VERIFIED (requires human listening)"
    assert (tmp_path / "korean-sample-0.wav").is_file()


def test_voice_probe_policy_failure_is_reported_safely(tmp_path):
    probe = load("ci_korean_voice_probe")
    result = probe.probe(tmp_path, tts=FakeKoreanTTS(fail_policy=True), platform="win32")
    assert result["korean_tts"] == "NOT VERIFIED (SAPI unavailable)" and result["state"] == "unavailable"


def test_docs_link_check_detects_missing_targets_and_anchors(tmp_path):
    checker = load("ci_docs_link_check")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text(
        "# 안내서 제목\n\n## 2. 실행과 종료\n\n[좋은 링크](other.md) [앵커](other.md#다른-문서) [깨진 링크](missing.md) "
        "[깨진 앵커](#없는-제목) [있는 앵커](#2-실행과-종료) [외부](https://example.com) [http](http://example.com)\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "other.md").write_text("# 다른 문서\n", encoding="utf-8")
    (tmp_path / "START_HERE.html").write_text('<a href="docs/guide.md">guide</a><a href="docs/nope.md">x</a>', encoding="utf-8")
    result = checker.check([tmp_path / "docs" / "guide.md", tmp_path / "START_HERE.html"], root=tmp_path)
    broken = {(b["file"], b["link"], b["reason"]) for b in result["broken"]}
    assert broken == {("docs/guide.md", "missing.md", "missing"), ("docs/guide.md", "#없는-제목", "anchor"), ("START_HERE.html", "docs/nope.md", "missing")}
    assert result["status"] == "FAIL" and result["checked"] == 9
    assert [e["https"] for e in result["external"]] == [True, False]
    assert checker.slug("## 2. 실행과 종료".lstrip("# ")) == "2-실행과-종료"
    assert checker.slug("Phase 5C · 실제 콘텐츠 (RSS)") == "phase-5c--실제-콘텐츠-rss"


def test_connection_check_mode_blocks_without_flag_or_key_and_never_spends_tokens(tmp_path, monkeypatch):
    tool = load("ai_live_check")
    assert tool.connection_check(model="gpt-4o-mini", environ={})["reason"] == "env_flag"
    assert tool.connection_check(model="gpt-4o-mini", environ={"NEWSFLOW_AI_LIVE_TEST": "1"})["reason"] == "key_missing"
    assert tool.connection_check(model="bad name!", environ={"NEWSFLOW_AI_LIVE_TEST": "1", "NEWSFLOW_AI_API_KEY": "k" * 30})["reason"] == "model"

    class Checker:
        def check_connection(self, options):
            assert options.model == "gpt-4o-mini" and options.timeout == 15
            return {"ok": True, "model": "gpt-4o-mini", "elapsed_ms": 12, "tokens": 0}

    passed = tool.connection_check(model="gpt-4o-mini", environ={"NEWSFLOW_AI_LIVE_TEST": "1"}, provider=Checker())
    assert passed["outcome"] == "PASS" and passed["tokens"] == 0 and passed["external_ai_calls"] == 1

    class Broken:
        def check_connection(self, options):
            raise ProviderAuthError("AI 인증에 실패했습니다. API 키와 권한을 확인하세요.")

    failed = tool.connection_check(model="gpt-4o-mini", environ={"NEWSFLOW_AI_LIVE_TEST": "1"}, provider=Broken())
    assert failed["outcome"] == "FAIL" and failed["code"] == "ai_auth_failed"
    target = tool.write_evidence(failed, tmp_path, "sk-synthetic-not-real-key-0123456789")
    assert json.loads(target.read_text(encoding="utf-8"))["outcome"] == "FAIL"


@pytest.mark.parametrize("name", ["ci_korean_voice_probe", "ci_docs_link_check", "ai_live_check", "ci_feed_review"])
def test_runtime_only_tools_do_not_import_dev_dependencies(name):
    source = (TOOLS / f"{name}.py").read_text(encoding="utf-8")
    for forbidden in ("playwright", "httpx", "fastapi.testclient", "ci_autopilot_validation", "ci_validation"):
        assert forbidden not in source, f"{name} must stay runnable with runtime dependencies only ({forbidden})"
