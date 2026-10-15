"""Registry-based Korean voice detection, LCID parsing, policy classification and script safety."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from newsflow.video.tts import TTSError, TTSPolicyError, WindowsTTS, is_korean_lcid

ONECORE = {"hive": "onecore", "token": "MSTTS_V110_koKR_HeamiM", "name": "Microsoft Heami", "language": "412", "gender": "Female"}
SAPI = {"hive": "sapi", "token": "TTS_MS_KO-KR_HEAMI_11.0", "name": "Microsoft Heami Desktop", "language": "412", "gender": "Female"}
ENGLISH = {"hive": "onecore", "token": "MSTTS_V110_enUS_ZiraM", "name": "Microsoft Zira", "language": "409", "gender": "Female"}
VALID = b'[{"hive":"onecore","token":"MSTTS_V110_koKR_HeamiM","name":"Microsoft Heami","language":"412","gender":"Female"}]'


def test_registry_payload_accepted_and_sent_with_fixed_switch(monkeypatch):
    calls = []
    monkeypatch.setattr(WindowsTTS, "_command", lambda self, args, timeout: calls.append(args) or VALID)
    assert WindowsTTS().registry_voices() == [ONECORE]
    assert calls == [["-RegistryVoices"]]


ITEM = b'{"hive":"sapi","token":"t","name":"n","language":"412","gender":"f"}'


@pytest.mark.parametrize("payload", [
    b"{}", b"not-json", b'["name"]',
    b'[{"hive":"onecore","token":"t","name":"n","language":"412","gender":"f","extra":1}]',
    b'[{"hive":"other","token":"t","name":"n","language":"412","gender":"f"}]',
    b'[{"hive":"sapi","token":"t","name":1,"language":"412","gender":"f"}]',
    b'[{"hive":"sapi","token":"t","name":"n","language":"412"}]',
    b"[" + b",".join([ITEM] * 201) + b"]",
    b'[{"hive":"sapi","token":"t","name":"' + b"n" * 201 + b'","language":"412","gender":"f"}]',
])
def test_registry_payload_rejected(monkeypatch, payload):
    monkeypatch.setattr(WindowsTTS, "_command", lambda *args: payload)
    with pytest.raises(TTSError, match="레지스트리"):
        WindowsTTS().registry_voices()


@pytest.mark.parametrize("language,expected", [
    ("412", True), ("0412", True), ("0x412", True), ("409;412", True), ("412;409", True), (" 412 ", True),
    ("409", False), ("", False), ("zzz", False), ("412a", False), ("4120", False), ("0x", False),
])
def test_is_korean_lcid(language, expected):
    assert is_korean_lcid(language) is expected
    assert is_korean_lcid(None) is False  # type: ignore[arg-type]


def report(monkeypatch, sapi, registry):
    def details(self):
        if isinstance(sapi, Exception):
            raise sapi
        return sapi

    def tokens(self):
        if isinstance(registry, Exception):
            raise registry
        return registry

    monkeypatch.setattr(WindowsTTS, "voice_details", details)
    monkeypatch.setattr(WindowsTTS, "registry_voices", tokens)
    return WindowsTTS().korean_voice_report()


def test_report_available_from_sapi(monkeypatch):
    result = report(monkeypatch, [{"name": "Microsoft Heami Desktop", "culture": "ko-KR"}, {"name": "Zira", "culture": "en-US"}], [SAPI, ONECORE])
    assert result["state"] == "available" and result["registry_read"] == "ok"
    assert result["sapi"] == [{"name": "Microsoft Heami Desktop", "culture": "ko-KR"}]
    assert result["onecore_only"] == ["Microsoft Heami"]  # informational only; state stays SAPI-driven


def test_report_onecore_only_lists_names_but_never_offers_them(monkeypatch):
    result = report(monkeypatch, [{"name": "Zira", "culture": "en-US"}], [ONECORE, ENGLISH, dict(ONECORE, token="dup")])
    assert result == {"state": "onecore_only", "sapi": [], "onecore_only": ["Microsoft Heami"], "registry_read": "ok"}


def test_report_both_installed_has_no_onecore_only_entry(monkeypatch):
    result = report(monkeypatch, [{"name": "Microsoft Heami", "culture": "ko-KR"}], [ONECORE, SAPI])
    assert result["state"] == "available" and result["onecore_only"] == []


def test_report_registry_failure_does_not_change_sapi_state(monkeypatch):
    result = report(monkeypatch, [{"name": "Microsoft Heami", "culture": "ko-KR"}], TTSError("SECRET"))
    assert result["state"] == "available" and result["registry_read"] == "unavailable" and "SECRET" not in str(result)
    result = report(monkeypatch, [], TTSError("SECRET"))
    assert result == {"state": "not_installed", "sapi": [], "onecore_only": [], "registry_read": "unavailable"}


def test_report_without_korean_anywhere_is_not_installed(monkeypatch):
    result = report(monkeypatch, [{"name": "Zira", "culture": "en-US"}], [ENGLISH, dict(SAPI, name="Disabled Korean")])
    assert result["state"] == "not_installed" and result["onecore_only"] == []


def test_report_policy_and_generic_sapi_failures(monkeypatch):
    assert report(monkeypatch, TTSPolicyError("정책"), [ONECORE])["state"] == "blocked_policy"
    assert report(monkeypatch, TTSError("x"), [ONECORE])["state"] == "unavailable"
    assert report(monkeypatch, TTSPolicyError("정책"), [ONECORE])["registry_read"] == "unavailable"


def test_report_with_prefetched_sapi_skips_catalog(monkeypatch):
    def never(self):
        raise AssertionError("catalog must not be read twice")

    monkeypatch.setattr(WindowsTTS, "voice_details", never)
    monkeypatch.setattr(WindowsTTS, "registry_voices", lambda self: [ONECORE])
    assert WindowsTTS().korean_voice_report(sapi=[])["state"] == "onecore_only"


@pytest.mark.parametrize("stderr", [
    b"File windows_tts.ps1 cannot be loaded ... UnauthorizedAccess SECRET-PATH",
    b"running scripts is disabled on this system",
    "이 시스템에서 스크립트를 실행할 수 없으므로 SECRET".encode("cp949"),
    "스크립트를 실행할 수 없으므로".encode(),
])
def test_execution_policy_failure_is_classified_without_keeping_stderr(stderr):
    provider = WindowsTTS()
    result = SimpleNamespace(returncode=1, stdout=b"", stderr=stderr)
    with patch("newsflow.video.tts.sys.platform", "win32"), patch("subprocess.run", return_value=result):
        with pytest.raises(TTSPolicyError) as failure:
            provider.voices()
        assert "SECRET" not in str(failure.value) and "실행 정책" in str(failure.value)
        assert provider.korean_voice_report()["state"] == "blocked_policy"


@pytest.mark.parametrize("result", [
    SimpleNamespace(returncode=1, stdout=b"", stderr=b"Windows TTS failed."),
    SimpleNamespace(returncode=1, stdout=b""),  # no stderr attribute at all
    SimpleNamespace(returncode=0, stdout=b"x" * 40000),
])
def test_other_failures_stay_generic(result):
    provider = WindowsTTS()
    with (
        patch("newsflow.video.tts.sys.platform", "win32"),
        patch("subprocess.run", return_value=result),
        pytest.raises(TTSError) as failure,
    ):
        provider.voices()
    assert not isinstance(failure.value, TTSPolicyError)


def test_script_reads_registry_before_synthesizer_and_never_writes():
    script = Path(WindowsTTS().script).read_text(encoding="utf-8")
    for literal in ("Speech_OneCore", "Get-ItemProperty", "RegistryVoices", "PromptBuilder", "AppendBreak", "$speaker.Rate",
                    "WOW6432Node", "HKCU:", "Test-Path", "SilentlyContinue"):
        assert literal in script
    for forbidden in ("Invoke-Expression", "Set-ItemProperty", "New-Item", "Remove-Item", "reg add", "reg import",
                      "ExecutionPolicy", "Start-Process", "-Command"):
        assert forbidden not in script
    assert script.index("RegistryVoices") < script.index("Add-Type")
    assert script.index("exit 0") < script.index("Add-Type")
