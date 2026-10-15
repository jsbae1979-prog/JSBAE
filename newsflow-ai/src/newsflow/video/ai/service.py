"""AI video mode service: storyboard plan, paid-generation gate, async provider jobs, recovery.

Flow (each step re-checks its preconditions in one IMMEDIATE transaction):
  plan from a reviewed draft (same scene split and timing as the local renderer)
  -> per-scene source (card / local image / generated) and prompt
  -> estimate -> the user confirms the shown total (gate + per-job and monthly limits)
  -> background worker submits, polls, downloads and validates each clip
  -> the user reviews every generated scene's relation to the news
  -> the user approves the final composition -> the existing FFmpeg renderer composes the MP4.

Duplicate generation is prevented by compare-and-set state changes, a unique usage row per
scene attempt, a worker file lock, and never resubmitting a request whose outcome is unknown.
The local FFmpeg path never depends on anything here.
"""

from __future__ import annotations

import hashlib
import shutil
import uuid
from datetime import UTC, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Lock, Thread

from filelock import FileLock, Timeout
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.db.models import (
    AIVideoPlan,
    AIVideoScene,
    ArticleMention,
    ContentDraft,
    NewsArticle,
    NewsSource,
    RenderJob,
    VideoAIUsage,
    utcnow,
)
from newsflow.video.service import VideoCoordinator, VideoError

from .clips import ClipStore, probe_clip
from .contracts import (
    CANCELED,
    COMPLETED,
    ERROR_MESSAGES,
    FAILED,
    IN_PROGRESS,
    NSFW,
    QUEUED,
    ClipDownloadError,
    ClipRequest,
    ProviderAmbiguousSubmit,
    ProviderRateLimited,
    ProviderRequestMissing,
    VideoProvider,
    VideoProviderError,
)
from .costs import clip_seconds, money, scene_cost
from .download import MAX_CLIP_BYTES
from .higgsfield import HiggsfieldProvider
from .keys import VideoAIKeyStore
from .policy import DEFAULT_PROMPT, PromptPolicyError, check_prompt, provider_prompt, same_prompt
from .settings import (
    CURRENCY_CHANGED,
    ModelEntry,
    VideoSettingsError,
    check_budget,
    list_models,
    month_start,
    plan_currency_mismatch,
    plan_spent,
    read_settings,
    readiness,
)

SOURCES = ("card", "local", "generated")
ACTIVE = frozenset({"waiting", "submitting", "queued", "in_progress", "downloading"})
SUBMITTED = frozenset({"submitting", "queued", "in_progress"})
RETRYABLE_END = frozenset({"planned", "failed", "nsfw", "canceled"})
MAX_REQUEUES = 3
MAX_REFETCHES = 3
TIMEOUT_OPEN_MESSAGE = (
    "생성이 제한시간 안에 끝나지 않았지만 공급사에서 아직 만들고 있을 수 있습니다. '결과 다시 받기'로 확인하거나(추가 요청 없음) "
    "프롬프트를 바꾸거나 카드로 바꾸세요."
)
CLIP_LOST_MESSAGE = "받아 둔 생성 영상 파일이 없거나 바뀌었습니다. '결과 다시 받기'로 다시 받거나 카드로 바꾸세요."
STATUS_RETRY = "상태 확인 실패 · 다음 확인에서 다시 시도합니다. "
PAUSED_MESSAGE = "AI 영상 공급사가 '사용 안 함'이라 상태 확인을 멈췄습니다. 공급사를 다시 켜면 이어서 확인합니다."
# Closed scenes that still hold a request id: re-checking status and downloading costs no new request.
REFETCHABLE = frozenset({"video_ai_download_failed", "video_ai_clip_invalid", "video_ai_disk_full", "video_ai_timeout"})
# Free space kept on top of one clip before a download starts.
DISK_MARGIN = 512 * 1024 * 1024
COMPOSE_OPEN = frozenset({"failed", "interrupted"})
TERMINAL_SCENE = {FAILED: "failed", NSFW: "nsfw", CANCELED: "canceled"}
TERMINAL_CODE = {FAILED: "video_ai_provider_failed", NSFW: "video_ai_nsfw", CANCELED: "video_ai_canceled"}


def _as_utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


DRAFT_CHANGED = "계획을 만든 뒤 대본이 바뀌었습니다. '바뀐 대본 반영'을 누르거나(장면 구성이 같을 때) 새 계획을 만드세요."


class AIVideoError(Exception):
    """Safe user-facing message; ``status`` is the HTTP status the GUI should answer with."""

    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def draft_is_real(session: Session, draft: ContentDraft) -> bool:
    """True when every source article came from a registered public feed, never the 체험 sample feed."""
    articles = (draft.sources or {}).get("articles") or []
    if not articles:
        return False
    for item in articles:
        article = session.get(NewsArticle, item.get("id")) if isinstance(item, dict) else None
        if article is None:
            return False
        urls = set(session.scalars(
            select(NewsSource.url).join(ArticleMention, ArticleMention.source_id == NewsSource.id)
            .where(ArticleMention.article_id == article.id)
        ))
        own = session.get(NewsSource, article.source_id)
        if own is not None:
            urls.add(own.url)
        if not urls or SAMPLE_URL in urls:
            return False
    return True


class AIVideoCoordinator:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        data_dir: Path,
        video: VideoCoordinator,
        key_store: VideoAIKeyStore | None = None,
        provider: VideoProvider | None = None,
        *,
        poll_interval: float | None = None,
    ) -> None:
        self.sessions, self.root, self.video = sessions, data_dir.resolve(), video
        self.keys = key_store or VideoAIKeyStore(data_dir)
        self.injected = provider
        self.clips = ClipStore(self.root)
        self.poll_interval = poll_interval
        self.stop = Event()
        self.lock = FileLock(str(self.root / "ai-video.lock"), thread_local=False)
        self.thread: Thread | None = None
        self.thread_guard = Lock()
        self.unsaved: list[tuple] = []

    # ------------------------------------------------------------------ provider and gate

    def provider(self) -> VideoProvider | None:
        if self.injected is not None:
            return self.injected
        settings = read_settings(self.sessions)
        if settings.provider != "higgsfield":
            return None
        return HiggsfieldProvider(self.keys.key, host=settings.host)

    def provider_name(self) -> str:
        if self.injected is not None:
            return self.injected.name
        return read_settings(self.sessions).provider

    def readiness(self, *, submitting: bool = False) -> dict:
        override = self.injected.name if self.injected is not None else None
        result = readiness(self.sessions, self.keys, provider_override=override, submitting=submitting)
        result["provider_label"] = self.injected.label if self.injected is not None else (
            "Higgsfield" if result["provider"] == "higgsfield" else "사용 안 함")
        result["test_provider"] = self.injected is not None
        return result

    # ------------------------------------------------------------------ plan editing

    def create_plan(self, draft_id: int, duration: int) -> int:
        if duration not in (30, 45, 60):
            raise AIVideoError("영상 길이는 30초, 45초, 60초 중 선택하세요.")
        with self.sessions.begin() as session:
            draft = session.get(ContentDraft, draft_id)
            if draft is None:
                raise AIVideoError("저장된 대본을 찾지 못했습니다.", 404)
            try:
                times = self.video.timings(draft.content, duration)
            except (VideoError, ValueError):
                raise AIVideoError("대본 장면을 영상 시간으로 나누지 못했습니다. 대본을 확인하세요.") from None
            plan = AIVideoPlan(
                draft_id=draft.id, draft_revision=draft.revision, duration=duration, provider=self.provider_name(),
                status="draft", currency=read_settings(self.sessions).currency,
                message="장면별로 카드·로컬 이미지·AI 생성 중 하나를 고르세요. 기본은 카드(외부 호출 없음)입니다.",
            )
            session.add(plan)
            session.flush()
            for index, ((start, end), scene) in enumerate(zip(times, draft.content["scenes"])):
                session.add(AIVideoScene(
                    plan_id=plan.id, position=index, start_ms=start, end_ms=end, narration=scene["narration"],
                    caption=scene["caption"], source="card", prompt=DEFAULT_PROMPT, status="planned",
                ))
            return plan.id

    def _plan(self, session: Session, plan_id: int, revision: int | None = None) -> AIVideoPlan:
        plan = session.get(AIVideoPlan, plan_id)
        if plan is None:
            raise AIVideoError("AI 영상 계획을 찾지 못했습니다.", 404)
        if revision is not None and plan.revision != revision:
            raise AIVideoError("다른 화면에서 계획이 바뀌었습니다. 새로고침 후 다시 저장하세요.", 409)
        return plan

    def _scenes(self, session: Session, plan_id: int) -> list[AIVideoScene]:
        return list(session.scalars(
            select(AIVideoScene).where(AIVideoScene.plan_id == plan_id).order_by(AIVideoScene.position)))

    @staticmethod
    def _locked(session: Session) -> None:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    def update_scenes(self, plan_id: int, revision: int, edits: list[dict], asset_permission: bool = False) -> None:
        """Change source, local image, prompt and model per scene; resets a clip that no longer matches."""
        models = {m.path: m for m in list_models(self.sessions)}
        if any(edit.get("source") == "local" for edit in edits) and not asset_permission:
            raise AIVideoError("로컬 이미지를 쓰려면 소재 이용 권한을 확인하세요.")
        secrets = self._secrets()
        if any(self._has_secret(str(edit.get("prompt") or ""), secrets) for edit in edits):
            raise AIVideoError("프롬프트에 비밀정보가 포함되어 저장할 수 없습니다.")
        with self.sessions.begin() as session:
            self._locked(session)
            plan = self._plan(session, plan_id, revision)
            self._reopen_compose(session, plan)
            scenes = {s.position: s for s in self._scenes(session, plan_id)}
            for edit in edits:
                scene = scenes.get(edit.get("position"))
                if scene is None:
                    raise AIVideoError("장면 번호를 확인하세요.")
                source = edit.get("source", scene.source)
                if source not in SOURCES:
                    raise AIVideoError("장면 소재는 카드·로컬 이미지·AI 생성 중에서 고르세요.")
                material = (edit.get("material") or "").strip() if source == "local" else ""
                prompt = edit.get("prompt", scene.prompt)
                model_path = (edit.get("model_path") or "").strip() if source == "generated" else ""
                unchanged = (source, model_path) == (scene.source, scene.model_path) and same_prompt(prompt, scene.prompt)
                if scene.status in ACTIVE or scene.status == "unknown":
                    # A confirmed or possibly billed request keeps exactly what was reserved: no
                    # re-pricing, and no new prompt/model under the same Idempotency-Key.
                    if not unchanged:
                        if scene.status == "unknown":
                            raise AIVideoError(
                                f"장면 {scene.position + 1}은 결과 불명 상태입니다. 먼저 실패로 확정한 뒤 바꾸세요.", 409)
                        raise AIVideoError(f"장면 {scene.position + 1}은 생성 중이라 바꿀 수 없습니다. 끝난 뒤 다시 시도하세요.", 409)
                    continue
                paid = self.holds_paid_result(scene)
                if paid and unchanged:
                    continue  # keeps a paid clip as it is, even if its model is no longer usable
                if paid and not edit.get("discard"):
                    raise AIVideoError(
                        f"장면 {scene.position + 1}의 받아 둔 유료 AI 영상(또는 다시 받을 수 있는 결과)이 버려집니다. "
                        "'받아 둔 영상 버리기'에 체크한 뒤 저장하세요.", 409)
                if source == "local":
                    try:
                        self.video.asset(material)
                    except VideoError:
                        raise AIVideoError(f"장면 {scene.position + 1}의 로컬 이미지를 assets 폴더에서 선택하세요.") from None
                if source == "generated":
                    try:
                        prompt = check_prompt(prompt)
                    except PromptPolicyError as exc:
                        raise AIVideoError(f"장면 {scene.position + 1}: {exc}") from None
                    model = models.get(model_path)
                    if model is None or not model.usable:
                        raise AIVideoError(f"장면 {scene.position + 1}의 모델을 공식 문서 확인·단가 입력이 끝난 목록에서 고르세요.")
                    seconds = clip_seconds((scene.end_ms - scene.start_ms) / 1000, model.durations)
                    estimate = money(scene_cost(seconds, model.price_per_second))
                else:
                    prompt = scene.prompt if source != "generated" else prompt
                    seconds, estimate = 0, ""
                changed_generation = (source, prompt, model_path) != (scene.source, scene.prompt, scene.model_path)
                scene.source, scene.material, scene.prompt, scene.model_path = source, material, prompt, model_path
                scene.clip_seconds, scene.estimated_cost = seconds, estimate
                if changed_generation and scene.status not in ACTIVE and scene.status != "unknown":
                    # A clip generated for a different prompt/model no longer belongs to this scene.
                    scene.status, scene.clip_name, scene.clip_meta = "planned", None, None
                    scene.reviewed, scene.error_code, scene.message, scene.submit_key = False, None, "", None
                scene.updated_at = utcnow()
            plan.revision += 1
            plan.reviewed_at = None
            self._refresh(session, plan)

    def rebase(self, plan_id: int, revision: int) -> None:
        """Take a later edit of the script into the plan, keeping paid clips, when the scene timing is unchanged."""
        with self.sessions.begin() as session:
            self._locked(session)
            plan = self._plan(session, plan_id, revision)
            self._reopen_compose(session, plan)
            draft = session.get(ContentDraft, plan.draft_id)
            if draft is None:
                raise AIVideoError("저장된 대본을 찾지 못했습니다.", 404)
            if draft.revision == plan.draft_revision:
                raise AIVideoError("이미 최신 대본을 쓰고 있습니다.", 409)
            try:
                times = self.video.timings(draft.content, plan.duration)
            except (VideoError, ValueError):
                times = []
            scenes = self._scenes(session, plan_id)
            if len(times) != len(scenes) or any((s.start_ms, s.end_ms) != tuple(t) for s, t in zip(scenes, times)):
                raise AIVideoError("대본의 장면 수나 장면 시간이 바뀌어 이 계획에 반영할 수 없습니다. 새 계획을 만드세요.", 409)
            for scene, content in zip(scenes, draft.content["scenes"]):
                scene.narration, scene.caption = content["narration"], content["caption"]
                scene.reviewed, scene.updated_at = False, utcnow()  # captions changed: review again
            plan.draft_revision = draft.revision
            plan.reviewed_at = None
            plan.revision += 1
            self._refresh(session, plan)

    def resolve_unknown(self, plan_id: int, revision: int, position: int) -> None:
        """The user checked the provider dashboard; the unknown request is closed as failed (cost stays counted)."""
        with self.sessions.begin() as session:
            self._locked(session)
            plan = self._plan(session, plan_id, revision)
            scene = next((s for s in self._scenes(session, plan_id) if s.position == position), None)
            if scene is None or scene.status != "unknown":
                raise AIVideoError("결과 불명 상태인 장면만 실패로 확정할 수 있습니다.", 409)
            scene.status, scene.error_code = "failed", "video_ai_unknown_submit"
            scene.message = "사용자가 결과 불명 요청을 실패로 확정했습니다. 예상 비용은 이번 달 사용량에 남습니다."
            scene.finished_at = scene.updated_at = utcnow()
            plan.revision += 1
            self._refresh(session, plan)

    # ------------------------------------------------------------------ estimate and confirmation

    @staticmethod
    def _quote(scene: AIVideoScene, models: dict[str, ModelEntry]) -> tuple[int, str] | None:
        """Clip seconds and cost at the model's CURRENT confirmed price and lengths (None: not usable)."""
        model = models.get(scene.model_path)
        if model is None or not model.usable:
            return None
        seconds = clip_seconds((scene.end_ms - scene.start_ms) / 1000, model.durations)
        return seconds, money(scene_cost(seconds, model.price_per_second))

    @staticmethod
    def _refetchable(scene: AIVideoScene) -> bool:
        return (scene.status == "failed" and scene.error_code in REFETCHABLE and bool(scene.request_id)
                and int((scene.clip_meta or {}).get("refetches", 0)) < MAX_REFETCHES)

    @classmethod
    def holds_paid_result(cls, scene: AIVideoScene) -> bool:
        """A generated scene whose paid result is in hand (ready) or can still be fetched again."""
        return scene.source == "generated" and (scene.status == "ready" or cls._refetchable(scene))

    def _pending(self, scenes: list[AIVideoScene]) -> list[AIVideoScene]:
        # A completed (paid) result that can still be fetched again is never re-bought by a new
        # batch: the user uses '결과 다시 받기' or changes the prompt to generate something else.
        return [s for s in scenes if s.source == "generated" and s.status in RETRYABLE_END and not self._refetchable(s)]

    def estimate(self, plan_id: int) -> dict:
        ready = self.readiness()
        settings = ready["settings"]
        models = {m.path: m for m in list_models(self.sessions)}
        with self.sessions() as session:
            plan = self._plan(session, plan_id)
            scenes = self._scenes(session, plan_id)
            pending = self._pending(scenes)
            quotes = {s.id: self._quote(s, models) for s in pending}
            lines = [{"position": s.position, "seconds": (quotes[s.id] or (s.clip_seconds, ""))[0], "model": s.model_path,
                      "cost": (quotes[s.id] or (0, ""))[1], "usable": quotes[s.id] is not None} for s in pending]
            total = sum((Decimal(q[1]) for q in quotes.values() if q), Decimal(0))
            spent = plan_spent(session, plan_id)
            draft = session.get(ContentDraft, plan.draft_id)
            problems = list(ready["reasons"])
            if draft is None or draft.revision != plan.draft_revision:
                problems.append(DRAFT_CHANGED)
            elif not draft_is_real(session, draft):
                problems.append("체험(합성) 뉴스 대본은 외부 AI 영상 공급사로 보내지 않습니다.")
            refetchable = [s for s in scenes if s.source == "generated" and self._refetchable(s)]
            notices = [
                "장면 " + ", ".join(str(s.position + 1) for s in refetchable)
                + "은 '결과 다시 받기'로 추가 비용 없이 받을 수 있어 새 유료 생성에 넣지 않습니다. 다시 생성하려면 프롬프트를 바꾸세요."
            ] if refetchable else []
            exhausted = [s for s in pending if s.request_id and s.error_code in REFETCHABLE]
            if exhausted:
                notices.append(
                    "장면 " + ", ".join(str(s.position + 1) for s in exhausted)
                    + f"은 결과를 {MAX_REFETCHES}번 받지 못해 새 유료 생성에 포함됩니다(추가 비용).")
            if not pending:
                problems.append("생성할 AI 장면이 없습니다. 장면 소재를 'AI 생성'으로 바꾸세요." if not refetchable
                                else "새로 생성할 AI 장면이 없습니다.")
            if any(s.status == "unknown" for s in scenes):
                problems.append("결과 불명 장면을 먼저 실패로 확정하세요.")
            for scene in pending:
                if quotes[scene.id] is None:
                    problems.append(f"장면 {scene.position + 1}의 모델이 바뀌었거나 사용할 수 없습니다. 모델을 다시 고르세요.")
            if pending and not problems:
                try:
                    check_budget(session, settings, plan_id, total)
                except VideoSettingsError as exc:
                    problems.append(str(exc))
        return {
            "scenes": lines,
            "total": money(total), "currency": settings.currency, "plan_spent": money(spent),
            "job_limit": money(settings.job_limit), "monthly_limit": money(settings.monthly_limit),
            "month_spent": money(ready["usage"]["spent"]), "remaining": money(ready["remaining"]),
            "problems": problems, "notices": notices, "can_submit": not problems,
        }

    def confirm_generation(self, plan_id: int, revision: int, shown_total: str, confirmed: bool) -> int:
        """Reserve the shown estimate and queue the generated scenes; the worker submits them."""
        if not confirmed:
            raise AIVideoError("예상 비용과 유료 생성을 확인한다는 항목에 체크하세요.")
        current = self.estimate(plan_id)
        if not current["can_submit"]:
            raise AIVideoError(" ".join(current["problems"]))
        if shown_total != current["total"]:
            raise AIVideoError("표시된 예상 비용이 바뀌었습니다. 새로고침해 다시 확인하세요.", 409)
        provider = self.provider_name()
        secrets = self._secrets()
        with self.sessions.begin() as session:
            self._locked(session)
            settings = read_settings(self.sessions)  # read under the write lock
            plan = self._plan(session, plan_id, revision)
            self._reopen_compose(session, plan)
            pending = self._pending(self._scenes(session, plan_id))
            models = {m.path: m for m in list_models(self.sessions)}  # read under the write lock
            previous = {s.id: session.scalar(select(VideoAIUsage).where(
                VideoAIUsage.scene_id == s.id, VideoAIUsage.attempt == s.attempt)) for s in pending}
            for scene in pending:
                quote = self._quote(scene, models)
                if quote is None:
                    raise AIVideoError(f"장면 {scene.position + 1}의 모델이 바뀌었거나 사용할 수 없습니다. 모델을 다시 고르세요.", 409)
                # The reservation, the limit check and the request all use today's confirmed price.
                scene.clip_seconds, scene.estimated_cost = quote
            batch = sum((Decimal(s.estimated_cost or "0") for s in pending), Decimal(0))
            if not pending or money(batch) != shown_total:
                raise AIVideoError("표시된 예상 비용이 바뀌었습니다. 새로고침해 다시 확인하세요.", 409)
            for scene in pending:
                if self._has_secret(scene.prompt, secrets):
                    raise AIVideoError("프롬프트에 비밀정보가 포함되어 보낼 수 없습니다.")
            try:
                check_budget(session, settings, plan_id, batch)
            except VideoSettingsError as exc:
                raise AIVideoError(str(exc)) from None
            now = utcnow()
            for scene in pending:
                # A resend after an unknown outcome keeps its key only for the identical request, so a
                # provider that honours Idempotency-Key answers with the first request instead of
                # billing a second one; any difference (model, seconds, resolution) gets a new key.
                last = previous[scene.id]
                resolution = models[scene.model_path].resolution
                # Rows from before 0011 have resolution '': that build always sent the model's resolution.
                same = last is not None and (last.model_path, last.seconds) == (scene.model_path, scene.clip_seconds) \
                    and last.resolution in ("", resolution)
                if scene.error_code != ProviderAmbiguousSubmit.code or not scene.submit_key or not same:
                    scene.submit_key = uuid.uuid4().hex
                scene.attempt += 1
                scene.status, scene.request_id, scene.error_code = "waiting", None, None
                scene.message, scene.clip_name, scene.clip_meta, scene.reviewed = "제출 대기 중", None, None, False
                scene.submitted_at = scene.finished_at = None
                scene.updated_at = now
                session.add(VideoAIUsage(
                    plan_id=plan_id, scene_id=scene.id, attempt=scene.attempt, provider=provider,
                    model_path=scene.model_path, seconds=scene.clip_seconds, estimated_cost=scene.estimated_cost,
                    resolution=resolution, approval=settings.approved_at or "", currency=settings.currency,
                    status="reserved", created_at=now, updated_at=now,
                ))
            plan.confirmed_at, plan.currency = now, settings.currency
            plan.revision += 1
            plan.reviewed_at = None
            plan.message = f"유료 생성 {len(pending)}개 장면 확인됨 · 예상 {money(batch)} {settings.currency}"
            self._refresh(session, plan)
            count = len(pending)
        self.wake()
        return count

    def _secrets(self) -> list[str]:
        """The configured key, and each half of a KEY_ID:KEY_SECRET pair, for prompt scanning."""
        try:
            key = (self.keys.key() or "").strip()
        except Exception:  # noqa: BLE001 - an unreadable key is simply not a secret to scan for
            return []
        values = {key, *(part for part in key.split(":") if len(part) >= 8)} if key else set()
        return sorted(v for v in values if v)

    def _has_secret(self, text: str, secrets: list[str]) -> bool:
        folded = (text or "").casefold()
        return any(secret.casefold() in folded for secret in secrets)

    # ------------------------------------------------------------------ review and composition

    @staticmethod
    def _reopen_compose(session: Session, plan: AIVideoPlan) -> None:
        """A failed or interrupted composition frees the plan again; a running or finished one does not."""
        if plan.render_job_id is None:
            return
        job = session.get(RenderJob, plan.render_job_id)
        if job is not None and job.status not in COMPOSE_OPEN:
            raise AIVideoError("최종 합성을 시작한 계획은 바꿀 수 없습니다. 새 계획을 만드세요.", 409)
        plan.render_job_id, plan.approved_at = None, None

    def sync(self) -> None:
        """Bring 'composing' plans up to date once their render job has ended (read paths call this)."""
        with self.sessions.begin() as session:
            plans = list(session.scalars(select(AIVideoPlan).where(
                AIVideoPlan.status == "composing", AIVideoPlan.render_job_id.is_not(None))))
            for plan in plans:
                job = session.get(RenderJob, plan.render_job_id)
                if job is None or job.status != "running":
                    self._refresh(session, plan)

    def refetch(self, plan_id: int, revision: int, position: int) -> None:
        """Download a completed clip again (no new paid request): the status is re-checked for a fresh URL."""
        provider = self.provider()
        if provider is None:
            raise AIVideoError("AI 영상 공급사가 설정되지 않아 결과를 다시 받을 수 없습니다.", 409)
        with self.sessions.begin() as session:
            self._locked(session)
            plan = self._plan(session, plan_id, revision)
            if plan.render_job_id is not None:
                self._reopen_compose(session, plan)
            scene = next((s for s in self._scenes(session, plan_id) if s.position == position), None)
            if scene is None or scene.status != "failed" or scene.error_code not in REFETCHABLE or not scene.request_id:
                raise AIVideoError("완료 후 내려받기·검증에 실패한 장면만 결과를 다시 받을 수 있습니다.", 409)
            meta = dict(scene.clip_meta or {})
            if int(meta.get("refetches", 0)) >= MAX_REFETCHES:
                raise AIVideoError(f"결과 다시 받기는 {MAX_REFETCHES}번까지입니다. 카드로 바꾸거나 다시 생성하세요.", 409)
            # Counted only when the provider answers 'completed' and a download is attempted.
            meta["refetch_pending"] = True
            scene.clip_meta = meta
            scene.status, scene.error_code = "in_progress", None
            scene.message = "완료된 결과를 다시 확인해 내려받습니다(추가 생성 요청 없음)."
            scene.submitted_at = scene.updated_at = utcnow()
            scene.finished_at = None
            plan.revision += 1
            self._refresh(session, plan)
        self.wake()

    def review(self, plan_id: int, revision: int, positions: set[int], statement: bool) -> None:
        with self.sessions.begin() as session:
            self._locked(session)
            plan = self._plan(session, plan_id, revision)
            self._reopen_compose(session, plan)
            scenes = self._scenes(session, plan_id)
            generated = [s for s in scenes if s.source == "generated"]
            for scene in generated:
                scene.reviewed = scene.status == "ready" and scene.position in positions
            all_reviewed = bool(generated) and all(s.reviewed for s in generated)
            plan.reviewed_at = utcnow() if statement and all_reviewed else None
            plan.revision += 1
            self._refresh(session, plan)

    def approve_compose(self, plan_id: int, revision: int, approved: bool) -> int:
        """Start the existing FFmpeg renderer with the plan's cards, local images and validated clips."""
        if not approved:
            raise AIVideoError("최종 합성을 승인한다는 항목에 체크하세요.")
        self._release_broken_clips(plan_id)
        with self.sessions.begin() as session:
            self._locked(session)
            plan = self._plan(session, plan_id, revision)
            if plan.render_job_id is not None:
                job = session.get(RenderJob, plan.render_job_id)
                if job is not None and job.status not in COMPOSE_OPEN:
                    raise AIVideoError("이미 최종 합성을 시작했습니다.", 409)
                plan.render_job_id = None  # retry after a failed or interrupted composition
            draft = session.get(ContentDraft, plan.draft_id)
            if draft is None or draft.revision != plan.draft_revision:
                raise AIVideoError(DRAFT_CHANGED, 409)
            scenes = self._scenes(session, plan_id)
            for scene in scenes:
                if scene.source == "generated" and (scene.status != "ready" or not scene.reviewed or not scene.clip_name):
                    raise AIVideoError(
                        f"장면 {scene.position + 1}의 AI 생성 영상이 준비·검토되지 않았습니다. 기다리거나 카드로 바꾸세요.")
            if any(s.source == "generated" for s in scenes) and plan.reviewed_at is None:
                raise AIVideoError("원본 뉴스와 AI 생성 장면의 관계 검토를 먼저 저장하세요.")
            specs = [
                {"material": s.material if s.source == "local" else "",
                 "clip": s.clip_name if s.source == "generated" else None,
                 "clip_format": (s.clip_meta or {}).get("format", "mov"),
                 "sha256": (s.clip_meta or {}).get("sha256") if s.source == "generated" else None}
                for s in scenes
            ]
            for scene, spec in zip(scenes, specs, strict=True):
                # The clip composed must be the clip the user reviewed.
                if spec["clip"] and (not spec["sha256"] or self._digest(spec["clip"]) != spec["sha256"]):
                    raise AIVideoError(
                        f"장면 {scene.position + 1}의 생성 영상 파일이 검토 후 바뀌었거나 없습니다. 결과를 다시 받거나 카드로 바꾸세요.", 409)
            plan.approved_at = utcnow()
            plan.revision += 1
            plan.status = "composing"
            plan.message = "최종 합성 승인됨 · 기존 FFmpeg 제작 경로로 MP4를 만듭니다."
            draft_id, duration = plan.draft_id, plan.duration
        try:
            job_id = self.video.start_ai(plan_id, draft_id, duration, specs, self.clips)
        except Exception as exc:
            with self.sessions.begin() as session:
                plan = session.get(AIVideoPlan, plan_id)
                plan.approved_at = None
                self._refresh(session, plan)
                plan.message = "최종 합성을 시작하지 못했습니다. 제작 중인 영상이 끝난 뒤 다시 시도하세요."
            if isinstance(exc, VideoError):
                raise AIVideoError(str(exc), 409 if "실행 중" in str(exc) else 422) from None
            raise
        with self.sessions.begin() as session:
            plan = session.get(AIVideoPlan, plan_id)
            plan.render_job_id = job_id
            self._refresh(session, plan)
        return job_id

    def _release_broken_clips(self, plan_id: int) -> None:
        """A reviewed clip that is missing or changed on disk becomes refetchable (no new paid request)."""
        with self.sessions() as session:
            states = {
                s.position: self._clip_state(s.clip_name, (s.clip_meta or {}).get("sha256"))
                for s in self._scenes(session, plan_id)
                if s.source == "generated" and s.status == "ready" and s.request_id
            }
        unreadable = [p for p, state in states.items() if state == "unreadable"]
        if unreadable:
            # Busy or locked (e.g. another program has it open): never mistake that for a lost clip.
            raise AIVideoError(
                "장면 " + ", ".join(str(p + 1) for p in unreadable)
                + "의 생성 영상 파일을 지금 읽을 수 없습니다. 다른 프로그램에서 열려 있는지 확인한 뒤 다시 시도하세요.", 409)
        broken = [p for p, state in states.items() if state == "lost"]
        if not broken:
            return
        with self.sessions.begin() as session:
            self._locked(session)
            plan = session.get(AIVideoPlan, plan_id)
            for scene in self._scenes(session, plan_id):
                if scene.position in broken and scene.status == "ready":
                    scene.status, scene.error_code, scene.message = "failed", ClipDownloadError.code, CLIP_LOST_MESSAGE
                    scene.clip_name, scene.reviewed, scene.updated_at = None, False, utcnow()
            plan.revision += 1
            plan.reviewed_at = None
            self._refresh(session, plan)
        raise AIVideoError(
            "장면 " + ", ".join(str(p + 1) for p in broken)
            + "의 받아 둔 생성 영상 파일이 없거나 바뀌었습니다. '결과 다시 받기'로 다시 받거나 카드로 바꾼 뒤 검토하세요.", 409)

    def _clip_state(self, name: str | None, sha256: str | None) -> str:
        """'ok', 'lost' (missing file or different bytes) or 'unreadable' (exists but cannot be read now)."""
        if not name or not sha256:
            return "lost"
        try:
            path = self.clips.path(name)
        except VideoProviderError:
            return "lost"
        digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except FileNotFoundError:
            return "lost"
        except OSError:
            return "unreadable"
        return "ok" if digest.hexdigest() == sha256 else "lost"

    def _digest(self, name: str) -> str | None:
        try:
            path = self.clips.path(name)
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except (OSError, VideoProviderError):
            return None
        return digest.hexdigest()

    def _refresh(self, session: Session, plan: AIVideoPlan) -> None:
        scenes = self._scenes(session, plan.id)
        if plan.render_job_id is not None:
            job = session.get(RenderJob, plan.render_job_id)
            plan.status = {"success": "composed", "simulated": "composed", "running": "composing"}.get(
                job.status if job else "", "compose_failed")
        elif any(s.status in ACTIVE for s in scenes):
            plan.status = "generating"
        elif any(s.source == "generated" and s.status == "ready" for s in scenes) or any(
                s.status in {"failed", "nsfw", "canceled", "unknown"} for s in scenes if s.source == "generated"):
            plan.status = "review"
        else:
            plan.status = "draft"
        plan.updated_at = utcnow()

    def cancel_scene(self, plan_id: int, revision: int, position: int) -> str:
        """Cancel a waiting scene locally or a queued provider request (started requests cannot be cancelled)."""
        provider = self.provider()
        with self.sessions.begin() as session:
            self._locked(session)
            plan = self._plan(session, plan_id, revision)
            scene = next((s for s in self._scenes(session, plan_id) if s.position == position), None)
            if scene is None or scene.status not in {"waiting", "queued"}:
                raise AIVideoError("제출 대기·대기열 상태인 장면만 취소할 수 있습니다.", 409)
            if scene.status == "waiting":
                scene.status, scene.error_code, scene.message = "canceled", "video_ai_canceled", "제출 전에 취소했습니다."
                self._usage(session, scene, "not_sent")
                scene.updated_at = utcnow()
                plan.revision += 1
                self._refresh(session, plan)
                return "canceled"
            request_id = scene.request_id
        if provider is None or request_id is None:
            raise AIVideoError("AI 영상 공급사가 설정되지 않아 취소 요청을 보낼 수 없습니다.", 409)
        try:
            accepted = provider.cancel(request_id)
        except VideoProviderError as exc:
            raise AIVideoError(ERROR_MESSAGES.get(exc.code, exc.message), 502) from None
        if not accepted:
            raise AIVideoError("공급사에서 이미 처리를 시작해 취소할 수 없습니다. 완료를 기다리세요.", 409)
        with self.sessions.begin() as session:
            scene = session.scalar(select(AIVideoScene).where(
                AIVideoScene.plan_id == plan_id, AIVideoScene.position == position))
            if scene is not None and scene.request_id == request_id:
                scene.status, scene.error_code = "canceled", "video_ai_canceled"
                scene.message, scene.finished_at = "공급사 대기열에서 취소했습니다.", utcnow()
                self._usage(session, scene, "canceled")
                plan = session.get(AIVideoPlan, plan_id)
                plan.revision += 1
                self._refresh(session, plan)
        return "canceled"

    # ------------------------------------------------------------------ worker

    @staticmethod
    def _usage(session: Session, scene: AIVideoScene, status: str, request_id: str | None = None) -> None:
        row = session.scalar(select(VideoAIUsage).where(
            VideoAIUsage.scene_id == scene.id, VideoAIUsage.attempt == scene.attempt))
        if row is not None:
            row.status, row.updated_at = status, utcnow()
            if request_id:
                row.request_id = request_id

    def _fail(self, session: Session, scene: AIVideoScene, code: str, usage: str | None) -> None:
        scene.status = "unknown" if code == "video_ai_unknown_submit" else "failed"
        scene.error_code, scene.message = code, ERROR_MESSAGES.get(code, ERROR_MESSAGES["video_ai_failed"])[:300]
        scene.finished_at = scene.updated_at = utcnow()
        if usage:
            self._usage(session, scene, usage)

    def tick(self) -> None:
        """One worker pass: submit waiting scenes, poll submitted ones, download completed clips."""
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            return  # another NewsFlow process owns the AI video worker
        try:
            self._submit_waiting()
            self._poll_active()
        finally:
            self.lock.release()

    def _submit_waiting(self) -> None:
        if not self._flush_submitted():
            return  # the database still refuses writes: send nothing new until the ids are stored
        with self.sessions() as session:
            waiting = [s.id for s in session.scalars(
                select(AIVideoScene).where(AIVideoScene.status == "waiting").order_by(AIVideoScene.updated_at, AIVideoScene.id))]
        for scene_id in waiting:
            if self.stop.is_set():
                return
            with self.sessions.begin() as session:
                self._locked(session)
                # Every send is gated on the settings committed when this scene is claimed: the
                # settings and model writers also take BEGIN IMMEDIATE, so nothing changes until the
                # compare-and-set below commits.
                settings = read_settings(self.sessions)
                busy = session.scalar(select(func.count(AIVideoScene.id)).where(AIVideoScene.status.in_(SUBMITTED)))
                ready = self.readiness(submitting=True)
                provider = self.provider()
                models = {m.path: m for m in list_models(self.sessions)}
                scene = session.get(AIVideoScene, scene_id)
                if scene is None or scene.status != "waiting":
                    continue
                plan = session.get(AIVideoPlan, scene.plan_id)
                draft = session.get(ContentDraft, plan.draft_id) if plan else None
                model = models.get(scene.model_path)
                reserved = session.scalar(select(VideoAIUsage).where(
                    VideoAIUsage.scene_id == scene.id, VideoAIUsage.attempt == scene.attempt))
                problem = None
                if provider is None or not ready["ready"]:
                    problem = "설정이 바뀌어 AI 영상 생성 조건을 만족하지 않아 제출하지 않았습니다. " + " ".join(ready["reasons"])
                elif reserved is None or not settings.approved_at or reserved.approval != settings.approved_at:
                    # This reservation was confirmed under another approval (withdrawn and granted
                    # again since): a confirmation never carries over to a new approval.
                    problem = "확인 뒤에 유료 생성 승인이 다시 저장되어 이전 확인으로는 제출하지 않았습니다. 예상 비용을 다시 확인하세요."
                elif reserved.created_at is not None and _as_utc(reserved.created_at) < month_start():
                    # Confirmed under last month's limit: this month's limit never counted it.
                    problem = "달이 바뀌어 지난달의 확인으로는 제출하지 않았습니다. 예상 비용을 다시 확인하세요."
                elif plan_currency_mismatch(session, plan.id, settings.currency):
                    problem = CURRENCY_CHANGED
                elif plan_spent(session, plan.id) > settings.job_limit:
                    problem = "작업별 한도가 확인 뒤에 낮아져 제출하지 않았습니다. 예상 비용을 다시 확인하세요."
                elif draft is None or draft.revision != plan.draft_revision or not draft_is_real(session, draft):
                    problem = "대본이 바뀌었거나 체험 뉴스여서 제출하지 않았습니다."
                elif (
                    model is None or not model.usable or reserved is None
                    or (reserved.model_path, reserved.seconds, reserved.estimated_cost, reserved.resolution)
                    != (scene.model_path, *(self._quote(scene, models) or (None, None)), model.resolution)
                ):
                    # The request must be exactly what was confirmed and limit-checked.
                    problem = "모델 설정이 바뀌어 제출하지 않았습니다. 장면을 다시 확인하세요."
                prompt = None
                if not problem:
                    try:
                        # Re-checked at send time: a prompt saved under an older rule is never sent.
                        prompt = provider_prompt(scene.prompt)
                    except PromptPolicyError:
                        problem = "프롬프트가 현재 정책을 통과하지 못해 제출하지 않았습니다. 프롬프트를 고친 뒤 다시 확인하세요."
                if problem:
                    scene.status, scene.error_code, scene.message = "canceled", "video_ai_canceled", problem[:300]
                    scene.finished_at = scene.updated_at = utcnow()
                    self._usage(session, scene, "not_sent")
                    self._refresh(session, plan)
                    continue
                if busy >= settings.max_active:
                    continue  # gated above every pass; sent when a slot frees up
                # Compare-and-set: from here on a crash leaves 'submitting', which recovery turns into
                # 'unknown' instead of resending (a resent submission could be billed twice).
                scene.status, scene.message, scene.updated_at = "submitting", "공급사에 제출 중", utcnow()
                request = ClipRequest(
                    reserved.model_path, prompt, reserved.seconds, reserved.resolution,
                    idempotency_key=scene.submit_key,
                )
                attempt = scene.attempt
            self._submit_one(provider, scene_id, attempt, request)

    def _flush_submitted(self) -> bool:
        """Store request ids whose first write failed (never resubmit; the provider already has them)."""
        while self.unsaved:
            scene_id, attempt, submission = self.unsaved[0]
            try:
                self._record_submission(scene_id, attempt, submission)
            except SQLAlchemyError:
                return False
            self.unsaved.pop(0)
        return True

    def _record_submission(self, scene_id: int, attempt: int, submission) -> None:
        with self.sessions.begin() as session:
            scene = session.get(AIVideoScene, scene_id)
            if scene is None or scene.attempt != attempt or scene.status not in ("submitting", "unknown"):
                return
            state = submission.state if submission.state in (QUEUED, IN_PROGRESS) else QUEUED
            scene.status, scene.request_id, scene.error_code = state, submission.request_id, None
            scene.submitted_at = scene.updated_at = utcnow()
            scene.message = "공급사 대기열에 등록됨"
            self._usage(session, scene, "submitted", submission.request_id)
            self._refresh(session, session.get(AIVideoPlan, scene.plan_id))

    def _submit_one(self, provider: VideoProvider, scene_id: int, attempt: int, request: ClipRequest) -> None:
        try:
            submission = provider.submit(request)
        except ProviderRateLimited:
            with self.sessions.begin() as session:
                scene = session.get(AIVideoScene, scene_id)
                requeues = int((scene.clip_meta or {}).get("requeues", 0)) + 1
                if requeues > MAX_REQUEUES:
                    self._fail(session, scene, ProviderRateLimited.code, "failed")
                else:
                    scene.status, scene.clip_meta = "waiting", {"requeues": requeues}
                    scene.message = ERROR_MESSAGES[ProviderRateLimited.code][:300]
                    scene.updated_at = utcnow()
                self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
            return
        except VideoProviderError as exc:
            code = exc.code
            usage = "not_sent" if not exc.sent else ("unknown" if isinstance(exc, ProviderAmbiguousSubmit) else "failed")
            with self.sessions.begin() as session:
                scene = session.get(AIVideoScene, scene_id)
                self._fail(session, scene, code, usage)
                self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
            return
        except Exception:  # noqa: BLE001 - an unexpected adapter defect after sending is treated as unknown
            with self.sessions.begin() as session:
                scene = session.get(AIVideoScene, scene_id)
                self._fail(session, scene, ProviderAmbiguousSubmit.code, "unknown")
                self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
            return
        # The request id is the only handle on a billed request: retry the write briefly, then keep it
        # in memory for the next pass instead of losing it (the scene stays 'submitting', never resent).
        for delay in (0.0, 0.5, 1.0, 2.0):
            if delay:
                self.stop.wait(delay)
            try:
                self._record_submission(scene_id, attempt, submission)
                return
            except SQLAlchemyError:
                continue
        self.unsaved.append((scene_id, attempt, submission))

    def _poll_active(self) -> None:
        settings = read_settings(self.sessions)
        provider = self.provider()
        with self.sessions() as session:
            active = [(s.id, s.request_id, s.attempt) for s in session.scalars(
                select(AIVideoScene).where(AIVideoScene.status.in_(("queued", "in_progress", "downloading"))))]
        for scene_id, request_id, attempt in active:
            if self.stop.is_set():
                return
            if provider is None or request_id is None:
                # Status checks resume when the provider is switched on again; say so on the scene.
                with self.sessions.begin() as session:
                    scene = session.get(AIVideoScene, scene_id)
                    if scene is not None and scene.message != PAUSED_MESSAGE:
                        scene.message, scene.updated_at = PAUSED_MESSAGE, utcnow()
                continue
            with self.sessions() as session:
                scene = session.get(AIVideoScene, scene_id)
                submitted = scene.submitted_at
            timed_out = submitted is not None and utcnow() - submitted > timedelta(minutes=settings.timeout_minutes)
            try:
                status = provider.status(request_id)
            except Exception as exc:  # noqa: BLE001 - one scene's status failure never stops the others
                code = exc.code if isinstance(exc, VideoProviderError) else "video_ai_bad_response"
                if isinstance(exc, ProviderRequestMissing):
                    with self.sessions.begin() as session:
                        scene = session.get(AIVideoScene, scene_id)
                        if scene is not None and scene.attempt == attempt and scene.status in ("queued", "in_progress", "downloading"):
                            self._fail(session, scene, code, "failed")
                            self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
                    continue
                if submitted is not None and utcnow() - submitted > 2 * timedelta(minutes=settings.timeout_minutes):
                    # Still no answer long after the deadline: close it, but keep it refetchable.
                    self._timeout(provider, scene_id, request_id, attempt)
                    continue
                with self.sessions.begin() as session:
                    scene = session.get(AIVideoScene, scene_id)
                    if scene is not None and scene.attempt == attempt:
                        scene.message = (STATUS_RETRY + ERROR_MESSAGES.get(code, ""))[:300]
                        scene.updated_at = utcnow()
                continue
            if status.state in (QUEUED, IN_PROGRESS) and timed_out:
                # A completed result is still downloaded after a long pause; only waiting work times out.
                self._timeout(provider, scene_id, request_id, attempt)
                continue
            if status.state in (QUEUED, IN_PROGRESS):
                with self.sessions.begin() as session:
                    scene = session.get(AIVideoScene, scene_id)
                    stale = scene is not None and (scene.message == PAUSED_MESSAGE or scene.message.startswith(STATUS_RETRY))
                    if scene is not None and scene.attempt == attempt and (scene.status != status.state or stale):
                        scene.status, scene.updated_at = status.state, utcnow()
                        scene.message = "공급사 대기열" if status.state == QUEUED else "공급사에서 생성 중"
                        self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
                continue
            if status.state in TERMINAL_SCENE:
                with self.sessions.begin() as session:
                    scene = session.get(AIVideoScene, scene_id)
                    if scene is not None and scene.attempt == attempt:
                        scene.status, scene.error_code = TERMINAL_SCENE[status.state], TERMINAL_CODE[status.state]
                        scene.message = ERROR_MESSAGES[TERMINAL_CODE[status.state]][:300]
                        scene.finished_at = scene.updated_at = utcnow()
                        self._usage(session, scene, "canceled" if status.state == CANCELED else "failed")
                        self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
                continue
            if status.state == COMPLETED:
                self._download(provider, scene_id, attempt, status)

    def _timeout(self, provider: VideoProvider, scene_id: int, request_id: str, attempt: int) -> None:
        try:
            canceled = provider.cancel(request_id) is True
        except Exception:  # noqa: BLE001 - best effort; an unanswered cancel may still finish
            canceled = False
        with self.sessions.begin() as session:
            scene = session.get(AIVideoScene, scene_id)
            if scene is not None and scene.attempt == attempt and scene.status in ("queued", "in_progress", "downloading"):
                if canceled:
                    # Cancelled at the provider: nothing will arrive, so it is not offered for refetch.
                    scene.status, scene.error_code = "canceled", "video_ai_timeout"
                    scene.message = ERROR_MESSAGES["video_ai_timeout"][:300]
                    scene.finished_at = scene.updated_at = utcnow()
                    self._usage(session, scene, "canceled")
                else:
                    self._fail(session, scene, "video_ai_timeout", "failed")  # may still finish: refetchable
                    scene.message = TIMEOUT_OPEN_MESSAGE
                self._refresh(session, session.get(AIVideoPlan, scene.plan_id))

    def _download(self, provider: VideoProvider, scene_id: int, attempt: int, status) -> None:
        with self.sessions.begin() as session:
            scene = session.get(AIVideoScene, scene_id)
            if scene is None or scene.attempt != attempt:
                return
            scene.status, scene.message, scene.updated_at = "downloading", "생성 완료 · 안전 검사 후 내려받는 중", utcnow()
            seconds = scene.clip_seconds
        target = self.clips.new_path()
        try:
            if shutil.disk_usage(self.clips.root).free < MAX_CLIP_BYTES + DISK_MARGIN:
                raise ClipDownloadError()
            fetched = provider.fetch(status, target, self.stop)
            meta = probe_clip(target, min_seconds=min(1.0, max(0.5, seconds - 0.5)))
        except Exception as exc:  # noqa: BLE001 - any failure closes this scene; the request id is kept
            target.unlink(missing_ok=True)
            low_disk = False
            try:
                low_disk = shutil.disk_usage(self.clips.root).free < MAX_CLIP_BYTES + DISK_MARGIN
            except OSError:
                low_disk = False
            code = "video_ai_disk_full" if low_disk else (
                exc.code if isinstance(exc, VideoProviderError) else ClipDownloadError.code)
            if code not in REFETCHABLE:
                code = ClipDownloadError.code
            with self.sessions.begin() as session:
                scene = session.get(AIVideoScene, scene_id)
                if scene is not None and scene.attempt == attempt:
                    if self.stop.is_set():
                        scene.status, scene.message = "downloading", ERROR_MESSAGES["video_ai_interrupted"]
                    else:
                        # Paid and completed: 'refetch' can download it again without a new request.
                        meta = dict(scene.clip_meta or {})
                        if meta.pop("refetch_pending", False) and code != "video_ai_disk_full":
                            meta["refetches"] = int(meta.get("refetches", 0)) + 1  # a real download attempt
                        scene.clip_meta = meta
                        self._fail(session, scene, code, "completed")
                        self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
            return
        with self.sessions.begin() as session:
            scene = session.get(AIVideoScene, scene_id)
            if scene is None or scene.attempt != attempt:
                target.unlink(missing_ok=True)
                return
            scene.status, scene.clip_name = "ready", target.name
            # The paid result is in hand: the refetch allowance starts again for any later loss.
            scene.clip_meta = {**meta, "sha256": fetched.sha256, "download_host": fetched.host}
            scene.message = "생성 영상 준비됨 · 원본 뉴스와의 관계를 검토하세요."
            scene.reviewed, scene.finished_at, scene.updated_at = False, utcnow(), utcnow()
            self._usage(session, scene, "completed")
            self._refresh(session, session.get(AIVideoPlan, scene.plan_id))

    def recover(self) -> None:
        """After a restart: never resend; mark interrupted submissions unknown and resume status checks."""
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            return
        try:
            with self.sessions.begin() as session:
                for scene in session.scalars(select(AIVideoScene).where(AIVideoScene.status == "submitting")):
                    self._fail(session, scene, ProviderAmbiguousSubmit.code, "unknown")
                    self._refresh(session, session.get(AIVideoPlan, scene.plan_id))
                for scene in session.scalars(select(AIVideoScene).where(AIVideoScene.status == "downloading")):
                    # The provider still holds the result; re-check status for a fresh URL next tick.
                    scene.status, scene.message = "in_progress", "재시작 후 생성 결과를 다시 확인합니다."
                    scene.updated_at = utcnow()
            for partial in self.clips.root.glob("clip-*.mp4"):
                with self.sessions() as session:
                    used = session.scalar(select(AIVideoScene.id).where(AIVideoScene.clip_name == partial.name))
                if used is None and not partial.is_symlink():
                    partial.unlink(missing_ok=True)
        finally:
            self.lock.release()

    def has_work(self) -> bool:
        with self.sessions() as session:
            return session.scalar(select(AIVideoScene.id).where(AIVideoScene.status.in_(ACTIVE)).limit(1)) is not None

    def wake(self) -> None:
        """Start the worker thread when there is work; it exits by itself once nothing is active."""
        with self.thread_guard:
            if self.stop.is_set() or (self.thread is not None and self.thread.is_alive()):
                return
            self.thread = Thread(target=self._loop, name="newsflow-ai-video", daemon=True)
            self.thread.start()

    def _loop(self) -> None:
        while not self.stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001, S110 - the worker must survive one bad pass; state stays in SQLite
                pass
            with self.thread_guard:
                if not self.has_work():
                    self.thread = None
                    return
            interval = self.poll_interval or read_settings(self.sessions).poll_seconds
            self.stop.wait(interval)

    def start(self) -> None:
        """App start: recover interrupted state, then resume only if scenes are still active."""
        self.recover()
        if self.has_work():
            self.wake()

    def close(self) -> None:
        self.stop.set()
        thread = self.thread
        if thread is not None:
            thread.join(timeout=30)
        try:
            self._flush_submitted()  # last chance to store request ids held in memory
        except Exception:  # noqa: BLE001, S110 - recovery then marks such scenes unknown (never resent)
            pass

    # ------------------------------------------------------------------ views

    def clip_path(self, scene_id: int) -> Path:
        with self.sessions() as session:
            scene = session.get(AIVideoScene, scene_id)
            if scene is None or scene.status != "ready" or not scene.clip_name:
                raise AIVideoError("검증된 생성 영상이 없습니다.", 404)
            name = scene.clip_name
        try:
            path = self.clips.path(name)
        except (VideoProviderError, ValueError, OSError):
            raise AIVideoError("생성 영상 파일이 없습니다.", 404) from None
        if not path.is_file():
            raise AIVideoError("생성 영상 파일이 없습니다.", 404)
        return path

    def models(self) -> list[ModelEntry]:
        return list_models(self.sessions)
