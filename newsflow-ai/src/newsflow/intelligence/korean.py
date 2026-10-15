"""Korean narration timing estimates and script review findings; pure functions, no I/O.

Estimates are planning aids for Windows SAPI narration. They are not a measurement
of produced audio and never replace the actual WAV duration check in the renderer.
"""

from __future__ import annotations

import re

# Typical Korean SAPI narration at rate 0: about 5 syllables (characters) per second.
CHARS_PER_SECOND = 5.0
SENTENCE_PAUSE_SECONDS = 0.35
MIN_SUMMARY_CHARS = 40
_SENTENCE_END = re.compile(r"(?<=[.!?。！？])\s+")
_HANGUL = re.compile(r"[가-힣]")
_WORD = re.compile(r"[A-Za-z0-9]+")


def rate_factor(rate: int) -> float:
    """SAPI rate -10..10 roughly scales speed geometrically; clamp outside that range."""
    rate = max(-10, min(10, int(rate)))
    return 1.6 ** (rate / 10)


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_END.split(" ".join(text.split()))]
    return [part for part in parts if part]


def speech_seconds(text: str, rate: int = 0, pause_ms: int = 250) -> float:
    """Estimated narration seconds for Korean text, including inter-sentence breaks."""
    sentences = split_sentences(text)
    if not sentences:
        return 0.0
    units = 0.0
    for sentence in sentences:
        units += len(_HANGUL.findall(sentence))
        # Latin words and digits are spoken roughly as groups of syllables.
        units += sum(max(1, len(word) / 2) for word in _WORD.findall(sentence))
    seconds = units / (CHARS_PER_SECOND * rate_factor(rate))
    seconds += SENTENCE_PAUSE_SECONDS * len(sentences) + (pause_ms / 1000) * max(0, len(sentences) - 1)
    return round(seconds, 2)


def speech_plan(content: dict, duration: int, rate: int = 0, pause_ms: int = 250) -> dict:
    """Per-scene estimates against the scene budget; scene seconds are the script's own values."""
    scenes = []
    total = 0.0
    for index, scene in enumerate(content.get("scenes", []), 1):
        estimate = speech_seconds(str(scene.get("narration", "")), rate, pause_ms)
        budget = float(scene.get("seconds", 0))
        total += estimate
        scenes.append({
            "scene": index, "budget_seconds": budget, "estimated_seconds": estimate,
            "fits": estimate <= budget,
        })
    return {
        "scenes": scenes, "estimated_total_seconds": round(total, 2), "duration": duration,
        "fits": total <= duration and all(s["fits"] for s in scenes), "rate": rate, "pause_ms": pause_ms,
    }


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text))


def assess_script(content: dict, evidence: dict, duration: int, rate: int = 0, pause_ms: int = 250) -> list[dict]:
    """Deterministic review findings; they flag, never approve, and never rewrite the script."""
    notes: list[dict] = []
    articles = evidence.get("articles", []) if isinstance(evidence, dict) else []
    evidence_text = " ".join(
        f"{a.get('title', '')} {a.get('summary', '')} {a.get('published_at') or ''}" for a in articles
    )
    script_text = " ".join([
        str(content.get("title", "")), str(content.get("hook", "")), str(content.get("summary", "")),
        str(content.get("closing", "")),
        *[f"{s.get('narration', '')} {s.get('caption', '')}" for s in content.get("scenes", [])],
    ])
    unknown = sorted(_numbers(script_text) - _numbers(evidence_text) - {str(duration)})
    unknown = [n for n in unknown if not re.fullmatch(r"\d", n)]  # single digits label scenes/lists
    if unknown:
        notes.append({
            "code": "numbers_not_in_source", "level": "warning",
            "message": "원문 제목·요약에 없는 숫자가 대본에 있습니다: " + ", ".join(unknown[:8])
            + ". 원문을 열어 확인하고 필요하면 수정하세요.",
        })
    if articles and all(len(str(a.get("summary", "")).strip()) < MIN_SUMMARY_CHARS for a in articles):
        notes.append({
            "code": "insufficient_source_text", "level": "warning",
            "message": "원문 RSS 요약이 짧거나 없습니다. 대본은 제목 위주의 초안이므로 원문 링크를 읽고 내용을 보완·확인하세요.",
        })
    if any(a.get("published_at") is None for a in articles):
        notes.append({
            "code": "unknown_publication_date", "level": "info",
            "message": "원문 발행 시각을 확인하지 못한 기사가 있습니다. 시점을 단정하는 표현이 없는지 확인하세요.",
        })
    plan = speech_plan(content, duration, rate, pause_ms)
    for scene in plan["scenes"]:
        if not scene["fits"]:
            notes.append({
                "code": "narration_too_long", "level": "warning",
                "message": f"장면 {scene['scene']}의 음성 예상 길이 {scene['estimated_seconds']}초가 배정 {scene['budget_seconds']:.0f}초를 넘습니다. 문장을 줄이거나 영상 길이를 늘리세요.",
            })
    if plan["estimated_total_seconds"] > duration:
        notes.append({
            "code": "total_narration_too_long", "level": "warning",
            "message": f"전체 음성 예상 길이 {plan['estimated_total_seconds']}초가 영상 길이 {duration}초를 넘습니다.",
        })
    return notes
