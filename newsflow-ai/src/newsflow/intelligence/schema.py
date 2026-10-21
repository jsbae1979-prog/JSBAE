"""Strict script shape; factual verification and sources are server controlled."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_serializer


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    seconds: int = Field(ge=1, le=60)
    narration: str = Field(min_length=1, max_length=400)
    caption: str = Field(min_length=1, max_length=150)
    material: str = Field(min_length=1, max_length=200)
    review_notes: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=5)

    @model_serializer(mode="wrap")
    def broadcast_compatible(self, handler):
        value = handler(self)
        if not value.get("review_notes"):
            value.pop("review_notes", None)
        return value


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str = Field(min_length=1, max_length=100)
    hook: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    scenes: list[Scene] = Field(min_length=1, max_length=8)
    # Phase 5C: closing sentence; optional so Phase 2–5B drafts remain valid.
    closing: str = Field("", max_length=200)


CAUTION = "사실 확인 미완료 · RSS 제목/요약 기반 · 게시 전 사람의 원문 확인과 승인 필수. 원문 전체 복제 금지. 이미지/영상 이용 허락을 확인하세요."


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    article_ids: list[int] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=500)
    uncertainties: str = Field(min_length=1, max_length=500)


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    overview: str = Field(min_length=1, max_length=600)
    comparisons: list[Comparison] = Field(min_length=1, max_length=10)
    # Optional for previously stored analyses and offline/Fake adapters.
    recommended_article_id: int | None = Field(default=None, ge=1)
    selection_reason: str = Field(default="", max_length=500)
