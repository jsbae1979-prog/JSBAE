"""Phase 5D composition: the clip FFmpeg argv, the labelled overlay, real clip renders and start_ai.

The FFmpeg/ffprobe tests run the real binaries on local files only (FakeVideoProvider clips made
with lavfi); they skip when the binaries are missing. Text rasterising tests need a Korean font
(NEWSFLOW_FONT_PATH in CI, a pinned font in the development container) and skip without one.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from PIL import Image, ImageChops, ImageFont, ImageStat
from sqlalchemy import select

from newsflow.db.models import AudioTrack, NewsArticle, RenderJob, Scene, VideoProject
from newsflow.intelligence.service import IntelligenceService
from newsflow.video.ai.clips import ClipStore, probe_clip
from newsflow.video.ai.contracts import COMPLETED, ClipInvalidError, ClipRequest
from newsflow.video.ai.fake import FakeVideoProvider
from newsflow.video.engine import (
    AI_SCENE_LABEL,
    CLIP_DEMUXERS,
    CLIP_FILTER,
    FakeRenderAdapter,
    FFmpegAdapter,
    RenderError,
    RenderPlan,
    ScenePlan,
    card,
    font_path,
    overlay,
)
from newsflow.video.service import VideoError
from newsflow.video.tts import FakeTTS

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe not installed"
)

LABEL_YELLOW = (255, 196, 0)
SOURCES = [{"publisher": "합성 언론", "url": "https://example.com/news/1"}]
MIDDLE = (90, 700, 990, 1300)
SAFE_AREA_MESSAGE = "자막이 안전 영역을 초과했습니다. 자막을 줄이거나 크기를 낮추세요."
# A clip that stops validating after review fails with its own hint (not the final-MP4 one).
CLIP_FAILED = "AI 생성 장면 파일(형식·검토한 파일과 같은지) 실패. 설치·음성 길이·자막 안전 영역·코덱·디스크 공간을 확인하세요."
MISSING_CLIP = "검증된 AI 생성 영상 파일을 찾지 못했습니다. 장면을 다시 생성하거나 카드로 바꾸세요."
ENCODER_TAIL = [
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-r", "30",
    "-c:a", "aac", "-b:a", "128k", "-af", "apad", "-ar", "48000", "-ac", "2",
    "-threads", "2", "-movflags", "+faststart",
]


@pytest.fixture
def korean_font(monkeypatch) -> Path:
    if not os.environ.get("NEWSFLOW_FONT_PATH"):
        pytest.skip("Korean font not configured (NEWSFLOW_FONT_PATH)")
    return font_path()


class VoiceTTS(FakeTTS):
    """A non-silent voice name so the audio-fit branch runs; the audio itself is silent PCM."""

    def voices(self):
        return ["Fake Voice"]

    def synthesize(self, text, target, voice, seconds, speech=None):
        assert voice == "Fake Voice"
        FakeTTS.synthesize(self, text, target, "offline-silence", seconds, speech)


def fake_clip(target: Path, seconds: int = 2) -> Path:
    """A real H.264 clip from the Fake provider (submit -> completed status -> lavfi fetch)."""
    provider = FakeVideoProvider(steps=1)
    submission = provider.submit(ClipRequest("vendor/model/text-to-video", "도시 경제 추상 그래픽", seconds, "720p"))
    status = provider.status(submission.request_id)
    assert status.state == COMPLETED
    provider.fetch(status, target, Event())
    return target


def ffprobe(path: Path) -> dict:
    result = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, timeout=60, check=True,
    )
    return json.loads(result.stdout)


def stream(payload: dict, kind: str) -> dict:
    return next(s for s in payload["streams"] if s["codec_type"] == kind)


def frame(video: Path, seconds: float, target: Path) -> Image.Image:
    subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-ss", f"{seconds:.3f}",
         "-i", str(video), "-frames:v", "1", str(target)],
        capture_output=True, timeout=60, check=True,
    )
    with Image.open(target) as image:
        return image.convert("RGB")


def is_label_yellow(pixel: tuple) -> bool:
    red, green, blue = pixel[:3]
    return red >= 235 and 170 <= green <= 220 and blue <= 50


def mean_difference(a: Image.Image, b: Image.Image) -> float:
    return sum(ImageStat.Stat(ImageChops.difference(a, b)).mean) / 3


def mocked_ffmpeg(tmp_path: Path):
    """Fake binaries, no subprocess, and a bundled bitmap font: argv and PNG dispatch only."""
    return (
        patch.object(FFmpegAdapter, "check", return_value=(tmp_path / "ffmpeg", tmp_path / "ffprobe", "6.1")),
        patch.object(FFmpegAdapter, "execute"),
        patch.object(
            FFmpegAdapter, "inspect",
            side_effect=lambda probe, target, expected: {"adapter": "ffmpeg", "playable": True, "duration": expected},
        ),
        patch("newsflow.video.engine.font_path", return_value=tmp_path / "font.ttf"),
        patch("newsflow.video.engine.ImageFont.truetype", return_value=ImageFont.load_default(size=20)),
    )


# ------------------------------------------------------------------ clip_command argv


def test_constants_and_scene_plan_defaults_keep_local_renders_unchanged():
    assert AI_SCENE_LABEL == "AI 생성 장면 · 실제 현장 영상 아님"
    assert CLIP_DEMUXERS == frozenset({"mov", "matroska"})
    assert CLIP_FILTER == (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30,setsar=0,"
        "setparams=range=unknown:color_primaries=unknown:color_trc=unknown:colorspace=unknown[bg];"
        "[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
    )
    scene = ScenePlan(3, "내레이션", "자막")
    assert scene.clip is None and scene.ai_generated is False and scene.clip_format == "mov"


@pytest.mark.parametrize("clip_format", ["mov", "matroska"])
def test_clip_command_is_a_constant_argv_apart_from_paths_and_seconds(tmp_path, clip_format):
    binary = tmp_path / "ffmpeg.exe"
    work = tmp_path / "작업 폴더 ' $(x)"
    clip, png, wav, out = (work / name for name in ("clip-0.bin", "scene-000.png", "scene-000.wav", "scene-000.mp4"))
    scene = ScenePlan(
        7.25, "내레이션 $(rm -rf /) `id`", "자막; & | > out.txt", clip=clip, ai_generated=True, clip_format=clip_format,
    )
    command = FFmpegAdapter.clip_command(binary, scene, png, wav, out)
    assert command == [
        str(binary), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
        "-protocol_whitelist", "file", "-f", clip_format, "-stream_loop", "-1", "-i", str(clip),
        "-loop", "1", "-framerate", "30", "-i", str(png),
        "-i", str(wav),
        "-filter_complex", CLIP_FILTER,
        "-map", "[v]", "-map", "2:a",
        "-t", "7.250",
        *ENCODER_TAIL, str(out),
    ]
    assert all(isinstance(arg, str) for arg in command)
    assert "-y" not in command and scene.narration not in command and scene.caption not in command
    # Input options bind to the clip only: whitelist, forced demuxer and endless loop precede its -i.
    first_input = command.index("-i")
    assert command[first_input + 1] == str(clip)
    assert {"-protocol_whitelist", "-f", "-stream_loop"} <= set(command[:first_input])
    # A second scene differs only in its paths and duration.
    other = replace(scene, seconds=2, clip=tmp_path / "b" / "clip-1.bin")
    second = FFmpegAdapter.clip_command(tmp_path / "ff", other, tmp_path / "o.png", tmp_path / "o.wav", tmp_path / "o.mp4")
    varying = {0, command.index(str(clip)), command.index(str(png)), command.index(str(wav)), len(command) - 1,
               command.index("-t") + 1}
    assert len(second) == len(command)
    assert [a for i, a in enumerate(second) if i not in varying] == [a for i, a in enumerate(command) if i not in varying]
    assert second[command.index("-t") + 1] == "2.000"


def test_clip_command_uses_the_same_encoder_arguments_as_card_command(tmp_path):
    clip = tmp_path / "clip-0.bin"
    scene = ScenePlan(4.5, "내레이션", "자막", clip=clip, ai_generated=True)
    paths = (tmp_path / "scene.png", tmp_path / "scene.wav", tmp_path / "scene.mp4")
    clip_args = FFmpegAdapter.clip_command(tmp_path / "ffmpeg", scene, *paths)
    card_args = FFmpegAdapter.command(tmp_path / "ffmpeg", replace(scene, clip=None, ai_generated=False), *paths)
    assert clip_args[:6] == card_args[:6]
    assert clip_args[clip_args.index("-t"):] == card_args[card_args.index("-t"):]
    assert card_args[card_args.index("-t"):] == ["-t", "4.500", *ENCODER_TAIL, str(paths[2])]
    assert "-filter_complex" not in card_args and "-protocol_whitelist" not in card_args


@pytest.mark.parametrize(
    "clip_format", ["concat", "hls", "lavfi", "image2", "mp4", "webm", "MOV", "mov,mp4", " mov", ""],
)
def test_clip_command_rejects_unsupported_demuxer(tmp_path, clip_format):
    scene = ScenePlan(3, "내레이션", "자막", clip=tmp_path / "clip-0.bin", ai_generated=True, clip_format=clip_format)
    with pytest.raises(RenderError) as caught:
        FFmpegAdapter.clip_command(tmp_path / "ffmpeg", scene, tmp_path / "o.png", tmp_path / "a.wav", tmp_path / "t.mp4")
    assert caught.value.kind == "clip" and str(caught.value) == "생성 장면 파일 형식을 확인하세요."


def test_clip_command_requires_a_clip(tmp_path):
    with pytest.raises(RenderError) as caught:
        FFmpegAdapter.clip_command(
            tmp_path / "ffmpeg", ScenePlan(3, "n", "c"), tmp_path / "o.png", tmp_path / "a.wav", tmp_path / "t.mp4"
        )
    assert caught.value.kind == "clip"


# ------------------------------------------------------------------ render dispatch (no binaries)


def test_render_dispatches_clip_scene_to_clip_command_and_overlay(tmp_path):
    clip = tmp_path / "clip-0.bin"
    clip.write_bytes(b"not read: execute is mocked")
    work = tmp_path / "work"
    work.mkdir()
    scenes = [ScenePlan(2, "첫 장면", "AI 장면", clip=clip, ai_generated=True), ScenePlan(1, "둘째 장면", "카드 장면")]
    plan = RenderPlan("제목", scenes, SOURCES)
    check, execute, inspect, font, truetype = mocked_ffmpeg(tmp_path)
    with check, execute as run, inspect, font, truetype:
        final, metadata = FFmpegAdapter().render(plan, work, FakeTTS(), lambda value: None, Event())
    binary = tmp_path / "ffmpeg"
    commands = [call.args[0] for call in run.call_args_list]
    assert len(commands) == 3  # two scenes and the concat
    assert commands[0] == FFmpegAdapter.clip_command(
        binary, scenes[0], work / "scene-000.png", work / "scene-000.wav", work / "scene-000.mp4"
    )
    assert commands[1] == FFmpegAdapter.command(
        binary, scenes[1], work / "scene-001.png", work / "scene-001.wav", work / "scene-001.mp4"
    )
    assert "-filter_complex" not in commands[2] and str(clip) not in commands[2]
    with Image.open(work / "scene-000.png") as layer, Image.open(work / "scene-001.png") as plain:
        assert layer.mode == "RGBA" and plain.mode == "RGB"
        assert layer.getpixel((150, 540)) == (*LABEL_YELLOW, 255)
        assert plain.getpixel((150, 540))[:3] != LABEL_YELLOW
    assert final == work / "result.mp4"
    assert metadata["ai_generated_scenes"] == [0] and metadata["ai_label"] == AI_SCENE_LABEL
    assert metadata["audio_fit"] is False and metadata["audio"] == "silent"


def test_render_without_clips_adds_no_ai_metadata(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    plan = RenderPlan("제목", [ScenePlan(2, "첫 장면", "자막 1"), ScenePlan(1, "둘째", "자막 2")], SOURCES)
    check, execute, inspect, font, truetype = mocked_ffmpeg(tmp_path)
    with check, execute as run, inspect, font, truetype:
        _, metadata = FFmpegAdapter().render(plan, work, FakeTTS(), lambda value: None, Event())
    assert all("-filter_complex" not in call.args[0] for call in run.call_args_list)
    assert "ai_generated_scenes" not in metadata and "ai_label" not in metadata
    for index in range(2):
        with Image.open(work / f"scene-{index:03d}.png") as image:
            assert image.mode == "RGB"


def test_render_rejects_unsupported_clip_format_before_ffmpeg(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    scene = ScenePlan(2, "첫 장면", "자막", clip=tmp_path / "clip.bin", ai_generated=True, clip_format="concat")
    check, execute, inspect, font, truetype = mocked_ffmpeg(tmp_path)
    with check, execute as run, inspect, font, truetype, pytest.raises(RenderError) as caught:
        FFmpegAdapter().render(RenderPlan("제목", [scene], []), work, FakeTTS(), lambda value: None, Event())
    assert caught.value.kind == "clip" and run.call_count == 0


def test_audio_fit_branch_keeps_the_clip_with_fitted_seconds(tmp_path):
    clip = tmp_path / "clip-0.bin"
    clip.write_bytes(b"not read: execute is mocked")
    work = tmp_path / "work"
    work.mkdir()
    scenes = [ScenePlan(4, "첫 장면 내레이션", "AI 장면", clip=clip, ai_generated=True, clip_format="matroska"),
              ScenePlan(2, "둘째 장면", "카드 장면")]
    plan = RenderPlan("제목", scenes, SOURCES, voice="Fake Voice", fit_audio=True)
    tts = VoiceTTS(seconds_per_call=1.0)
    check, execute, inspect, font, truetype = mocked_ffmpeg(tmp_path)
    with check, execute as run, inspect, font, truetype:
        _, metadata = FFmpegAdapter().render(plan, work, tts, lambda value: None, Event())
    timings = metadata["scene_timings"]
    assert metadata["audio_fit"] is True and metadata["audio"] == "voice" and len(timings) == 2
    assert tts.calls == [s.narration for s in scenes]  # synthesized once per scene
    first = run.call_args_list[0].args[0]
    assert first == FFmpegAdapter.clip_command(
        tmp_path / "ffmpeg", replace(scenes[0], seconds=timings[0]["seconds"]),
        work / "scene-000.png", work / "scene-000.wav", work / "scene-000.mp4",
    )
    assert first[first.index("-f") + 1] == "matroska" and first[first.index("-t") + 1] == f"{timings[0]['seconds']:.3f}"
    assert "-filter_complex" not in run.call_args_list[1].args[0]
    assert metadata["ai_generated_scenes"] == [0] and metadata["ai_label"] == AI_SCENE_LABEL


# ------------------------------------------------------------------ overlay and card pixels


def test_overlay_draws_opaque_label_band_and_leaves_the_clip_visible(tmp_path, korean_font):
    plan = RenderPlan("한국어 제목 · 합성 뉴스 검증", [ScenePlan(2, "내레이션", "AI 장면 자막")], SOURCES)
    target = tmp_path / "overlay.png"
    overlay(plan, plan.scenes[0], 0, target, korean_font)
    with Image.open(target) as image:
        assert image.format == "PNG" and image.mode == "RGBA" and image.size == (1080, 1920)
        band = image.crop((110, 500, 970, 580))  # the rounded band without its corners
        assert band.getchannel("A").getextrema() == (255, 255)
        yellow = sum(count for count, colour in band.getcolors(band.width * band.height) if colour == (*LABEL_YELLOW, 255))
        assert yellow / (band.width * band.height) > 0.8  # the rest is the dark label text
        for strip in ((110, 500, 240, 580), (850, 500, 970, 580)):  # beside the centred text
            assert image.crop(strip).getcolors() == [((strip[2] - strip[0]) * 80, (*LABEL_YELLOW, 255))]
        assert image.crop((0, 700, 1080, 1300)).getchannel("A").getextrema() == (0, 0)
        assert image.getpixel((5, 5)) == (16, 23, 38, 214)  # translucent title band above the label
        assert image.getpixel((5, 1900)) == (16, 23, 38, 214)  # translucent subtitle/source band


@pytest.mark.parametrize(
    ("caption", "font_size", "subtitle_y"),
    [("가" * 150, 48, 1100), ("자막 " * 30, 64, 1420), ("가" * 55, 64, 1500)],
    ids=["five-plus-lines", "five-plus-lines-with-spaces", "four-lines-below-safe-bottom"],
)
def test_overlay_and_card_enforce_the_same_subtitle_safe_area(tmp_path, korean_font, caption, font_size, subtitle_y):
    plan = RenderPlan("제목", [ScenePlan(2, "내레이션", caption)], SOURCES, font_size=font_size, subtitle_y=subtitle_y)
    for draw in (card, overlay):
        with pytest.raises(RenderError) as caught:
            draw(plan, plan.scenes[0], 0, tmp_path / f"{draw.__name__}.png", korean_font)
        assert caught.value.kind == "subtitle" and str(caught.value) == SAFE_AREA_MESSAGE
    fitting = RenderPlan("제목", [ScenePlan(2, "내레이션", "짧은 자막")], SOURCES, font_size=font_size, subtitle_y=subtitle_y)
    overlay(fitting, fitting.scenes[0], 0, tmp_path / "ok.png", korean_font)
    card(fitting, fitting.scenes[0], 0, tmp_path / "ok-card.png", korean_font)


def test_card_is_deterministic_has_no_ai_label_and_ignores_clip_fields(tmp_path, korean_font):
    plan = RenderPlan("한국어 제목 · 합성 뉴스 검증", [ScenePlan(2, "내레이션", "카드 장면 자막")], SOURCES)
    scene = plan.scenes[0]
    card(plan, scene, 0, tmp_path / "a.png", korean_font)
    card(plan, scene, 0, tmp_path / "b.png", korean_font)
    labelled = replace(scene, clip=tmp_path / "clip-0.bin", ai_generated=True, clip_format="matroska")
    card(plan, labelled, 0, tmp_path / "c.png", korean_font)
    first = (tmp_path / "a.png").read_bytes()
    assert first == (tmp_path / "b.png").read_bytes() == (tmp_path / "c.png").read_bytes()
    with Image.open(tmp_path / "a.png") as image:
        assert image.mode == "RGB" and image.size == (1080, 1920)
        colours = image.getcolors(1080 * 1920)
        assert not [count for count, colour in colours if colour == LABEL_YELLOW]
        assert image.crop((90, 500, 990, 580)).getcolors() == [(900 * 80, (16, 23, 38))]
    overlay(plan, scene, 0, tmp_path / "o.png", korean_font)
    assert (tmp_path / "o.png").read_bytes() != first


# ------------------------------------------------------------------ real FFmpeg renders


@needs_ffmpeg
@pytest.mark.parametrize("fit_audio", [False, True], ids=["planned-seconds", "audio-fit"])
def test_fake_provider_clip_and_card_render_a_playable_labelled_mp4(tmp_path, korean_font, fit_audio):
    clip = fake_clip(tmp_path / "clip.mp4", 2)
    clip_format = probe_clip(clip)["format"]
    assert clip_format == "mov"
    scenes = [ScenePlan(2, "첫 장면 내레이션", "AI 장면 자막", clip=clip, ai_generated=True, clip_format=clip_format),
              ScenePlan(1, "둘째 장면 내레이션", "카드 장면 자막")]
    plan = RenderPlan(
        "합성 검증 제목", scenes, SOURCES, voice="Fake Voice" if fit_audio else "offline-silence", fit_audio=fit_audio,
    )
    tts = VoiceTTS(seconds_per_call=0.6) if fit_audio else FakeTTS()
    work = tmp_path / "work"
    work.mkdir()
    progress: list[int] = []
    final, metadata = FFmpegAdapter().render(plan, work, tts, progress.append, Event())
    assert final == work / "result.mp4" and progress[-1] == 95
    assert metadata["playable"] is True and metadata["video_codec"] == "h264" and metadata["audio_codec"] == "aac"
    assert (metadata["width"], metadata["height"]) == (1080, 1920)
    assert metadata["ai_generated_scenes"] == [0] and metadata["ai_label"] == AI_SCENE_LABEL
    assert metadata["expected_duration"] == 3 and abs(metadata["duration"] - 3) <= 0.1
    assert metadata["audio_fit"] is fit_audio
    payload = ffprobe(final)
    video = stream(payload, "video")
    assert (video["width"], video["height"], video["pix_fmt"]) == (1080, 1920, "yuv420p")
    assert abs(float(video["duration"]) - 3) < 0.05
    boundary = metadata["scene_timings"][0]["seconds"] if fit_audio else 2
    if fit_audio:
        assert boundary < 2 and abs(sum(t["seconds"] for t in metadata["scene_timings"]) - 3) < 0.01
    ai_frame = frame(final, 0.5, tmp_path / "ai.png")
    card_frame = frame(final, boundary + 0.5, tmp_path / "card.png")
    assert ai_frame.size == (1080, 1920)
    assert is_label_yellow(ai_frame.getpixel((150, 540))) and is_label_yellow(ai_frame.getpixel((930, 540)))
    assert not is_label_yellow(card_frame.getpixel((150, 540)))
    # The clip shows through the transparent middle; the card scene keeps its own panel there.
    assert mean_difference(ai_frame.crop(MIDDLE), card_frame.crop(MIDDLE)) > 10


def avcc(path: Path) -> bytes:
    """The MP4 'avcC' box: the H.264 SPS/PPS a '-c copy' concat keeps from the first scene only."""
    data = path.read_bytes()
    index = data.index(b"avcC")
    return data[index + 4:index - 4 + int.from_bytes(data[index - 4:index], "big")]


@needs_ffmpeg
def test_clip_and_card_scene_files_share_one_h264_header_even_for_tagged_clips(tmp_path, korean_font):
    """A clip with non-square SAR and bt709 tags must not give its scene a different SPS than the cards."""
    clip = tmp_path / "tagged.mp4"
    subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "lavfi", "-i",
         "testsrc2=size=540x960:rate=24:duration=2", "-vf", "setsar=4/3", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
         "-f", "mp4", str(clip)],
        check=True, timeout=120,
    )
    scenes = [ScenePlan(1, "", "카드"), ScenePlan(2, "", "클립", clip=clip, ai_generated=True, clip_format="mov"),
              ScenePlan(1, "", "카드 둘")]
    work = tmp_path / "work"
    work.mkdir()
    final, metadata = FFmpegAdapter().render(RenderPlan("헤더 비교", scenes, SOURCES), work, FakeTTS(), lambda v: None, Event())
    headers = [avcc(work / f"scene-{index:03d}.mp4") for index in range(3)]
    assert headers[0] == headers[1] == headers[2] == avcc(final)
    video = stream(ffprobe(work / "scene-001.mp4"), "video")
    assert video.get("sample_aspect_ratio") in (None, "0:1") and "color_primaries" not in video
    assert metadata["playable"] and metadata["ai_generated_scenes"] == [1]


@needs_ffmpeg
def test_landscape_clip_shorter_than_scene_is_cropped_looped_and_its_audio_dropped(tmp_path, korean_font):
    clip = tmp_path / "clip.mp4"
    subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
         "-f", "lavfi", "-i", "testsrc2=size=480x360:rate=30:duration=5,hue=H=2*PI*t/5",
         "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000:duration=5",
         "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
        capture_output=True, timeout=120, check=True,
    )
    meta = probe_clip(clip)
    assert meta["duration"] == pytest.approx(5, abs=0.05) and meta["has_audio"] is True
    assert (meta["width"], meta["height"]) == (480, 360)  # landscape: CLIP_FILTER scales and centre-crops
    plan = RenderPlan(
        "반복 재생 검증", [ScenePlan(7, "내레이션", "자막", clip=clip, ai_generated=True, clip_format=meta["format"])], SOURCES,
    )
    work = tmp_path / "work"
    work.mkdir()
    final, metadata = FFmpegAdapter().render(plan, work, FakeTTS(), lambda value: None, Event())
    assert abs(metadata["duration"] - 7) <= 0.1 and metadata["ai_generated_scenes"] == [0]
    video = stream(ffprobe(final), "video")
    assert (video["width"], video["height"], video["pix_fmt"]) == (1080, 1920, "yuv420p")
    assert abs(float(video["duration"]) - 7) < 0.05 and abs(int(video["nb_frames"]) - 210) <= 1
    # Looped, not frozen: 6.5 s shows the clip's 1.5 s frame again, and the label stays burned in.
    early, late, other = (frame(final, t, tmp_path / f"f{t}.png") for t in (1.5, 6.5, 3.0))
    assert mean_difference(early.crop(MIDDLE), late.crop(MIDDLE)) < 1.5
    assert mean_difference(early.crop(MIDDLE), other.crop(MIDDLE)) > 20  # the clip hue rotates over time
    assert is_label_yellow(late.getpixel((150, 540)))
    # Only the (silent) narration WAV is heard; the clip's 1 kHz tone never reaches the MP4.
    detect = subprocess.run(
        [shutil.which("ffmpeg"), "-hide_banner", "-nostdin", "-i", str(final), "-map", "0:a", "-af", "volumedetect",
         "-f", "null", "-"],
        capture_output=True, timeout=60, check=True, text=True,
    )
    level = re.search(r"max_volume: (-?[0-9.]+|-inf) dB", detect.stderr)
    assert level and (level.group(1) == "-inf" or float(level.group(1)) <= -60)


@needs_ffmpeg
def test_probe_refuses_a_concat_script_disguised_as_a_clip_before_it_opens_anything(tmp_path):
    """Only container demuxers may open downloaded bytes (-format_whitelist)."""
    store = ClipStore(tmp_path / "data")
    victim = store.new_path()
    fake_clip(victim, 1)
    disguised = store.new_path()
    disguised.write_text(f"ffconcat version 1.0\nfile {victim.name}\n", encoding="utf-8")
    with pytest.raises(ClipInvalidError):
        probe_clip(disguised)
    assert probe_clip(victim)["format"] == "mov"


def test_disk_message_for_an_ai_compose_names_the_real_requirement(studio, app):
    coordinator, draft_id = studio
    name = coordinator.clip_store.new_path().name
    coordinator.clip_store.path(name).write_bytes(b"x" * 300_000)
    with patch("newsflow.video.service.shutil.disk_usage", return_value=SimpleNamespace(free=0)), \
            pytest.raises(VideoError) as caught:
        coordinator.start_ai(1, draft_id, 30, [{"clip": name}, {}, {}])
    assert "AI 생성 장면을 포함해 최소 약" in str(caught.value) and "MB를 확보하세요" in str(caught.value)
    assert_nothing_created(app, coordinator)


@needs_ffmpeg
def test_corrupted_clip_fails_probe_and_render(tmp_path, korean_font):
    good = fake_clip(tmp_path / "good.mp4", 2)
    truncated, garbage = tmp_path / "truncated.mp4", tmp_path / "garbage.mp4"
    data = good.read_bytes()
    truncated.write_bytes(data[: len(data) // 2])
    garbage.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"NOT A VIDEO" * 64)
    for path in (truncated, garbage):
        with pytest.raises(ClipInvalidError) as caught:
            probe_clip(path)
        assert caught.value.code == "video_ai_clip_invalid" and caught.value.sent is False
        assert str(caught.value) == "생성된 영상 파일의 형식·길이·해상도 검증에 실패했습니다."
    work = tmp_path / "work"
    work.mkdir()
    plan = RenderPlan("손상 영상", [ScenePlan(2, "내레이션", "자막", clip=garbage, ai_generated=True)], SOURCES)
    with pytest.raises(RenderError) as caught:
        FFmpegAdapter().render(plan, work, FakeTTS(), lambda value: None, Event())
    assert isinstance(caught.value.exit_code, int) and caught.value.exit_code != 0
    assert not (work / "result.mp4").exists() and not (work / "scene-000.mp4").exists()


# ------------------------------------------------------------------ VideoCoordinator.start_ai


@pytest.fixture
def studio(app):
    with app.state.sessions.begin() as session:
        session.add(NewsArticle(
            title="AI 영상 합성 테스트 뉴스", summary="합성 요약", url="https://example.com/news/1",
            canonical_url="https://example.com/news/1", source_id=1, publisher="합성 언론",
        ))
    ai = IntelligenceService(app.state.sessions)
    draft_id = ai.generate(ai.analyze([1]), 30)  # three 10-second scenes
    coordinator = app.state.video
    coordinator.engine, coordinator.tts = FakeRenderAdapter(), FakeTTS()
    yield coordinator, draft_id
    app.state.video_ai.close()
    coordinator.close()


def wait(coordinator) -> None:
    coordinator.future.result(timeout=60)


def store_clip(coordinator, seconds: int = 2) -> str:
    path = coordinator.clip_store.new_path()
    fake_clip(path, seconds)
    probe_clip(path)  # validated once, as the AI coordinator does after download
    return path.name


def project_rows(app, job_id: int) -> tuple[RenderJob, VideoProject, list[Scene]]:
    with app.state.sessions() as session:
        job = session.get(RenderJob, job_id)
        project = session.get(VideoProject, job.project_id)
        scenes = list(session.scalars(select(Scene).where(Scene.project_id == project.id).order_by(Scene.position)))
        session.expunge_all()
    return job, project, scenes


def assert_nothing_created(app, coordinator) -> None:
    with app.state.sessions() as session:
        assert session.scalar(select(VideoProject)) is None and session.scalar(select(RenderJob)) is None
    assert not coordinator.guard.locked() and not coordinator.lock.is_locked


@needs_ffmpeg
def test_start_ai_records_clip_scenes_plan_id_and_mixes_local_material(studio, app):
    coordinator, draft_id = studio
    name = store_clip(coordinator)
    stored = coordinator.clip_store.path(name)
    digest = hashlib.sha256(stored.read_bytes()).hexdigest()
    Image.new("RGB", (160, 120), "green").save(coordinator.assets / "로컬 소재.png")
    specs = [{"clip": name, "clip_format": "matroska"}, {"material": "로컬 소재.png", "clip": None}, {}]
    job_id = coordinator.start_ai(41, draft_id, 30, specs)
    wait(coordinator)
    job, project, scenes = project_rows(app, job_id)
    assert job.status == "simulated" and project.ai_plan_id == 41 and not project.preview_only
    assert [(s.clip_name, s.ai_generated, s.material) for s in scenes] == [
        (name, True, ""), (None, False, "로컬 소재.png"), (None, False, ""),
    ]
    plan = coordinator.engine.calls[0]
    first, local, plain = plan.scenes
    # The renderer reads a private copy, re-probed: the caller's clip_format hint is ignored.
    assert first.clip is not None and first.clip.name == "clip-0.bin"
    assert first.clip.parent.parent == coordinator.temporary and first.clip != stored
    assert first.clip_format == "mov" and first.ai_generated is True and first.image is None
    assert local.clip is None and local.ai_generated is False and local.image.name == "asset-1.png"
    assert plain.clip is None and plain.ai_generated is False and plain.image is None
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == digest  # store copy untouched
    assert not list(coordinator.temporary.iterdir())


@needs_ffmpeg
def test_renderer_reads_the_private_copy_even_if_the_store_file_changes(studio, app):
    coordinator, draft_id = studio
    name = store_clip(coordinator)
    stored = coordinator.clip_store.path(name)
    seen: list[str] = []

    class SwapDuringRender(FakeRenderAdapter):
        def render(self, plan, work, tts, progress, cancel):
            stored.write_bytes(b"SWAPPED AFTER COPY")
            seen.append(probe_clip(plan.scenes[0].clip)["format"])
            return super().render(plan, work, tts, progress, cancel)

    coordinator.engine = SwapDuringRender()
    job_id = coordinator.start_ai(7, draft_id, 30, [{"clip": name}, {}, {}])
    wait(coordinator)
    job, _, _ = project_rows(app, job_id)
    assert seen == ["mov"] and job.status == "simulated"


@needs_ffmpeg
def test_clip_replaced_by_garbage_after_validation_fails_the_job(studio, app):
    coordinator, draft_id = studio
    name = store_clip(coordinator)
    coordinator.clip_store.path(name).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"GARBAGE" * 128)
    job_id = coordinator.start_ai(9, draft_id, 30, [{}, {"clip": name}, {}])
    wait(coordinator)
    job, project, scenes = project_rows(app, job_id)
    assert job.status == "failed" and job.message == CLIP_FAILED and job.finished_at is not None
    assert project.ai_plan_id == 9 and scenes[1].clip_name == name and scenes[1].ai_generated
    assert coordinator.engine.calls == []  # never handed to the renderer
    assert not coordinator.output_path(job.output_name).exists()
    assert not list(coordinator.outputs.iterdir()) and not list(coordinator.temporary.iterdir())
    with app.state.sessions() as session:
        assert session.scalar(select(AudioTrack).where(AudioTrack.project_id == project.id)).status == "failed"
    assert not coordinator.guard.locked() and not coordinator.lock.is_locked


def test_start_ai_missing_clip_file_is_rejected_before_any_job(studio, app):
    coordinator, draft_id = studio
    name = "clip-" + "a" * 32 + ".mp4"
    with pytest.raises(VideoError) as caught:
        coordinator.start_ai(3, draft_id, 30, [{"clip": name}, {}, {}])
    assert str(caught.value) == MISSING_CLIP
    assert coordinator.engine.calls == []
    assert_nothing_created(app, coordinator)


HEX = "0123456789abcdef" * 2


@pytest.mark.parametrize(
    "name",
    ["../x", "clip-xyz.mp4", f"../clip-{HEX}.mp4", f"..\\clip-{HEX}.mp4", f"sub/clip-{HEX}.mp4",
     f"clip-{HEX.upper()}.mp4", f"clip-{HEX}.exe", f"clip-{HEX}.mp4\x00", f"clip-{HEX}.mp4/../../x",
     f"C:/clip-{HEX}.mp4", ""],
)
def test_clip_store_rejects_traversal_and_foreign_names(tmp_path, name):
    with pytest.raises(ClipInvalidError) as caught:
        ClipStore(tmp_path).path(name)
    assert caught.value.sent is False and caught.value.code == "video_ai_clip_invalid"


@pytest.mark.parametrize("name", ["../x", "clip-xyz.mp4", f"../clip-{HEX}.mp4", f"clip-{HEX}.mp4/../../x"])
def test_start_ai_rejects_unsafe_clip_names_before_any_job(studio, app, name):
    coordinator, draft_id = studio
    (coordinator.root / "x").write_bytes(b"outside the clip store")
    with pytest.raises((VideoError, ClipInvalidError)):
        coordinator.start_ai(3, draft_id, 30, [{"clip": name}, {}, {}])
    assert coordinator.engine.calls == []
    assert_nothing_created(app, coordinator)


def test_start_ai_reports_an_unsafe_clip_name_as_a_video_error(studio, app):
    """approve_compose maps only VideoError to a user-facing AIVideoError; anything else becomes HTTP 500."""
    coordinator, draft_id = studio
    with pytest.raises(VideoError):
        coordinator.start_ai(3, draft_id, 30, [{"clip": "../x"}, {}, {}])
    assert_nothing_created(app, coordinator)


@needs_ffmpeg
def test_start_ai_never_checks_one_clip_store_and_renders_from_another(studio, app, tmp_path):
    """The clip_store argument must be the store the job reads from, or be refused up front."""
    coordinator, draft_id = studio
    other = ClipStore(tmp_path / "elsewhere")
    path = other.new_path()
    fake_clip(path, 2)
    try:
        job_id = coordinator.start_ai(5, draft_id, 30, [{"clip": path.name}, {}, {}], other)
    except VideoError:
        assert_nothing_created(app, coordinator)
        return
    wait(coordinator)
    job, _, _ = project_rows(app, job_id)
    assert job.status == "simulated", job.message
    assert coordinator.engine.calls[0].scenes[0].clip is not None


def test_clip_store_rejects_symlinks(tmp_path):
    store = ClipStore(tmp_path / "data")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    link = store.root / f"clip-{HEX}.mp4"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are not available for this user")
    with pytest.raises(ClipInvalidError):
        store.path(link.name)
    assert store.path(f"clip-{'b' * 32}.webm") == store.root / f"clip-{'b' * 32}.webm"


@pytest.mark.parametrize(
    ("duration", "specs"),
    [(20, [{}, {}, {}]), (30, [{}, {}]), (30, [{}, {}, {}, {}])],
)
def test_start_ai_rejects_bad_duration_or_scene_count(studio, app, duration, specs):
    coordinator, draft_id = studio
    with pytest.raises(VideoError):
        coordinator.start_ai(3, draft_id, duration, specs)
    assert coordinator.engine.calls == []
    assert_nothing_created(app, coordinator)


def test_local_renders_keep_clip_fields_empty(studio, app):
    coordinator, draft_id = studio
    job_ids = [coordinator.start(draft_id, 30, reviewed=True)]
    wait(coordinator)
    job_ids.append(coordinator.start_preview(draft_id, 30))
    wait(coordinator)
    for job_id, preview in zip(job_ids, (False, True)):
        job, project, scenes = project_rows(app, job_id)
        assert job.status == "simulated" and project.preview_only is preview and project.ai_plan_id is None
        assert len(scenes) == 3 and all(s.clip_name is None and s.ai_generated is False for s in scenes)
    for plan in coordinator.engine.calls:
        assert all(s.clip is None and s.ai_generated is False and s.clip_format == "mov" for s in plan.scenes)
