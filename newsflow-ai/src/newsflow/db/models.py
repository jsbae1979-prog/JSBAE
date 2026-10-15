"""UTC-aware SQLite models and explicit provenance."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTC timestamps must be timezone-aware")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        return value.replace(tzinfo=UTC) if value else None


class Base(DeclarativeBase):
    pass


class NewsSource(Base):
    __tablename__ = "news_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    url: Mapped[str] = mapped_column(String(2048), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class NewsArticle(Base):
    __tablename__ = "news_articles"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(2048))
    canonical_url: Mapped[str] = mapped_column(String(2048), unique=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("news_sources.id"))
    publisher: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(30), default="미분류")
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ArticleMention(Base):
    """Dedup retains other publishers and their exact original RSS links."""

    __tablename__ = "article_mentions"
    __table_args__ = (UniqueConstraint("article_id", "url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("news_sources.id"))
    publisher: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(String(2048))


class CollectionRun(Base):
    __tablename__ = "collection_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="running")
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    added: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)


class ArticleScore(Base):
    __tablename__ = "article_scores"
    article_id: Mapped[int] = mapped_column(
        ForeignKey("news_articles.id", ondelete="CASCADE"), primary_key=True
    )
    total: Mapped[int] = mapped_column(Integer)
    assessed_max: Mapped[int] = mapped_column(Integer)
    components: Mapped[dict] = mapped_column(JSON)
    scored_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("collection_runs.id"), nullable=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("news_sources.id"), nullable=True)
    level: Mapped[str] = mapped_column(String(20))
    event: Mapped[str] = mapped_column(String(50))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


class IntelligenceRun(Base):
    __tablename__ = "intelligence_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20))
    options: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict] = mapped_column(JSON)
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ContentDraft(Base):
    __tablename__ = "content_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("intelligence_runs.id"))
    duration: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[dict] = mapped_column(JSON)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    review_status: Mapped[str] = mapped_column(String(30), default="review_required")
    # Phase 5C: server-computed review findings (numbers/dates not in evidence, speech length).
    review_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class VideoProject(Base):
    __tablename__ = "video_projects"
    preview_only: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("content_drafts.id"))
    title: Mapped[str] = mapped_column(String(100))
    duration: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    sources: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    # Phase 5D: the AI video plan this project was composed from (None for local FFmpeg renders).
    ai_plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Scene(Base):
    __tablename__ = "video_scenes"
    __table_args__ = (UniqueConstraint("project_id", "position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str] = mapped_column(Text)
    caption: Mapped[str] = mapped_column(Text)
    material: Mapped[str] = mapped_column(String(255), default="")
    # Phase 5D: a validated provider clip from the AI clip store, always labelled as AI-generated.
    clip_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")


class AudioTrack(Base):
    __tablename__ = "audio_tracks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(30))
    voice: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="pending")


class SubtitleTrack(Base):
    __tablename__ = "subtitle_tracks"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"), unique=True)
    font_size: Mapped[int] = mapped_column(Integer)
    position_y: Mapped[int] = mapped_column(Integer)
    cues: Mapped[list] = mapped_column(JSON)


class RenderJob(Base):
    __tablename__ = "render_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id"))
    status: Mapped[str] = mapped_column(String(30), default="running")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    output_name: Mapped[str] = mapped_column(String(100), unique=True)
    message: Mapped[str] = mapped_column(String(500), default="영상 제작 준비 중")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="not_connected")
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    credential_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    api_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PublishDraft(Base):
    __tablename__ = "publish_drafts"
    autopilot_task_id: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    id: Mapped[int] = mapped_column(primary_key=True)
    render_job_id: Mapped[int] = mapped_column(ForeignKey("render_jobs.id"))
    platform: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[list] = mapped_column(JSON)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("platform_accounts.id"), nullable=True)
    sources: Mapped[dict] = mapped_column(JSON)
    media_sha256: Mapped[str] = mapped_column(String(64))
    content_reviewed: Mapped[bool] = mapped_column(Boolean, default=False)
    copyright_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    sources_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_disclosure: Mapped[str] = mapped_column(String(30), default="unreviewed")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(30), default="unvalidated")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PublishValidation(Base):
    __tablename__ = "publish_validations"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("publish_drafts.id"))
    draft_revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30))
    results: Mapped[list] = mapped_column(JSON)
    media_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PublishJob(Base):
    __tablename__ = "publish_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("publish_drafts.id"))
    platform: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String(500))
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PublishAttempt(Base):
    __tablename__ = "publish_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("publish_jobs.id"))
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class PublishEvidence(Base):
    __tablename__ = "publish_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("publish_drafts.id"))
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OAuthConnection(Base):
    """Only offline preparation/fake lifecycle metadata. No codes/state/verifiers/tokens."""

    __tablename__ = "oauth_connections"
    account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="unprepared")
    mode: Mapped[str] = mapped_column(String(20), default="offline")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OAuthCredentialRotation(Base):
    """Secret-free credential journal; opaque references do not contain token values."""

    __tablename__ = "oauth_credential_rotations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), index=True)
    account_key: Mapped[str] = mapped_column(String(40))
    identity_digest: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(20))
    expected_revision: Mapped[int] = mapped_column(Integer)
    old_reference: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_reference: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OAuthIdentityBinding(Base):
    """Permanent account/client/channel binding digest; no tokens or OAuth callback data."""

    __tablename__ = "oauth_identity_bindings"
    account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), primary_key=True)
    account_key: Mapped[str] = mapped_column(String(40), unique=True)
    identity_digest: Mapped[str] = mapped_column(String(64))
    channel_binding_digest: Mapped[str] = mapped_column(String(64), unique=True)
    grant_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mode: Mapped[str] = mapped_column(String(24), default="synthetic")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class OAuthLifecycleOperation(Base):
    """A durable operation owns a ciphertext reference before the file is written."""

    __tablename__ = "oauth_lifecycle_operations"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"), index=True)
    account_key: Mapped[str] = mapped_column(String(40))
    identity_digest: Mapped[str] = mapped_column(String(64))
    operation: Mapped[str] = mapped_column(String(20))
    expected_revision: Mapped[int] = mapped_column(Integer)
    old_reference: Mapped[str | None] = mapped_column(String(32), nullable=True)
    new_reference: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(32))
    claim_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AutopilotJob(Base):
    """One nullable unique slot serializes active work, including guided review pauses."""

    __tablename__ = "autopilot_jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    active_slot: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    mode: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    duration: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(16))
    # Phase 5C: trial (synthetic news, offline script) or real (registered RSS, optional external AI).
    content_mode: Mapped[str] = mapped_column(String(16), default="trial", server_default="trial")
    ai_mode: Mapped[str] = mapped_column(String(16), default="offline", server_default="offline")
    voice: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    current_stage: Mapped[str] = mapped_column(String(16))
    progress: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    article_id: Mapped[int | None] = mapped_column(ForeignKey("news_articles.id"), nullable=True)
    stage_results: Mapped[dict] = mapped_column(JSON, default=dict)
    message: Mapped[str] = mapped_column(String(300), default="작업 준비 중")
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AutopilotAttempt(Base):
    __tablename__ = "autopilot_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("autopilot_jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class AutopilotArtifact(Base):
    __tablename__ = "autopilot_artifacts"
    __table_args__ = (UniqueConstraint("job_id", "kind", "reference"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("autopilot_jobs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    reference: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AutopilotEvent(Base):
    __tablename__ = "autopilot_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("autopilot_jobs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AutopilotArticleClaim(Base):
    """A selected news item cannot silently produce another automatic video."""

    __tablename__ = "autopilot_article_claims"
    article_id: Mapped[int] = mapped_column(ForeignKey("news_articles.id"), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("autopilot_jobs.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class NewsSourceCheck(Base):
    """Latest explicit connection test per RSS source; never stores feed bytes or raw errors."""

    __tablename__ = "news_source_checks"
    source_id: Mapped[int] = mapped_column(
        ForeignKey("news_sources.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    message: Mapped[str] = mapped_column(String(300))
    article_count: Mapped[int] = mapped_column(Integer, default=0)
    dated_count: Mapped[int] = mapped_column(Integer, default=0)
    summarized_count: Mapped[int] = mapped_column(Integer, default=0)
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AIUsage(Base):
    """Per-request token accounting from provider responses; no prompt, response or key text."""

    __tablename__ = "ai_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("intelligence_runs.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class VideoAIModel(Base):
    """User-confirmed model catalog entry; the path and unit price come from the official docs."""

    __tablename__ = "video_ai_models"
    __table_args__ = (UniqueConstraint("provider", "path"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    path: Mapped[str] = mapped_column(String(160))
    label: Mapped[str] = mapped_column(String(80))
    price_per_second: Mapped[str] = mapped_column(String(20))
    durations: Mapped[str] = mapped_column(String(60))
    resolution: Mapped[str] = mapped_column(String(10))
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AIVideoPlan(Base):
    """Storyboard extension for the optional AI video mode; FFmpeg still composes the final MP4."""

    __tablename__ = "ai_video_plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("content_drafts.id"))
    draft_revision: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    render_job_id: Mapped[int | None] = mapped_column(ForeignKey("render_jobs.id"), nullable=True)
    message: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AIVideoScene(Base):
    """One storyboard scene: card, local image or a generated clip, with its provider state."""

    __tablename__ = "ai_video_scenes"
    __table_args__ = (UniqueConstraint("plan_id", "position"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("ai_video_plans.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    start_ms: Mapped[int] = mapped_column(Integer)
    end_ms: Mapped[int] = mapped_column(Integer)
    narration: Mapped[str] = mapped_column(Text)
    caption: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(12), default="card")
    material: Mapped[str] = mapped_column(String(255), default="", server_default="")
    prompt: Mapped[str] = mapped_column(Text, default="", server_default="")
    model_path: Mapped[str] = mapped_column(String(160), default="", server_default="")
    clip_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    estimated_cost: Mapped[str] = mapped_column(String(20), default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")
    attempt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Idempotency-Key for the submit; reused only to resend a submission whose outcome is unknown.
    submit_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message: Mapped[str] = mapped_column(String(300), default="", server_default="")
    clip_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    clip_meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class VideoAIUsage(Base):
    """Reserved generation cost per scene attempt; separate from the OpenAI token usage table."""

    __tablename__ = "video_ai_usage"
    __table_args__ = (UniqueConstraint("scene_id", "attempt"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("ai_video_plans.id"))
    scene_id: Mapped[int] = mapped_column(ForeignKey("ai_video_scenes.id"))
    attempt: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(20))
    model_path: Mapped[str] = mapped_column(String(160))
    seconds: Mapped[int] = mapped_column(Integer)
    resolution: Mapped[str] = mapped_column(String(10), default="", server_default="")
    estimated_cost: Mapped[str] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20))
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
