"""Research contracts, observed-search evidence and read-only RSS matching."""

import json
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select

from newsflow.db.models import NewsArticle
from newsflow.intelligence.schema import Scene, Script
from newsflow.news.dedup import canonical_url
from newsflow.news.rss_adapter import URLPolicyError, validate_url


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    category: Literal["all", "politics", "economy", "society", "it", "world"] = "all"
    period: Literal["today", "24h", "7d"] = "24h"
    count: Literal[5, 10, 20] = 5


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    publisher: str = Field(min_length=1, max_length=150)
    url: str = Field(min_length=1, max_length=2048)
    evidence: str = Field(min_length=1, max_length=800)

    @field_validator("url")
    @classmethod
    def public_url(cls, value: str) -> str:
        # Syntax/policy check only: this does not prove that an article exists.
        try:
            return validate_url(value)
        except URLPolicyError as exc:
            raise ValueError("Unsafe research source URL") from exc


class Draft(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    seconds: Literal[30, 45, 60]
    script: Script

    @model_validator(mode="after")
    def duration_matches(self):
        if sum(scene.seconds for scene in self.script.scenes) != self.seconds:
            raise ValueError("Draft scene durations must match the requested duration")
        return self


class ResearchArticle(Source):
    title: str = Field(min_length=1, max_length=200)
    published_at: AwareDatetime | None
    researched_at: AwareDatetime
    facts: list[str] = Field(min_length=1, max_length=8)
    video_points: list[str] = Field(min_length=1, max_length=8)
    related: list[Source] = Field(max_length=10)
    confidence: Literal["unverified", "needs_review"]
    uncertainties: list[str] = Field(min_length=1, max_length=8)
    drafts: list[Draft] = Field(min_length=3, max_length=3)

    @field_validator("facts", "video_points", "uncertainties")
    @classmethod
    def bounded_text(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 800 for value in values):
            raise ValueError("Research text must contain 1–800 characters per entry")
        return values

    @model_validator(mode="after")
    def all_durations(self):
        if {draft.seconds for draft in self.drafts} != {30, 45, 60}:
            raise ValueError("Provide one draft for each supported duration")
        return self


class FakeResearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    synthetic: Literal[True] = True
    articles: list[ResearchArticle] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def distinct_urls(self):
        if len({article.url for article in self.articles}) != len(self.articles):
            raise ValueError("Duplicate fixture URL")
        return self


class ResearchBlocked(RuntimeError):
    """Fixed diagnostics must not include credentials or raw server errors."""


class SearchArticle(Source):
    """A search candidate, never a fact-verified or automatically imported article."""

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=800)
    published_at: AwareDatetime | None
    facts: list[str] = Field(min_length=1, max_length=8)
    uncertainties: list[str] = Field(min_length=1, max_length=8)
    verification: Literal["needs_review"] = "needs_review"

    @field_validator("facts", "uncertainties")
    @classmethod
    def bounded_text(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 800 for value in values):
            raise ValueError("Research text must contain 1–800 characters per entry")
        return values

    @field_validator("url")
    @classmethod
    def exclude_fixture_url(cls, value: str) -> str:
        host = (urlsplit(value).hostname or "").lower().rstrip(".")
        if any(host == domain or host.endswith("." + domain) for domain in (
            "example.com", "example.org", "example.net", "example", "test", "invalid", "localhost",
        )):
            raise ValueError("Synthetic fixture URLs cannot be real search candidates")
        return value


class NewsSearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    articles: list[SearchArticle] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def distinct_urls(self):
        if len({canonical_url(article.url) for article in self.articles}) != len(self.articles):
            raise ValueError("Duplicate canonical search source URL")
        return self


def validate_search_evidence(payload: dict, completed_items: list[dict]) -> NewsSearchResult:
    """Bind candidate URLs to actual completed App Server webSearch notifications.

    Callers must pass observed item/completed events, never tool claims from the model's
    JSON. Opening a URL is evidence of a tool action, not semantic fact verification.
    No article body is fetched here and this function never writes to the news store.
    """
    searched = False
    opened: set[str] = set()
    for item in completed_items:
        if not isinstance(item, dict) or item.get("type") != "webSearch":
            continue
        if item.get("status") not in (None, "completed"):
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            continue
        if action.get("type") == "search":
            searched = True
        elif action.get("type") == "openPage":
            urls = action.get("urls", [])
            if not isinstance(urls, list):
                urls = []
            if isinstance(action.get("url"), str):
                urls = [*urls, action["url"]]
            for url in urls:
                if not isinstance(url, str):
                    continue
                try:
                    opened.add(canonical_url(validate_url(url)))
                except URLPolicyError:
                    continue
    if not searched:
        raise ResearchBlocked("실제 웹 검색 완료 근거가 없어 조사를 성공으로 처리하지 않습니다.")
    try:
        # Validate JSON datetime values strictly while preserving unknown publication dates.
        result = NewsSearchResult.model_validate_json(json.dumps(payload, ensure_ascii=False))
    except (ValueError, TypeError):
        raise ResearchBlocked("뉴스 조사 결과가 비어 있거나 출처·JSON 형식이 올바르지 않습니다.") from None
    if any(canonical_url(article.url) not in opened for article in result.articles):
        raise ResearchBlocked("검색 도구에서 직접 연 기사 URL과 조사 결과가 일치하지 않습니다.")
    return result


def find_existing_articles(sessions, result: NewsSearchResult) -> dict[str, int]:
    """Match only canonical URLs already collected through RSS; never insert candidates."""
    wanted = {canonical_url(article.url) for article in result.articles}
    with sessions() as session:
        existing = dict(session.execute(
            select(NewsArticle.canonical_url, NewsArticle.id).where(NewsArticle.canonical_url.in_(wanted))
        ).all())
    return {
        article.url: existing[canonical_url(article.url)]
        for article in result.articles if canonical_url(article.url) in existing
    }


class CodexResearchProvider:
    """Fail closed until real authentication/search/JSON passes the integration gate."""

    def research(self, request: ResearchRequest) -> FakeResearchResult:
        raise ResearchBlocked("Codex 실제 웹 뉴스 조사 미검증: GUI·DB 연동 차단")


class FakeResearchProvider:
    """Local-only test data, deliberately unsuitable for importing as real news."""

    def research(self, request: ResearchRequest, *, cancelled: bool = False) -> FakeResearchResult:
        if cancelled:
            raise ResearchBlocked("합성 조사 취소")
        now = datetime.now(UTC)
        articles = []
        for index in range(request.count):
            text = "[합성] 실제 기사가 아닌 뉴스 조사 테스트 자료입니다."
            drafts = [Draft(seconds=seconds, script=Script(
                title="[합성] 조사 테스트", hook=text, summary=text,
                scenes=[Scene(seconds=seconds, narration=text, caption=text, material="합성 카드")],
            )) for seconds in (30, 45, 60)]
            articles.append(ResearchArticle(
                publisher="합성 출처 · 실제 언론사 아님", url=f"https://example.com/synthetic/{index}",
                evidence="테스트 fixture이며 원문 확인 근거가 아닙니다.", title=f"[합성] 테스트 {index + 1}",
                published_at=None, researched_at=now, facts=[text], video_points=[text], related=[],
                confidence="unverified", uncertainties=["실제 기사·인기 순위·사실 검증 없음"], drafts=drafts,
            ))
        return FakeResearchResult(articles=articles)
