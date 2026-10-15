"""Phase 5C.1 public feed review: the application's own RSS policy against curated candidates.

Runtime dependencies only (standard library plus the installed ``newsflow`` package and its
runtime requirements), so the same script runs on a user's Windows PC after ``run.bat`` and
in Cloud/Actions. The production adapter, collector, dedup and coordinator are used
unchanged: robots.txt (first-match, fail-closed), SSRF/DNS pinning, TLS, redirect, 2 MiB,
identity-encoding and strict ``published_at`` policies are observed, never altered.

Article bodies are never fetched. The evidence file keeps counts, publishers, link domains
and at most three titles (80 characters) per feed; summaries never enter it.

Statuses:
  PASS          connection test passed and two consecutive collections succeeded.
  BLOCKED       the app's conservative policy stopped the feed (robots/policy); not a defect.
  NOT VERIFIED  the network, the server or the feed could not be verified here (dns, timeout,
                https, http, parse, empty, budget, preflight failure, disabled candidate).
  FAIL          an application-internal defect (unexpected exception, failed collection after
                a passing check, inconsistent counts).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import quote, unquote, urljoin, urlparse, urlsplit, urlunparse
from urllib.robotparser import RobotFileParser

import feedparser
from defusedxml import ElementTree
from sqlalchemy import select

from newsflow.db.models import (
    AppSetting,
    ArticleMention,
    AuditLog,
    CollectionRun,
    NewsArticle,
    NewsSource,
    NewsSourceCheck,
    utcnow,
)
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.korean import MIN_SUMMARY_CHARS
from newsflow.news.collector import Collector
from newsflow.news.rss_adapter import (
    USER_AGENT,
    FeedError,
    PublicRSSAdapter,
    PublicTransport,
    Transport,
    public_addresses,
    validate_url,
)
from newsflow.news.service import CollectionCoordinator, NewsService

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CANDIDATES = ROOT / "tools" / "feed_candidates.json"
TOOL = "ci_feed_review"
ADAPTER_NOTE = "PublicRSSAdapter (robots/SSRF/TLS/redirect/2MiB policy unchanged)"
PREFLIGHT_HOST = "news.google.com"
NOTICE_LIMIT = 4000
MAX_NOTICES = 10
MAX_ENABLED = 18
STATUSES = ("PASS", "BLOCKED", "NOT VERIFIED", "FAIL")
BLOCKED_KINDS = {"robots", "policy"}
UNVERIFIED_KINDS = {"dns", "proxy", "https", "timeout", "http", "network", "parse", "empty"}
VALID_ROLES = {"app_default", "control", ""}
VALID_EXPECTATIONS = {"PASS", "BLOCKED_robots", "BLOCKED_crawl_delay", "unknown"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_FORMATS = {"rss2", "atom", "rdf"}
REDIRECTS = {301, 302, 303, 307, 308}
ROBOTS_MAX_BYTES = 32 * 1024
PASS1_SHARE = 0.8  # wall-clock share of --max-seconds reserved for pass 1; the rest serves pass 2
SAMPLE_LIMIT = 3
TITLE_LIMIT = 80
EMPTY_MESSAGE = "피드에 기사 항목이 없습니다."
RAW_FAILURE_MESSAGE = "RSS 수집 또는 파싱에 실패했습니다."


# --------------------------------------------------------------------------- notices


def encode_notice(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def notice(title: str, payload: object) -> None:
    """One GitHub workflow annotation; payloads above the limit are replaced, never split here."""
    encoded = encode_notice(payload)
    if len(encoded.encode()) > NOTICE_LIMIT:
        encoded = encode_notice({"truncated": True, "title": title})
    print(f"::notice title={title}::{encoded}")


def chunk_items(items: list, limit: int = NOTICE_LIMIT) -> list[list]:
    """Greedy packing of compact items so every chunk encodes to at most ``limit`` bytes."""
    chunks: list[list] = []
    current: list = []
    for item in items:
        candidate = [*current, item]
        if current and len(encode_notice(candidate).encode()) > limit:
            chunks.append(current)
            current = [item]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


# --------------------------------------------------------------------------- candidates


def load_candidates(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    candidates = data["candidates"]
    if not isinstance(candidates, list):
        raise TypeError("candidates must be a list")
    return candidates


def validate_candidates(candidates: list[dict]) -> list[str]:
    """Return human-readable problems; an empty list means the file is consistent."""
    problems: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        label = item.get("id", "?")
        if label in seen:
            problems.append(f"{label}: duplicate id")
        seen.add(label)
        try:
            validate_url(item["url"])
        except (FeedError, KeyError) as exc:
            problems.append(f"{label}: url rejected ({type(exc).__name__})")
        if item.get("role", "") not in VALID_ROLES:
            problems.append(f"{label}: role")
        if item.get("expectation") not in VALID_EXPECTATIONS:
            problems.append(f"{label}: expectation")
        if item.get("confidence") not in VALID_CONFIDENCE:
            problems.append(f"{label}: confidence")
        if item.get("format_expected") not in VALID_FORMATS:
            problems.append(f"{label}: format_expected")
        if not isinstance(item.get("enabled"), bool):
            problems.append(f"{label}: enabled")
    if sum(1 for item in candidates if item.get("enabled") is True) > MAX_ENABLED:
        problems.append(f"more than {MAX_ENABLED} enabled candidates")
    return problems


def select_candidates(candidates: list[dict], only: str | None) -> list[dict]:
    """``--only`` picks candidates by id and runs them even when the file disables them."""
    if not only:
        return candidates
    wanted = {token.strip() for token in only.split(",") if token.strip()}
    selected = [dict(item, enabled=True) for item in candidates if item.get("id") in wanted]
    missing = wanted - {item["id"] for item in selected}
    if missing:
        print(f"알 수 없는 후보 id를 건너뜁니다: {', '.join(sorted(missing))}")
    return selected


# --------------------------------------------------------------------------- classification


def classify(
    *,
    attempted: bool,
    check_status: str | None,
    kind: str | None,
    feed_error: bool,
    first_status: str | None,
    second_status: str | None,
    error_type: str | None = None,
    count_mismatch: bool = False,
) -> str:
    """Map one feed's observations to PASS / BLOCKED / NOT VERIFIED / FAIL.

    BLOCKED is the app's conservative robots/policy decision, never a defect. NOT VERIFIED
    covers every classified external failure and everything not attempted. FAIL is reserved
    for application-internal defects: a non-FeedError exception, a collection that did not
    succeed after a passing check, or inconsistent counts.
    """
    if not attempted:
        return "NOT VERIFIED"
    if error_type:
        return "FAIL"
    if check_status != "pass":
        if kind in BLOCKED_KINDS:
            return "BLOCKED"
        if kind == "empty" or (feed_error and kind in UNVERIFIED_KINDS):
            return "NOT VERIFIED"
        return "FAIL"
    if first_status == "success" and second_status == "success" and not count_mismatch:
        return "PASS"
    if first_status == "success" and second_status is None and not count_mismatch:
        return "NOT VERIFIED"  # second collection not run (wall-clock budget)
    if "client_timeout" in (first_status, second_status):
        return "NOT VERIFIED"  # the feed was slower than the review's wait; not an app defect
    return "FAIL"


def expectation_met(expectation: str, status: str, kind: str | None, message: str) -> bool | None:
    """True/False when the outcome can be compared with the curated expectation, else None."""
    if expectation not in VALID_EXPECTATIONS or expectation == "unknown" or status == "NOT VERIFIED":
        return None
    if expectation == "PASS":
        return status == "PASS"
    if expectation == "BLOCKED_robots":
        return status == "BLOCKED" and kind == "robots"
    return status == "BLOCKED" and kind == "robots" and "crawl-delay" in message


# --------------------------------------------------------------------------- app steps


def default_dns_check(host: str = PREFLIGHT_HOST, timeout: float = 5) -> str:
    """Same resolver and public-address policy as the transport; records OK or FAIL(kind)."""
    try:
        public_addresses(host, 443, timeout)
    except FeedError as exc:
        return f"FAIL({exc.kind})"
    return "OK"


def connection_check(collector: Collector, url: str, name: str, timeout: int) -> dict:
    """Same logic as the GUI connection test: counts and a classified message, nothing stored."""
    begun = time.monotonic()
    status, kind, message, counts = "pass", None, "", (0, 0, 0)
    feed_error, error_type = False, None
    try:
        articles = collector.collect(url, name, timeout)
        counts = (
            len(articles),
            sum(1 for a in articles if a.published_at is not None),
            sum(1 for a in articles if len(a.summary.strip()) >= MIN_SUMMARY_CHARS),
        )
        if not articles:
            status, kind, message = "fail", "empty", EMPTY_MESSAGE
        else:
            message = f"기사 {counts[0]}개 · 발행시각 있음 {counts[1]}개 · 요약 충분 {counts[2]}개"
    except FeedError as exc:
        status, kind, message, feed_error = "fail", str(exc.kind), str(exc)[:300], True
    except Exception as exc:  # noqa: BLE001 - raw adapter/network details never enter evidence
        status, kind, message = "fail", "network", RAW_FAILURE_MESSAGE
        error_type = type(exc).__name__
    return {
        "status": status,
        "kind": kind,
        "message": message,
        "article_count": counts[0],
        "dated_count": counts[1],
        "summarized_count": counts[2],
        "elapsed_ms": int((time.monotonic() - begun) * 1000),
        "feed_error": feed_error,
        "error_type": error_type,
    }


def record_check(sessions, source_id: int, check: dict) -> None:
    """Persist the check exactly as the sources page does (counts and classification only)."""
    status, message = check["status"], check["message"]
    with sessions.begin() as session:
        row = session.get(NewsSourceCheck, source_id)
        if row is None:
            row = NewsSourceCheck(source_id=source_id, status=status, message=message)
            session.add(row)
        row.status, row.kind, row.message = status, check["kind"], message
        row.article_count = check["article_count"]
        row.dated_count = check["dated_count"]
        row.summarized_count = check["summarized_count"]
        row.checked_at = utcnow()
        session.add(
            AuditLog(
                source_id=source_id,
                level="info" if status == "pass" else "warning",
                event="source_tested",
                message=("연결 테스트 성공: " if status == "pass" else "연결 테스트 실패: ") + message[:450],
            )
        )


def run_collection(coordinator: CollectionCoordinator, sessions, source_id: int, timeout: int) -> dict:
    """One coordinator run for a single source, awaited, with the run row and its audit line.

    A run that outlives the client wait is reported as ``client_timeout`` (NOT VERIFIED, never
    FAIL). The worker is then drained for a further bounded time so the next feed does not hit
    CollectionBusy; ``drained`` says whether that worked.
    """
    run_id = coordinator.start([source_id])
    future = coordinator.future
    assert future is not None
    try:
        future.result(timeout=timeout * 10 + 30)
    except TimeoutError:
        try:
            future.result(timeout=timeout * 30 + 60)
            drained = True
        except TimeoutError:
            drained = False
        return {"run_id": run_id, "status": "client_timeout", "drained": drained, "added": None,
                "duplicates": None, "audit_event": None, "audit_message": None}
    with sessions() as session:
        run = session.get(CollectionRun, run_id)
        log = session.scalar(
            select(AuditLog)
            .where(AuditLog.run_id == run_id, AuditLog.source_id == source_id)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        return {
            "run_id": run_id,
            "status": run.status if run else None,
            "added": run.added if run else None,
            "duplicates": run.duplicates if run else None,
            "audit_event": log.event if log else None,
            "audit_message": log.message[:200] if log else None,
        }


def collection_evidence(sessions, source_id: int) -> dict:
    """Aggregate counts for one source; titles and summaries are deliberately absent."""
    with sessions() as session:
        rows = session.execute(
            select(ArticleMention, NewsArticle)
            .join(NewsArticle, NewsArticle.id == ArticleMention.article_id)
            .where(ArticleMention.source_id == source_id)
            .order_by(ArticleMention.id)
        ).all()
    articles = {article.id: article for _, article in rows}
    dated = sorted(a.published_at for a in articles.values() if a.published_at is not None)
    publishers = sorted({mention.publisher for mention, _ in rows})
    domains = Counter(urlsplit(a.url).hostname or "" for a in articles.values())
    categories = Counter(a.category for a in articles.values())
    return {
        "articles_stored": len(articles),
        "mentions": len(rows),
        "title_merges": sum(1 for mention, article in rows if mention.url != article.url),
        "dated_ratio": f"{len(dated)}/{len(articles)}",
        "earliest_published": dated[0].isoformat() if dated else None,
        "latest_published": dated[-1].isoformat() if dated else None,
        "publishers": publishers[:10],
        "link_domains": dict(domains.most_common(10)),
        "categories": dict(categories.most_common()),
    }


def samples(sessions, source_id: int, limit: int = SAMPLE_LIMIT) -> list[dict]:
    with sessions() as session:
        articles = session.scalars(
            select(NewsArticle)
            .join(ArticleMention, ArticleMention.article_id == NewsArticle.id)
            .where(ArticleMention.source_id == source_id)
            .order_by(NewsArticle.id)
            .distinct()
            .limit(limit)
        ).all()
    return [
        {
            "title": article.title[:TITLE_LIMIT],
            "publisher": article.publisher[:60],
            "published_at": article.published_at.isoformat() if article.published_at else None,
            "link_domain": urlsplit(article.url).hostname,
        }
        for article in articles
    ]


# --------------------------------------------------------------------------- diagnostics


def _robots_path(feed_url: str) -> str:
    """The path form RobotFileParser.can_fetch compares against rule prefixes (Python 3.12)."""
    parsed = urlparse(unquote(feed_url))
    path = urlunparse(("", "", parsed.path, parsed.params, parsed.query, parsed.fragment))
    return quote(path) or "/"


def explain_robots(
    feed_url: str, timeout: float, transport: Transport | None = None, save_dir: Path | None = None
) -> dict:
    """Explain the app's robots decision for one feed without changing the policy.

    One extra GET of ``<origin>/robots.txt`` goes through the same validated transport (DNS
    pinning, TLS, identity encoding, 2 MiB); redirects are followed at most three times like the
    adapter. The decision mirrors ``PublicRSSAdapter.fetch``: 404 means a synthetic allow-all,
    any other non-200 status fails closed, then first-match can_fetch, request-rate and
    crawl-delay rejection, in that order.
    """
    transport = transport or PublicTransport()
    feed_url = validate_url(feed_url)
    parts = urlsplit(feed_url)
    origin = f"{parts.scheme}://{parts.netloc}"
    info: dict = {
        "origin": origin,
        "robots_url": origin + "/robots.txt",
        "redirects": 0,
        "status": None,
        "bytes": 0,
        "sha256": None,
        "user_agent_token": USER_AGENT.split("/")[0].lower(),
        "applicable_group": None,
        "first_matching_rule": None,
        "crawl_delay": None,
        "request_rate": None,
        "can_fetch": None,
        "decision": "deny",
        "decision_reason": None,
        "saved": None,
        # The adapter checks robots.txt for the origin of every redirect hop of the feed; this
        # diagnostic explains the configured feed origin only, so a denial on a redirect target
        # can show decision "allow" here.
        "scope": "configured feed origin only; feed redirect targets are not explained",
    }
    target = info["robots_url"]
    response = None
    for _ in range(4):
        target = validate_url(target)
        response = transport.get(target, timeout)
        if response.status in REDIRECTS:
            if not response.location:
                info["decision_reason"] = "redirect_without_location"
                return info
            target = urljoin(target, response.location)
            info["redirects"] += 1
            response = None
            continue
        break
    if response is None:
        info["decision_reason"] = "redirect_limit"
        return info
    info["robots_url"], info["status"], info["bytes"] = target, response.status, len(response.body)
    info["sha256"] = hashlib.sha256(response.body).hexdigest()
    if response.status == 404:
        rules = ["User-agent: *", "Allow: /"]
        info["synthetic"] = "404 → allow all"
    elif response.status == 200:
        rules = response.body.decode("utf-8", errors="replace").splitlines()
        if save_dir is not None and len(response.body) <= ROBOTS_MAX_BYTES:
            save_dir.mkdir(parents=True, exist_ok=True)
            name = re.sub(r"[^A-Za-z0-9.-]", "_", urlsplit(target).hostname or "unknown") + ".txt"
            (save_dir / name).write_bytes(response.body)
            info["saved"] = f"robots/{name}"
    else:
        info["decision_reason"] = "robots_unavailable"  # fail closed → kind robots
        return info
    robot = RobotFileParser()
    robot.parse(rules)
    group = next((entry for entry in robot.entries if entry.applies_to(USER_AGENT)), None)
    if group is None and robot.default_entry is not None:
        group = robot.default_entry
    info["applicable_group"] = list(group.useragents) if group else []
    if group is not None:
        path = _robots_path(feed_url)
        rule = next((line for line in group.rulelines if line.applies_to(path)), None)
        info["first_matching_rule"] = str(rule) if rule else None
    info["can_fetch"] = robot.can_fetch(USER_AGENT, feed_url)
    info["crawl_delay"] = robot.crawl_delay(USER_AGENT)
    rate = robot.request_rate(USER_AGENT)
    info["request_rate"] = {"requests": rate.requests, "seconds": rate.seconds} if rate else None
    if not info["can_fetch"]:
        info["decision_reason"] = "disallowed"
    elif rate:
        info["decision_reason"] = "request_rate"
    elif info["crawl_delay"]:
        info["decision_reason"] = "crawl_delay"
    else:
        info["decision"] = "allow"
    return info


def parse_diagnostic(adapter, url: str, timeout: int) -> dict:
    """Why the strict parser rejected a feed: class names and declared shape only, never text."""
    payload = adapter.fetch(url, timeout)
    info: dict = {"bytes": len(payload), "declared_encoding": None, "root_tag": None, "bozo_exception": None}
    head = payload[:300].decode("ascii", errors="replace")
    declared = re.search(r"""encoding=["']([A-Za-z0-9._-]+)["']""", head)
    if declared:
        info["declared_encoding"] = declared.group(1)
    try:
        info["root_tag"] = ElementTree.fromstring(payload).tag.split("}")[-1][:40]
    except Exception as exc:  # noqa: BLE001 - diagnostic only
        info["xml_error_type"] = type(exc).__name__
        text = payload[:4096].decode("utf-8", errors="replace")
        first = re.search(r"<(?![?!/])([A-Za-z_][\w.:-]*)", text)
        info["root_tag"] = first.group(1)[:40] if first else None
    parsed = feedparser.parse(payload)
    if parsed.bozo:
        info["bozo_exception"] = type(parsed.bozo_exception).__name__
    info["feedparser_format"] = parsed.get("version") or None
    info["entries"] = len(parsed.entries)
    return info


# --------------------------------------------------------------------------- review run


def _feed_record(candidate: dict) -> dict:
    url = candidate["url"]
    return {
        "id": candidate["id"],
        "name": candidate["name"],
        "url": url,
        "host": urlsplit(url).hostname,
        "language": candidate.get("language", ""),
        "confidence": candidate.get("confidence", "low"),
        "expectation": candidate.get("expectation", "unknown"),
        "role": candidate.get("role", ""),
        "enabled": bool(candidate.get("enabled", False)),
        "status": "NOT VERIFIED",
        "reason": None if candidate.get("enabled") else "not_enabled",
        "attempted": False,
        "check": None,
        "robots": None,
        "parse_diagnostic": None,
        "collection": None,
        "samples": [],
        "expectation_met": None,
        "error_type": None,
    }


def register_sources(sessions, feeds: list[dict]) -> dict[str, int]:
    """Insert enabled candidates as NewsSource rows, reusing a row when the URL already exists."""
    source_ids: dict[str, int] = {}
    with sessions.begin() as session:
        for feed in feeds:
            if not feed["enabled"]:
                continue
            try:
                url = validate_url(feed["url"])
            except FeedError as exc:
                feed["reason"], feed["error_type"] = "invalid_url", type(exc).__name__
                continue
            existing = session.scalar(select(NewsSource).where(NewsSource.url == url))
            if existing is not None and existing.id in source_ids.values():
                feed["reason"] = "duplicate_url"
                continue
            if existing is None:
                existing = NewsSource(name=feed["name"][:100], url=url, enabled=True)
                session.add(existing)
                session.flush()
            source_ids[feed["id"]] = existing.id
    return source_ids


def _public_check(check: dict) -> dict:
    keys = ("status", "kind", "message", "article_count", "dated_count", "summarized_count", "elapsed_ms")
    public = {key: check[key] for key in keys}
    public["feed_error"] = check["feed_error"]
    return public


def _diagnose(feed: dict, check: dict, adapter, transport: Transport | None, timeout: int, output: Path) -> None:
    if not check["feed_error"]:
        return
    try:
        if check["kind"] == "robots":
            if transport is None:
                feed["robots"] = {"skipped": "adapter_without_transport"}
            else:
                feed["robots"] = explain_robots(feed["url"], timeout, transport, output / "robots")
        elif check["kind"] == "parse":
            feed["parse_diagnostic"] = parse_diagnostic(adapter, feed["url"], timeout)
    except Exception as exc:  # noqa: BLE001 - diagnostics never fail the review
        key = "robots" if check["kind"] == "robots" else "parse_diagnostic"
        feed[key] = {"diagnostic_error_type": type(exc).__name__}


def _finalize(feed: dict) -> None:
    check = feed.get("check") or {}
    collection = feed.get("collection") or {}
    first, second = collection.get("first"), collection.get("second")
    count_mismatch = False
    if first and first.get("status") == "success":
        processed = (first.get("added") or 0) + (first.get("duplicates") or 0)
        stored = collection.get("articles_stored")
        count_mismatch = (processed == 0 and check.get("article_count", 0) > 0) or (
            stored == 0 and (first.get("added") or 0) > 0
        )
    feed["status"] = classify(
        attempted=feed["attempted"],
        check_status=check.get("status"),
        kind=check.get("kind"),
        feed_error=bool(check.get("feed_error")),
        first_status=first.get("status") if first else None,
        second_status=second.get("status") if second else None,
        error_type=feed.get("error_type"),
        count_mismatch=count_mismatch,
    )
    if feed["attempted"] and feed["reason"] is None:
        if feed["error_type"]:
            feed["reason"] = feed["error_type"]
        elif check.get("status") != "pass":
            feed["reason"] = check.get("kind")
        elif count_mismatch:
            feed["reason"] = "count_mismatch"
        elif first and first.get("status") != "success":
            feed["reason"] = f"first_collection_{first.get('status')}"
        elif second is None:
            feed["reason"] = "budget"
        elif second.get("status") != "success":
            feed["reason"] = f"second_collection_{second.get('status')}"
    feed["expectation_met"] = (
        expectation_met(feed["expectation"], feed["status"], check.get("kind"), check.get("message", ""))
        if feed["attempted"]
        else None
    )


def _summary(feeds: list[dict], elapsed: float) -> dict:
    by_status = Counter(feed["status"] for feed in feeds)
    by_kind = Counter(
        feed["check"]["kind"] for feed in feeds if feed.get("check") and feed["check"]["status"] != "pass"
    )
    by_reason = Counter(feed["reason"] for feed in feeds if feed["reason"] and not feed["attempted"])
    summary = {"feeds": len(feeds), "attempted": sum(1 for feed in feeds if feed["attempted"])}
    summary.update({status: by_status.get(status, 0) for status in STATUSES})
    summary["by_kind"] = dict(sorted(by_kind.items()))
    summary["by_reason"] = dict(sorted(by_reason.items()))
    summary["expectation_unmet"] = [feed["id"] for feed in feeds if feed["expectation_met"] is False]
    summary["elapsed_seconds"] = round(elapsed, 1)
    return summary


def write_report(report: dict, output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    path = output / "feed-review.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def new_report(mode: str, timeout: int) -> dict:
    proxy_present = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    return {
        "tool": TOOL,
        "mode": mode,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "feedparser": feedparser.__version__,
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "adapter": ADAPTER_NOTE,
        "user_agent": USER_AGENT,
        "request_timeout": timeout,
        "network": {
            "dns_preflight": None,
            "https_proxy_present": proxy_present,
            "proxy_used_by_transport": False,
        },
        "terms_confirmed_by_human": False,
        "article_bodies_fetched": False,
        "summary": {},
        "feeds": [],
    }


def run_review(
    candidates: list[dict],
    output: Path,
    *,
    mode: str,
    max_seconds: float,
    timeout: int,
    adapter=None,
    dns_check: Callable[[], str] | None = None,
    pause: float = 1.0,
) -> dict:
    """Review every candidate sequentially through the production collection path.

    ``adapter`` and ``dns_check`` are injection points for offline tests (FakeRSSAdapter and a
    stub returning "OK"); production uses PublicRSSAdapter and the real DNS preflight. The
    temporary database and coordinator are always disposed. The report is written before
    returning, whatever happened.
    """
    output = Path(output)
    started = time.monotonic()
    report = new_report(mode, timeout)
    feeds = [_feed_record(candidate) for candidate in candidates]
    report["feeds"] = feeds
    try:
        preflight = (dns_check or default_dns_check)()
        report["network"]["dns_preflight"] = preflight
        if preflight != "OK":
            for feed in feeds:
                if feed["enabled"]:
                    feed["reason"] = "network_preflight"
        else:
            _review_feeds(feeds, output, max_seconds, timeout, adapter, pause, started)
    finally:
        for feed in feeds:
            _finalize(feed)
        report["summary"] = _summary(feeds, time.monotonic() - started)
        write_report(report, output)
    return report


def _review_feeds(feeds, output: Path, max_seconds: float, timeout: int, adapter, pause: float, started: float):
    adapter = adapter or PublicRSSAdapter()
    transport = getattr(adapter, "transport", None)
    collector = Collector(adapter)
    with TemporaryDirectory(prefix="newsflow-feed-review-") as tmp:
        data_dir = Path(tmp)
        engine = make_engine(data_dir / "newsflow.db")
        migrate(engine)
        sessions = session_factory(engine)
        coordinator = CollectionCoordinator(NewsService(sessions, collector), data_dir)
        try:
            with sessions.begin() as session:
                session.add(AppSetting(key="request_timeout", value=str(timeout)))
            source_ids = register_sources(sessions, feeds)
            # Pass 1: connection test, then one collection, one host at a time.
            stalled = False  # a collection worker that could not be drained blocks every later start
            for feed in feeds:
                source_id = source_ids.get(feed["id"])
                if source_id is None:
                    continue
                if stalled or time.monotonic() - started > max_seconds * PASS1_SHARE:
                    feed["reason"] = "budget"
                    continue
                feed["attempted"], feed["reason"] = True, None
                try:
                    check = connection_check(collector, feed["url"], feed["name"], timeout)
                    record_check(sessions, source_id, check)
                    feed["check"] = _public_check(check)
                    feed["error_type"] = check["error_type"]
                    if check["status"] == "pass":
                        first = run_collection(coordinator, sessions, source_id, timeout)
                        feed["collection"] = {"first": first, "second": None}
                        stalled = first["status"] == "client_timeout" and not first["drained"]
                    else:
                        _diagnose(feed, check, adapter, transport, timeout, output)
                except Exception as exc:  # noqa: BLE001 - one feed never stops the review
                    feed["error_type"] = type(exc).__name__
                if pause:
                    time.sleep(pause)
            # Pass 2: a second collection of every feed that collected successfully → dedup evidence.
            for feed in feeds:
                collection = feed.get("collection")
                if not collection or feed["error_type"]:
                    continue
                source_id = source_ids[feed["id"]]
                try:
                    if (
                        collection["first"]["status"] == "success" and not stalled
                        and time.monotonic() - started <= max_seconds
                    ):
                        collection["second"] = run_collection(coordinator, sessions, source_id, timeout)
                    collection.update(collection_evidence(sessions, source_id))
                    feed["samples"] = samples(sessions, source_id)
                except Exception as exc:  # noqa: BLE001
                    feed["error_type"] = type(exc).__name__
                if pause and collection.get("second"):
                    time.sleep(pause)
        finally:
            coordinator.close()
            engine.dispose()


# --------------------------------------------------------------------------- output


def _feed_line(feed: dict) -> dict:
    check = feed.get("check") or {}
    collection = feed.get("collection") or {}
    line = {"id": feed["id"], "host": feed["host"], "reason": feed["reason"]}
    if check:
        line.update(kind=check.get("kind"), msg=(check.get("message") or "")[:100], n=check.get("article_count"))
        line["dated"] = check.get("dated_count")
    for key in ("first", "second"):
        run = collection.get(key)
        if run:
            line[key] = f"{run.get('status')} +{run.get('added')}/={run.get('duplicates')}"
    if collection.get("articles_stored") is not None:
        line["stored"] = collection["articles_stored"]
        line["merges"] = collection.get("title_merges")
    if feed.get("expectation_met") is not None:
        line["expected"] = feed["expectation_met"]
    return line


def _robots_line(feed: dict) -> dict:
    robots = feed["robots"]
    keys = ("status", "applicable_group", "first_matching_rule", "crawl_delay", "request_rate", "decision")
    line = {"id": feed["id"], "host": feed["host"]}
    line.update({key: robots.get(key) for key in keys if key in robots})
    for key in ("decision_reason", "diagnostic_error_type", "skipped"):
        if robots.get(key):
            line[key] = robots[key]
    return line


def build_notices(report: dict) -> list[tuple[str, object]]:
    """Summary first, then chunked per-status lists and robots explanations, at most MAX_NOTICES."""
    feeds = report.get("feeds", [])
    sections: list[tuple[str, list]] = []
    for status in STATUSES:
        sections.append((f"FeedReview {status}", [_feed_line(f) for f in feeds if f["status"] == status]))
    sections.append(("FeedReview robots", [_robots_line(f) for f in feeds if f.get("robots")]))
    detail: list[tuple[str, object]] = []
    for title, items in sections:
        chunks = chunk_items(items)
        for index, chunk in enumerate(chunks, start=1):
            suffix = f" {index}/{len(chunks)}" if len(chunks) > 1 else ""
            detail.append((title + suffix, chunk))
    summary = {
        "mode": report.get("mode"),
        "dns_preflight": (report.get("network") or {}).get("dns_preflight"),
        "summary": report.get("summary"),
        "python": report.get("python"),
        "platform": report.get("platform"),
        "started_at": report.get("started_at"),
        "error_type": report.get("error_type"),
    }
    if len(detail) > MAX_NOTICES - 1:
        summary["notices_truncated"] = True
    return [("FeedReview", summary), *detail[: MAX_NOTICES - 1]]


def emit_notices(report: dict) -> None:
    for title, payload in build_notices(report):
        notice(title, payload)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="공개 RSS 후보를 앱의 수집 정책 그대로 검토합니다.")
    parser.add_argument("--mode", choices=("cloud", "windows"), required=True)
    parser.add_argument("--output", type=Path, required=True, help="feed-review.json을 쓸 폴더")
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--max-seconds", type=float, default=540, help="전체 실행 시간 예산(초)")
    parser.add_argument("--timeout", type=int, default=10, help="요청당 제한 시간(초)")
    parser.add_argument("--only", default=None, help="쉼표로 구분한 후보 id만 실행")
    parser.add_argument("--preflight-host", default=PREFLIGHT_HOST, help="DNS 사전 점검 호스트")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = Path(args.output)
    try:
        candidates = load_candidates(args.candidates)
        problems = validate_candidates(candidates)
        if problems:
            print("후보 목록 경고: " + "; ".join(problems))
        candidates = select_candidates(candidates, args.only)
        report = run_review(
            candidates,
            output,
            mode=args.mode,
            max_seconds=args.max_seconds,
            timeout=args.timeout,
            dns_check=lambda: default_dns_check(args.preflight_host),
        )
    except Exception as exc:  # noqa: BLE001 - evidence is written and exit code stays 0
        report = new_report(args.mode, args.timeout)
        report["error_type"] = type(exc).__name__
        report["summary"] = _summary([], 0.0)
        write_report(report, output)
    emit_notices(report)
    summary = report["summary"]
    print(
        f"feed-review.json: {output / 'feed-review.json'} · "
        + " · ".join(f"{status} {summary.get(status, 0)}" for status in STATUSES)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
