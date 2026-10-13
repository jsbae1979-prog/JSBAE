"""Actual short MP4 and local Windows TTS validation, separate from visual quality."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import wave
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from uuid import uuid4

from PIL import Image

from newsflow.video.engine import FFmpegAdapter, RenderPlan, ScenePlan
from newsflow.video.tts import OfflineTTS, TTSError, WindowsTTS, wav_duration


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = {
        "real_RSS": "NOT VERIFIED",
        "real_AI_API": "NOT VERIFIED",
        "full_30_45_60_quality": "NOT VERIFIED (short synthetic samples; no human quality review)",
        "Windows11_user_PC": "NOT VERIFIED",
    }
    try:
        with TemporaryDirectory(prefix="newsflow-한글 공백-") as directory:
            work = Path(directory)
            local_image = work / "허가된 합성 이미지.png"
            Image.new("RGB", (900, 650), "#274060").save(local_image)
            scenes = [
                ScenePlan(1, "합성 대본", "한국어 자막 · 장면 1", local_image),
                ScenePlan(1, "합성 대본", "한국어 자막 · 장면 2"),
                ScenePlan(1, "합성 대본", "한국어 자막 · 장면 3"),
            ]
            plan = RenderPlan(
                "한국어 뉴스 영상 · 검증용 샘플",
                scenes,
                [{"publisher": "합성 출처", "url": "https://example.com/source"}],
            )
            progress = []
            path, metadata = FFmpegAdapter().render(plan, work, OfflineTTS(), progress.append, Event())
            name = f"sample-3s-{uuid4().hex}.mp4"
            with (args.output / name).open("xb") as output, path.open("rb") as source:
                shutil.copyfileobj(source, output)
            result.update(
                sample_MP4="PASS",
                sample_file=name,
                sample_metadata=metadata,
                Korean_subtitle_raster="PASS (pinned/installed Korean font)",
                scene_transition="PASS (cuts)",
                Offline_TTS="PASS (silent PCM -> AAC; not spoken voice)",
                progress=progress,
            )
            if sys.platform == "win32":
                tts = WindowsTTS()
                try:
                    voices = tts.voices()
                except TTSError:
                    voices = []
                if voices:
                    speech_work = work / "Windows 음성"
                    speech_work.mkdir()
                    speech_plan = RenderPlan(
                        "Windows local TTS test",
                        [ScenePlan(5, "News flow.", "Windows 로컬 TTS 샘플")],
                        [],
                        voice=voices[0],
                    )
                    speech_path, speech_metadata = FFmpegAdapter().render(
                        speech_plan, speech_work, tts, lambda _: None, Event()
                    )
                    speech_duration = wav_duration(speech_work / "scene-000.wav")
                    assert speech_duration > 0
                    with wave.open(str(speech_work / "scene-000.wav"), "rb") as speech:
                        assert any(speech.readframes(speech.getnframes())), (
                            "speech samples must not be all silent"
                        )
                    voice_name = f"sample-voice-5s-{uuid4().hex}.mp4"
                    with (args.output / voice_name).open("xb") as output, speech_path.open("rb") as source:
                        shutil.copyfileobj(source, output)
                    result.update(
                        Windows_TTS="PASS (installed SAPI voice -> WAV -> MP4 audio)",
                        Windows_TTS_speech_seconds=speech_duration,
                        Windows_TTS_sample_metadata=speech_metadata,
                        Windows_TTS_sample_file=voice_name,
                        Windows_TTS_quality="NOT VERIFIED (no human listening; Korean pronunciation not verified)",
                    )
                else:
                    result["Windows_TTS"] = "NOT VERIFIED (no usable installed SAPI voice on Runner)"
            else:
                result["Windows_TTS"] = "NOT VERIFIED (Cloud Linux; adapter tested with mocks only)"
        result["outcome"] = "PASS with explicit unverified items"
    except Exception as exc:
        result["outcome"] = "FAIL"
        result["error_type"] = type(exc).__name__
        raise
    finally:
        (args.output / "video-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        notice = (
            json.dumps(result, ensure_ascii=False, separators=(",", ":"))
            .replace("%", "%25")
            .replace("\r", "%0D")
            .replace("\n", "%0A")
        )
        print(f"::notice title=NewsFlow video validation::{notice}")


if __name__ == "__main__":
    main()
