"""Strict script shape; factual verification and sources are server controlled."""

import logging
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

Role = Literal['fact', 'meaning', 'action', 'next']
Risk = Literal['low', 'medium', 'high']


def soft_text(value, limit):
    if not isinstance(value, str):
        if value is not None:
            logging.getLogger(__name__).warning('explainer_optional_text_type')
        return ''
    if len(value) > limit:
        logging.getLogger(__name__).warning('explainer_optional_text_trimmed')
    return value[:limit]


def soft_enum(value, choices):
    normalized = value.strip().lower() if isinstance(value, str) else None
    if normalized in choices:
        return normalized
    if value is not None:
        logging.getLogger(__name__).warning('explainer_optional_enum_normalized')
    return None


class ScriptAnalysis(BaseModel):
    model_config = ConfigDict(extra='ignore')
    misconception: str = ''
    viewer_relevance: str = ''
    viewer_action: str = ''
    next_event: str = ''
    ad_risk: Risk | None = None

    @field_validator('misconception', 'viewer_relevance', 'viewer_action', 'next_event', mode='before')
    @classmethod
    def text(cls, value):
        return soft_text(value, 150)

    @field_validator('ad_risk', mode='before')
    @classmethod
    def risk(cls, value):
        return soft_enum(value, {'low', 'medium', 'high'})


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    seconds: int = Field(ge=1, le=60)
    narration: str = Field(min_length=1, max_length=400)
    caption: str = Field(min_length=1, max_length=150)
    material: str = Field(min_length=1, max_length=200)
    role: Role | None = None
    review_notes: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(default_factory=list, max_length=5)

    @field_validator('role', mode='before')
    @classmethod
    def normalize_role(cls, value):
        return soft_enum(value, {'fact', 'meaning', 'action', 'next'})

    @model_serializer(mode="wrap")
    def broadcast_compatible(self, handler):
        value = handler(self)
        if not value.get("review_notes"):
            value.pop("review_notes", None)
        if value.get('role') is None:
            value.pop('role', None)
        return value


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    analysis: ScriptAnalysis | None = None
    title: str = Field(min_length=1, max_length=100)
    hook: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=500)
    scenes: list[Scene] = Field(min_length=1, max_length=8)
    # Phase 5C: closing sentence; optional so Phase 2–5B drafts remain valid.
    closing: str = Field("", max_length=200)

    @field_validator('analysis', mode='before')
    @classmethod
    def normalize_analysis(cls, value):
        if value is None or isinstance(value, (dict, ScriptAnalysis)):
            return value
        logging.getLogger(__name__).warning('explainer_optional_analysis_type')
        return None

    @model_serializer(mode='wrap')
    def legacy_compatible(self, handler):
        value = handler(self)
        if value.get('analysis') is None:
            value.pop('analysis', None)
        return value


CAUTION = "사실 확인 미완료 · RSS 제목/요약 기반 · 게시 전 사람의 원문 확인과 승인 필수. 원문 전체 복제 금지. 이미지/영상 이용 허락을 확인하세요."


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    article_ids: list[int] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=500)
    uncertainties: str = Field(min_length=1, max_length=500)
    viewer_relevance: Literal['high', 'medium', 'low'] | None = None
    ad_risk: Risk | None = None
    viewer_angle: str = ''

    @field_validator('viewer_relevance', 'ad_risk', mode='before')
    @classmethod
    def normalize_risk(cls, value):
        return soft_enum(value, {'low', 'medium', 'high'})

    @field_validator('viewer_angle', mode='before')
    @classmethod
    def angle(cls, value):
        return soft_text(value, 300)

    @model_serializer(mode='wrap')
    def legacy_compatible(self, handler):
        value = handler(self)
        for key in ('viewer_relevance', 'ad_risk', 'viewer_angle'):
            if not value.get(key):
                value.pop(key, None)
        return value


class Analysis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    overview: str = Field(min_length=1, max_length=600)
    comparisons: list[Comparison] = Field(min_length=1, max_length=10)
    # Optional for previously stored analyses and offline/Fake adapters.
    recommended_article_id: int | None = Field(default=None, ge=1)
    selection_reason: str = Field(default="", max_length=500)
    recommended_angle: str = ''

    @field_validator('recommended_angle', mode='before')
    @classmethod
    def angle(cls, value):
        return soft_text(value, 300)

    @model_serializer(mode='wrap')
    def legacy_compatible(self, handler):
        value = handler(self)
        if not value.get('recommended_angle'):
            value.pop('recommended_angle', None)
        return value
