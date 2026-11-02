"""Owner-scoped metadata and durable per-target publication journals; no token plaintext."""

from datetime import datetime

from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from newsflow.db.models import Base, UTCDateTime, utcnow


class MetaAccount(Base):
    __tablename__ = "meta_accounts"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    app_id: Mapped[str] = mapped_column(String(40))
    page_id: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(200))
    instagram_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    instagram_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scopes: Mapped[list] = mapped_column(JSON)
    tasks: Mapped[list] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(30))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    user_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    page_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    data_expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    user_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    page_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    identity: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    __table_args__ = (UniqueConstraint("owner", "app_id", "page_id"),)


class MetaPublication(Base):
    __tablename__ = "meta_publications"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    connection_id: Mapped[str] = mapped_column(String(32))
    connection_revision: Mapped[int] = mapped_column(Integer)
    target_id: Mapped[str] = mapped_column(String(40))
    platform: Mapped[str] = mapped_column(String(20))
    content_id: Mapped[str] = mapped_column(String(100))
    media_sha256: Mapped[str] = mapped_column(String(64))
    media_kind: Mapped[str] = mapped_column(String(10))
    caption: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(30))
    remote_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    container_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (UniqueConstraint("owner", "connection_id", "platform", "fingerprint"),)
