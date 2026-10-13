"""Opt-in real RSS storage validation. No policy changes or proxy/TLS bypass."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from sqlalchemy import func, select

from .db.models import AuditLog, CollectionRun, NewsArticle, NewsSource
from .db.session import make_engine, migrate, session_factory
from .news.collector import Collector
from .news.rss_adapter import FeedError, PublicRSSAdapter, public_addresses, validate_url
from .news.service import NewsService


def diagnose(url: str, timeout: int = 10) -> dict:
    url = validate_url(url)
    host = urlsplit(url).hostname or ""
    result: dict = {"dns": "NOT VERIFIED", "proxy": "NOT CONFIGURED", "rss_store": "NOT VERIFIED"}
    try:
        public_addresses(host, 443, timeout)
        result["dns"] = "PASS"
    except FeedError:
        result["dns"] = "FAIL"
    # Probe only when DNS is unavailable, using an existing HTTPS proxy, and never parse/store
    # the proxy response as verified RSS. This diagnoses egress, not an SSRF fallback.
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        result["proxy"] = "PRESENT (not used by pinned transport)"
    if proxy and result["dns"] == "FAIL" and host in {"news.google.com", "feeds.bbci.co.uk"}:
        try:
            opener = build_opener(ProxyHandler({"https": proxy}), HTTPSHandler())
            request = Request(f"https://{host}/robots.txt", method="HEAD")
            # Reject redirects: the diagnostic must not probe arbitrary destinations.
            from urllib.request import HTTPRedirectHandler

            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, *args, **kwargs):
                    return None

            opener.add_handler(NoRedirect())
            with opener.open(request, timeout=timeout) as response:
                result["proxy"] = f"HTTP {response.status} (diagnostic only)"
        except HTTPError as exc:
            result["proxy"] = f"HTTP {exc.code} (diagnostic only)"
        except URLError as exc:
            result["proxy"] = (
                "FAIL: CONNECT/HTTPS blocked" if "403" in str(exc.reason) else "FAIL: proxy/HTTPS connection"
            )
        except OSError:
            result["proxy"] = "FAIL: proxy connection"
    try:
        payload = PublicRSSAdapter().fetch(url, timeout)

        class VerifiedSnapshot:
            def fetch(self, url: str, timeout: int) -> bytes:
                return payload

        # Reuse the actual verified bytes for parsing/storage; do not request a feed twice.
        collector = Collector(VerifiedSnapshot())
        collector.collect(url, "Live validation", timeout)
        with tempfile.TemporaryDirectory(prefix="newsflow-rss-") as directory:
            engine = make_engine(Path(directory) / "validation.db")
            try:
                migrate(engine)
                sessions = session_factory(engine)
                with sessions.begin() as session:
                    session.add(NewsSource(name="Live validation", url=url))
                    run = CollectionRun()
                    session.add(run)
                    session.flush()
                    run_id = run.id
                NewsService(sessions, collector).collect(run_id)
                with sessions() as session:
                    run = session.get(CollectionRun, run_id)
                    count = session.scalar(select(func.count()).select_from(NewsArticle))
                    result["rss_store"] = "PASS" if run.status == "success" and count > 0 else "NOT VERIFIED"
                    result["article_count"] = count
                    result["collection_status"] = run.status
                    result["error_count"] = session.scalar(
                        select(func.count()).select_from(AuditLog).where(AuditLog.level == "error")
                    )
            finally:
                engine.dispose()
    except FeedError as exc:
        result["failure_stage"] = exc.kind.value
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="명시적 실제 RSS/저장 진단 (사용자 DB 미변경)")
    parser.add_argument("--url", required=True)
    parser.add_argument("--timeout", type=int, choices=range(1, 31), default=10)
    args = parser.parse_args()
    try:
        result = diagnose(args.url, args.timeout)
    except Exception:  # noqa: BLE001 -- never expose supplied secret URL or raw exceptions
        result = {"rss_store": "NOT VERIFIED", "failure_stage": "validation_or_environment"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["rss_store"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
