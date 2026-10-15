"""Local-only TTS adapters; no API/network or paid provider implementation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from newsflow.intelligence.korean import split_sentences

PREVIEW_TEXT = "안녕하세요. 뉴스플로 음성 미리 듣기입니다. 선택한 음성과 속도로 이렇게 읽어 드립니다."
RATE_RANGE = (-5, 5)
PAUSE_RANGE = (0, 1000)


def local_process_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().endswith(("_KEY", "_TOKEN", "_PASSWORD", "_SECRET"))
    }


class TTSError(Exception):
    pass


@dataclass(frozen=True)
class SpeechSettings:
    """SAPI rate step and pause between sentences; validated so the script never sees raw input."""

    rate: int = 0
    pause_ms: int = 250

    def __post_init__(self) -> None:
        if type(self.rate) is not int or not RATE_RANGE[0] <= self.rate <= RATE_RANGE[1]:
            raise TTSError("발화 속도는 -5~5 범위에서 선택하세요.")
        if type(self.pause_ms) is not int or not PAUSE_RANGE[0] <= self.pause_ms <= PAUSE_RANGE[1]:
            raise TTSError("문장 사이 쉼은 0~1000밀리초 범위에서 선택하세요.")


class TTSProvider(Protocol):
    def voices(self) -> list[str]: ...
    def synthesize(
        self, text: str, target: Path, voice: str, seconds: float, speech: SpeechSettings | None = None,
    ) -> None: ...


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            if audio.getnchannels() not in (1, 2) or audio.getsampwidth() != 2:
                raise ValueError
            return duration
    except (OSError, ValueError, EOFError, ZeroDivisionError, wave.Error):
        raise TTSError("음성 WAV 형식 검증에 실패했습니다.") from None


def wav_has_signal(path: Path, threshold: int = 64) -> bool:
    """True when any sample exceeds a small amplitude; a silent placeholder returns False."""
    try:
        with wave.open(str(path), "rb") as audio:
            width = audio.getsampwidth()
            frames = audio.readframes(min(audio.getnframes(), 16000 * 60))
    except (OSError, EOFError, wave.Error):
        return False
    if width != 2:
        return False
    for offset in range(0, len(frames) - 1, 2):
        sample = int.from_bytes(frames[offset:offset + 2], "little", signed=True)
        if abs(sample) > threshold:
            return True
    return False


class OfflineTTS:
    def voices(self) -> list[str]:
        return ["offline-silence"]

    def synthesize(
        self, text: str, target: Path, voice: str, seconds: float, speech: SpeechSettings | None = None,
    ) -> None:
        if voice != "offline-silence" or not 0 < seconds <= 60:
            raise TTSError("Offline 음성 설정이 잘못되었습니다.")
        with wave.open(str(target), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * round(16000 * seconds))


class FakeTTS(OfflineTTS):
    def __init__(self, error: Exception | None = None, seconds_per_call: float | None = None) -> None:
        self.error, self.calls, self.seconds_per_call = error, [], seconds_per_call
        self.settings: list[SpeechSettings | None] = []

    def synthesize(
        self, text: str, target: Path, voice: str, seconds: float, speech: SpeechSettings | None = None,
    ) -> None:
        self.calls.append(text)
        self.settings.append(speech)
        if self.error:
            raise self.error
        super().synthesize(text, target, voice, self.seconds_per_call or seconds)


class WindowsTTS:
    def __init__(self) -> None:
        self.script = Path(__file__).with_name("windows_tts.ps1")

    def _command(self, args: list[str], timeout: int) -> bytes:
        if sys.platform != "win32":
            raise TTSError("Windows 로컬 음성은 Windows 환경에서만 사용할 수 있습니다.")
        executable = (
            Path(os.environ.get("SystemRoot", "C:/Windows"))
            / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        try:
            result = subprocess.run(
                [str(executable), "-NoProfile", "-NonInteractive", "-File", str(self.script), *args],
                shell=False,
                env=local_process_env(),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            if result.returncode != 0 or len(result.stdout) > 32768:
                raise TTSError("Windows 음성 실행에 실패했습니다. 설치된 음성과 권한을 확인하세요.")
            return result.stdout
        except (OSError, subprocess.TimeoutExpired):
            raise TTSError("Windows 음성 실행 파일 또는 제한시간을 확인하세요.") from None

    def voices(self) -> list[str]:
        try:
            voices = json.loads(self._command(["-ListVoices"], 15).decode("utf-8-sig"))
            if not isinstance(voices, list) or any(not isinstance(v, str) or len(v) > 200 for v in voices):
                raise ValueError
            return voices
        except (ValueError, UnicodeError):
            raise TTSError("Windows 음성 목록을 읽지 못했습니다.") from None

    def voice_details(self) -> list[dict[str, str]]:
        try:
            entries = json.loads(self._command(["-VoiceDetails"], 15).decode("utf-8-sig"))
            if not isinstance(entries, list) or len(entries) > 100 or any(
                not isinstance(v, dict) or set(v) != {"name", "culture"}
                or any(not isinstance(x, str) or len(x) > 200 for x in v.values()) for v in entries
            ):
                raise ValueError
            return entries
        except (ValueError, UnicodeError):
            raise TTSError("Windows 음성 언어 정보를 읽지 못했습니다.") from None

    def korean_voices(self) -> list[dict[str, str]]:
        return [v for v in self.voice_details() if v["culture"].lower().startswith("ko-")]

    @staticmethod
    def spec(text: str, voice: str, target: Path, speech: SpeechSettings) -> dict:
        """Fixed data document for the packaged script: sentences, never code or shell text."""
        return {
            "text": text, "sentences": split_sentences(text) or [text], "voice": voice, "target": str(target),
            "rate": speech.rate, "pause_ms": speech.pause_ms,
        }

    def _speak(self, text: str, target: Path, voice: str, speech: SpeechSettings) -> None:
        if voice not in self.voices() or not 0 < len(text) <= 400:
            raise TTSError("선택한 Windows 음성을 확인하세요.")
        spec = target.with_suffix(".json")
        spec.write_text(json.dumps(self.spec(text, voice, target, speech), ensure_ascii=False), encoding="utf-8")
        self._command(["-Spec", str(spec)], 60)
        if not wav_has_signal(target):
            raise TTSError("음성이 생성되지 않았습니다. 선택한 음성이 한국어 문장을 읽는지 확인하세요.")

    def synthesize(
        self, text: str, target: Path, voice: str, seconds: float, speech: SpeechSettings | None = None,
    ) -> None:
        self._speak(text, target, voice, speech or SpeechSettings())
        if wav_duration(target) > seconds + 0.05:
            raise TTSError("음성이 장면 길이를 초과했습니다. 대본을 줄이거나 영상 길이를 늘리세요.")

    def preview(self, target: Path, voice: str, speech: SpeechSettings | None = None) -> float:
        """Short fixed Korean sample for listening tests; returns the produced duration."""
        self._speak(PREVIEW_TEXT, target, voice, speech or SpeechSettings())
        duration = wav_duration(target)
        if duration > 20:
            raise TTSError("미리 듣기 음성이 너무 깁니다. 속도 설정을 확인하세요.")
        return duration
