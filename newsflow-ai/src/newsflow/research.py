"""Research contract and explicitly synthetic fixtures; no live adapter or DB writes."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from newsflow.intelligence.schema import Scene, Script
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
