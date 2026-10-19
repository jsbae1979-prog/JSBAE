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
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Event
from typing import Protocol
from urllib.parse import urlsplit

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from newsflow.intelligence.korean import split_sentences

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
    # Phase 5D: a validated provider clip shown behind the text layer, always labelled as AI-generated.
    clip: Path | None = None
    ai_generated: bool = False
    clip_format: str = "mov"
    effect: str = "cut"


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
    # New API drafts must return to review instead of silently padding or rewriting speech.
    strict_audio_fit: bool = False

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
        if any(s.effect not in {"cut", "fade"} for s in self.scenes):
            raise RenderError("지원하는 장면 효과를 선택하세요.")


AUDIO_TAIL_SECONDS = 0.35
API_MIN_AUDIO_COVERAGE = 0.90
API_MAX_SCENE_TAIL_SECONDS = 2.0


def fit_api_timings(audio_seconds: list[float], total: float) -> list[float]:
    """Fit measured WAVs, with at most 10% overall slack and a two-second scene tail.

    WAV duration includes the selected engine's pauses; this is a pacing check,
    not a claim about phoneme alignment or listening quality. Short tails are
    shared evenly so a planned long scene cannot consume all remaining slack.
    """
    try:
        if sum(audio_seconds) < total * API_MIN_AUDIO_COVERAGE:
            raise RenderError("음성 분량 부족")
        fitted = fit_timings(audio_seconds, [1.0] * len(audio_seconds), total)
        if any(seconds - audio > API_MAX_SCENE_TAIL_SECONDS + 0.001
               for seconds, audio in zip(fitted, audio_seconds)):
            raise RenderError("장면 무음 초과")
    except RenderError:
        raise RenderError(
            "음성 분량이 목표 영상 길이와 맞지 않습니다. 대본을 검토·편집한 뒤 다시 제작하세요. "
            "음성 축약·가속·추가 API 요청은 실행하지 않았습니다.", kind="audio_review",
        ) from None
    return fitted


def fit_timings(audio_seconds: list[float], planned: list[float], total: float) -> list[float]:
    """Give every scene at least its narration plus a short tail, then share the slack.

    Scene order and the exact total are preserved. When narration cannot fit, the
    error names how much is over so the user can shorten the script or lengthen the video.
    """
    if len(audio_seconds) != len(planned) or not planned:
        raise RenderError("장면 수와 음성 수가 일치하지 않습니다.", kind="audio")
    if not math.isfinite(total) or total <= 0 or any(
        not math.isfinite(value) or value <= 0 for value in audio_seconds + planned
    ):
        raise RenderError("음성 길이가 유효하지 않습니다.", kind="audio")
    # Quantize scene boundaries to the renderer's 30 fps grid, so concatenated frames
    # and persisted subtitle starts cannot accumulate fractional-frame drift.
    minimum_frames = [math.ceil((a + AUDIO_TAIL_SECONDS) * 30) for a in audio_seconds]
    minimum = [frames / 30 for frames in minimum_frames]
    over = sum(minimum) - total
    if over > 0.001:
        raise RenderError(
            f"음성 총 길이가 영상 길이를 {over:.1f}초 초과합니다. 대본을 줄이거나 영상 길이를 늘리세요.", kind="audio"
        )
    slack_frames = round(total * 30) - sum(minimum_frames)
    weights = [max(p, 0.1) for p in planned]
    extra_frames = [int(slack_frames * w / sum(weights)) for w in weights]
    extra_frames[-1] += slack_frames - sum(extra_frames)
    result = [round((m + e) / 30, 3) for m, e in zip(minimum_frames, extra_frames)]
    result[-1] = round(total - sum(result[:-1]), 3)
    if any(value < 0.1 for value in result):
        raise RenderError("장면 시간이 너무 짧습니다.", kind="audio")
    return result


def prepare_audio(plan: RenderPlan, work: Path, tts: TTSProvider, cancel: Event) -> tuple[list[ScenePlan], list[dict]]:
    """Measure once for API drafts; retain legacy whole-sentence fitting for older projects."""
    scenes = list(plan.scenes)
    measured, cue_lists = [], []

    def synthesize(index: int) -> None:
        if cancel.is_set():
            raise RenderError("음성 생성이 취소되었습니다.")
        scene, audio = scenes[index], work / f"scene-{index:03d}.wav"
        timed = getattr(tts, "synthesize_timed", None)
        if callable(timed):
            cues = timed(scene.narration, audio, plan.voice, 120, plan.speech, cancel=cancel)
        else:
            tts.synthesize(scene.narration, audio, plan.voice, 120, plan.speech)
            cues = []
        duration = wav_duration(audio)
        if not math.isfinite(duration) or not 0 < duration <= 120:
            raise RenderError("음성 길이가 유효하지 않습니다.", kind="audio")
        if not cues:
            # No word/sentence alignment is claimed for adapters without timestamps.
            cues = [{"start_ms": 0, "end_ms": round(duration * 1000), "text": scene.caption or scene.narration}]
        previous = 0
        for cue in cues:
            if (not isinstance(cue.get("text"), str) or not 0 < len(cue["text"]) <= 400
                    or not previous <= cue["start_ms"] < cue["end_ms"] <= round(duration * 1000) + 1):
                raise RenderError("엔진 문장 타임스탬프가 잘못되었습니다.", kind="audio")
            previous = cue["end_ms"]
        if index == len(measured):
            measured.append(duration)
            cue_lists.append(cues)
        else:
            measured[index], cue_lists[index] = duration, cues

    for index in range(len(scenes)):
        synthesize(index)
    if plan.strict_audio_fit:
        fitted = fit_api_timings(measured, plan.duration)
    for attempt in range(0 if plan.strict_audio_fit else 9):
        try:
            fitted = fit_timings(measured, [s.seconds for s in scenes], plan.duration)
            break
        except RenderError:
            candidates = [index for index, scene in enumerate(scenes) if len(split_sentences(scene.narration)) > 1]
            if attempt == 8 or not candidates:
                raise RenderError(
                    "음성이 목표 길이를 초과합니다. 완전한 문장 단위 축약으로 맞출 수 없어 중단했습니다. "
                    "대본을 검토·축약한 뒤 다시 제작하세요. 음성은 자르지 않았습니다.", kind="audio"
                ) from None
            index = max(candidates, key=lambda i: measured[i])
            shortened = " ".join(split_sentences(scenes[index].narration)[:-1])
            # Do not leave a caption claiming material removed from narration.
            caption = split_sentences(shortened)[0]
            if len(caption) > 150:
                raise RenderError("축약 대본 자막을 검토하세요.", kind="subtitle") from None
            scenes[index] = replace(scenes[index], narration=shortened, caption=caption)
            synthesize(index)
    metadata, start = [], 0
    for index, seconds in enumerate(fitted):
        metadata.append({"seconds": seconds, "audio_seconds": round(measured[index], 3),
                         "start_ms": start, "audio_end_ms": start + round(measured[index] * 1000),
                         "narration": scenes[index].narration, "caption": scenes[index].caption,
                         "shortened": scenes[index].narration != plan.scenes[index].narration,
                         "timing_source": "measured_sentences" if callable(getattr(tts, "synthesize_timed", None))
                         else "scene_audio_only",
                         "sentence_cues": cue_lists[index]})
        start += round(seconds * 1000)
    return [replace(scene, seconds=seconds) for scene, seconds in zip(scenes, fitted)], metadata


def write_ass(path: Path, cues: list[dict], plan: RenderPlan, font: Path) -> None:
    def timestamp(milliseconds: int) -> str:
        centiseconds = round(milliseconds / 10)
        return f"{centiseconds // 360000}:{centiseconds // 6000 % 60:02}:{centiseconds // 100 % 60:02}.{centiseconds % 100:02}"

    lines = ["[Script Info]", "PlayResX: 1080", "PlayResY: 1920", "WrapStyle: 0", "[V4+ Styles]",
             "Format: Name,Fontname,Fontsize,PrimaryColour,BackColour,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV",
             f"Style: Default,Malgun Gothic,{plan.font_size},&H00FFFFFF,&H80000000,3,3,0,2,90,90,{1920 - plan.subtitle_y - 150}",
             "[Events]", "Format: Layer,Start,End,Style,Text"]
    draw = ImageDraw.Draw(Image.new("RGB", (1080, 1920)))
    selected = ImageFont.truetype(str(font), plan.font_size)
    for cue in cues:
        wrapped, line = [], ""
        for word in cue["text"].split():
            candidate = f"{line} {word}".strip()
            if line and draw.textlength(candidate, font=selected) > 900:
                wrapped.append(line)
                line = ""
            pieces = text_lines(draw, word, selected, 900)
            if len(pieces) > 1:
                if line:
                    wrapped.append(line)
                wrapped.extend(pieces[:-1])
                line = pieces[-1]
            else:
                line = f"{line} {word}".strip()
        if line:
            wrapped.append(line)
        if len(wrapped) > 4:
            raise RenderError("문장 자막이 안전 영역을 초과합니다. 대본을 줄이세요.", kind="subtitle")
        # Never allow untrusted ASS override tags or newline injection.
        text = r"\N".join(line.replace("\\", "＼").replace("{", "｛").replace("}", "｝") for line in wrapped)
        lines.append(f"Dialogue: 0,{timestamp(cue['start_ms'])},{timestamp(cue['end_ms'])},Default,{text}")
    path.write_text("\n".join(lines), encoding="utf-8-sig")


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


AI_SCENE_LABEL = "AI 생성 장면 · 실제 현장 영상 아님"
CLIP_DEMUXERS = frozenset({"mov", "matroska"})
# Constant filter graph: scale/crop the clip to the vertical frame, then draw the RGBA text layer.
# setsar=0 and setparams=...unknown leave the aspect-ratio and colour tags unset, exactly like the
# PNG card scenes, so every scene file has a byte-identical H.264 header for the '-c copy' concat.
CLIP_FILTER = (
    "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=0,"
    "setparams=range=unknown:color_primaries=unknown:color_trc=unknown:colorspace=unknown[bg];"
    "[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
)


def overlay(plan: RenderPlan, scene: ScenePlan, index: int, target: Path, font: Path) -> None:
    """Transparent text layer for a generated clip: same texts as ``card`` plus the AI label.

    The label cannot be turned off; it sits in its own opaque band so the clip never hides it.
    """
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(font), 56)
    body_font = ImageFont.truetype(str(font), plan.font_size)
    small_font = ImageFont.truetype(str(font), 28)
    label_font = ImageFont.truetype(str(font), 40)
    draw.rectangle((0, 0, 1080, 600), fill=(16, 23, 38, 214))
    draw.rounded_rectangle((90, 105, 990, 115), fill="#8b83ff", radius=5)
    draw.text((90, 145), "NEWSFLOW · 미확인 보도 · 사람 검토 필요", font=small_font, fill="#b7adff")
    for i, line in enumerate(text_lines(draw, plan.title, title_font, 900)[:4]):
        draw.text((90, 210 + i * 74), line, font=title_font, fill="#f0f4ff")
    draw.rounded_rectangle((90, 500, 990, 580), radius=20, fill=(255, 196, 0, 255))
    width = draw.textlength(AI_SCENE_LABEL, font=label_font)
    draw.text((540 - width / 2, 516), AI_SCENE_LABEL, font=label_font, fill="#111111")
    lines = text_lines(draw, scene.caption, body_font, 900)
    if len(lines) > 4 or plan.subtitle_y + len(lines) * (plan.font_size + 16) > 1790:
        raise RenderError(
            "자막이 안전 영역을 초과했습니다. 자막을 줄이거나 크기를 낮추세요.", kind="subtitle"
        )
    draw.rectangle((0, plan.subtitle_y - 40, 1080, 1920), fill=(16, 23, 38, 214))
    for i, line in enumerate(lines):
        draw.text((90, plan.subtitle_y + i * (plan.font_size + 16)), line, font=body_font, fill="#ffffff", stroke_width=1)
    audio_label = "무음 검토영상 · 음성 없음" if plan.silent else "한국어 음성 · 발음 품질 미검증"
    draw.text((990 - draw.textlength(audio_label, font=small_font), 1762), audio_label, font=small_font, fill="#8d9ab3")
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
    def clip_command(binary: Path, scene: ScenePlan, overlay_png: Path, audio: Path, target: Path) -> list[str]:
        """Generated clip (looped, scaled and cropped to 1080x1920) under the labelled text layer.

        Only local files can be read (``-protocol_whitelist file``) and the demuxer is fixed from
        the ffprobe result, so a crafted clip cannot open network or playlist inputs. The clip's
        own audio is dropped; the scene narration WAV is the only sound.
        """
        if scene.clip is None or scene.clip_format not in CLIP_DEMUXERS:
            raise RenderError("생성 장면 파일 형식을 확인하세요.", kind="clip")
        return [
            str(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
            "-protocol_whitelist", "file", "-f", scene.clip_format, "-stream_loop", "-1", "-i", str(scene.clip),
            "-loop", "1", "-framerate", "30", "-i", str(overlay_png),
            "-i", str(audio),
            "-filter_complex", CLIP_FILTER,
            "-map", "[v]", "-map", "2:a",
            "-t", f"{scene.seconds:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", "30",
            "-c:a", "aac", "-b:a", "128k", "-af", "apad", "-ar", "48000", "-ac", "2",
            "-threads", "2", "-movflags", "+faststart", str(target),
        ]

    @staticmethod
    def apply_effect(command: list[str], scene: ScenePlan) -> list[str]:
        """Apply only our enum-based filters after captions; preserve narration/timing."""
        if scene.effect not in {"cut", "fade"}:
            raise RenderError("지원하는 장면 효과를 선택하세요.")
        command = list(command)
        if scene.effect == "cut":
            return command
        duration = min(0.25, scene.seconds / 4)
        effect = f"fade=t=in:st=0:d={duration:.3f},fade=t=out:st={scene.seconds-duration:.3f}:d={duration:.3f}"
        if "-filter_complex" in command:
            index = command.index("-filter_complex") + 1
            command[index] = command[index].replace("[v]", f"[effectbase];[effectbase]{effect}[v]")
        elif "-vf" in command:
            index = command.index("-vf") + 1
            command[index] += "," + effect
        else:
            command[-1:-1] = ["-vf", effect]
        return command

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
        if (plan.fit_audio or plan.strict_audio_fit) and not plan.silent:
            scenes, timings = prepare_audio(plan, work, tts, cancel)
        if getattr(tts, "attribution_required", False):
            plan = replace(plan, title=plan.title + " · elevenlabs.io")
        for index, scene in enumerate(scenes):
            if cancel.is_set():
                raise RenderError("영상 제작이 중단되었습니다.")
            image, audio, target = (
                work / f"scene-{index:03d}{suffix}" for suffix in (".png", ".wav", ".mp4")
            )
            cues = timings[index].get("sentence_cues", []) if timings else []
            visual_scene = replace(scene, caption="") if cues else scene
            if scene.clip is not None:
                overlay(plan, visual_scene, index, image, font)
            else:
                card(plan, visual_scene, index, image, font)
            if not timings:
                tts.synthesize(scene.narration, audio, plan.voice, scene.seconds, plan.speech)
            if wav_duration(audio) > scene.seconds + 0.05:
                raise RenderError("음성이 장면 길이를 초과했습니다. 대본을 수정하세요.", kind="audio")
            if scene.clip is not None:
                command = self.clip_command(binary, scene, image, audio, target)
            else:
                command = self.command(binary, scene, image, audio, target)
            if cues:
                ass = work / f"scene-{index:03d}.ass"
                write_ass(ass, cues, plan, font)
                if scene.clip is not None:
                    filter_index = command.index("-filter_complex") + 1
                    command[filter_index] = command[filter_index].replace("[v]", f"[base];[base]ass={ass.name}[v]")
                else:
                    command[-1:-1] = ["-vf", f"ass={ass.name}"]
            command = self.apply_effect(command, scene)
            self.execute(command, work, cancel)
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
        if plan.voice == "elevenlabs":
            metadata["tts_provider"] = "elevenlabs"
            metadata["attribution_required"] = bool(getattr(tts, "attribution_required", False))
            metadata["non_commercial_only"] = metadata["attribution_required"]
        if timings:
            metadata["scene_timings"] = timings
            metadata["script_shortened"] = any(t["shortened"] for t in timings)
            metadata["human_review_required"] = True
        # Every clip scene carries the label (overlay), so every clip scene is listed as AI-generated.
        ai_scenes = [index for index, scene in enumerate(scenes) if scene.clip is not None or scene.ai_generated]
        if ai_scenes:
            metadata["ai_generated_scenes"] = ai_scenes
            metadata["ai_label"] = AI_SCENE_LABEL
        return final, metadata
