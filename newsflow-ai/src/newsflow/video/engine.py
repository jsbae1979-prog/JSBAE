"""Bounded FFmpeg argument arrays, image cards, validated MP4 output."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from typing import Protocol
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .tts import SpeechSettings, TTSProvider, local_process_env, wav_duration


class RenderError(Exception):
    def __init__(self, message: str, kind: str = "render", exit_code: int | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.exit_code = exit_code


@dataclass(frozen=True)
class ScenePlan:
    seconds: float
    narration: str
    caption: str
    image: Path | None = None


@dataclass(frozen=True)
class RenderPlan:
    title: str
    scenes: list[ScenePlan]
    sources: list[dict]
    voice: str = "offline-silence"
    font_size: int = 48
    subtitle_y: int = 1420
    # Phase 5C: narration speed/pauses and audio-fit timing for real Korean voices.
    speech: SpeechSettings = field(default_factory=SpeechSettings)
    fit_audio: bool = False

    @property
    def duration(self) -> float:
        return sum(scene.seconds for scene in self.scenes)

    @property
    def silent(self) -> bool:
        return self.voice == "offline-silence"

    def validate(self) -> None:
        if not 1 <= len(self.scenes) <= 8 or not 0 < self.duration <= 60:
            raise RenderError("장면 수 또는 길이가 잘못되었습니다.")
        if not 36 <= self.font_size <= 64 or not 1100 <= self.subtitle_y <= 1500:
            raise RenderError("자막은 안전 영역 안의 크기와 위치를 선택하세요.")
        if any(
            not 0.1 <= s.seconds <= 60 or len(s.narration) > 400 or len(s.caption) > 150 for s in self.scenes
        ):
            raise RenderError("장면 시간 또는 텍스트 길이를 확인하세요.")


AUDIO_TAIL_SECONDS = 0.35


def fit_timings(audio_seconds: list[float], planned: list[float], total: float) -> list[float]:
    """Give every scene at least its narration plus a short tail, then share the slack.

    Scene order and the exact total are preserved. When narration cannot fit, the
    error names how much is over so the user can shorten the script or lengthen the video.
    """
    if len(audio_seconds) != len(planned) or not planned:
        raise RenderError("장면 수와 음성 수가 일치하지 않습니다.", kind="audio")
    minimum = [round(a + AUDIO_TAIL_SECONDS, 3) for a in audio_seconds]
    over = sum(minimum) - total
    if over > 0.001:
        raise RenderError(
            f"음성 총 길이가 영상 길이를 {over:.1f}초 초과합니다. 대본을 줄이거나 영상 길이를 늘리세요.", kind="audio"
        )
    slack = total - sum(minimum)
    weights = [max(p, 0.1) for p in planned]
    result = [round(m + slack * w / sum(weights), 3) for m, w in zip(minimum, weights)]
    result[-1] = round(total - sum(result[:-1]), 3)
    if any(value < 0.1 for value in result):
        raise RenderError("장면 시간이 너무 짧습니다.", kind="audio")
    return result


class RenderEngine(Protocol):
    def render(
        self, plan: RenderPlan, work: Path, tts: TTSProvider, progress: Callable[[int], None], cancel: Event
    ) -> tuple[Path, dict]: ...


def font_path() -> Path:
    custom = os.environ.get("NEWSFLOW_FONT_PATH")
    candidates = (
        [Path(custom)]
        if custom
        else [
            Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts/malgun.ttf",
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        ]
    )
    for path in candidates:
        if path.is_file() and path.suffix.lower() in {".ttf", ".ttc", ".otf"}:
            return path.resolve()
    raise RenderError(
        "한국어 글꼴을 찾지 못했습니다. NEWSFLOW_FONT_PATH에 설치된 한국어 글꼴 경로를 설정하세요."
    )


def load_image(path: Path) -> Image.Image:
    try:
        if (
            path.is_symlink()
            or path.stat().st_size > 20 * 1024 * 1024
            or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}
        ):
            raise RenderError("이미지는 20MB 이하의 로컬 PNG/JPEG만 허용합니다.")
        with Image.open(path) as opened:
            if opened.format not in {"PNG", "JPEG"} or opened.width * opened.height > 16_000_000:
                raise RenderError("이미지 형식 또는 픽셀 크기를 확인하세요.")
            opened.load()
            return ImageOps.exif_transpose(opened).convert("RGB")
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise RenderError("이미지 파일을 안전하게 읽지 못했습니다.") from None


def text_lines(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines, current = [], ""
    for char in text.replace("\r", "").replace("\n", " "):
        if current and draw.textlength(current + char, font=font) > width:
            lines.append(current)
            current = ""
        current += char
    if current:
        lines.append(current)
    return lines


def card(plan: RenderPlan, scene: ScenePlan, index: int, target: Path, font: Path) -> None:
    image = Image.new("RGB", (1080, 1920), "#101726")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(font), 56)
    body_font = ImageFont.truetype(str(font), plan.font_size)
    small_font = ImageFont.truetype(str(font), 28)
    draw.rounded_rectangle((90, 105, 990, 115), fill="#8b83ff", radius=5)
    draw.text((90, 145), "NEWSFLOW · 미확인 보도 · 사람 검토 필요", font=small_font, fill="#b7adff")
    audio_label = "무음 검토영상 · 음성 없음" if plan.silent else "한국어 음성 · 발음 품질 미검증"
    draw.text((990 - draw.textlength(audio_label, font=small_font), 1762), audio_label, font=small_font, fill="#8d9ab3")
    for i, line in enumerate(text_lines(draw, plan.title, title_font, 900)[:5]):
        draw.text((90, 230 + i * 78), line, font=title_font, fill="#f0f4ff")
    if scene.image:
        asset = ImageOps.fit(load_image(scene.image), (900, 650))
        image.paste(asset, (90, 650))
    else:
        draw.rounded_rectangle((90, 650, 990, 1000), radius=35, fill="#272d46")
        draw.ellipse((750, 710, 920, 880), fill="#524980")
        draw.text((140, 735), f"장면 {index + 1:02d}", font=title_font, fill="#e7ecf5")
        draw.text((140, 835), "텍스트 기반 뉴스 브리핑", font=small_font, fill="#aaa5ff")
    lines = text_lines(draw, scene.caption, body_font, 900)
    if len(lines) > 4 or plan.subtitle_y + len(lines) * (plan.font_size + 16) > 1790:
        raise RenderError(
            "자막이 안전 영역을 초과했습니다. 자막을 줄이거나 크기를 낮추세요.", kind="subtitle"
        )
    for i, line in enumerate(lines):
        draw.text(
            (90, plan.subtitle_y + i * (plan.font_size + 16)),
            line,
            font=body_font,
            fill="#ffffff",
            stroke_width=1,
        )
    names = []
    for source in plan.sources[:100]:
        label = source.get("publisher", "") + " · " + urlsplit(source.get("url", "")).netloc
        if label not in names:
            names.append(label[:200])
            if len(names) == 3:
                break
    for i, line in enumerate(text_lines(draw, "출처: " + " / ".join(names), small_font, 900)[:2]):
        draw.text((90, 1810 + i * 38), line, font=small_font, fill="#9ba9c1")
    image.save(target, format="PNG")


class FakeRenderAdapter:
    def __init__(self, error: Exception | None = None) -> None:
        self.error, self.calls = error, []

    def render(
        self, plan: RenderPlan, work: Path, tts: TTSProvider, progress: Callable[[int], None], cancel: Event
    ) -> tuple[Path, dict]:
        self.calls.append(plan)
        if self.error:
            raise self.error
        if cancel.is_set():
            raise RenderError("사용자 종료로 영상 제작이 중단되었습니다.")
        plan.validate()
        for index, scene in enumerate(plan.scenes):
            tts.synthesize(scene.narration, work / f"audio-{index}.wav", plan.voice, scene.seconds, plan.speech)
        path = work / "result.mp4"
        path.write_bytes(b"FAKE_RENDER_NOT_PLAYABLE")
        progress(95)
        return path, {"adapter": "fake", "playable": False, "duration": plan.duration}


class FFmpegAdapter:
    def __init__(self, ffmpeg: Path | None = None, ffprobe: Path | None = None) -> None:
        self.ffmpeg, self.ffprobe = ffmpeg, ffprobe

    @staticmethod
    def executable(name: str, explicit: Path | None) -> Path:
        selected = (
            str(explicit) if explicit else os.environ.get("NEWSFLOW_" + name.upper()) or shutil.which(name)
        )
        if not selected or not Path(selected).is_file():
            raise RenderError(
                f"{name} 실행 파일을 찾지 못했습니다. 설치 후 PATH 또는 실행 파일 설정을 확인하세요.",
                kind="dependency",
            )
        return Path(selected).resolve()

    def check(self) -> tuple[Path, Path, str]:
        binaries = [self.executable("ffmpeg", self.ffmpeg), self.executable("ffprobe", self.ffprobe)]
        version = ""
        for name, path in zip(("ffmpeg", "ffprobe"), binaries):
            try:
                result = subprocess.run(
                    [str(path), "-version"],
                    shell=False,
                    env=local_process_env(),
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                match = re.search(
                    name + r" version ([0-9][a-zA-Z0-9._-]{0,60})",
                    result.stdout[:4096].decode(errors="replace"),
                )
                if result.returncode != 0 or not match:
                    raise RenderError("FFmpeg/ffprobe 버전 확인에 실패했습니다.", kind="dependency")
                if name == "ffmpeg":
                    version = match.group(1)
            except (OSError, subprocess.TimeoutExpired):
                raise RenderError("FFmpeg 실행 파일 또는 버전 확인 제한시간을 확인하세요.") from None
        return binaries[0], binaries[1], version

    @staticmethod
    def command(binary: Path, scene: ScenePlan, image: Path, audio: Path, target: Path) -> list[str]:
        return [
            str(binary),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-n",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-i",
            str(image),
            "-i",
            str(audio),
            "-t",
            f"{scene.seconds:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-r",
            "30",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-af",
            "apad",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-threads",
            "2",
            "-movflags",
            "+faststart",
            str(target),
        ]

    @staticmethod
    def execute(args: list[str], work: Path, cancel: Event, timeout: float = 600) -> None:
        try:
            with subprocess.Popen(
                args,
                shell=False,
                env=local_process_env(),
                cwd=work,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ) as process:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if cancel.is_set() or time.monotonic() > deadline:
                        process.kill()
                        process.wait(timeout=10)
                        raise RenderError("영상 제작이 종료되었거나 렌더링 제한시간을 초과했습니다.")
                    cancel.wait(0.1)
                if process.returncode != 0:
                    raise RenderError(
                        f"FFmpeg 렌더링에 실패했습니다 (종료 코드 {process.returncode}). 코덱·입력·디스크 공간을 확인하세요.",
                        exit_code=process.returncode,
                    )
        except OSError:
            raise RenderError("FFmpeg 실행 또는 파일 접근에 실패했습니다.") from None

    @staticmethod
    def inspect(probe: Path, target: Path, expected: float) -> dict:
        try:
            result = subprocess.run(
                [str(probe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)],
                shell=False,
                env=local_process_env(),
                capture_output=True,
                timeout=20,
                check=False,
            )
            if result.returncode != 0 or len(result.stdout) > 1_000_000:
                raise ValueError
            payload = json.loads(result.stdout)
            video = next(s for s in payload["streams"] if s["codec_type"] == "video")
            audio = next(s for s in payload["streams"] if s["codec_type"] == "audio")
            duration = float(payload["format"]["duration"])
            if (
                not math.isfinite(duration)
                or "mp4" not in payload["format"].get("format_name", "")
                or video["codec_name"] != "h264"
                or (video["width"], video["height"]) != (1080, 1920)
                or video.get("pix_fmt") != "yuv420p"
                or audio["codec_name"] != "aac"
                or abs(duration - expected) > 0.25
            ):
                raise ValueError
            return {
                "adapter": "ffmpeg",
                "playable": True,
                "video_codec": "h264",
                "audio_codec": "aac",
                "width": 1080,
                "height": 1920,
                "duration": duration,
                "expected_duration": expected,
                "audio_channels": audio["channels"],
                "bytes": target.stat().st_size,
            }
        except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
            raise RenderError(
                "완성 MP4의 코덱·해상도·길이·오디오 검증에 실패했습니다.", kind="validation"
            ) from None

    def render(
        self, plan: RenderPlan, work: Path, tts: TTSProvider, progress: Callable[[int], None], cancel: Event
    ) -> tuple[Path, dict]:
        plan.validate()
        binary, probe, version = self.check()
        font = font_path()
        progress(5)
        scenes = list(plan.scenes)
        timings: list[dict] = []
        if plan.fit_audio and not plan.silent:
            # Synthesize everything first so scene timing can follow the real narration.
            measured = []
            for index, scene in enumerate(scenes):
                if cancel.is_set():
                    raise RenderError("영상 제작이 중단되었습니다.")
                audio = work / f"scene-{index:03d}.wav"
                tts.synthesize(scene.narration, audio, plan.voice, plan.duration, plan.speech)
                measured.append(wav_duration(audio))
            fitted = fit_timings(measured, [s.seconds for s in scenes], plan.duration)
            scenes = [
                ScenePlan(seconds, scene.narration, scene.caption, scene.image)
                for seconds, scene in zip(fitted, scenes)
            ]
            timings = [
                {"seconds": seconds, "audio_seconds": round(audio, 3)} for seconds, audio in zip(fitted, measured)
            ]
        for index, scene in enumerate(scenes):
            if cancel.is_set():
                raise RenderError("영상 제작이 중단되었습니다.")
            image, audio, target = (
                work / f"scene-{index:03d}{suffix}" for suffix in (".png", ".wav", ".mp4")
            )
            card(plan, scene, index, image, font)
            if not timings:
                tts.synthesize(scene.narration, audio, plan.voice, scene.seconds, plan.speech)
            if wav_duration(audio) > scene.seconds + 0.05:
                raise RenderError("음성이 장면 길이를 초과했습니다. 대본을 수정하세요.", kind="audio")
            self.execute(self.command(binary, scene, image, audio, target), work, cancel)
            progress(10 + int((index + 1) / len(scenes) * 75))
        manifest = work / "concat.txt"
        manifest.write_text(
            "".join(f"file 'scene-{i:03d}.mp4'\n" for i in range(len(scenes))), encoding="utf-8"
        )
        final = work / "result.mp4"
        self.execute(
            [
                str(binary),
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-n",
                "-protocol_whitelist",
                "file,pipe",
                "-f",
                "concat",
                "-safe",
                "1",
                "-i",
                str(manifest),
                "-t",
                f"{plan.duration:.3f}",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(final),
            ],
            work,
            cancel,
        )
        progress(95)
        metadata = self.inspect(probe, final, plan.duration)
        metadata["ffmpeg_version"] = version
        metadata["audio"] = "silent" if plan.silent else "voice"
        metadata["audio_fit"] = bool(timings)
        if timings:
            metadata["scene_timings"] = timings
        return final, metadata
