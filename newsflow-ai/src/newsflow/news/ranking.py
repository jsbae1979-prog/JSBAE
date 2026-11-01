"""Explainable internal heuristic; unknown signals receive no invented points."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

CATEGORY_WORDS = {
    "정치": ("대통령", "국회", "선거", "정책", "정부"),
    "경제": ("금리", "증시", "주식", "경제", "물가", "수출"),
    "사회": ("사고", "재난", "지진", "교육", "법원", "의료"),
    "IT·과학": ("인공지능", "AI", "반도체", "우주", "과학", "기술"),
    "문화": ("영화", "음악", "공연", "문화", "전시", "미술", "책", "출판", "뮤지컬", "문화재", "축제"),
    "연예": ("연예", "K팝", "케이팝", "아이돌", "걸그룹", "보이그룹", "컴백", "드라마", "배우", "가수", "예능", "웹툰", "넷플릭스", "OTT", "앨범", "콘서트", "팬미팅", "시상식"),
    "스포츠": ("축구", "야구", "올림픽", "스포츠"),
    "국제": ("미국", "중국", "유럽", "전쟁", "유엔"),
}


CATEGORIES = tuple(CATEGORY_WORDS)
CATEGORY_TOPICS = {"경제": ("BUSINESS",), "IT·과학": ("TECHNOLOGY", "SCIENCE"),
                   "연예": ("ENTERTAINMENT",), "스포츠": ("SPORTS",), "국제": ("WORLD",), "사회": ("NATION",)}


def selected_categories(values=None):
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or len(values) > len(CATEGORIES):
        raise ValueError("수집 분야를 확인하세요.")
    if any(not isinstance(v, str) or v not in CATEGORIES for v in values):
        raise ValueError("허용된 수집 분야를 선택하세요.")
    return [v for v in CATEGORIES if v in values]


def category_query(category):
    selected_categories([category])
    return "(" + " OR ".join(CATEGORY_WORDS[category]) + ") when:1d"


def category_feeds(category):
    from urllib.parse import urlencode
    selected_categories([category])
    params = {"hl": "ko", "gl": "KR", "ceid": "KR:ko"}
    if category in CATEGORY_TOPICS:
        return ["https://news.google.com/rss/headlines/section/topic/" + topic + "?" + urlencode(params)
                for topic in CATEGORY_TOPICS[category]]
    return ["https://news.google.com/rss/search?" + urlencode({"q": category_query(category), **params})]


def classify(text: str) -> str:
    matches = {
        category: sum(word.casefold() in text.casefold() for word in words)
        for category, words in CATEGORY_WORDS.items()
    }
    best = max(matches, key=matches.get)
    return best if matches[best] else "미분류"


@dataclass(frozen=True)
class ScoreResult:
    total: int
    assessed_max: int
    components: dict[str, dict]


def rank(
    title: str, summary: str, published_at: datetime | None, publishers: set[str], now: datetime
) -> ScoreResult:
    components: dict[str, dict] = {}

    def add(key: str, maximum: int, value: int | None, reason: str) -> None:
        components[key] = {
            "maximum": maximum,
            "value": value,
            "status": "미평가" if value is None else "평가",
            "reason": reason,
        }

    if published_at is None:
        add("최신성", 30, None, "RSS 발행시각을 확인할 수 없음")
    else:
        hours = (now - published_at).total_seconds() / 3600
        if hours < 0:
            add("최신성", 30, None, "미래 발행시각으로 최신성 평가 불가")
        else:
            value = (
                30 if hours <= 6 else 24 if hours <= 24 else 15 if hours <= 48 else 6 if hours <= 72 else 0
            )
            add("최신성", 30, value, f"RSS 발행 후 {hours:.1f}시간; 6/24/48/72시간 구간")
    count = len({p.strip().casefold() for p in publishers if p.strip()})
    add(
        "복수 출처",
        25,
        25 if count >= 3 else 15 if count == 2 else None,
        f"중복 묶음 내 서로 다른 RSS 보도 출처 {count}개; 1개는 추가 보도 여부 미확인",
    )
    text = title + " " + summary
    category = classify(text)
    important = [w for w in ("재난", "지진", "전쟁", "선거", "금리", "의료", "정책") if w in text]
    add(
        "주제 중요도",
        20,
        20 if important else None,
        f"공공 영향 키워드: {', '.join(important)}" if important else f"분류 {category}; 공공 영향 근거 부족",
    )
    visual = [w for w in ("영상", "현장", "발사", "시연", "공연", "경기") if w in text]
    add(
        "영상 제작 적합성",
        15,
        15 if visual else None,
        f"장면화 키워드: {', '.join(visual)}" if visual else "RSS에서 영상화 가능성 근거 부족",
    )
    domestic = [w for w in ("한국", "대한민국", "서울", "부산", "국내", "국회") if w in text]
    add(
        "국내 관심도 추정",
        10,
        10 if domestic else None,
        f"국내 연관 키워드: {', '.join(domestic)}; 실제 검색량 아님" if domestic else "국내 연관 근거 부족",
    )
    return ScoreResult(
        sum(v["value"] or 0 for v in components.values()),
        sum(v["maximum"] for v in components.values() if v["value"] is not None),
        components,
    )
