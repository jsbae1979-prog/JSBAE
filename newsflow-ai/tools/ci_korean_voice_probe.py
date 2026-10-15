"""Korean SAPI voice probe for Windows CI and user PCs: measurements only, never a quality verdict.

Records the installed voice catalogue (name and culture), the Korean voice state from the
registry-aware report when available, preview durations at several rate/pause settings for
up to three Korean voices, and a fixed Korean sample WAV (numbers, a date, an English acronym)
for a human listener. A non-Korean voice is never used for Korean text. On non-Windows hosts
the result is NOT VERIFIED. The tool never fails the CI run on probe findings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from newsflow.intelligence.korean import speech_seconds
from newsflow.video.tts import (
    PREVIEW_TEXT,
    SpeechSettings,
    TTSError,
    WindowsTTS,
    wav_duration,
    wav_has_signal,
)

SAMPLE_TEXT = "2026년 10월 15일, AI 기술로 3개 기사를 45초 영상으로 만들었습니다. 매출은 1,250,000달러였습니다."
RATES = (-3, 0, 3)
PAUSES = (0, 600)
MAX_VOICES = 3


def notice(title: str, payload: dict) -> None:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))
    print(f"::notice title={title}::" + encoded[:3900], flush=True)


def spoken(text: str) -> str:
    try:
        from newsflow.video.speech_text import normalize_for_speech
    except ImportError:  # normalization not available in this checkout
        return text
    return normalize_for_speech(text)


def probe(output: Path, tts: WindowsTTS | None = None, platform: str = sys.platform) -> dict:
    result: dict = {
        "tool": "ci_korean_voice_probe", "platform": platform,
        "korean_pronunciation": "NOT VERIFIED (requires human listening)",
        "korean_voice_count": 0, "state": "unavailable", "voices": [], "registry": None, "measurements": [],
        "sample_text": SAMPLE_TEXT, "sample_spoken": spoken(SAMPLE_TEXT), "sample_wav": None,
    }
    if platform != "win32":
        result["korean_tts"] = "NOT VERIFIED (not a Windows host; no SAPI)"
        return result
    tts = tts or WindowsTTS()
    try:
        catalog = tts.voice_details()
    except TTSError as exc:
        result["korean_tts"] = "NOT VERIFIED (SAPI unavailable)"
        result["state"] = "blocked_policy" if type(exc).__name__ == "TTSPolicyError" else "unavailable"
        return result
    result["voices"] = [{"name": v["name"], "culture": v["culture"]} for v in catalog]
    korean = [v for v in catalog if v["culture"].lower().startswith("ko-")]
    result["korean_voice_count"] = len(korean)
    result["state"] = "available" if korean else "not_installed"
    report = getattr(tts, "korean_voice_report", None)
    if callable(report):
        try:
            detail = report()
            result["state"] = detail.get("state", result["state"])
            result["registry"] = {"read": detail.get("registry_read"), "onecore_only": detail.get("onecore_only", [])}
        except TTSError:
            result["registry"] = {"read": "unavailable"}
    registry = getattr(tts, "registry_voices", None)
    if callable(registry):
        try:
            entries = registry()
            counts: dict[str, int] = {}
            for entry in entries:
                counts[entry["hive"]] = counts.get(entry["hive"], 0) + 1
            result["registry"] = {**(result["registry"] or {}), "hive_counts": counts,
                                  "korean_names": [e["name"] for e in entries if "412" in e.get("language", "").lower()][:20]}
        except TTSError:
            result["registry"] = {**(result["registry"] or {}), "hive_counts": "unavailable"}
    if not korean:
        result["korean_tts"] = "NOT VERIFIED (no installed Korean SAPI voice)"
        return result
    output.mkdir(parents=True, exist_ok=True)
    for voice in korean[:MAX_VOICES]:
        name = voice["name"]
        row = {"voice": name, "culture": voice["culture"], "previews": [], "errors": []}
        for rate, pause in [(r, 250) for r in RATES] + [(0, p) for p in PAUSES]:
            target = output / f"preview-{korean.index(voice)}-r{rate}-p{pause}.wav"
            try:
                tts.preview(target, name, SpeechSettings(rate, pause))
                row["previews"].append({
                    "rate": rate, "pause_ms": pause, "seconds": round(wav_duration(target), 2),
                    "signal": wav_has_signal(target),
                    "estimated_seconds": speech_seconds(spoken(getattr(tts, "preview_text", PREVIEW_TEXT)), rate, pause) or None,
                })
            except TTSError as exc:
                row["errors"].append({"rate": rate, "pause_ms": pause, "error": str(exc)[:200]})
        try:
            sample = output / f"korean-sample-{korean.index(voice)}.wav"
            tts.synthesize(SAMPLE_TEXT, sample, name, 30, SpeechSettings(0, 250))
            row["sample"] = {"file": sample.name, "seconds": round(wav_duration(sample), 2), "signal": wav_has_signal(sample)}
            result["sample_wav"] = result["sample_wav"] or sample.name
        except TTSError as exc:
            row["errors"].append({"sample": str(exc)[:200]})
        result["measurements"].append(row)
    durations = [p["seconds"] for p in result["measurements"][0]["previews"] if p["rate"] != 0 or p["pause_ms"] == 250]
    result["korean_tts"] = (
        f"PASS (non-silent Korean WAV produced; {len(result['measurements'])} voice(s) measured); "
        "pronunciation quality NOT VERIFIED until a human listens"
        if any(p["signal"] for m in result["measurements"] for p in m["previews"]) and durations
        else "NOT VERIFIED (Korean voice present but no signal produced)"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        result = probe(args.output)
    except Exception as exc:  # noqa: BLE001 - probe defects must not fail the CI run
        result = {"tool": "ci_korean_voice_probe", "korean_tts": "NOT VERIFIED (probe error)", "error_type": type(exc).__name__,
                  "korean_pronunciation": "NOT VERIFIED (requires human listening)"}
    (args.output / "voice-probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    core = {k: v for k, v in result.items() if k not in {"voices", "measurements", "registry"}}
    notice("KoreanVoiceProbe", core)
    notice("KoreanVoiceProbe measurements", {"voices": result.get("voices", [])[:20], "measurements": result.get("measurements", []),
                                              "registry": result.get("registry")})


if __name__ == "__main__":
    main()
