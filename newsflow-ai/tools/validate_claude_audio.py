"""Explicit local sample: Fake Claude by default, real Heami/FFmpeg, no user database writes."""

import argparse
import json
from pathlib import Path
from threading import Event

from newsflow.intelligence.claude_code import ClaudeCodeProvider
from newsflow.intelligence.provider import FakeProvider, Options
from newsflow.intelligence.service import IntelligenceService
from newsflow.video.engine import FFmpegAdapter, RenderPlan, ScenePlan
from newsflow.video.tts import WindowsTTS, wav_has_signal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--voice", default="Microsoft Heami Desktop")
    parser.add_argument("--script", type=Path, help="Reuse an existing script/source JSON without another AI call")
    parser.add_argument("--live-claude", action="store_true",
                        help="Explicitly consent to sending synthetic news text and using your Claude subscription")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    sources = [{"publisher": "NewsFlow 체험용 합성 뉴스 · 실제 보도 아님",
                "url": "https://example.com/newsflow/synthetic/8"}]
    evidence = {"articles": [{"id": 1, "title": "[합성] 안전한 자전거 정비 방법 배우기",
                             "summary": "프로그램 사용 흐름을 연습하기 위해 만든 가상 기사입니다. 실제 사건이나 보도가 아닙니다.",
                             "sources": sources}], "groups": [[1]]}
    fixture = {
        "title": "[합성] 자전거 정비 체험 뉴스", "hook": "실제 보도가 아닌 체험 뉴스입니다.",
        "summary": "영상·한국어 음성·자막 동기화 검증용 합성 자료입니다.", "closing": "실제 뉴스로 게시하지 마세요.",
        "scenes": [
            {"seconds": 5, "narration": "합성 체험 뉴스입니다. 안전한 자전거 정비 방법을 배우는 주제입니다. 실제 사건을 보도한 기사는 아닙니다.",
             "caption": "합성 체험 뉴스 · 실제 보도 아님", "material": "합성 카드"},
            {"seconds": 10, "narration": "프로그램 사용 흐름을 연습하는 가상 자료입니다. 정비 정보의 정확성은 확인하지 않았습니다.",
             "caption": "가상 자료 · 사실 검증 없음", "material": "검토 카드"},
            {"seconds": 15, "narration": "원문과 이용 권한을 사람이 확인해야 합니다. 실제 뉴스로 게시하지 마세요.",
             "caption": "사람 검토 필요", "material": "출처 카드"},
        ],
    }
    if args.script:
        if args.live_claude or args.script.stat().st_size > 64000:
            raise ValueError("Use either an existing bounded script or a live Claude request")
        document = json.loads(args.script.read_text(encoding="utf-8"))
        script, sources = IntelligenceService.validate(document["script"], 30), document["sources"]
    else:
        provider = ClaudeCodeProvider() if args.live_claude else FakeProvider(fixture)
        script = IntelligenceService.validate(provider.complete(evidence, 30, Options(timeout=60)), 30)
    (args.output / "script-original.json").write_text(
        json.dumps({"script": script, "sources": sources}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.voice.startswith("supertonic:"):
        from newsflow.video.supertonic_tts import SupertonicTTS

        tts = SupertonicTTS()
    else:
        tts = WindowsTTS()
    voice = args.voice
    if voice not in tts.voices():
        raise RuntimeError("Microsoft Heami Desktop unavailable")
    plan = RenderPlan(script["title"], [ScenePlan(s["seconds"], s["narration"], s["caption"])
                                      for s in script["scenes"]], sources, voice=voice, fit_audio=True)
    path, metadata = FFmpegAdapter().render(plan, args.output.resolve(), tts, lambda _: None, Event())
    start = 0
    for index, timing in enumerate(metadata["scene_timings"]):
        assert wav_has_signal(args.output / f"scene-{index:03d}.wav")
        assert timing["seconds"] >= timing["audio_seconds"] + .349
        assert timing["start_ms"] == start
        assert timing["sentence_cues"]
        start += round(timing["seconds"] * 1000)
    assert abs(start - 30000) <= 2
    result = {"claude_live": "SUCCESS" if args.live_claude else (
        "NOT CALLED · existing script reused" if args.script else "NOT VERIFIED · Fake script only"),
              "human_listening": "NOT VERIFIED", "human_visual_quality": "NOT VERIFIED",
              "file": str(path), "metadata": metadata, "sources": sources}
    (args.output / "validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
