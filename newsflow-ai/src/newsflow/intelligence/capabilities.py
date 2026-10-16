"""Feature contracts, independent of a user's credentials or a successful live request.

This catalogue performs no discovery, login, inference or network request. In particular,
official vendor support for a paid search API does not enable it in NewsFlow.
"""

from __future__ import annotations

NEWS_SEARCH = "NEWS_SEARCH"
NEWS_ANALYSIS = "NEWS_ANALYSIS"
SCRIPT_GENERATION = "SCRIPT_GENERATION"
DEFAULT_ACQUISITION_POLICY = "ai_web"
ACQUISITION_POLICIES = {"rss": "등록 RSS", "ai_web": "AI 웹 뉴스 조사", "hybrid": "AI 웹 조사 + RSS 보완"}
NEWS_CATEGORIES = {"all": "전체", "politics": "정치", "economy": "경제", "society": "사회",
                   "it": "IT·과학", "world": "국제"}
NEWS_PERIODS = {"today": "오늘", "24h": "최근 24시간", "7d": "최근 7일"}
_LABELS = {"offline": "Offline", "claude_code": "Claude Code", "codex": "Codex",
           "openai": "OpenAI API", "claude_api": "Claude API · 별도 API 키·과금"}
_SEARCH_REASONS = {
    "offline": "웹 검색 미지원 · 등록 RSS만 사용합니다.",
    "claude_code": "웹 검색 미검증 · 기존 최소 권한 분석·대본 어댑터는 웹 도구를 허용하지 않습니다.",
    "codex": "웹 검색 BLOCKED · RSS 분석·대본만 지원하며 검색을 재시도하지 않습니다.",
    "openai": "Responses 웹 검색은 별도 API 기능입니다. 검색 승인·한도·계정/모델 검증 전 차단합니다.",
    "claude_api": "Claude Code와 별도 API 키·과금입니다. 검색 승인·비용 한도·계정/모델 검증 전 차단합니다.",
}


def provider_capabilities(provider: str) -> dict:
    """Return a fresh contract; ``available=None`` requires runtime authentication/gates."""
    if provider not in _LABELS:
        raise ValueError("지원하는 AI를 선택하세요.")
    api = provider in {"openai", "claude_api"}
    local = provider == "offline"
    return {
        "provider": provider, "label": _LABELS[provider],
        "features": {
            NEWS_SEARCH: {"implemented": api, "available": False,
                          "verification": "NOT VERIFIED" if provider == "claude_code" else "BLOCKED",
                          "reason": _SEARCH_REASONS[provider]},
            NEWS_ANALYSIS: {"implemented": True, "available": True if local else None,
                            "verification": "LOCAL" if local else "실제 요청 성공과 별도",
                            "reason": "RSS 제목·요약 비교 · 원문 전체 확인 및 사실 검증을 의미하지 않습니다."},
            SCRIPT_GENERATION: {"implemented": True, "available": True if local else None,
                                "verification": "LOCAL" if local else "실제 요청 성공과 별도",
                                "reason": "30·45·60초 검토용 대본 · 대본/출처/권리 검토 필요"},
        },
        "authentication": ("해당 없음" if local else "공식 구독 로그인 · 실행 전 확인"
                           if provider in {"claude_code", "codex"} else "별도 API 키 · 승인 및 한도 필요"),
        "cost": ("외부 AI 비용 없음" if local else "본인 계정 구독 사용량 적용 · 무료·무제한 아님"
                 if provider in {"claude_code", "codex"} else "구독과 별도 API 과금 · 자동 전환 없음"),
    }


def require_acquisition(provider: str, policy: str, *, api_ready: bool = False) -> None:
    """Fail closed; never substitute RSS for unapproved/unverified web search."""
    contract = provider_capabilities(provider)
    if policy not in ACQUISITION_POLICIES:
        raise ValueError("뉴스 확보 방식을 직접 선택해 저장하세요.")
    if policy != "rss" and not (provider in {"openai", "claude_api"} and api_ready is True):
        raise ValueError(contract["features"][NEWS_SEARCH]["reason"])
