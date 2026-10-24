"""Server-owned presentation choices; they never change factual/review policy."""
from __future__ import annotations

STYLES = {"news": "전문 뉴스", "explainer": "쉽게 풀어 설명", "briefing": "핵심 브리핑"}
TONES = {"neutral": "차분하고 객관적으로", "friendly": "친근하고 명확하게"}
AUDIENCES = {"general": "일반 시청자", "beginner": "배경지식이 없는 시청자", "informed": "주제를 알고 있는 시청자"}


def presentation(style: str = "news", tone: str = "neutral", audience: str = "general") -> dict:
    if style not in STYLES or tone not in TONES or audience not in AUDIENCES:
        raise ValueError("대본 스타일·톤·시청자 선택을 확인하세요.")
    return {"style": style, "tone": tone, "audience": audience, "language": "ko",
            "instructions": f"{STYLES[style]}. {TONES[tone]}. 대상: {AUDIENCES[audience]}. 한국어로 작성."}
