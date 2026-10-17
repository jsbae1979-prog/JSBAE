"""News-use policy, without networking or inferred factual verification.

URL shape can prioritize a candidate; it cannot prove an article's contents or
publication date. The application currently has no independent source verifier,
so VERIFIED is deliberately blocked. Unverified material can still select a
category explainer, whose words come from a local template, not model claims.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

from newsflow.intelligence.schema import Script

NEWS_USAGE_LABELS = {"QUICK": "빠른 제작", "STANDARD": "균형 제작", "VERIFIED": "검증 우선"}
_CATEGORIES = {
    "all": ("뉴스", "뉴스는 사건과 주장을 전합니다. 보도 내용과 의미를 풀이하는 해설은 구분해야 합니다."),
    "politics": ("정치", "정책은 문제에 대응하는 방안입니다. 제안과 확정, 시행은 서로 다른 단계입니다."),
    "economy": ("경제", "물가는 가격 수준을 뜻합니다. 구매력은 같은 돈으로 살 수 있는 정도입니다."),
    "society": ("사회", "사회 문제에는 개인의 경험과 제도가 얽힙니다. 같은 대응도 대상별 영향이 다를 수 있습니다."),
    "it": ("기술", "기술의 가치는 기능뿐 아니라 사용 목적과 실제 필요에 따라 달라집니다."),
    "world": ("국제", "국제 관계에는 외교와 무역, 안보가 얽힙니다. 당사자별 이해도 다를 수 있습니다."),
    "culture": ("문화", "문화 작품은 창작자의 표현과 관객의 해석이 만납니다. 취향과 평가도 다를 수 있습니다."),
    "sports": ("스포츠", "스포츠 기록은 경기 규칙과 조건 안에서 나옵니다. 결과와 경기 내용은 구분해 볼 수 있습니다."),
}
_CONSIDERATIONS = {
    "all": "배경과 근거를 비교해 보세요. 단편적인 제목만으로 전체 의미를 판단하기는 어렵습니다.",
    "politics": "정책의 대상과 재원, 시행 조건을 함께 살펴보세요. 목표와 실행 방법도 나누어 볼 수 있습니다.",
    "economy": "가격의 변화와 가계 부담을 구분해 보세요. 소득과 소비 품목에 따라 체감은 다를 수 있습니다.",
    "society": "문제의 원인과 영향을 나누어 보세요. 해결 방안의 접근성과 부담도 함께 살펴야 합니다.",
    "it": "도입 전 비용과 개인정보 처리 방식, 이용 조건을 함께 비교해 보세요.",
    "world": "공식 입장과 실제 조치를 나누어 보세요. 다른 지역에 미칠 영향도 맥락 속에서 살펴야 합니다.",
    "culture": "작품의 배경과 표현 방식을 살펴보세요. 인기도와 작품에 대한 평가는 같은 뜻이 아닙니다.",
    "sports": "기록을 비교할 때는 종목과 경기 조건을 살펴보세요. 한 경기만으로 장기 성과를 단정하기 어렵습니다.",
}
_CATEGORY_ALIASES = {
    "전체": "all", "미분류": "all", "기타": "all", "정치": "politics", "경제": "economy", "사회": "society",
    "IT·과학": "it", "IT/과학": "it", "IT": "it", "기술": "it", "과학": "it", "국제": "world",
    "문화": "culture", "스포츠": "sports",
}
_URL_TOPIC_LABELS = {
    "technology": "it", "tech": "it", "science": "it", "politics": "politics",
    "economy": "economy", "business": "economy", "finance": "economy", "markets": "economy",
    "society": "society", "world": "world", "international": "world", "culture": "culture", "sports": "sports",
}
_TOPIC_CAPTIONS = {
    "all": ("보도와 해설", "배경 · 근거 · 맥락"),
    "politics": ("제안 · 확정 · 시행", "대상 · 재원 · 실행 조건"),
    "economy": ("물가와 구매력", "소득 · 소비 · 체감 부담"),
    "society": ("개인과 제도", "원인 · 영향 · 접근성"),
    "it": ("활용 목적과 필요", "비용 · 개인정보 · 이용 조건"),
    "world": ("외교 · 무역 · 안보", "입장 · 조치 · 지역 영향"),
    "culture": ("표현과 해석", "배경 · 인기도 · 평가"),
    "sports": ("결과와 경기 내용", "규칙 · 조건 · 장기 성과"),
}
_LISTING_PARTS = {
    "technology", "tech", "politics", "economy", "business", "world", "news", "latest",
    "science", "society", "search", "category", "categories", "section", "sections", "topics",
    "tag", "tags", "index", "index.html", "index.htm",
}


def validate_news_usage(value: str | None) -> str:
    """Missing selections default to STANDARD; never replace an invalid selection."""
    if value is None:
        return "STANDARD"
    if not isinstance(value, str) or value.strip().upper() not in NEWS_USAGE_LABELS:
        raise ValueError("뉴스 활용 수준을 확인하세요.")
    return value.strip().upper()


def _articles(evidence: dict) -> list[dict]:
    if not isinstance(evidence, dict):
        raise ValueError("뉴스 참고 자료가 없습니다.")  # noqa: TRY004 - one public validation error contract
    articles = evidence.get("articles", [evidence])
    if not isinstance(articles, list) or not articles or any(not isinstance(a, dict) for a in articles):
        raise ValueError("뉴스 참고 자료가 없습니다.")
    if any(not any(a.get(key) for key in ("title", "url", "sources")) for a in articles):
        raise ValueError("뉴스 참고 자료가 없습니다.")
    return articles


def _source_kind(article: dict) -> str:
    url = article.get("url")
    if not url:
        sources = article.get("sources", [])
        url = sources[0].get("url") if isinstance(sources, list) and sources and isinstance(sources[0], dict) else ""
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return "unknown"
        path = [part.lower() for part in parts.path.split("/") if part]
        query = parse_qs(parts.query)
    except (TypeError, ValueError, AttributeError):
        return "unknown"
    if (not path or path[-1] in _LISTING_PARTS or "search" in path
            or any(key in query for key in ("q", "query", "search"))):
        return "listing"
    if ("articles" in path or "article" in path or path[-1].endswith((".html", ".htm"))
            or re.search(r"/\d{4}/\d{2}/\d{2}/", parts.path)
            or any(key in query for key in ("article_id", "articleId", "aid"))):
        return "article_candidate"
    # No attempt to guess that an unknown slug is an independently read article.
    return "unknown"


def assess_news_usage(evidence: dict, mode: str = "STANDARD") -> dict:
    mode = validate_news_usage(mode)
    articles = _articles(evidence)
    kinds = [_source_kind(article) for article in articles]
    ordered = list(zip(articles, kinds, strict=True))
    if mode == "STANDARD":
        ordered.sort(key=lambda entry: entry[1] != "article_candidate")
    blocked = mode == "VERIFIED"
    return {
        "mode": mode,
        "label": NEWS_USAGE_LABELS[mode],
        "approach": "blocked" if blocked else "topic",
        "source_kind": kinds[0] if len(set(kinds)) == 1 else "mixed",
        "verification_status": "NOT VERIFIED",
        "message": (
            "개별 기사·발행일·핵심 사실의 독립 확인 근거가 없어 제작을 중단합니다."
            if blocked else
            "주제 설명형으로 제작합니다. 개별 사건·수치·발언·발행일은 미검증입니다."
        ),
        "preferred_article_ids": [article["id"] for article, _ in ordered if type(article.get("id")) is int],
    }


def safe_topic_script(evidence: dict, duration: int) -> dict:
    """Use only allowlisted category text; never turn a model/title claim into narration.

    The source URL/title/unknown date remain in the caller's evidence, not copied
    into spoken text. This is a transparent local fallback, not an AI fact check.
    """
    if type(duration) is not int or duration not in (30, 45, 60):
        raise ValueError("영상 길이를 확인하세요.")
    article = _articles(evidence)[0]
    category = article.get("category", "all")
    if isinstance(category, str):
        category = _CATEGORY_ALIASES.get(category, category)
    category = category if isinstance(category, str) and category in _CATEGORIES else "all"
    if category == "all":
        # A category path can choose a topic label only, never prove page type,
        # an event, publication date, or any other fact about the source.
        sources = article.get("sources", [])
        urls = [article.get("url")]
        if isinstance(sources, list):
            urls.extend(source.get("url") for source in sources if isinstance(source, dict))
        for url in urls:
            if not isinstance(url, str):
                continue
            try:
                parts = urlsplit(url)
            except ValueError:
                continue
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                continue
            matches = [_URL_TOPIC_LABELS[part] for part in parts.path.lower().split("/") if part in _URL_TOPIC_LABELS]
            if matches:
                category = matches[-1]
                break
    topic, explanation = _CATEGORIES[category]
    narrations = [
        f"{topic} 뉴스의 배경을 풀어봅니다. 개별 사건은 미검증입니다.",
        explanation,
        _CONSIDERATIONS[category],
    ]
    if duration >= 45:
        narrations[0] += " 참고 자료에서 출발해 기본 개념과 판단 기준을 소개합니다."
        narrations[1] += " 무엇을 비교하는지 먼저 정하면 의미를 이해하기 쉽습니다."
        narrations[2] += " 자신의 상황에 어떤 의미가 있는지도 생각해 보세요."
    if duration == 60:
        narrations[0] += " 결론을 내리기보다 쟁점을 나누어 살펴보겠습니다."
        narrations[1] += " 같은 단어라도 쓰이는 맥락에 따라 뜻이 달라질 수 있습니다."
        narrations[2] += " 서로 다른 관점의 근거를 함께 읽으면 시야를 넓힐 수 있습니다."
    return {
        "title": f"{topic} 뉴스의 배경과 핵심 쟁점",
        "hook": f"{topic} 뉴스의 기본 개념과 판단 기준을 소개합니다.",
        "summary": "참고 자료에서 출발한 주제 설명입니다. 개별 사건과 원문 사실은 미검증입니다.",
        "scenes": [
            {"seconds": duration // 3, "narration": narration, "caption": caption,
             "material": "직접 제작한 주제 설명 텍스트 카드"}
            for narration, caption in zip(narrations, (
                "주제 참고 · 개별 기사 미확인", *_TOPIC_CAPTIONS[category],
            ), strict=True)
        ],
        "closing": "원문과 이용 권한을 확인한 뒤 게시해 주세요.",
    }


def validate_news_usage_script(output: dict, evidence: dict, assessment: dict) -> None:
    """Reject unsupported claims without claiming a heuristic can verify prose.

    No independent verifier exists yet. Topic mode therefore accepts only the
    known local template, including its uncertainty captions. VERIFIED cannot
    be enabled by booleans supplied in model output or by a modified assessment.
    """
    if not isinstance(assessment, dict):
        raise ValueError("뉴스 활용 수준을 확인하세요.")  # noqa: TRY004 - callers handle policy validation uniformly
    actual = assess_news_usage(evidence, assessment.get("mode"))
    if actual["approach"] == "blocked":
        raise ValueError(actual["message"])
    try:
        script = Script.model_validate(output).model_dump()
        duration = sum(scene["seconds"] for scene in script["scenes"])
        expected = safe_topic_script(evidence, duration)
    except (ValueError, TypeError):
        raise ValueError("미확인 자료의 주제 설명 대본 형식을 확인하세요.") from None
    if script != expected:
        raise ValueError("미확인 사실이 포함될 수 있어 대본을 차단했습니다. 주제 설명형을 사용하세요.")
