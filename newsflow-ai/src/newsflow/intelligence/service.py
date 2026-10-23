"""Evidence snapshots, conservative grouping, persisted runs and editable drafts."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from copy import deepcopy
from difflib import SequenceMatcher
from threading import Event, Thread

from sqlalchemy import select, update

from newsflow.db.models import (
    ArticleMention,
    ArticleScore,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    utcnow,
)

from .credentials import CredentialError
from .estimate import estimate_call
from .korean import assess_script, speech_plan
from .news_usage import (
    API_SCRIPT_METHODS,
    api_news_contract,
    assess_news_usage,
    explainer_findings,
    safe_topic_script,
    validate_api_news_script,
    validate_explainer_analysis,
    validate_news_usage,
    validate_news_usage_script,
)
from .presentation import presentation
from .provider import (
    AnalysisResponseError,
    OfflineProvider,
    OpenAIProvider,
    Options,
    Provider,
    ProviderError,
    ProviderOutputLimitError,
    ProviderTimeoutError,
    ScriptResponseError,
    prompt_instruction,
    prompt_options,
    prompt_version,
)
from .schema import CAUTION, Analysis, Script

MODES = ("offline", "openai", "claude_code", "codex", "claude_api")
_PROVIDER_MESSAGES = {
    "codex_auth": "Codex의 공식 ChatGPT 로그인이 필요합니다. 연결 상태를 확인하세요.",
    "codex_billing": "Codex가 ChatGPT 구독 인증이 아닙니다. API 과금으로 전환하지 않습니다.",
    "codex_usage": "Codex 구독 사용 가능 여부가 확인되지 않아 실행을 차단했습니다.",
    "codex_isolation": "Codex 최소 권한 격리를 확인하지 못해 실행을 차단했습니다.",
    "codex_version": "이 Codex 버전의 도구 격리는 미검증입니다. 실행을 차단했습니다.",
    "codex_busy": "Codex 요청이 이미 진행 중입니다. 완료 또는 취소 후 확인하세요.",
    "codex_cancelled": "Codex 요청을 취소했습니다. 이미 발생한 구독 사용량은 되돌아가지 않습니다.",
    "codex_model": "선택 모델을 Codex 목록에서 확인하지 못했습니다. default를 선택하세요.",
    "codex_rpc": "Codex 공식 연결 요청이 실패했습니다. 자동 재시도하지 않습니다.",
    "codex_turn_failed": "Codex가 요청을 완료하지 못했습니다. 사용량·인증·모델을 확인하세요.",
    "ai_billing_approval": "Claude 인증은 확인됐으나 해당 과금 방식은 NewsFlow AI에서 사용 승인되지 않았습니다.",
    "ai_auth_failed": "AI 인증에 실패했습니다. API 키와 권한을 확인하세요.",
    "ai_rate_limited": "AI 요청 한도(Rate Limit)를 초과했습니다. 잠시 후 다시 시도하세요.",
    "ai_timeout": "AI 요청 시간이 초과되었습니다.",
    "ai_unavailable": "AI 서비스에 연결하지 못했습니다. 네트워크를 확인하고 다시 시도하세요.",
    "ai_bad_response": "AI 응답 형식이 올바르지 않습니다. 모델 설정을 확인하세요.",
    "ai_key_missing": "AI API 키가 설정되지 않았습니다.",
    "ai_cancelled": "AI 요청을 취소했습니다. 요청이 전송되었다면 계정 사용량이 발생했을 수 있습니다.",
}


class IntelligenceError(Exception):
    """User-safe message plus a stable code for callers that map failures to guidance."""

    def __init__(self, message: str, code: str = "ai_failed", retryable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class IntelligenceService:
    def __init__(self, sessions, provider: Provider | None = None, key_store=None, speech: dict | None = None,
                 *, api_key_stores: dict | None = None, api_providers: dict | None = None, api_budget=None):
        self.sessions, self.provider, self.key_store = sessions, provider, key_store
        self.api_key_stores = dict(api_key_stores or {})
        if key_store is not None:
            self.api_key_stores.setdefault("openai", key_store)
        self.api_providers = dict(api_providers or {})
        self.api_budget = api_budget
        self.api_managed = api_key_stores is not None or api_budget is not None
        # Speech settings only affect review estimates; they never alter the saved script.
        self.speech = {"rate": 0, "pause_ms": 250, **(speech or {})}

    def _key(self) -> str:
        if self.key_store is not None:
            return self.key_store.key()
        return os.environ.get("NEWSFLOW_AI_API_KEY", "")

    def _provider(self, mode: str) -> Provider:
        if mode in self.api_providers:
            return self.api_providers[mode]
        if self.provider is not None:
            return self.provider
        if mode == "claude_api":
            from .api_providers import AnthropicProvider
            from .credentials import AnthropicKeyStore
            from .error_diagnostics import ErrorDiagnosticStore

            store = self.api_key_stores.get(mode)
            recorder = ErrorDiagnosticStore(store.path.parent) if isinstance(store, AnthropicKeyStore) else None
            return AnthropicProvider(lambda: self._api_key(mode), error_recorder=recorder)
        if mode == "codex":
            from .codex import CODEX_PROVIDER

            return CODEX_PROVIDER
        if mode == "claude_code":
            from .claude_code import CLAUDE_PROVIDER

            return CLAUDE_PROVIDER
        return OfflineProvider() if mode == "offline" else OpenAIProvider(self._key, allow_retry=not self.api_managed)

    def _api_key(self, mode: str) -> str:
        store = self.api_key_stores.get(mode)
        return store.key() if store is not None else ""

    def api_readiness(self, mode: str, capability: str = "search") -> dict:
        """Read-only gates; setting a key never establishes real authentication."""
        from .api_settings import APIBudgetService

        budget = self.api_budget or APIBudgetService(self.sessions)
        return budget.readiness(mode, self.api_key_stores.get(mode), capability=capability)

    def _reserve_api(self, mode: str, run_id: int, kind: str, options: Options, payload: dict):
        if mode not in {"openai", "claude_api"} or (mode == "openai" and not self.api_managed and kind != "search"):
            return None
        from .api_settings import APIBudgetService, APISettingsError

        budget = self.api_budget or APIBudgetService(self.sessions)
        try:
            reservation = budget.reserve(
                provider=mode, request_id=f"intelligence:{run_id}", kind=kind, model=options.model,
                max_output_tokens=options.max_tokens,
                max_search_calls=1 if kind == "search" else 0, key_store=self.api_key_stores.get(mode),
            )
        except APISettingsError as exc:
            raise IntelligenceError(str(exc), "ai_budget", False) from None
        return budget, reservation

    @staticmethod
    def _finish_api(reservation, provider, status: str) -> None:
        if reservation:
            budget, record = reservation
            budget.finish(record.id, status=status, usage=getattr(provider, "last_usage", None))

    def _usage(self, provider: Provider, run_id: int, mode: str, options: Options, kind: str, status: str) -> None:
        usage = getattr(provider, "last_usage", None)
        if mode == "offline" or (usage is None and status == "success"):
            return
        from .settings import record_usage

        record_usage(
            self.sessions, run_id=run_id, provider=mode,
            model=getattr(provider, "last_model", options.model), kind=kind, status=status,
            usage=usage, elapsed_ms=int(getattr(provider, "last_elapsed_ms", 0) or 0),
        )

    @staticmethod
    def _failure(exc: Exception, fallback: str) -> tuple[str, str, bool]:
        """Fixed messages per failure class; provider exception text is never persisted."""
        if isinstance(exc, AnalysisResponseError):
            return str(exc.safe_copy()), "ai_bad_response", False
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

    def search_news(self, mode: str, request, *, consent: bool = False, options: Options | None = None,
                    on_run: Callable[[int], None] | None = None, cancel: Event | None = None) -> int:
        """One approved search, with request ID journaled before dispatch and no replay.

        Search sources are imported only after an actual tool-result match. Generated
        dates stay claims; unverified dates cannot enter the current-news selection.
        """
        from newsflow.news.collector import CollectedArticle
        from newsflow.news.service import NewsService

        from .api_providers import AnthropicProvider, OpenAISearchProvider
        from .api_search import SEARCH_INSTRUCTION, SearchRequest, SearchResponseError, validate_search_result

        if mode not in {"openai", "claude_api"} or consent is not True:
            raise IntelligenceError("API 웹 검색에는 별도 사용·비용 승인이 필요합니다.", "ai_consent", False)
        if not isinstance(request, SearchRequest):
            raise IntelligenceError("뉴스 검색 요청 형식을 확인하세요.", "invalid_selection", False)
        options = options or Options(max_tokens=3000)
        payload = request.model_dump(mode="json")
        with self.sessions.begin() as session:
            run = IntelligenceRun(kind="search", provider=mode, status="running", options=vars(options),
                                  evidence=payload, result={}, message="API 검색 요청 준비 · 원문 사실 확인 미완료")
            session.add(run)
            session.flush()
            run_id = run.id
        provider = self.api_providers.get(mode)
        if provider is None:
            factory = OpenAISearchProvider if mode == "openai" else AnthropicProvider
            provider = factory(lambda: self._api_key(mode))
        reservation = None
        done = Event()

        def monitor():
            while not done.wait(.05):
                if cancel.is_set():
                    provider.cancel()
                    return

        worker = Thread(target=monitor, daemon=True) if cancel is not None and callable(getattr(provider, "cancel", None)) else None
        try:
            if on_run:
                on_run(run_id)
            reservation = self._reserve_api(mode, run_id, "search", options,
                                            {"instruction": SEARCH_INSTRUCTION, "request": payload})
            if cancel is not None and cancel.is_set():
                raise IntelligenceError("API 뉴스 검색을 취소했습니다.", "ai_cancelled", False)
            if worker:
                worker.start()
            result = validate_search_result(provider.search(request, options))
            if result.provider != mode or result.model != options.model or len(result.articles) > request.count:
                raise IntelligenceError("검색 제공자·모델·결과 건수가 요청과 다릅니다.", "ai_bad_response", False)
            if result.tool_evidence.provenance == "test_fixture" and mode not in self.api_providers:
                raise IntelligenceError("테스트 검색 근거를 실제 검색으로 저장할 수 없습니다.", "ai_bad_response", False)
            data = result.model_dump(mode="json")
            self._check_stored_secret(data)
            source_url = "https://api.openai.com/v1/responses" if mode == "openai" else "https://api.anthropic.com/v1/messages"
            with self.sessions.begin() as session:
                source = session.scalar(select(NewsSource).where(NewsSource.url == source_url))
                if source is None:
                    source = NewsSource(name=f"{mode} 웹 검색 · 원문 검토 필요", url=source_url, enabled=False)
                    session.add(source)
                    session.flush()
                stored = NewsService.store_articles(session, source.id, [CollectedArticle(
                    article.title, article.url, article.publisher[:200], article.summary, article.published_at,
                ) for article in result.articles])
                from newsflow.news.lifecycle import replace_collection

                replace_collection(session, stored["article_ids"])
                run = session.get(IntelligenceRun, run_id)
                run.status, run.finished_at = "success", utcnow()
                run.message = "검색 도구 출처 확인 · 발행일·언론사·원문 사실은 별도 검토 필요"
                run.result = {**data, **stored, "source_ids": [source.id],
                              "web_search_performed": result.tool_evidence.provenance == "provider_response",
                              "simulated": result.tool_evidence.provenance == "test_fixture",
                              "full_body_verified": False, "facts_verified": False}
            self._usage(provider, run_id, mode, options, "search", "success")
            self._finish_api(reservation, provider, "success")
            return run_id
        except Exception as exc:  # noqa: BLE001 - fixed messages only, never persist vendor text
            message, code, _ = self._failure(exc, "API 뉴스 검색에 실패했습니다. 자동 재요청하지 않습니다.")
            failure = exc.safe_copy() if isinstance(exc, SearchResponseError) else None
            if failure is not None:
                message = str(failure) + " 자동 재요청하지 않습니다."
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
                if failure is not None:
                    run.result = {"search_failure": failure.diagnostics()}
            self._usage(provider, run_id, mode, options, "search", "failed")
            self._finish_api(reservation, provider, "unknown" if code in {"ai_timeout", "ai_unavailable", "ai_cancelled"} else "failed")
            raise IntelligenceError(message, code, False) from None
        finally:
            done.set()
            if worker and worker.ident is not None:
                worker.join(timeout=1)

    def evidence_for(self, ids: list[int]) -> dict:
        """Read-only evidence payload for `ids`, identical to what analyze() stores and sends."""
        with self.sessions() as session:
            articles = [session.get(NewsArticle, i) for i in ids]
            if any(a is None for a in articles):
                raise IntelligenceError("선택한 기사가 없습니다.", "invalid_selection", False)
            search_by_article = {}
            for search in session.scalars(select(IntelligenceRun).where(
                IntelligenceRun.kind.in_(["search", "news_search"]),
                IntelligenceRun.status.in_(["success", "failed", "unknown"]),
            ).order_by(IntelligenceRun.id)):
                for identifier in search.result.get("article_ids", []):
                    if identifier in ids:
                        search_by_article[identifier] = {
                            "search_run_id": search.id, "provider": search.provider,
                            "search_status": search.status,
                            "model": search.options.get("model"), "searched_at": search.result.get("searched_at"),
                            "collection_policy": search.result.get("collection_policy"),
                            "edition_appearances": search.result.get("article_origins", {}).get(str(identifier), []),
                            "frequency_meaning": "이번 수집에서 등장한 조회 판 수 · 실제 기사 노출수/조회수/SNS 통계 아님",
                            "tool_evidence": search.result.get("tool_evidence"),
                            "full_body_verified": False, "facts_verified": False,
                            "summary_kind": ("SerpApi Google News 자료 · 원문 본문 미확인" if search.provider == "serpapi"
                                             else "AI 검색 요약 · 원문 본문 미확인"),
                            "topic_candidates": [
                                {"url": candidate.get("url"), "title": candidate.get("claimed_title")}
                                for candidate in search.result.get("articles", []) if isinstance(candidate, dict)
                            ],
                        }
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
                        "popularity": ("SerpApi Google News 후보 · 실제 조회수 미측정"
                                       if search_by_article.get(a.id, {}).get("provider") == "serpapi" else
                                       "AI 검색 후보 · 실제 조회수/검색량 미측정" if a.id in search_by_article
                                       else "RSS 내부 휴리스틱 · 실제 조회수/검색량 미측정"),
                        **({"search_provenance": search_by_article[a.id]} if a.id in search_by_article else {}),
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
            "caution": (CAUTION.replace("RSS 제목/요약", "SerpApi 제목/제공 요약")
                        if any(v.get("provider") == "serpapi" for v in search_by_article.values()) else CAUTION),
        }

    def create_topic_analysis(
        self, article_ids: list[int], news_usage: str, *,
        on_run: Callable[[int], None] | None = None,
        category: str | None = None, selected_provider: str | None = None,
    ) -> int:
        """Record the explicit local topic path; no AI call or usage reservation."""
        if (not isinstance(article_ids, list) or not article_ids or len(article_ids) > 10
                or any(type(identifier) is not int or identifier < 1 for identifier in article_ids)
                or len(article_ids) != len(set(article_ids))):
            raise IntelligenceError("기사 1~10개를 선택하세요.", "invalid_selection", False)
        if selected_provider is not None and selected_provider not in MODES:
            raise IntelligenceError("선택한 AI를 확인하세요.", "invalid_selection", False)
        if category is not None and (
            not isinstance(category, str) or category not in {"all", "politics", "economy", "society", "it", "world"}
        ):
            raise IntelligenceError("뉴스 분야를 확인하세요.", "invalid_selection", False)
        try:
            mode = validate_news_usage(news_usage)
        except ValueError:
            raise IntelligenceError("뉴스 활용 수준을 확인하세요.", "invalid_selection", False) from None
        evidence = self.evidence_for(article_ids)
        if category is not None and category != "all":
            evidence = {**evidence, "articles": [
                {**article, "source_category": article.get("category"), "category": category}
                for article in evidence["articles"]
            ]}
        assessment = assess_news_usage(evidence, mode)
        if assessment["approach"] == "blocked":
            raise IntelligenceError(assessment["message"], "news_usage_blocked", False)
        evidence = {**evidence, "news_usage": mode, "news_usage_result": assessment}
        result = Analysis.model_validate({
            "overview": "주제 설명형 로컬 구성입니다. 선택 AI의 추가 분석이나 독립 사실 검증은 수행하지 않았습니다.",
            "comparisons": [{
                "article_ids": group,
                "reason": "출처는 주제 참고 자료로 보존합니다. 기사 후보 여부는 URL 형태에 따른 분류입니다.",
                "uncertainties": "원문 본문·개별 사건·발행일 미검증",
            } for group in evidence["groups"]],
            "recommended_article_id": assessment["preferred_article_ids"][0],
            "selection_reason": "제목과 검색 요약의 주제어로 배경·쟁점·판단 기준을 구성합니다. 개별 사실은 미검증입니다."
            if mode == "STANDARD" else "제목과 검색 요약의 주제어로 짧은 소개와 확인할 점을 구성합니다.",
        }).model_dump()
        with self.sessions.begin() as session:
            run = IntelligenceRun(
                kind="analysis", provider="local_topic_template", status="running",
                options={"model": "local-topic-v1", "news_usage": mode, "selected_provider": selected_provider},
                evidence=evidence, result={}, message="로컬 주제 구성 중 · 외부 AI 호출 없음",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        try:
            if on_run:
                on_run(run_id)
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.result, run.finished_at = "success", result, utcnow()
                run.message = "로컬 주제 구성 완료 · 개별 기사 사실 미검증"
            return run_id
        except Exception as exc:  # noqa: BLE001 - no external error text in persisted runs
            message, code, _ = self._failure(exc, "로컬 주제 구성을 완료하지 못했습니다.")
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
            raise IntelligenceError(message, code, False) from None

    def generate_topic(
        self, analysis_id: int, duration: int, news_usage: str, *,
        on_run: Callable[[int], None] | None = None, article_ids: list[int] | None = None,
    ) -> int:
        """Create a review-required local template draft without switching API providers."""
        try:
            mode = validate_news_usage(news_usage)
        except ValueError:
            raise IntelligenceError("뉴스 활용 수준을 확인하세요.", "invalid_selection", False) from None
        if type(duration) is not int or duration not in (30, 45, 60):
            raise IntelligenceError("영상 길이를 확인하세요.", "invalid_selection", False)
        with self.sessions() as session:
            analysis = session.get(IntelligenceRun, analysis_id)
            if (not analysis or analysis.kind != "analysis" or analysis.status != "success"
                    or analysis.provider != "local_topic_template"
                    or analysis.evidence.get("news_usage") != mode):
                raise IntelligenceError("저장된 뉴스 활용 수준과 주제 구성을 확인하세요.", "invalid_selection", False)
            evidence = analysis.evidence
            selected_provider = analysis.options.get("selected_provider")
        if article_ids is not None:
            known = {article["id"] for article in evidence["articles"]}
            if (not isinstance(article_ids, list) or not article_ids or len(article_ids) > 10
                    or any(type(identifier) is not int for identifier in article_ids)
                    or len(article_ids) != len(set(article_ids)) or not set(article_ids) <= known):
                raise IntelligenceError("대본 뉴스가 저장된 분석 자료와 다릅니다.", "invalid_selection", False)
            selected = set(article_ids)
            evidence = {**evidence, "articles": [article for article in evidence["articles"] if article["id"] in selected],
                        "groups": [[identifier for identifier in group if identifier in selected]
                                   for group in evidence["groups"] if any(identifier in selected for identifier in group)]}
        assessment = assess_news_usage(evidence, mode)
        evidence = {**evidence, "news_usage_result": assessment}
        if assessment["approach"] == "blocked":
            raise IntelligenceError(assessment["message"], "news_usage_blocked", False)
        script = self.validate(safe_topic_script(evidence, duration), duration)
        self.check_news_usage(script, evidence)
        self._check_stored_secret(script)
        self.check_copy(script, evidence)
        notes = assess_script(script, evidence, duration, **self.speech)
        with self.sessions.begin() as session:
            run = IntelligenceRun(
                kind="script", provider="local_topic_template", status="running", evidence=evidence,
                options={"model": "local-topic-v1", "duration": duration, "analysis_run_id": analysis_id,
                         "news_usage": mode, "selected_provider": selected_provider,
                         "selected_article_ids": [article["id"] for article in evidence["articles"]]},
                result={}, message="로컬 주제 설명 대본 구성 중 · 외부 AI 호출 없음",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        try:
            if on_run:
                on_run(run_id)
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.result, run.finished_at = "success", script, utcnow()
                run.message = "주제 설명형 대본 완료 · 개별 사건 미검증 · 사용자 검토 필요"
                draft = ContentDraft(
                    run_id=run_id, duration=duration, content=script, sources=evidence,
                    revision=1, review_status="review_required", review_notes=notes,
                )
                session.add(draft)
                session.flush()
                draft_id = draft.id
            return draft_id
        except Exception as exc:  # noqa: BLE001 - local callback/DB errors stay sanitized
            message, code, _ = self._failure(exc, "로컬 주제 설명 대본을 완료하지 못했습니다.")
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
            raise IntelligenceError(message, code, False) from None

    @staticmethod
    def check_news_usage(content: dict, evidence: dict) -> None:
        """Reusable review/render gate; legacy drafts without this policy are unchanged."""
        from newsflow.shortform import validate_script as validate_shortform

        try:
            validate_shortform(content, evidence)
        except ValueError:
            raise IntelligenceError("숏폼 훅·장면·분량을 검토하세요.", "shortform_review", False) from None
        if ("news_usage" not in evidence and "news_usage_result" not in evidence
                and evidence.get('script_method') != 'api_grounded_v2'):
            return
        try:
            if "news_usage" not in evidence and evidence.get('script_method') != 'api_grounded_v2':
                raise ValueError
            assessment = assess_news_usage(evidence, evidence.get("news_usage"))
            if evidence.get("script_method") in API_SCRIPT_METHODS:
                validate_api_news_script(content, evidence)
            else:
                validate_news_usage_script(content, evidence, assessment)
        except ValueError:
            raise IntelligenceError(
                "뉴스 활용 수준의 근거 요건을 충족하지 않는 대본입니다. 미확인 사실을 추가할 수 없습니다.",
                "news_usage_blocked", False,
            ) from None

    def analyze(
        self,
        ids: list[int],
        mode: str = "offline",
        consent: bool = False,
        options: Options | None = None,
        on_run: Callable[[int], None] | None = None,
        news_usage: str | None = None,
        curate: bool = False,
        trend_snapshot: dict | None = None,
        curation_top_k: int = 10,
        script_prompt_version: str | None = None,
        comparison_approval_id: int | None = None,
        comparison_step: str | None = None,
    ) -> int:
        if mode not in MODES or (mode != "offline" and not consent):
            raise IntelligenceError("외부 AI 분석에는 전송과 비용 발생에 대한 명시적 동의가 필요합니다.", "ai_consent", False)
        if news_usage is not None and mode in {"openai", "claude_api"} and not self.api_managed:
            raise IntelligenceError("API 단계별 비용 보호가 연결되지 않아 실행을 차단했습니다.", "ai_budget", False)
        options = options or Options()
        base_options = options
        comparison_options = {}
        if comparison_approval_id is not None or comparison_step is not None:
            if (mode != 'claude_api' or type(comparison_approval_id) is not int or comparison_approval_id < 1
                    or not isinstance(comparison_step, str)):
                raise IntelligenceError('비교 승인 식별자·Provider를 확인하세요.', 'ai_consent', False)
            comparison_options = {'comparison_approval_id': comparison_approval_id, 'comparison_step': comparison_step}
        selected_version = prompt_version(selected=script_prompt_version) if mode in {'openai', 'claude_api'} else 'v1'
        options = prompt_options(options, 'analysis', selected_version)
        instruction_text = prompt_instruction('analysis', version=selected_version)
        from .curation import MAX_CURATION_ARTICLES

        limit = MAX_CURATION_ARTICLES if curate else 10
        if not ids or len(ids) > limit or len(set(ids)) != len(ids):
            message = ("전체 뉴스가 한 번의 평가 범위를 초과했습니다. 일부 제외·자동 추가 호출 없이 중단합니다."
                       if curate else "기사 1~10개를 선택하세요.")
            raise IntelligenceError(message, "invalid_selection", False)
        payload = self.evidence_for(ids)
        if mode in {'openai', 'claude_api'}:
            payload = {**payload, 'script_prompt_version': selected_version}
        if curate:
            if mode not in {"openai", "claude_api"} or not self.api_managed:
                raise IntelligenceError("화제성 평가는 선택한 API의 승인 경로로 실행하세요.", "ai_budget", False)
            from .curation import enrich

            payload = enrich(payload, trend_snapshot, utcnow(), top_k=curation_top_k)
            if mode == "claude_api":
                from .curation_wire import SCORE_DERIVATION

                payload["curation_contract"]["score_derivation"] = dict(SCORE_DERIVATION)
        if news_usage is not None:
            if mode not in {"openai", "claude_api"}:
                raise IntelligenceError("선택한 API 분석 경로를 확인하세요.", "invalid_selection", False)
            try:
                level = validate_news_usage(news_usage)
                contract = api_news_contract(payload, level, version=selected_version)
            except ValueError:
                raise IntelligenceError("뉴스 활용 수준의 근거 요건을 확인하세요.", "news_usage_blocked", False) from None
            payload = {**payload, "news_usage": level, "news_usage_result": assess_news_usage(payload, level),
                       "script_method": 'api_grounded_' + selected_version, "news_usage_contract": contract}
        with self.sessions.begin() as session:
            run = IntelligenceRun(
                kind="analysis",
                status="running",
                provider=mode,
                options={**vars(options), **comparison_options, 'script_prompt_version': selected_version,
                         'base_max_tokens': base_options.max_tokens,
                         'output_token_allowance': options.max_tokens-base_options.max_tokens},
                evidence=payload,
                result={},
                message="제공된 출처 근거 분석; 사실 확인 미완료",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        provider = self._provider(mode)
        reservation = None
        try:
            if on_run:
                on_run(run_id)
            self._budget(mode, options, instruction_text, {"evidence": payload})
            reservation = self._reserve_api(mode, run_id, "analysis", options,
                                            {"instruction": instruction_text, "evidence": payload})
            try:
                output = provider.analyze(payload, base_options)
                self._check_stored_secret(output)
                if mode in {'openai', 'claude_api'}:
                    validate_explainer_analysis(output, payload)
                if curate:
                    from .curation import validate_ranking

                    result = validate_ranking(output, payload)
                else:
                    result = Analysis.model_validate(output).model_dump()
            except IntelligenceError:
                raise
            except ProviderError:
                raise
            except Exception as exc:
                if isinstance(exc, TimeoutError):
                    raise
                if mode == "claude_api":
                    raise AnalysisResponseError("analysis_schema") from None
                raise IntelligenceError("AI 분석 응답 형식이 올바르지 않습니다.", "ai_bad_response", True) from None
            referenced = {i for comparison in result["comparisons"] for i in comparison["article_ids"]}
            if referenced != set(ids):
                if mode == "claude_api":
                    raise AnalysisResponseError("source_binding")
                raise IntelligenceError("분석 출처가 선택 기사와 일치하지 않습니다.", "ai_bad_response", True)
            recommended = result.get("recommended_article_id")
            if recommended is not None and (recommended not in ids or not result["selection_reason"].strip()):
                if mode == "claude_api":
                    raise AnalysisResponseError("source_binding")
                raise IntelligenceError("추천 기사와 근거가 선택 자료와 일치하지 않습니다.", "ai_bad_response", False)
            self._check_stored_secret(result)
            self.check_copy(result, payload)
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.result, run.finished_at = "success", result, utcnow()
            self._usage(provider, run_id, mode, options, "analysis", "success")
            self._finish_api(reservation, provider, "success")
            return run_id
        except Exception as exc:  # noqa: BLE001 - sanitize provider failure
            message, code, retryable = self._failure(exc, "AI 분석에 실패했습니다. API 설정 또는 응답 형식을 확인하세요.")
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
                if isinstance(exc, AnalysisResponseError):
                    run.result = {"analysis_failure": exc.diagnostics()}
                    if exc.stop_reason == 'max_tokens':
                        run.result = {**run.result, 'output_limit': {'stop_reason': 'max_tokens'}}
                elif isinstance(exc, ProviderOutputLimitError):
                    run.result = {'output_limit': {'finish_reason': 'length'}}
            self._usage(provider, run_id, mode, options, "analysis", "failed")
            self._finish_api(reservation, provider, "unknown" if code in {"ai_timeout", "ai_unavailable", "ai_cancelled"} else "failed")
            raise IntelligenceError(message, code, retryable) from None

    def _budget(self, mode: str, options: Options, instruction: str = "", payload: dict | None = None) -> None:
        """Every external call needs the openai provider, the stored dated approval and budget headroom.

        The reservation includes the estimated prompt tokens of this exact call when the
        instruction and payload are known, so the check is conservative.
        """
        if mode in ("offline", "claude_code", "codex", "claude_api"):
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
        article_ids: list[int] | None = None,
        news_usage: str | None = None,
        script_style: str = "news",
        script_tone: str = "neutral",
        script_audience: str = "general",
        shortform_profile: dict | None = None,
        script_prompt_version: str | None = None,
        comparison_approval_id: int | None = None,
        comparison_step: str | None = None,
    ) -> int:
        from dataclasses import asdict

        from newsflow.shortform import Shortform, allowed_duration, instruction
        from newsflow.shortform import read as read_shortform

        profile = read_shortform(self.sessions) if shortform_profile is None else Shortform(**shortform_profile)
        profile_on = profile.enabled and 15 <= duration <= 35 and mode in {"openai", "claude_api"}
        chosen_presentation = presentation(script_style, script_tone, script_audience)
        if mode == "offline" and (script_style, script_tone, script_audience) != ("news", "neutral", "general"):
            raise IntelligenceError("스타일 적용은 연결된 AI로 대본을 생성할 때 사용할 수 있습니다.", "invalid_selection", False)
        if not allowed_duration(duration, profile_on) or mode not in MODES:
            raise IntelligenceError("영상 길이 또는 Provider가 잘못되었습니다.", "invalid_selection", False)
        if mode != "offline" and not consent:
            raise IntelligenceError("외부 API 전송과 비용 발생에 대한 명시적 동의가 필요합니다.", "ai_consent", False)
        options = options or Options()
        base_options = options
        comparison_options = {}
        if comparison_approval_id is not None or comparison_step is not None:
            if (mode != 'claude_api' or type(comparison_approval_id) is not int or comparison_approval_id < 1
                    or not isinstance(comparison_step, str)):
                raise IntelligenceError('비교 승인 식별자·Provider를 확인하세요.', 'ai_consent', False)
            comparison_options = {'comparison_approval_id': comparison_approval_id, 'comparison_step': comparison_step}
        selected_version = prompt_version(selected=script_prompt_version) if mode in {'openai', 'claude_api'} else 'v1'
        options = prompt_options(options, 'script', selected_version)
        instruction_text = prompt_instruction('script', version=selected_version)
        with self.sessions.begin() as session:
            analysis = session.get(IntelligenceRun, analysis_id)
            if not analysis or analysis.kind != "analysis" or analysis.status != "success":
                raise IntelligenceError("먼저 기사 분석을 실행하세요.", "invalid_selection", False)
            evidence = analysis.evidence
            if profile_on:
                evidence = {**evidence, "shortform": asdict(profile)}
            if evidence.get("curation_contract"):
                if (mode not in {"openai", "claude_api"} or mode != analysis.provider
                        or options.model != analysis.options.get("model") or not self.api_managed):
                    raise IntelligenceError("화제성 평가와 같은 승인된 API·모델을 사용하세요.", "invalid_selection", False)
                groups = [item["article_ids"] for item in analysis.result["ranking"]]
                article_ids = article_ids or groups[0]
                if not any(set(article_ids) == set(group) for group in groups):
                    raise IntelligenceError("선정된 한 뉴스 그룹을 선택하세요.", "invalid_selection", False)
                evidence = {**evidence, "analysis_result": analysis.result}
            api_news = evidence.get("script_method") in API_SCRIPT_METHODS
            if mode in {'openai', 'claude_api'}:
                evidence = {**evidence, 'script_prompt_version': selected_version,
                            'script_method': 'api_grounded_' + selected_version,
                            **({'analysis_result': analysis.result} if selected_version == 'v2' else {})}
            if api_news:
                if not self.api_managed:
                    raise IntelligenceError("API 단계별 비용 보호가 연결되지 않아 실행을 차단했습니다.", "ai_budget", False)
                if (mode not in {"openai", "claude_api"} or mode != analysis.provider
                        or options.model != analysis.options.get("model")):
                    raise IntelligenceError("저장된 분석과 같은 API·모델로 대본을 생성하세요.", "invalid_selection", False)
                try:
                    level = validate_news_usage(news_usage if news_usage is not None else evidence.get("news_usage"))
                    if level != evidence.get("news_usage"):
                        raise ValueError
                    contract = api_news_contract(evidence, level, duration, speech=self.speech, version=selected_version)
                except ValueError:
                    raise IntelligenceError("저장된 분석의 뉴스 활용 수준을 확인하세요.", "news_usage_blocked", False) from None
                evidence = {**evidence, "news_usage_contract": contract, "analysis_result": analysis.result}
            elif "news_usage" in evidence or "news_usage_result" in evidence or news_usage is not None:
                raise IntelligenceError(
                    "저장된 분석 방식과 뉴스 활용 수준을 확인하세요. 기존 로컬 대본은 기존 경로를 사용합니다.",
                    "news_usage_blocked", False,
                )
            if article_ids is not None:
                known = {a["id"] for a in evidence["articles"]}
                from .curation import MAX_CURATION_ARTICLES

                limit = MAX_CURATION_ARTICLES if evidence.get("curation_contract") else 10
                if (not isinstance(article_ids, list) or not article_ids or len(article_ids) > limit
                        or any(type(i) is not int for i in article_ids)
                        or len(article_ids) != len(set(article_ids)) or not set(article_ids) <= known):
                    raise IntelligenceError("대본 뉴스가 저장된 분석 자료와 다릅니다.", "invalid_selection", False)
                selected = set(article_ids)
                evidence = {**evidence, "articles": [a for a in evidence["articles"] if a["id"] in selected],
                            "groups": [[i for i in group if i in selected] for group in evidence["groups"]
                                       if any(i in selected for i in group)]}
            if api_news:
                evidence = {**evidence, "news_usage_result": assess_news_usage(evidence, evidence["news_usage"]),
                            "news_usage_contract": api_news_contract(
                                evidence, evidence["news_usage"], duration, speech=self.speech, version=selected_version,
                            )}
            if profile_on:
                if len(evidence.get("groups", [])) > 1:
                    raise IntelligenceError("숏폼 강조는 한 이슈만 선택하세요.", "invalid_selection", False)
                evidence = {**evidence, "shortform": asdict(profile), "shortform_contract": instruction(profile)}
            if len(evidence.get("articles", [])) > 1:
                evidence = {**evidence, "synthesis": {
                    "article_ids": [a["id"] for a in evidence["articles"]],
                    "facts_verified": False,
                    "instruction": "같은 주제의 제공 자료를 한 편으로 종합하되 서로 다른 수치·날짜·주장을 합치거나 다수결로 확정하지 마세요. "
                                   "출처별 차이와 미확인 사항을 구분하고 같은 보도의 재전재를 독립 확인으로 취급하지 마세요.",
                }}
            evidence = {**evidence, "presentation": chosen_presentation}
            if mode in {'openai', 'claude_api'} and selected_version == 'v2' and not evidence.get('news_usage_contract'):
                evidence = {**evidence, 'news_usage_contract': api_news_contract(
                    evidence, 'STANDARD', duration, speech=self.speech, version=selected_version)}
            run = IntelligenceRun(
                kind="script",
                provider=mode,
                status="running",
                evidence=evidence,
                options={**vars(options), **comparison_options, "duration": duration, "analysis_run_id": analysis_id,
                         'script_prompt_version': selected_version, 'base_max_tokens': base_options.max_tokens,
                         'output_token_allowance': options.max_tokens-base_options.max_tokens,
                         "presentation": chosen_presentation,
                         **({"selected_article_ids": article_ids} if article_ids is not None else {})},
                result={},
                message="대본 생성 중",
            )
            session.add(run)
            session.flush()
            run_id = run.id
        provider = self._provider(mode)
        reservation = None
        try:
            if on_run:
                on_run(run_id)
            self._budget(mode, options, instruction_text, {"duration": duration, "evidence": evidence})
            reservation = self._reserve_api(mode, run_id, "script", options,
                                            {"instruction": instruction_text, "duration": duration, "evidence": evidence})
            output = provider.complete(evidence, duration, base_options)
            self._check_stored_secret(output)
            try:
                script = self.validate(output, duration)
                if mode in {'openai', 'claude_api'} and (selected_version == 'v2' or isinstance(output.get('analysis'), dict)):
                    try:
                        validate_api_news_script(output, evidence)
                    except ValueError:
                        raise IntelligenceError('해석형 대본의 수치·날짜·인용 근거를 확인하세요.', 'news_usage_blocked', False) from None
                self.check_news_usage(script, evidence)
                from .curation import validate_script as validate_curated_script

                try:
                    validate_curated_script(script, evidence)
                except ValueError:
                    raise IntelligenceError("화제성 쇼츠의 구성·분량·근거 조건을 확인하세요.", "ai_bad_response", False) from None
                self._check_stored_secret(script)
                self.check_copy(script, evidence)
            except IntelligenceError as exc:
                if mode == "claude_api" and exc.code == "ai_bad_response":
                    raise ScriptResponseError("script_validation") from None
                raise
            notes = self._review_notes(script, evidence, duration)
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
            self._finish_api(reservation, provider, "success")
            return draft_id
        except Exception as exc:  # noqa: BLE001 - persist safe failure at adapter boundary
            # Never store provider exception text, response body or credential-bearing data.
            message, code, retryable = self._failure(exc, "대본 생성에 실패했습니다. API 설정 또는 응답 형식을 확인하세요.")
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
                if isinstance(exc, ScriptResponseError):
                    run.result = {"script_failure": exc.diagnostics()}
                    if exc.stop_reason == 'max_tokens':
                        run.result = {**run.result, 'output_limit': {'stop_reason': 'max_tokens'}}
                elif isinstance(exc, ProviderOutputLimitError):
                    run.result = {'output_limit': {'finish_reason': 'length'}}
            self._usage(provider, run_id, mode, options, "script", "failed")
            self._finish_api(reservation, provider, "unknown" if code in {"ai_timeout", "ai_unavailable", "ai_cancelled"} else "failed")
            raise IntelligenceError(message, code, retryable) from None

    @staticmethod
    def validate(output: dict, duration: int) -> dict:
        IntelligenceService.check_secret(output)
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

    def _review_notes(self, content: dict, evidence: dict, duration: int) -> list[dict]:
        notes = assess_script(content, evidence, duration, **self.speech)
        if any(a.get("search_provenance", {}).get("provider") == "serpapi" for a in evidence.get("articles", [])):
            notes = [{**note, "message": note["message"].replace("원문 RSS 요약", "공급사 제공 요약")}
                     for note in notes]
        notes.extend(explainer_findings(content, evidence, speech=self.speech))
        if evidence.get("script_method") in API_SCRIPT_METHODS:
            estimated = speech_plan(content, duration, **self.speech)["estimated_total_seconds"]
            if estimated < duration * .90:
                notes.append({
                    "code": "total_narration_too_short", "level": "warning",
                    "message": (
                        f"전체 음성 예상 길이 {estimated}초가 목표 {duration}초보다 짧습니다. "
                        "근거 범위에서 대본을 보완하세요. 실제 WAV 길이는 음성 생성 후 확인하며 API를 자동 재호출하지 않습니다."
                    ),
                })
        return notes

    def edit(self, draft_id: int, revision: int, output: dict) -> None:
        with self.sessions.begin() as session:
            draft = session.get(ContentDraft, draft_id)
            if not draft:
                raise IntelligenceError("초안이 없습니다.", "invalid_selection", False)
            # Older editors may omit the additive notes field; preserve notes for unchanged scenes.
            output = deepcopy(output)
            self._check_stored_secret(output)
            if 'analysis' not in output and draft.content.get('analysis') is not None:
                output['analysis'] = deepcopy(draft.content['analysis'])
            for scene in output.get("scenes", []):
                if "review_notes" not in scene:
                    previous = next((old for old in draft.content.get("scenes", [])
                                     if old.get("narration") == scene.get("narration")), {})
                    scene["review_notes"] = previous.get("review_notes", [])
            if len(output.get('scenes', [])) == len(draft.content.get('scenes', [])):
                for scene, previous in zip(output['scenes'], draft.content['scenes']):
                    if 'role' not in scene and previous.get('role') is not None:
                        scene['role'] = previous['role']
            content = self.validate(output, draft.duration)
            if (draft.sources.get('script_method') == 'api_grounded_v2'
                    or draft.sources.get('script_method') in API_SCRIPT_METHODS and isinstance(output.get('analysis'), dict)):
                try:
                    validate_api_news_script(output, draft.sources)
                except ValueError:
                    raise IntelligenceError('해석형 대본의 수치·날짜·인용 근거를 확인하세요.', 'news_usage_blocked', False) from None
            self.check_news_usage(content, draft.sources)
            from .curation import validate_script as validate_curated_script

            try:
                validate_curated_script(content, draft.sources)
            except ValueError:
                raise IntelligenceError("화제성 쇼츠의 구성·분량·근거 조건을 확인하세요.", "ai_bad_response", False) from None
            self._check_stored_secret(content)
            self.check_copy(content, draft.sources)
            notes = self._review_notes(content, draft.sources, draft.duration)
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
        self.check_secret(value)
        stores = [self.key_store, *self.api_key_stores.values()]
        for store in stores:
            if store is None:
                continue
            try:
                key = store.key()
            except Exception:  # noqa: BLE001, S112 - do not expose credential-store failures
                continue
            if key and key in json.dumps(value, ensure_ascii=False):
                raise IntelligenceError("보안 정책에 의해 차단되었습니다.", "ai_bad_response", False)
