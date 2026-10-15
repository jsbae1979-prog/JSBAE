"""Local-only TTS adapters; no API/network or paid provider implementation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path
from typing import Protocol


def local_process_env() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.upper().endswith(("_KEY", "_TOKEN", "_PASSWORD", "_SECRET"))
    }


class TTSError(Exception):
    pass


class TTSProvider(Protocol):
    def voices(self) -> list[str]: ...
    def synthesize(self, text: str, target: Path, voice: str, seconds: float) -> None: ...


def wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
            if audio.getnchannels() not in (1, 2) or audio.getsampwidth() != 2:
                raise ValueError
            return duration
    except (OSError, ValueError, EOFError, ZeroDivisionError, wave.Error):
        raise TTSError("음성 WAV 형식 검증에 실패했습니다.") from None


class OfflineTTS:
    def voices(self) -> list[str]:
        return ["offline-silence"]

    def synthesize(self, text: str, target: Path, voice: str, seconds: float) -> None:
        if voice != "offline-silence" or not 0 < seconds <= 60:
            raise TTSError("Offline 음성 설정이 잘못되었습니다.")
        with wave.open(str(target), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * round(16000 * seconds))


class FakeTTS(OfflineTTS):
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []

    def synthesize(self, text: str, target: Path, voice: str, seconds: float) -> None:
        self.calls.append(text)
        if self.error:
            raise self.error
        super().synthesize(text, target, voice, seconds)


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

    def synthesize(self, text: str, target: Path, voice: str, seconds: float) -> None:
        if voice not in self.voices() or len(text) > 400:
            raise TTSError("선택한 Windows 음성을 확인하세요.")
        spec = target.with_suffix(".json")
        spec.write_text(
            json.dumps({"text": text, "voice": voice, "target": str(target)}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._command(["-Spec", str(spec)], 60)
        if wav_duration(target) > seconds + 0.05:
            raise TTSError("음성이 장면 길이를 초과했습니다. 대본을 줄이거나 영상 길이를 늘리세요.")
