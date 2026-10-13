"""Foundation preparation checks; no validated draft becomes executable in Phase 4A."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from newsflow.db.models import (
    PlatformAccount,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    PublishValidation,
    RenderJob,
    VideoProject,
    utcnow,
)

from .media import FFprobeMediaInspector, MediaInspector


class PublishingError(Exception):
    pass


class ConflictError(PublishingError):
    pass


PLATFORMS = {"instagram", "youtube"}
REAL_BLOCKERS = {"account", "permissions", "api_readiness", "instagram_delivery", "official_policy"}
OFFICIAL_URLS = {
    "youtube": "https://developers.google.com/youtube/v3/docs/videos/insert",
    "instagram": "https://developers.facebook.com/docs/instagram-platform/content-publishing/",
}


def reject_secrets(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False)
    for name, secret_value in os.environ.items():
        if (
            name.upper().endswith(("_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))
            and len(secret_value) >= 8
            and secret_value in text
        ):
            raise PublishingError("비밀정보는 게시 메타데이터에 저장할 수 없습니다.")
    if re.search(r"(?i)Bearer\s+[\w.~+-]{8,}|\bya29\.[\w-]{8,}|\bsk-[\w-]{12,}", text):
        raise PublishingError("인증정보로 보이는 문자열은 입력할 수 없습니다.")


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class PublishingService:
    def __init__(
        self, sessions: sessionmaker[Session], outputs_dir: Path, inspector: MediaInspector | None = None
    ) -> None:
        self.sessions, self.outputs, self.inspector = (
            sessions,
            outputs_dir.resolve(),
            inspector or FFprobeMediaInspector(),
        )

    def media_path(self, job: RenderJob) -> Path:
        if (
            job.status != "success"
            or not job.metadata_json.get("playable")
            or not re.fullmatch(r"video-[0-9a-f]{32}\.mp4", job.output_name)
        ):
            raise PublishingError("검증된 완성 MP4만 선택할 수 있습니다.")
        path = self.outputs / job.output_name
        try:
            if (
                path.is_symlink()
                or not path.resolve().is_relative_to(self.outputs)
                or not path.is_file()
                or not 0 < path.stat().st_size <= 2 * 1024**3
            ):
                raise PublishingError("완성 MP4의 경로·존재·크기를 확인하세요.")
        except OSError:
            raise PublishingError("완성 MP4에 접근하지 못했습니다.") from None
        return path

    @staticmethod
    def input(platform: str, title: str, description: str, hashtags: str, ai_disclosure: str) -> dict:
        reject_secrets((platform, title, description, hashtags, ai_disclosure))
        if platform not in PLATFORMS or ai_disclosure not in {"unreviewed", "not_required", "disclose"}:
            raise PublishingError("플랫폼 또는 AI 표시 검토 상태를 확인하세요.")
        if not isinstance(title, str) or not isinstance(description, str) or not isinstance(hashtags, str):
            raise PublishingError("게시 텍스트 형식을 확인하세요.")
        title, description = title.strip(), description.strip()
        if (
            not 1 <= len(title) <= 100
            or len(description) > 5000
            or any(ord(c) < 32 and c not in "\n\t" for c in title + description)
        ):
            raise PublishingError("제목 1~100자, 설명 최대 5000자와 텍스트 형식을 확인하세요.")
        tags = []
        for token in hashtags.split():
            tag = token.removeprefix("#")
            if (
                not tag
                or len(tag) > 60
                or not all(c.isalnum() or c == "_" for c in tag)
                or not any(c.isalpha() for c in tag)
            ):
                raise PublishingError("해시태그는 문자·숫자·밑줄로 작성하세요.")
            if tag.casefold() not in {t.casefold() for t in tags}:
                tags.append(tag)
        if len(tags) > 30:
            raise PublishingError("앱의 준비 프로파일은 최대 30개 해시태그를 허용합니다.")
        return {
            "platform": platform,
            "title": title,
            "description": description,
            "hashtags": tags,
            "ai_disclosure": ai_disclosure,
        }

    def account_check(self, session: Session, account_id: int | None, platform: str) -> None:
        if account_id is not None:
            account = session.get(PlatformAccount, account_id)
            if not account or account.platform != platform:
                raise PublishingError("플랫폼과 대상 계정 메타데이터가 일치하지 않습니다.")

    def add_account(self, platform: str, label: str, account_type: str) -> int:
        reject_secrets((platform, label, account_type))
        types = {
            "instagram": {"professional_business", "professional_creator", "personal", "unknown"},
            "youtube": {"youtube_channel", "unknown"},
        }
        if (
            platform not in types
            or account_type not in types[platform]
            or not label.strip()
            or len(label) > 100
            or any(ord(c) < 32 for c in label)
        ):
            raise PublishingError("계정 메타데이터의 플랫폼·이름·유형을 확인하세요.")
        with self.sessions.begin() as session:
            account = PlatformAccount(
                platform=platform,
                label=label.strip(),
                account_type=account_type,
                status="not_connected",
                scopes=[],
                credential_ref=None,
                api_ready=False,
            )
            session.add(account)
            session.flush()
            return account.id

    def create(
        self,
        render_job_id: int,
        platform: str,
        title: str,
        description: str,
        hashtags: str,
        account_id: int | None = None,
        content_reviewed: bool = False,
        copyright_confirmed: bool = False,
        sources_confirmed: bool = False,
        ai_disclosure: str = "unreviewed",
    ) -> int:
        fields = self.input(platform, title, description, hashtags, ai_disclosure)
        with self.sessions.begin() as session:
            job = session.get(RenderJob, render_job_id)
            if not job:
                raise PublishingError("완성 영상이 없습니다.")
            path = self.media_path(job)
            project = session.get(VideoProject, job.project_id)
            reject_secrets(project.sources)
            self.account_check(session, account_id, platform)
            try:
                media_hash = hash_file(path)
            except OSError:
                raise PublishingError("완성 MP4를 읽지 못했습니다.") from None
            draft = PublishDraft(
                render_job_id=job.id,
                **fields,
                account_id=account_id,
                sources=project.sources,
                media_sha256=media_hash,
                content_reviewed=content_reviewed,
                copyright_confirmed=copyright_confirmed,
                sources_confirmed=sources_confirmed,
                state="unvalidated",
                revision=1,
            )
            session.add(draft)
            session.flush()
            session.add(
                PublishEvidence(
                    draft_id=draft.id,
                    kind="media_snapshot",
                    payload={
                        "sha256": media_hash,
                        "bytes": path.stat().st_size,
                        "render_job_id": job.id,
                        "source": "local completed MP4; baseline established at draft creation",
                    },
                )
            )
            return draft.id

    def edit(
        self,
        draft_id: int,
        revision: int,
        platform: str,
        title: str,
        description: str,
        hashtags: str,
        account_id: int | None = None,
        content_reviewed: bool = False,
        copyright_confirmed: bool = False,
        sources_confirmed: bool = False,
        ai_disclosure: str = "unreviewed",
    ) -> None:
        fields = self.input(platform, title, description, hashtags, ai_disclosure)
        with self.sessions.begin() as session:
            if not session.get(PublishDraft, draft_id):
                raise PublishingError("게시 초안이 없습니다.")
            self.account_check(session, account_id, platform)
            changed = session.execute(
                update(PublishDraft)
                .where(PublishDraft.id == draft_id, PublishDraft.revision == revision)
                .values(
                    **fields,
                    account_id=account_id,
                    content_reviewed=content_reviewed,
                    copyright_confirmed=copyright_confirmed,
                    sources_confirmed=sources_confirmed,
                    revision=revision + 1,
                    state="unvalidated",
                    updated_at=utcnow(),
                )
            )
            if changed.rowcount != 1:
                raise ConflictError("다른 수정이 저장되었습니다. 새로고침 후 다시 확인하세요.")

    def validate(self, draft_id: int) -> int:
        with self.sessions.begin() as session:
            draft = session.get(PublishDraft, draft_id)
            if not draft:
                raise PublishingError("게시 초안이 없습니다.")
            results = []

            def check(key: str, status: str, reason: str) -> None:
                results.append({"key": key, "status": status, "reason": reason})

            sha = None
            job = session.get(RenderJob, draft.render_job_id)
            try:
                path = self.media_path(job)
                sha = hash_file(path)
                if sha != draft.media_sha256:
                    raise ValueError
                media = self.inspector.inspect(path)
                if hash_file(path) != sha:
                    raise ValueError
                check("media", "pass", "로컬 파일·SHA256·독립 ffprobe 검사 완료; 최초 초안 시점 기준 무결성")
                expected = session.get(VideoProject, job.project_id).duration
                valid = (
                    "mp4" in media.get("format", "")
                    and media.get("video_codec") == "h264"
                    and media.get("audio_codec") == "aac"
                    and media.get("width") == 1080
                    and media.get("height") == 1920
                    and math.isfinite(float(media.get("duration", 0)))
                    and abs(float(media.get("duration", 0)) - expected) <= 0.25
                    and expected in (30, 45, 60)
                    and 23 <= float(media.get("fps", 0)) <= 60
                )
                check(
                    "video_profile",
                    "pass" if valid else "fail",
                    "앱 준비 프로파일: MP4/H.264/AAC/1080×1920/30·45·60초; 공식 플랫폼 전체 규격 확정과 구분",
                )
            except Exception:  # noqa: BLE001 - no raw file/probe or secret error text
                check(
                    "media", "fail", "MP4 접근·해시·ffprobe 검증 실패. 변경/손상/경로/설치 상태를 확인하세요."
                )
                check("video_profile", "unverified", "파일 검증 실패로 영상 규격을 확인하지 못했습니다.")
            check(
                "title",
                "pass"
                if 1 <= len(draft.title) <= 100 and not any(c in draft.title for c in "<>\n\r")
                else "fail",
                "앱 제목 프로파일 1~100자; 꺾쇠/줄바꿈 제외",
            )
            caption = (
                draft.title + "\n" + draft.description + "\n" + " ".join("#" + tag for tag in draft.hashtags)
            )
            limit = 2200 if draft.platform == "instagram" else 5000
            check(
                "description",
                "pass" if len(caption) <= limit else "fail",
                f"제목/설명/태그 합친 앱 준비 예산 {limit}자; 최신 플랫폼 규정은 재확인 필요",
            )
            check(
                "hashtags",
                "pass" if len(draft.hashtags) <= 30 else "fail",
                "중복 정규화·문법 검사, 앱 준비 예산 30개; 공식 제한 확인 필요",
            )
            links = [
                s.get("url", "") for a in draft.sources.get("articles", []) for s in a.get("sources", [])
            ]
            check(
                "source_links",
                "pass"
                if links
                and all(urlsplit(u).scheme in {"https", "http"} and urlsplit(u).netloc for u in links)
                else "fail",
                "원문 링크 보존; 원문 사실 및 이용권을 자동 검증하지 않음",
            )
            for key, value, reason in (
                ("content_review", draft.content_reviewed, "사용자 내용 검토"),
                ("copyright_review", draft.copyright_confirmed, "사용자 소재/저작권 확인"),
                ("source_review", draft.sources_confirmed, "사용자 출처/사실 검토 확인"),
            ):
                check(
                    key, "pass" if value else "fail", reason + "; 체크 여부는 외부 검증 완료를 의미하지 않음"
                )
            check(
                "ai_disclosure",
                "pass" if draft.ai_disclosure in {"not_required", "disclose"} else "fail",
                "사용자 AI 표시 필요성 검토; YouTube containsSyntheticMedia/Meta is_ai_generated 매핑 후보, 적용 정책 재확인 필요",
            )
            account = session.get(PlatformAccount, draft.account_id) if draft.account_id else None
            check(
                "account",
                "fail"
                if not account or account.platform != draft.platform or account.status != "configured"
                else "unverified",
                "계정 연결 없음 또는 만료/취소. Phase 4A는 이름/유형 메타데이터만 저장",
            )
            check(
                "permissions",
                "unverified",
                "OAuth 최소권한/동의/토큰 만료·회수 상태를 실계정에서 확인하지 않았음",
            )
            check(
                "api_readiness",
                "fail",
                "Phase 4A 외부 게시·OAuth 실행 경로 없음. 실제 계정/API 준비 상태 미확인",
            )
            if draft.platform == "instagram":
                check(
                    "instagram_delivery",
                    "unverified",
                    "로컬 MP4는 공개/업로드하지 않음. 공식 로그인 경로별 URL 또는 resumable 제공 방식 승인 필요",
                )
            check(
                "official_policy",
                "unverified",
                "최신 계정 자격·게시 제한·Shorts 분류/Instagram 전달 규정 공식 웹 문서 미확인; 공식 SDK/스키마 근거만 확보",
            )
            key = identity(draft)
            check(
                "duplicate_identity",
                "fail"
                if session.scalar(select(PublishJob.id).where(PublishJob.idempotency_key == key))
                else "pass",
                "플랫폼/대상 계정/영상 SHA256 단위 중복 식별; 결과 불명 자동 재시도 금지",
            )
            validation = PublishValidation(
                draft_id=draft.id,
                draft_revision=draft.revision,
                status="blocked",
                results=results,
                media_sha256=sha,
            )
            session.add(validation)
            changed = session.execute(
                update(PublishDraft)
                .where(PublishDraft.id == draft.id, PublishDraft.revision == draft.revision)
                .values(state="blocked")
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise ConflictError("검증 중 초안이 변경되었습니다. 새 버전을 다시 검증하세요.")
            session.flush()
            session.add(
                PublishEvidence(
                    draft_id=draft.id,
                    kind="validation",
                    payload={
                        "validation_id": validation.id,
                        "draft_revision": draft.revision,
                        "media_sha256": sha,
                        "official_url": OFFICIAL_URLS[draft.platform],
                        "checked_on": "2026-10-13",
                        "real_publishing_enabled": False,
                    },
                )
            )
            return validation.id


def identity(draft: PublishDraft) -> str:
    return hashlib.sha256(f"{draft.platform}:{draft.account_id}:{draft.media_sha256}".encode()).hexdigest()
