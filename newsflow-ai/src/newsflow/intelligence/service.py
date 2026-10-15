"""Evidence snapshots, conservative grouping, persisted runs and editable drafts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from difflib import SequenceMatcher

from sqlalchemy import select, update

from newsflow.db.models import (
    ArticleMention,
    ArticleScore,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    utcnow,
)

from .credentials import CredentialError
from .estimate import estimate_call
from .korean import assess_script
from .provider import (
    ANALYSIS_INSTRUCTION,
    SCRIPT_INSTRUCTION,
    OfflineProvider,
    OpenAIProvider,
    Options,
    Provider,
    ProviderError,
    ProviderTimeoutError,
)
from .schema import CAUTION, Analysis, Script

MODES = ("offline", "openai")
_PROVIDER_MESSAGES = {
    "ai_auth_failed": "AI 인증에 실패했습니다. API 키와 권한을 확인하세요.",
    "ai_rate_limited": "AI 요청 한도(Rate Limit)를 초과했습니다. 잠시 후 다시 시도하세요.",
    "ai_timeout": "AI 요청 시간이 초과되었습니다.",
    "ai_unavailable": "AI 서비스에 연결하지 못했습니다. 네트워크를 확인하고 다시 시도하세요.",
    "ai_bad_response": "AI 응답 형식이 올바르지 않습니다. 모델 설정을 확인하세요.",
    "ai_key_missing": "AI API 키가 설정되지 않았습니다.",
}


class IntelligenceError(Exception):
    """User-safe message plus a stable code for callers that map failures to guidance."""

    def __init__(self, message: str, code: str = "ai_failed", retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class IntelligenceService:
    def __init__(self, sessions, provider: Provider | None = None, key_store=None, speech: dict | None = None):
        self.sessions, self.provider, self.key_store = sessions, provider, key_store
        # Speech settings only affect review estimates; they never alter the saved script.
        self.speech = {"rate": 0, "pause_ms": 250, **(speech or {})}

    def _key(self) -> str:
        if self.key_store is not None:
            return self.key_store.key()
        return os.environ.get("NEWSFLOW_AI_API_KEY", "")

    def _provider(self, mode: str) -> Provider:
        if self.provider is not None:
            return self.provider
        return OfflineProvider() if mode == "offline" else OpenAIProvider(self._key)

    def _usage(self, provider: Provider, run_id: int, mode: str, options: Options, kind: str, status: str) -> None:
        usage = getattr(provider, "last_usage", None)
        if mode == "offline" or (usage is None and status == "success"):
            return
        from .settings import record_usage

        record_usage(
            self.sessions, run_id=run_id, provider=mode, model=options.model, kind=kind, status=status,
            usage=usage, elapsed_ms=int(getattr(provider, "last_elapsed_ms", 0) or 0),
        )

    @staticmethod
    def _failure(exc: Exception, fallback: str) -> tuple[str, str, bool]:
        """Fixed messages per failure class; provider exception text is never persisted."""
        if isinstance(exc, (TimeoutError, ProviderTimeoutError)):
            return "AI 요청 시간이 초과되었습니다.", "ai_timeout", True
        if isinstance(exc, ProviderError):
            return _PROVIDER_MESSAGES.get(exc.code, fallback), exc.code, exc.retryable
        if isinstance(exc, CredentialError):
            # The key store's messages are fixed Korean strings without key material.
            return str(exc), "ai_key_missing", False
        if isinstance(exc, IntelligenceError):
            return str(exc), exc.code, exc.retryable
        return fallback, "ai_failed", True

    def evidence_for(self, ids: list[int]) -> dict:
        """Read-only evidence payload for `ids`, identical to what analyze() stores and sends."""
        with self.sessions() as session:
            articles = [session.get(NewsArticle, i) for i in ids]
            if any(a is None for a in articles):
                raise IntelligenceError("선택한 기사가 없습니다.", "invalid_selection", False)
            evidence, groups = [], []
            for a in articles:
                mentions = list(
                    session.scalars(select(ArticleMention).where(ArticleMention.article_id == a.id))
                )
                sources = [{"publisher": m.publisher, "url": m.url} for m in mentions]
                if not any(s["url"] == a.url for s in sources):
                    sources.insert(0, {"publisher": a.publisher, "url": a.url})
                score = session.get(ArticleScore, a.id)
                evidence.append(
                    {
                        "id": a.id,
                        "title": a.title,
                        "summary": a.summary[:800],
                        "category": a.category,
                        "published_at": a.published_at.isoformat() if a.published_at else None,
                        "sources": sources,
                        "verification": "unverified",
                        "confidence": "미평가",
                        "score": {
                            "total": score.total,
                            "assessed_max": score.assessed_max,
                            "reasons": score.components,
                        }
                        if score
                        else None,
                        "popularity": "RSS 내부 휴리스틱 · 실제 조회수/검색량 미측정",
                    }
                )
                for group in groups:
                    first = next(x for x in evidence if x["id"] == group[0])
                    if SequenceMatcher(None, a.title, first["title"]).ratio() >= 0.65:
                        group.append(a.id)
                        break
                else:
                    groups.append([a.id])
        return {
            "articles": evidence,
            "groups": groups,
            "comparison": "제목 유사도 0.65 기준 후보 그룹입니다. 서로 다른 보도 내용과 독립 출처 여부는 사람이 확인해야 합니다.",
            "caution": CAUTION,
        }

    def analyze(
        self,
        ids: list[int],
        mode: str = "offline",
        consent: bool = False,
        options: Options | None = None,
        on_run: Callable[[int], None] | None = None,
    ) -> int:
        if mode not in MODES or (mode != "offline" and not consent):
            raise IntelligenceError("외부 AI 분석에는 전송과 비용 발생에 대한 명시적 동의가 필요합니다.", "ai_consent", False)
        options = options or Options()
        if not ids or len(ids) > 10 or len(set(ids)) != len(ids):
            raise IntelligenceError("기사 1~10개를 선택하세요.", "invalid_selection", False)
        payload = self.evidence_for(ids)
        with self.sessions.begin() as session:
            run = IntelligenceRun(
                kind="analysis",
                status="running",
                provider=mode,
                options=vars(options),
                evidence=payload,
                result={},
                message="RSS 근거 분석 완료; 사실 확인 미완료",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        provider = self._provider(mode)
        try:
            if on_run:
                on_run(run_id)
            self._budget(mode, options, ANALYSIS_INSTRUCTION, {"evidence": payload})
            try:
                result = Analysis.model_validate(provider.analyze(payload, options)).model_dump()
            except IntelligenceError:
                raise
            except ProviderError:
                raise
            except Exception as exc:
                if isinstance(exc, TimeoutError):
                    raise
                raise IntelligenceError("AI 분석 응답 형식이 올바르지 않습니다.", "ai_bad_response", True) from None
            referenced = {i for comparison in result["comparisons"] for i in comparison["article_ids"]}
            if referenced != set(ids):
                raise IntelligenceError("분석 출처가 선택 기사와 일치하지 않습니다.", "ai_bad_response", True)
            self.check_secret(result)
            self.check_copy(result, payload)
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.result, run.finished_at = "success", result, utcnow()
            self._usage(provider, run_id, mode, options, "analysis", "success")
            return run_id
        except Exception as exc:  # noqa: BLE001 - sanitize provider failure
            message, code, retryable = self._failure(exc, "AI 분석에 실패했습니다. API 설정 또는 응답 형식을 확인하세요.")
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
            self._usage(provider, run_id, mode, options, "analysis", "failed")
            raise IntelligenceError(message, code, retryable) from None

    def _budget(self, mode: str, options: Options, instruction: str = "", payload: dict | None = None) -> None:
        """Every external call needs the openai provider, the stored dated approval and budget headroom.

        The reservation includes the estimated prompt tokens of this exact call when the
        instruction and payload are known, so the check is conservative.
        """
        if mode == "offline":
            return
        from .settings import SettingsError, check_budget, read_settings

        settings = read_settings(self.sessions)
        if settings.provider != "openai":
            raise IntelligenceError(
                "AI 제공자가 기본 대본(외부 호출 없음)으로 저장되어 있어 외부 AI를 호출하지 않습니다. AI 연결 설정에서 제공자를 바꾸세요.",
                "ai_consent", False,
            )
        if not settings.approved:
            raise IntelligenceError("외부 AI 사용 승인이 AI 연결 설정에 저장되지 않았습니다.", "ai_consent", False)
        prompt_estimate = estimate_call(instruction, payload, options.max_tokens)["prompt_tokens"] if payload is not None else 0
        try:
            check_budget(self.sessions, settings, options, prompt_estimate)
        except SettingsError as exc:
            raise IntelligenceError(str(exc), "ai_budget", False) from None

    def generate(
        self,
        analysis_id: int,
        duration: int,
        mode: str = "offline",
        consent: bool = False,
        options: Options | None = None,
        on_run: Callable[[int], None] | None = None,
    ) -> int:
        if duration not in (30, 45, 60) or mode not in MODES:
            raise IntelligenceError("영상 길이 또는 Provider가 잘못되었습니다.", "invalid_selection", False)
        if mode != "offline" and not consent:
            raise IntelligenceError("외부 API 전송과 비용 발생에 대한 명시적 동의가 필요합니다.", "ai_consent", False)
        options = options or Options()
        with self.sessions.begin() as session:
            analysis = session.get(IntelligenceRun, analysis_id)
            if not analysis or analysis.kind != "analysis" or analysis.status != "success":
                raise IntelligenceError("먼저 기사 분석을 실행하세요.", "invalid_selection", False)
            evidence = analysis.evidence
            run = IntelligenceRun(
                kind="script",
                provider=mode,
                status="running",
                evidence=evidence,
                options={**vars(options), "duration": duration},
                result={},
                message="대본 생성 중",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        provider = self._provider(mode)
        try:
            if on_run:
                on_run(run_id)
            self._budget(mode, options, SCRIPT_INSTRUCTION, {"duration": duration, "evidence": evidence})
            output = provider.complete(evidence, duration, options)
            script = self.validate(output, duration)
            self._check_stored_secret(script)
            self.check_copy(script, evidence)
            notes = assess_script(script, evidence, duration, **self.speech)
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.result, run.finished_at, run.message = (
                    "success",
                    script,
                    utcnow(),
                    "검토용 대본 생성 완료" + (f" · 확인 사항 {len(notes)}건" if notes else ""),
                )
                draft = ContentDraft(
                    run_id=run_id,
                    duration=duration,
                    content=script,
                    sources=evidence,
                    revision=1,
                    review_status="review_required",
                    review_notes=notes,
                )
                session.add(draft)
                session.flush()
                draft_id = draft.id
            self._usage(provider, run_id, mode, options, "script", "success")
            return draft_id
        except Exception as exc:  # noqa: BLE001 - persist safe failure at adapter boundary
            # Never store provider exception text, response body or credential-bearing data.
            message, code, retryable = self._failure(exc, "대본 생성에 실패했습니다. API 설정 또는 응답 형식을 확인하세요.")
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
            self._usage(provider, run_id, mode, options, "script", "failed")
            raise IntelligenceError(message, code, retryable) from None

    @staticmethod
    def validate(output: dict, duration: int) -> dict:
        try:
            script = Script.model_validate(output)
        except Exception:  # noqa: BLE001 - pydantic detail may echo provider output
            raise IntelligenceError("대본 형식이 올바르지 않습니다. 필드 길이와 장면 구성을 확인하세요.", "ai_bad_response", True) from None
        if sum(s.seconds for s in script.scenes) != duration:
            raise IntelligenceError("장면 길이 합계가 영상 길이와 다릅니다.", "ai_bad_response", True)
        serialized = script.model_dump_json()
        IntelligenceService.check_secret(script.model_dump())
        if any(word in serialized for word in ("충격!", "100% 확실", "검증 완료", "무조건 사실")):
            raise IntelligenceError("확정적 또는 선정적 표현을 검토하세요.", "ai_bad_response", True)
        if "http://" in serialized or "https://" in serialized:
            raise IntelligenceError("대본 본문에는 URL을 넣을 수 없습니다. 출처는 별도로 표시됩니다.", "ai_bad_response", True)
        return script.model_dump()

    def edit(self, draft_id: int, revision: int, output: dict) -> None:
        with self.sessions.begin() as session:
            draft = session.get(ContentDraft, draft_id)
            if not draft:
                raise IntelligenceError("초안이 없습니다.", "invalid_selection", False)
            content = self.validate(output, draft.duration)
            self._check_stored_secret(content)
            self.check_copy(content, draft.sources)
            notes = assess_script(content, draft.sources, draft.duration, **self.speech)
            result = session.execute(
                update(ContentDraft)
                .where(ContentDraft.id == draft_id, ContentDraft.revision == revision)
                .values(
                    content=content,
                    revision=revision + 1,
                    review_status="review_required",
                    review_notes=notes,
                    updated_at=utcnow(),
                )
            )
            if result.rowcount != 1:
                raise IntelligenceError("다른 편집 내용이 저장되었습니다. 새로고침 후 다시 시도하세요.", "conflict", False)

    @staticmethod
    def check_copy(content: dict, evidence: dict) -> None:
        text = json.dumps(content, ensure_ascii=False)
        for article in evidence["articles"]:
            summary = article["summary"]
            if len(summary) >= 100 and any(summary[i : i + 100] in text for i in range(len(summary) - 99)):
                raise IntelligenceError(
                    "긴 원문/요약의 그대로 복제는 허용하지 않습니다. 요약을 다시 작성하세요.", "ai_bad_response", True
                )

    @staticmethod
    def check_secret(value: dict) -> None:
        key = os.environ.get("NEWSFLOW_AI_API_KEY", "")
        if key and key in json.dumps(value, ensure_ascii=False):
            raise IntelligenceError("보안 정책에 의해 차단되었습니다.", "ai_bad_response", False)

    def _check_stored_secret(self, value: dict) -> None:
        """The GUI-stored key must be as unreachable in drafts as the environment key."""
        if self.key_store is None:
            return
        try:
            key = self.key_store.key()
        except Exception:  # noqa: BLE001 - an unreadable store cannot leak into a draft
            return
        if key and key in json.dumps(value, ensure_ascii=False):
            raise IntelligenceError("보안 정책에 의해 차단되었습니다.", "ai_bad_response", False)
