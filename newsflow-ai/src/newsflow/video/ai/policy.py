"""Rules that keep AI-generated scenes from being mistaken for real news footage.

Four layers, none optional: a style guard appended to every prompt, a refusal of prompts that
ask for footage-like realism or real-person likeness, a burned-in label on every generated
scene, and a human review of each clip's relation to the news before final composition.
"""

from __future__ import annotations

import re
import unicodedata

PROMPT_MAX_CHARS = 600
# Appended to every prompt sent to a provider (shown in the GUI; the user cannot remove it).
STYLE_GUARD = (
    "Stylized abstract illustration for a news briefing background. "
    "Not photorealistic, not documentary or news footage, no real people, no faces, "
    "no real places or landmarks, no logos, no on-screen text."
)
SCENE_LABEL = "AI 생성 장면 · 실제 현장 영상 아님"
VIDEO_NOTICE = "이 영상의 일부 장면은 AI로 생성한 연출 화면이며 실제 사건 현장이 아닙니다."
DEFAULT_PROMPT = "뉴스 브리핑 배경용 추상 모션 그래픽"

# Phrases that request footage-like realism, a recording device or a real person's likeness.
_BLOCKED = (
    "실제 영상", "실제 현장", "현장 영상", "현장 화면", "보도 영상", "뉴스 영상", "뉴스 화면", "실사",
    "다큐멘터리 영상", "cctv", "블랙박스", "몰래카메라", "보디캠", "바디캠", "목격 영상", "생중계", "속보 화면",
    "딥페이크", "얼굴 합성", "실존 인물", "대통령", "총리", "real footage", "news footage", "actual footage",
    "documentary footage", "archival footage", "raw footage", "eyewitness", "bodycam", "body cam", "body-cam",
    "dashcam", "dash cam", "security camera", "surveillance", "live broadcast", "breaking news", "photorealistic",
    "photo-realistic", "hyperrealistic", "hyper-realistic", "realistic footage", "deepfake", "face swap",
    "lookalike", "look-alike",
)


class PromptPolicyError(ValueError):
    pass


# Spaces, hyphens and similar joiners are ignored when matching, so '실제영상', 'photo realistic',
# 'deep fake' and 'face-swap' match the listed phrases as well.
_JOINERS = re.compile(r"[\s\-_.·・‐-―]+")
_COMPACT = tuple(sorted({_JOINERS.sub("", phrase) for phrase in _BLOCKED}))
_ADDRESS = re.compile(r"://|\bwww\.|@|\b[a-z0-9-]+\.(com|net|org|kr|io|ai|co)\b")


def _normal(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def check_prompt(prompt: str) -> str:
    """Return the cleaned user prompt or raise with a fixed message naming the rule."""
    text = _normal(prompt or "")
    if not text:
        raise PromptPolicyError("AI 생성 장면의 프롬프트를 입력하세요.")
    if len(text) > PROMPT_MAX_CHARS:
        raise PromptPolicyError(f"프롬프트는 {PROMPT_MAX_CHARS}자 이내로 입력하세요.")
    # Cc covers C0, DEL and C1 controls; Cf covers zero-width and bidi characters that could hide
    # a blocked phrase from the check below.
    if any(unicodedata.category(c) in {"Cc", "Cf"} for c in text):
        raise PromptPolicyError("프롬프트에 제어 문자를 넣을 수 없습니다.")
    lowered = text.casefold()
    compact = _JOINERS.sub("", lowered)
    if any(phrase in compact for phrase in _COMPACT):
        raise PromptPolicyError(
            "실제 뉴스 현장·기록 영상이나 실존 인물처럼 보이게 하는 표현은 사용할 수 없습니다. "
            "추상적인 배경·상징 화면으로 바꿔 쓰세요."
        )
    if _ADDRESS.search(lowered):
        raise PromptPolicyError("프롬프트에 인터넷 주소나 이메일을 넣을 수 없습니다.")
    return text


def provider_prompt(prompt: str) -> str:
    """The exact text sent to a provider: the checked user prompt plus the style guard."""
    return f"{check_prompt(prompt)}\n\n{STYLE_GUARD}"
