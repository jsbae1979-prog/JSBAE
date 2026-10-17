"""Explicit local STEP 4 media evidence; no external adapters or user database."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event

from newsflow.intelligence.news_usage import assess_news_usage, safe_topic_script, validate_news_usage_script
from newsflow.video.engine import FFmpegAdapter, RenderPlan, ScenePlan
from newsflow.video.tts import SpeechSettings, WindowsTTS, local_process_env, wav_has_signal

CASES = tuple(f"{mode}-{duration}" for duration in (30, 45, 60) for mode in ("quick", "standard"))


def isolated_path(path: Path) -> Path:
    root = Path(__file__).resolve().parents[1] / "validation-output"
    resolved = path.resolve()
    if resolved == root.resolve() or not resolved.is_relative_to(root.resolve()):
        raise ValueError("Media evidence must stay in a new validation-output subfolder")
    return resolved


def decoded_audio_peak(ffmpeg: Path, video: Path) -> float:
    result = subprocess.run(
        [
            str(ffmpeg),
            "-v",
            "info",
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(video),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        env=local_process_env(),
        timeout=180,
    )
    match = re.search(rb"max_volume:\s*(-?[\d.]+) dB", result.stderr)
    if not match or not math.isfinite(peak := float(match[1])):
        raise ValueError("Decoded audio signal was not confirmed")
    return peak


def write_results(path: Path, results: list[dict]) -> None:
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    parser.add_argument("--inspect-existing", type=Path)
    args = parser.parse_args()
    args.output = isolated_path(args.output)
    args.ffmpeg = args.ffmpeg.resolve(strict=True)
    probe = args.ffmpeg.with_name("ffprobe.exe").resolve(strict=True)
    if len(set(args.cases)) != len(args.cases):
        raise ValueError("Duplicate media cases are not permitted")
    existing = isolated_path(args.inspect_existing) if args.inspect_existing else None
    args.output.mkdir(parents=True, exist_ok=False)
    engine = FFmpegAdapter(args.ffmpeg, probe)
    if existing:
        inspected = []
        for name, duration in (("quick-30", 30), ("quick-45", 45), ("standard-30", 30)):
            video = existing / f"{name}.mp4"
            before = hashlib.sha256(video.read_bytes()).hexdigest()
            metadata = engine.inspect(probe, video, duration)
            peak = decoded_audio_peak(args.ffmpeg, video)
            assert hashlib.sha256(video.read_bytes()).hexdigest() == before
            inspected.append(
                {
                    "file": str(video),
                    "sha256": before,
                    "metadata": metadata,
                    "full_decode": "PASS",
                    "audio_peak_db": peak,
                    "unchanged": True,
                    "human_viewing_listening": "NOT VERIFIED",
                }
            )
            write_results(args.output / "existing-results.json", inspected)
            print(f"{name}: existing file inspected, unchanged", flush=True)
    tts = WindowsTTS()
    voices = tts.korean_voices()
    if not voices:
        raise RuntimeError("Installed Korean local voice required")
    results = []
    for case in args.cases:
        raw_mode, raw_duration = case.split("-")
        mode, duration = raw_mode.upper(), int(raw_duration)
        title = "스마트폰 신제품 매출 9999억 발표" if mode == "QUICK" else "반도체 신제품 매출 9999억 발표"
        source = {
            "news_usage": mode,
            "articles": [
                {
                    "id": 1,
                    "title": title,
                    "category": "it",
                    "summary": "Fake 검색 자료 · 실제 사건 아님",
                    "published_at": None,
                    "url": "https://example.com/technology/",
                }
            ],
        }
        script = safe_topic_script(source, duration)
        validate_news_usage_script(script, source, assess_news_usage(source, mode))
        name = f"{mode.lower()}-{duration}"
        (args.output / f"{name}.json").write_text(
            json.dumps({"source": source, "script": script}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        with TemporaryDirectory(prefix="topic-shorts-", dir=args.output) as temporary:
            work = Path(temporary)
            assert work.resolve().is_relative_to(args.output)
            plan = RenderPlan(
                script["title"],
                [ScenePlan(s["seconds"], s["narration"], s["caption"]) for s in script["scenes"]],
                [],
                voice=voices[0]["name"],
                fit_audio=True,
                speech=SpeechSettings(rate=2, pause_ms=150),
            )
            video, metadata = engine.render(plan, work, tts, lambda _: None, Event())
            wav_files = list(work.glob("*.wav"))
            assert wav_files and all(wav_has_signal(wav) for wav in wav_files)
            # Decode every frame and audio packet in addition to ffprobe checks.
            peak = decoded_audio_peak(args.ffmpeg, video)
            shutil.copyfile(video, args.output / f"{name}.mp4")
            shutil.copyfile(work / "scene-000.png", args.output / f"{name}.png")
            audio_evidence = args.output / f"{name}-audio"
            audio_evidence.mkdir()
            for artifact in (*work.glob("*.wav"), *work.glob("*.ass"), *work.glob("scene-*-sentence-*.json")):
                shutil.copyfile(artifact, audio_evidence / artifact.name)
            cues = [
                cue for timing in metadata.get("scene_timings", []) for cue in timing.get("sentence_cues", [])
            ]
            results.append(
                {
                    "file": f"{name}.mp4",
                    "mode": mode,
                    "duration": duration,
                    "metadata": metadata,
                    "sentence_cues": cues,
                    "audio_signal": True,
                    "full_decode": "PASS",
                    "audio_peak_db": peak,
                    "voice": voices[0]["name"],
                    "audio_evidence": audio_evidence.name,
                    "human_viewing_listening": "NOT VERIFIED",
                }
            )
            write_results(args.output / "results.json", results)
            print(f"{name}: rendered and decoded", flush=True)


if __name__ == "__main__":
    main()
