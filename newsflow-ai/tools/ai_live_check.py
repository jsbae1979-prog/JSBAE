"""Approved single live OpenAI check: one gated script generation with key-free evidence.

Phase 5C.1 B.4 procedure. Every precondition is reported as BLOCKED when unmet:
NEWSFLOW_AI_LIVE_TEST=1 in the environment, an explicit --max-tokens cap, the app closed
(server and migration locks free), the stored gate open (provider openai, dated approval,
monthly limit with headroom, key), a real article collected from a registered public
source (never the 체험 sample), and a typed '동의' unless --yes is given.

Exactly one paid request is made: the analysis runs offline, then one script generation
through the existing IntelligenceService gate (approval, budget with prompt estimate, key).
The evidence JSON never contains the key, the provider body or the script text.

    NEWSFLOW_AI_LIVE_TEST=1 python tools/ai_live_check.py --article-id 12 --max-tokens 1400 --output ai-live
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout
from sqlalchemy import select

from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.db.models import AIUsage, ArticleMention, ContentDraft, NewsArticle, NewsSource
from newsflow.intelligence.credentials import AIKeyStore, CredentialError
from newsflow.intelligence.estimate import estimate_call, estimate_cost
from newsflow.intelligence.provider import (
    SCRIPT_INSTRUCTION,
    OfflineProvider,
    OpenAIProvider,
    Options,
    ProviderError,
)
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.intelligence.settings import external_ready, read_prices, read_settings, usage_this_month

ENV_FLAG = "NEWSFLOW_AI_LIVE_TEST"
PRE_SEND_CODES = frozenset({"ai_key_missing", "ai_budget", "ai_consent"})
OUTPUT_NAME = "ai-live-check.json"
CONFIRM_WORD = "동의"


def _blocked(result: dict, reason: str, message: str) -> dict:
    result.update({"outcome": "BLOCKED", "reason": reason, "message": message})
    return result


def article_is_real(session, article_id: int) -> tuple[NewsArticle | None, bool]:
    """A real article comes only from registered public sources, never the 체험 sample feed."""
    article = session.get(NewsArticle, article_id)
    if article is None:
        return None, False
    urls = set(session.scalars(
        select(NewsSource.url).join(ArticleMention, ArticleMention.source_id == NewsSource.id)
        .where(ArticleMention.article_id == article_id)
    ))
    own = session.get(NewsSource, article.source_id)
    if own is not None:
        urls.add(own.url)
    return article, bool(urls) and SAMPLE_URL not in urls


def run(
    *, article_id: int, duration: int, max_tokens: int, output: Path, yes: bool, sessions=None, store=None,
    provider=None, confirm: Callable[[str], str] | None = None, environ: dict | None = None,
    data_dir: Path | None = None,
) -> dict:
    environ = os.environ if environ is None else environ
    result: dict = {
        "tool": "ai_live_check", "timestamp": datetime.now(UTC).isoformat(), "outcome": "BLOCKED",
        "external_ai_calls": 0, "article_id": article_id, "duration": duration, "max_tokens": max_tokens,
        "key_in_evidence": False,
    }
    if environ.get(ENV_FLAG) != "1":
        return _blocked(result, "env_flag", f"{ENV_FLAG}=1 환경변수가 없어 유료 호출을 시작하지 않았습니다.")
    if type(max_tokens) is not int or not 200 <= max_tokens <= 3000:
        return _blocked(result, "max_tokens", "--max-tokens는 200~3000 사이의 정수여야 합니다 (이번 호출의 출력 상한).")
    if duration not in (30, 45, 60):
        return _blocked(result, "duration", "--duration은 30, 45, 60 중 하나여야 합니다.")
    locks: list[FileLock] = []
    engine = None
    try:
        if sessions is None:
            from newsflow.config import Settings
            from newsflow.db.session import make_engine, migrate, session_factory

            settings = Settings.from_env() if data_dir is None else Settings(data_dir=data_dir)
            data_dir = settings.data_dir
            result["data_dir_name"] = data_dir.name
            for name in (f"server-{settings.port}.lock", "migration.lock"):
                lock = FileLock(str(data_dir / name))
                try:
                    lock.acquire(timeout=0)
                except Timeout:
                    return _blocked(result, "app_running", "NewsFlow가 실행 중입니다. 프로그램을 종료(Ctrl+C)한 뒤 실행하세요.")
                locks.append(lock)
            engine = make_engine(data_dir / "newsflow.db")
            migrate(engine)
            sessions = session_factory(engine)
        if store is None:
            store = AIKeyStore(data_dir or Path("."))
        gate = external_ready(sessions, store)
        result["gate"] = {
            "ready": gate["ready"], "reasons": gate["reasons"], "provider": gate["provider"], "model": gate["model"],
            "approved_at": gate["approved_at"], "limit": gate["limit"], "usage_before": gate["usage"],
        }
        if not gate["ready"]:
            return _blocked(result, "gate_closed", "AI 연결 설정의 승인·월 한도·키 조건이 충족되지 않았습니다: " + " ".join(gate["reasons"]))
        with sessions() as session:
            article, real = article_is_real(session, article_id)
            if article is None:
                return _blocked(result, "article_missing", "기사를 찾지 못했습니다. 뉴스 메뉴에서 수집한 기사 번호를 확인하세요.")
            result["article"] = {"title_chars": len(article.title), "summary_chars": len(article.summary or ""),
                                 "publisher": article.publisher, "published_at": article.published_at.isoformat() if article.published_at else None}
            if not real:
                return _blocked(result, "article_not_real", "체험(합성) 뉴스는 외부로 보내지 않습니다. 등록한 공개 RSS에서 수집한 기사를 선택하세요.")
        settings_ai = read_settings(sessions)
        options = settings_ai.options(max_tokens=max_tokens)
        offline = IntelligenceService(sessions, OfflineProvider(), store)
        evidence = offline.evidence_for([article_id])
        estimate = estimate_call(SCRIPT_INSTRUCTION, {"duration": duration, "evidence": evidence}, options.max_tokens)
        prices = read_prices(sessions)
        result["estimate"] = {**estimate, "cost": estimate_cost(estimate, prices),
                              "prices_configured": prices["input_per_1m"] is not None and prices["output_per_1m"] is not None}
        used = gate["usage"]["tokens"]
        if used + estimate["prompt_tokens"] + options.max_tokens > gate["limit"]:
            return _blocked(result, "budget", f"월 한도 {gate['limit']} 토큰 안에서 이번 호출(사용 {used} + 예상 {estimate['prompt_tokens'] + options.max_tokens})을 할 수 없습니다.")
        summary = (
            f"모델 {options.model} · 출력 상한 {options.max_tokens} 토큰 · 예상 입력 약 {estimate['prompt_tokens']} 토큰 · "
            f"예상 최대 {estimate['total_max']} 토큰 · 이번 달 남은 {gate['limit'] - used} 토큰 · 예상 비용 "
            + (f"{result['estimate']['cost']['amount']} {result['estimate']['cost']['currency']}" if result["estimate"]["cost"] else "단가 미입력")
        )
        result["confirmation_summary"] = summary
        if not yes:
            ask = confirm or input
            answer = ask(f"유료 외부 AI 호출 1회를 수행합니다. {summary}\n계속하려면 '{CONFIRM_WORD}'를 입력하세요: ")
            if (answer or "").strip() != CONFIRM_WORD:
                return _blocked(result, "not_confirmed", "사용자가 동의하지 않아 호출하지 않았습니다.")
        analysis_id = offline.analyze([article_id], mode="offline")
        result["analysis_run_id"] = analysis_id
        provider = provider or OpenAIProvider(store.key)
        live = IntelligenceService(sessions, provider, store)
        result["external_ai_calls"] = 1
        try:
            draft_id = live.generate(analysis_id, duration, mode="openai", consent=True, options=options)
        except IntelligenceError as exc:
            # These codes are raised by the gate or the key store before any request is opened.
            if exc.code in PRE_SEND_CODES:
                result["external_ai_calls"] = 0
            result.update({"outcome": "FAIL", "code": exc.code, "message": str(exc), "retryable": exc.retryable,
                           "retried": bool(getattr(provider, "last_retried", False))})
            return result
        with sessions() as session:
            draft = session.get(ContentDraft, draft_id)
            rows = session.scalars(select(AIUsage).where(AIUsage.run_id == draft.run_id).order_by(AIUsage.id)).all()
            content = json.dumps(draft.content, ensure_ascii=False, sort_keys=True)
            result.update({
                "outcome": "PASS", "draft_id": draft_id, "script_run_id": draft.run_id,
                "script_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "script_chars": len(content),
                "review_notes": len(draft.review_notes or []), "review_status": draft.review_status,
                "retried": bool(getattr(provider, "last_retried", False)),
                "usage_rows": [{"status": r.status, "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                                "total_tokens": r.total_tokens, "elapsed_ms": r.elapsed_ms, "model": r.model} for r in rows],
            })
        actual = sum(r["prompt_tokens"] for r in result["usage_rows"])
        result["prompt_ratio_actual_over_estimate"] = round(actual / estimate["prompt_tokens"], 3) if estimate["prompt_tokens"] and actual else None
        result["usage_after"] = usage_this_month(sessions)
        return result
    except CredentialError as exc:
        return _blocked(result, "key_unreadable", str(exc))
    finally:
        if engine is not None:
            engine.dispose()
        for lock in locks:
            lock.release()


def connection_check(*, model: str, environ: dict | None = None, provider=None) -> dict:
    """Zero-token model lookup for CI or a user PC: proves key, network and model name only.

    Requires NEWSFLOW_AI_LIVE_TEST=1 and the key in NEWSFLOW_AI_API_KEY (no key store, no DB,
    no settings written). Never generates a script and never spends tokens.
    """
    environ = os.environ if environ is None else environ
    result: dict = {"tool": "ai_live_check", "mode": "connection_check", "timestamp": datetime.now(UTC).isoformat(),
                    "model": model, "outcome": "BLOCKED", "external_ai_calls": 0, "tokens": 0}
    if environ.get(ENV_FLAG) != "1":
        return _blocked(result, "env_flag", f"{ENV_FLAG}=1 환경변수가 없어 연결 확인을 시작하지 않았습니다.")
    key = (environ.get("NEWSFLOW_AI_API_KEY") or "").strip()
    if provider is None and not key:
        return _blocked(result, "key_missing", "NEWSFLOW_AI_API_KEY 환경변수가 없어 연결 확인을 시작하지 않았습니다.")
    try:
        options = Options(model=model, timeout=15)
    except ValueError:
        return _blocked(result, "model", "모델 이름 형식을 확인하세요.")
    provider = provider or OpenAIProvider(lambda: key)
    result["external_ai_calls"] = 1
    try:
        outcome = provider.check_connection(options)
    except ProviderError as exc:
        result.update({"outcome": "FAIL", "code": exc.code, "message": str(exc)})
        return result
    result.update({"outcome": "PASS", "elapsed_ms": int(outcome.get("elapsed_ms", 0)), "tokens": int(outcome.get("tokens", 0)),
                   "message": "연결 성공 · 모델 확인 · 토큰 사용 0"})
    return result


def resolved_keys(data_dir: Path | None, environ: dict | None = None) -> list[str]:
    """Every key the tool could have used (stored DPAPI key and environment), for the evidence scrub."""
    environ = os.environ if environ is None else environ
    keys = []
    try:
        if data_dir is None:
            from newsflow.config import Settings

            data_dir = Settings.from_env().data_dir
        stored = AIKeyStore(data_dir).key()
        if stored:
            keys.append(stored)
    except (CredentialError, OSError, ValueError):
        pass
    env_key = (environ.get("NEWSFLOW_AI_API_KEY") or "").strip()
    if env_key:
        keys.append(env_key)
    return keys


def write_evidence(result: dict, output: Path, key: str | list[str] = "") -> Path:
    encoded = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    keys = [key] if isinstance(key, str) else list(key)
    if any(k and k in encoded for k in keys):  # defensive: evidence must never carry key material
        raise RuntimeError("evidence would contain key material")
    output.mkdir(parents=True, exist_ok=True)
    target = output / OUTPUT_NAME
    target.write_text(encoded, encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--article-id", type=int, default=None, help="등록한 공개 RSS에서 수집한 기사 번호")
    parser.add_argument("--duration", type=int, default=30, choices=(30, 45, 60))
    parser.add_argument("--max-tokens", type=int, default=None, help="이번 호출의 출력 토큰 상한 (200~3000)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=None, help="기본값: NEWSFLOW_DATA_DIR 또는 %%LOCALAPPDATA%%\\NewsFlowAI")
    parser.add_argument("--yes", action="store_true", help="대화형 '동의' 입력 생략 (이미 승인한 경우에만)")
    parser.add_argument("--connection-check", action="store_true", help="토큰 0의 모델 조회만 수행 (대본 생성 없음)")
    parser.add_argument("--model", default="gpt-4o-mini", help="--connection-check에서 조회할 모델 이름")
    args = parser.parse_args()
    if args.connection_check:
        result = connection_check(model=args.model)
        target = write_evidence(result, args.output, (os.environ.get("NEWSFLOW_AI_API_KEY") or "").strip())
        print(f"연결 확인 {result['outcome']} · 토큰 {result['tokens']} · 증거 {target}")
        return 0
    if args.article_id is None or args.max_tokens is None:
        parser.error("--article-id와 --max-tokens가 필요합니다 (또는 --connection-check).")
    try:
        result = run(article_id=args.article_id, duration=args.duration, max_tokens=args.max_tokens, output=args.output,
                     yes=args.yes, data_dir=args.data_dir)
    except Exception as exc:  # noqa: BLE001 - tool defect; never print provider or key details
        result = {"tool": "ai_live_check", "outcome": "FAIL", "reason": "tool_error", "error_type": type(exc).__name__,
                  "external_ai_calls": 0}
        write_evidence(result, args.output)
        print("도구 오류로 중단했습니다. 증거 파일을 확인하세요.")
        return 1
    target = write_evidence(result, args.output, resolved_keys(args.data_dir))
    print(f"결과 {result['outcome']} · 외부 호출 {result['external_ai_calls']}회 · 증거 {target}")
    if result["outcome"] != "PASS":
        print(result.get("message") or result.get("reason", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
