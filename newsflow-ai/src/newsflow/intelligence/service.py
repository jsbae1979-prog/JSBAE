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

from .provider import OfflineProvider, OpenAIProvider, Options, Provider
from .schema import CAUTION, Analysis, Script


class IntelligenceError(Exception):
    pass


class IntelligenceService:
    def __init__(self, sessions, provider: Provider | None = None):
        self.sessions, self.provider = sessions, provider

    def analyze(
        self,
        ids: list[int],
        mode: str = "offline",
        consent: bool = False,
        options: Options | None = None,
        on_run: Callable[[int], None] | None = None,
    ) -> int:
        if mode not in ("offline", "openai") or (mode == "openai" and not consent):
            raise IntelligenceError("외부 AI 분석에는 전송과 비용 발생에 대한 명시적 동의가 필요합니다.")
        options = options or Options()
        if not ids or len(ids) > 10 or len(set(ids)) != len(ids):
            raise IntelligenceError("기사 1~10개를 선택하세요.")
        with self.sessions.begin() as session:
            articles = [session.get(NewsArticle, i) for i in ids]
            if any(a is None for a in articles):
                raise IntelligenceError("선택한 기사가 없습니다.")
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
            payload = {
                "articles": evidence,
                "groups": groups,
                "comparison": "제목 유사도 0.65 기준 후보 그룹입니다. 서로 다른 보도 내용과 독립 출처 여부는 사람이 확인해야 합니다.",
                "caution": CAUTION,
            }
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
        try:
            if on_run:
                on_run(run_id)
            provider = self.provider or (OfflineProvider() if mode == "offline" else OpenAIProvider())
            result = Analysis.model_validate(provider.analyze(payload, options)).model_dump()
            referenced = {i for comparison in result["comparisons"] for i in comparison["article_ids"]}
            if referenced != set(ids):
                raise IntelligenceError("분석 출처가 선택 기사와 일치하지 않습니다.")
            self.check_secret(result)
            self.check_copy(result, payload)
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.result, run.finished_at = "success", result, utcnow()
            return run_id
        except Exception:  # noqa: BLE001 - sanitize provider failure
            message = "AI 분석에 실패했습니다. API 설정 또는 응답 형식을 확인하세요."
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
            raise IntelligenceError(message) from None

    def generate(
        self,
        analysis_id: int,
        duration: int,
        mode: str = "offline",
        consent: bool = False,
        options: Options | None = None,
        on_run: Callable[[int], None] | None = None,
    ) -> int:
        if duration not in (30, 45, 60) or mode not in ("offline", "openai"):
            raise IntelligenceError("영상 길이 또는 Provider가 잘못되었습니다.")
        if mode == "openai" and not consent:
            raise IntelligenceError("외부 API 전송과 비용 발생에 대한 명시적 동의가 필요합니다.")
        options = options or Options()
        with self.sessions.begin() as session:
            analysis = session.get(IntelligenceRun, analysis_id)
            if not analysis or analysis.kind != "analysis" or analysis.status != "success":
                raise IntelligenceError("먼저 기사 분석을 실행하세요.")
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
        try:
            if on_run:
                on_run(run_id)
            provider = self.provider or (OfflineProvider() if mode == "offline" else OpenAIProvider())
            output = provider.complete(evidence, duration, options)
            script = self.validate(output, duration)
            self.check_copy(script, evidence)
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.result, run.finished_at, run.message = (
                    "success",
                    script,
                    utcnow(),
                    "검토용 대본 생성 완료",
                )
                draft = ContentDraft(
                    run_id=run_id,
                    duration=duration,
                    content=script,
                    sources=evidence,
                    revision=1,
                    review_status="review_required",
                )
                session.add(draft)
                session.flush()
                return draft.id
        except Exception as exc:  # noqa: BLE001 - persist safe failure at adapter boundary
            # Never store provider exception text, response body or credential-bearing data.
            message = (
                "AI 요청 시간이 초과되었습니다."
                if isinstance(exc, TimeoutError)
                else "대본 생성에 실패했습니다. API 설정 또는 응답 형식을 확인하세요."
            )
            with self.sessions.begin() as session:
                run = session.get(IntelligenceRun, run_id)
                run.status, run.message, run.finished_at = "failed", message, utcnow()
            raise IntelligenceError(message) from None

    @staticmethod
    def validate(output: dict, duration: int) -> dict:
        script = Script.model_validate(output)
        if sum(s.seconds for s in script.scenes) != duration:
            raise IntelligenceError("장면 길이 합계가 영상 길이와 다릅니다.")
        serialized = script.model_dump_json()
        IntelligenceService.check_secret(script.model_dump())
        if any(word in serialized for word in ("충격!", "100% 확실", "검증 완료", "무조건 사실")):
            raise IntelligenceError("확정적 또는 선정적 표현을 검토하세요.")
        return script.model_dump()

    def edit(self, draft_id: int, revision: int, output: dict) -> None:
        with self.sessions.begin() as session:
            draft = session.get(ContentDraft, draft_id)
            if not draft:
                raise IntelligenceError("초안이 없습니다.")
            content = self.validate(output, draft.duration)
            self.check_copy(content, draft.sources)
            result = session.execute(
                update(ContentDraft)
                .where(ContentDraft.id == draft_id, ContentDraft.revision == revision)
                .values(
                    content=content,
                    revision=revision + 1,
                    review_status="review_required",
                    updated_at=utcnow(),
                )
            )
            if result.rowcount != 1:
                raise IntelligenceError("다른 편집 내용이 저장되었습니다. 새로고침 후 다시 시도하세요.")

    @staticmethod
    def check_copy(content: dict, evidence: dict) -> None:
        text = json.dumps(content, ensure_ascii=False)
        for article in evidence["articles"]:
            summary = article["summary"]
            if len(summary) >= 100 and any(summary[i : i + 100] in text for i in range(len(summary) - 99)):
                raise IntelligenceError(
                    "긴 원문/요약의 그대로 복제는 허용하지 않습니다. 요약을 다시 작성하세요."
                )

    @staticmethod
    def check_secret(value: dict) -> None:
        key = os.environ.get("NEWSFLOW_AI_API_KEY", "")
        if key and key in json.dumps(value, ensure_ascii=False):
            raise IntelligenceError("보안 정책에 의해 차단되었습니다.")
