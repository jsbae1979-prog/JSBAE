"""Offline contract tests for tools/ci_feed_review.py (Phase 5C.1 public feed review).

No test here touches the network: the adapter and the DNS preflight are injected, and the
subprocess run points the preflight at ``localhost`` which the public-address policy rejects.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from newsflow.news.rss_adapter import (
    ErrorKind,
    FakeRSSAdapter,
    FeedError,
    PublicRSSAdapter,
    Response,
    validate_url,
)

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "ci_feed_review.py"
FEED = "https://example.com/rss"
ROBOTS = "https://example.com/robots.txt"


@pytest.fixture(scope="module")
def tool():
    spec = importlib.util.spec_from_file_location("ci_feed_review", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Transport:
    """Fake transport for PublicRSSAdapter, same shape as tests/test_collector.py."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def candidate(identifier: str, url: str = FEED, **overrides) -> dict:
    base = {
        "id": identifier, "name": f"후보 {identifier}", "url": url, "language": "ko", "country": "KR",
        "format_expected": "rss2", "official_rss_page": "unknown", "terms_note": "", "confidence": "high",
        "enabled": True, "expectation": "PASS", "role": "",
    }
    base.update(overrides)
    return base


def review(tool, tmp_path, candidates, adapter, **kwargs):
    options = {"mode": "cloud", "max_seconds": 60, "timeout": 5, "dns_check": lambda: "OK", "pause": 0}
    options.update(kwargs)
    return tool.run_review(candidates, tmp_path / "out", adapter=adapter, **options)


# --------------------------------------------------------------------------- candidates


def test_candidates_file_is_consistent(tool):
    candidates = tool.load_candidates(tool.DEFAULT_CANDIDATES)
    assert tool.validate_candidates(candidates) == []
    assert candidates and len({c["id"] for c in candidates}) == len(candidates)
    assert sum(1 for c in candidates if c["enabled"]) <= 18
    for item in candidates:
        assert validate_url(item["url"]) == item["url"]
        assert item["role"] in tool.VALID_ROLES and item["expectation"] in tool.VALID_EXPECTATIONS
        assert item["confidence"] in tool.VALID_CONFIDENCE and item["format_expected"] in tool.VALID_FORMATS
        assert item["name"] and isinstance(item["official_rss_page"], str)
        host = item["url"].split("/")[2]
        assert "reuters" not in host and "apnews" not in host
    by_id = {c["id"]: c for c in candidates}
    default = by_id["google-news-kr-top"]
    assert default["role"] == "app_default" and default["confidence"] == "high"
    main_source = (ROOT / "src/newsflow/main.py").read_text(encoding="utf-8")
    assert default["url"] in main_source  # the app's seeded default source, deduplicated by URL
    assert by_id["bbc-news"]["expectation"] == "BLOCKED_robots"
    assert by_id["hn-front"]["expectation"] == "BLOCKED_crawl_delay" and by_id["hn-front"]["role"] == "control"
    assert by_id["dw-en-rdf"]["format_expected"] == "rdf"


def test_validate_and_select_candidates(tool):
    bad = [candidate("a", role="owner"), candidate("a", url="http://127.0.0.1/rss", expectation="MAYBE")]
    problems = tool.validate_candidates(bad)
    assert any("duplicate id" in p for p in problems) and any("url rejected" in p for p in problems)
    assert any("role" in p for p in problems) and any("expectation" in p for p in problems)
    assert tool.validate_candidates([candidate(str(i)) for i in range(19)]) == ["more than 18 enabled candidates"]
    items = [candidate("x", enabled=False), candidate("y")]
    assert tool.select_candidates(items, None) is items
    selected = tool.select_candidates(items, "x, nope")
    assert [c["id"] for c in selected] == ["x"] and selected[0]["enabled"] is True


# --------------------------------------------------------------------------- classification


@pytest.mark.parametrize("kind", list(ErrorKind))
def test_every_error_kind_is_blocked_or_not_verified(tool, kind):
    status = tool.classify(
        attempted=True, check_status="fail", kind=str(kind), feed_error=True, first_status=None, second_status=None
    )
    expected = "BLOCKED" if kind in {ErrorKind.ROBOTS, ErrorKind.POLICY} else "NOT VERIFIED"
    assert status == expected


def test_classification_table(tool):
    classify = tool.classify
    base = {"attempted": True, "check_status": "fail", "kind": None, "feed_error": False, "first_status": None,
            "second_status": None}
    assert classify(**{**base, "kind": "empty"}) == "NOT VERIFIED"
    assert classify(**{**base, "kind": "network", "error_type": "RuntimeError"}) == "FAIL"
    assert classify(**{**base, "kind": "network"}) == "FAIL"  # non-FeedError exception → app defect
    assert classify(**{**base, "attempted": False}) == "NOT VERIFIED"  # budget / preflight / disabled
    passed = {**base, "check_status": "pass"}
    assert classify(**{**passed, "first_status": "success", "second_status": "success"}) == "PASS"
    assert classify(**{**passed, "first_status": "success", "second_status": None}) == "NOT VERIFIED"
    assert classify(**{**passed, "first_status": "failed", "second_status": None}) == "FAIL"
    assert classify(**{**passed, "first_status": "success", "second_status": "interrupted"}) == "FAIL"
    assert classify(**{**passed, "first_status": "success", "second_status": "success", "count_mismatch": True}) == "FAIL"
    assert classify(**{**passed, "first_status": "success", "second_status": "success", "error_type": "TimeoutError"}) == "FAIL"


def test_expectation_comparison(tool):
    met = tool.expectation_met
    assert met("PASS", "PASS", None, "") is True and met("PASS", "BLOCKED", "robots", "") is False
    assert met("PASS", "FAIL", "network", "") is False and met("PASS", "NOT VERIFIED", "timeout", "") is None
    assert met("BLOCKED_robots", "BLOCKED", "robots", "robots.txt 정책") is True
    assert met("BLOCKED_robots", "BLOCKED", "policy", "") is False
    assert met("BLOCKED_crawl_delay", "BLOCKED", "robots", "crawl-delay가 지정된 출처") is True
    assert met("BLOCKED_crawl_delay", "BLOCKED", "robots", "robots.txt 정책") is False
    assert met("unknown", "PASS", None, "") is None and met("weird", "PASS", None, "") is None


# --------------------------------------------------------------------------- robots explanation


def test_robots_allow_all_and_disallow(tool, tmp_path):
    allow = Transport({ROBOTS: Response(200, b"User-agent: *\nAllow: /\n")})
    info = tool.explain_robots(FEED, 5, allow, tmp_path / "robots")
    assert (info["status"], info["decision"], info["decision_reason"]) == (200, "allow", None)
    assert info["applicable_group"] == ["*"] and info["first_matching_rule"] == "Allow: /"
    assert info["user_agent_token"] == "newsflowai" and info["can_fetch"] is True
    assert info["bytes"] == 23 and len(info["sha256"]) == 64 and info["redirects"] == 0
    assert info["saved"] == "robots/example.com.txt" and (tmp_path / "robots/example.com.txt").is_file()
    assert allow.calls == [(ROBOTS, 5)]
    deny = Transport({ROBOTS: Response(200, b"User-agent: *\nDisallow: /\n")})
    info = tool.explain_robots(FEED, 5, deny)
    assert (info["decision"], info["decision_reason"], info["first_matching_rule"]) == ("deny", "disallowed", "Disallow: /")
    assert info["can_fetch"] is False


def test_robots_first_match_and_substring_user_agent(tool):
    body = b"User-agent: news\nDisallow: /rss\n\nUser-agent: *\nAllow: /\n"
    info = tool.explain_robots(FEED, 5, Transport({ROBOTS: Response(200, body)}))
    # Python 3.12 substring semantics: "news" is contained in the token "newsflowai".
    assert info["applicable_group"] == ["news"] and info["first_matching_rule"] == "Disallow: /rss"
    assert info["decision"] == "deny"
    body = b"User-agent: *\nAllow: /rss\nDisallow: /\n"
    info = tool.explain_robots(FEED, 5, Transport({ROBOTS: Response(200, body)}))
    assert info["first_matching_rule"] == "Allow: /rss" and info["decision"] == "allow"
    body = b"User-agent: otherbot\nDisallow: /\n"
    info = tool.explain_robots(FEED, 5, Transport({ROBOTS: Response(200, body)}))
    assert info["applicable_group"] == [] and info["first_matching_rule"] is None and info["decision"] == "allow"


def test_robots_crawl_delay_and_request_rate_are_rejected(tool):
    delayed = Transport({ROBOTS: Response(200, b"User-agent: *\nCrawl-delay: 30\nAllow: /\n")})
    info = tool.explain_robots(FEED, 5, delayed)
    assert info["can_fetch"] is True and info["crawl_delay"] == 30
    assert (info["decision"], info["decision_reason"]) == ("deny", "crawl_delay")
    rated = Transport({ROBOTS: Response(200, b"User-agent: *\nRequest-rate: 1/10\n")})
    info = tool.explain_robots(FEED, 5, rated)
    assert info["request_rate"] == {"requests": 1, "seconds": 10}
    assert (info["decision"], info["decision_reason"]) == ("deny", "request_rate")
    with pytest.raises(FeedError, match="crawl-delay"):  # the adapter itself agrees
        PublicRSSAdapter(delayed).fetch(FEED, 5)


def test_robots_404_synthetic_allow_and_403_fail_closed(tool, tmp_path):
    missing = Transport({ROBOTS: Response(404, b"")})
    info = tool.explain_robots(FEED, 5, missing, tmp_path / "robots")
    assert info["status"] == 404 and info["decision"] == "allow" and info["synthetic"]
    assert info["applicable_group"] == ["*"] and info["first_matching_rule"] == "Allow: /"
    assert info["saved"] is None and not (tmp_path / "robots").exists()
    forbidden = Transport({ROBOTS: Response(403, b"")})
    info = tool.explain_robots(FEED, 5, forbidden)
    assert info["status"] == 403 and (info["decision"], info["decision_reason"]) == ("deny", "robots_unavailable")
    assert info["applicable_group"] is None and info["can_fetch"] is None
    with pytest.raises(FeedError) as caught:
        PublicRSSAdapter(forbidden).fetch(FEED, 5)
    assert caught.value.kind == ErrorKind.ROBOTS


def test_robots_redirects(tool):
    moved = Transport({
        ROBOTS: Response(301, b"", "/txt/robots.txt"),
        "https://example.com/txt/robots.txt": Response(200, b"User-agent: *\nAllow: /\n"),
    })
    info = tool.explain_robots(FEED, 5, moved)
    assert info["redirects"] == 1 and info["robots_url"] == "https://example.com/txt/robots.txt"
    assert info["decision"] == "allow" and len(moved.calls) == 2
    headless = Transport({ROBOTS: Response(302, b"", None)})
    info = tool.explain_robots(FEED, 5, headless)
    assert info["status"] is None and info["decision_reason"] == "redirect_without_location"
    loop = Transport({ROBOTS: Response(301, b"", ROBOTS)})
    info = tool.explain_robots(FEED, 5, loop)
    assert info["decision_reason"] == "redirect_limit" and len(loop.calls) == 4
    private = Transport({ROBOTS: Response(301, b"", "http://127.0.0.1/robots.txt")})
    with pytest.raises(FeedError):  # every hop stays behind validate_url
        tool.explain_robots(FEED, 5, private)


# --------------------------------------------------------------------------- review runs


def test_two_pass_dedup_through_python_api(tool, tmp_path, rss, monkeypatch):
    for name in ("HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    fake = FakeRSSAdapter({FEED: rss})
    report = review(tool, tmp_path, [candidate("ok"), candidate("off", "https://off.example/rss", enabled=False)], fake)
    assert fake.calls == [FEED, FEED, FEED]  # check, first collection, second collection
    ok, off = report["feeds"]
    assert (ok["status"], ok["reason"], ok["attempted"], ok["expectation_met"]) == ("PASS", None, True, True)
    assert ok["check"]["status"] == "pass" and ok["check"]["article_count"] == 3
    assert (ok["check"]["dated_count"], ok["check"]["summarized_count"]) == (2, 0)
    assert "기사 3개" in ok["check"]["message"] and ok["check"]["elapsed_ms"] >= 0
    first, second = ok["collection"]["first"], ok["collection"]["second"]
    assert (first["status"], first["added"], first["duplicates"]) == ("success", 3, 0)
    assert (second["status"], second["added"], second["duplicates"]) == ("success", 0, 3)
    assert first["audit_event"] == "source_success" and second["audit_message"] == "신규 0, 중복 3"
    assert second["run_id"] > first["run_id"]
    collection = ok["collection"]
    assert (collection["articles_stored"], collection["mentions"], collection["title_merges"]) == (3, 3, 0)
    assert collection["dated_ratio"] == "2/3" and collection["link_domains"] == {"example.com": 3}
    assert collection["earliest_published"] == "2026-10-13T07:30:00+00:00"
    assert collection["latest_published"] == "2026-10-13T08:00:00+00:00"
    assert "테스트언론 A" in collection["publishers"] and sum(collection["categories"].values()) == 3
    assert len(ok["samples"]) == 3 and all(set(s) == {"title", "publisher", "published_at", "link_domain"} for s in ok["samples"])
    assert all(len(s["title"]) <= 80 and s["link_domain"] == "example.com" for s in ok["samples"])
    assert ok["samples"][2]["published_at"] is None  # undated stays undated
    assert ok["robots"] is None and ok["parse_diagnostic"] is None and ok["error_type"] is None
    assert (off["status"], off["reason"], off["attempted"]) == ("NOT VERIFIED", "not_enabled", False)
    summary = report["summary"]
    assert (summary["feeds"], summary["attempted"], summary["PASS"], summary["NOT VERIFIED"]) == (2, 1, 1, 1)
    assert summary["BLOCKED"] == 0 and summary["FAIL"] == 0 and summary["expectation_unmet"] == []
    written = json.loads((tmp_path / "out" / "feed-review.json").read_text(encoding="utf-8"))
    assert set(written) >= {
        "tool", "mode", "platform", "python", "feedparser", "started_at", "adapter", "user_agent",
        "request_timeout", "network", "terms_confirmed_by_human", "article_bodies_fetched", "summary", "feeds",
    }
    assert written["tool"] == "ci_feed_review" and written["mode"] == "cloud" and written["request_timeout"] == 5
    assert written["network"] == {"dns_preflight": "OK", "https_proxy_present": False, "proxy_used_by_transport": False}
    assert written["terms_confirmed_by_human"] is False and written["article_bodies_fetched"] is False
    assert written["user_agent"].startswith("NewsFlowAI/") and "policy unchanged" in written["adapter"]
    text = json.dumps(written, ensure_ascii=False)
    assert "summary\"" not in text.replace('"summary": {', "") and "우주 기술 발사 현장을 공개했습니다" not in text


def test_blocked_feeds_and_expectations(tool, tmp_path):
    robots = FeedError("robots.txt 정책에서 이 RSS 경로를 허용하지 않습니다.", ErrorKind.ROBOTS)
    fake = FakeRSSAdapter({
        FEED: robots, "https://surprise.example/rss": robots,
        "https://policy.example/rss": FeedError("사설", ErrorKind.POLICY),
    })
    report = review(tool, tmp_path, [
        candidate("expected", expectation="BLOCKED_robots"),
        candidate("surprise", "https://surprise.example/rss", expectation="PASS"),
        candidate("policy", "https://policy.example/rss", expectation="unknown"),
    ], fake)
    expected, surprise, policy = report["feeds"]
    assert expected["status"] == "BLOCKED" and expected["reason"] == "robots" and expected["expectation_met"] is True
    assert expected["check"]["kind"] == "robots" and expected["check"]["feed_error"] is True
    assert expected["robots"] == {"skipped": "adapter_without_transport"}
    assert surprise["status"] == "BLOCKED" and surprise["expectation_met"] is False
    assert policy["status"] == "BLOCKED" and policy["expectation_met"] is None
    assert expected["collection"] is None and expected["samples"] == []
    assert report["summary"]["BLOCKED"] == 3 and report["summary"]["by_kind"] == {"policy": 1, "robots": 2}
    assert report["summary"]["expectation_unmet"] == ["surprise"]


def test_blocked_with_real_adapter_explains_robots(tool, tmp_path, rss):
    transport = Transport({
        ROBOTS: Response(200, b"User-agent: *\nCrawl-delay: 10\nAllow: /\n"),
        FEED: Response(200, rss),
    })
    report = review(tool, tmp_path, [candidate("hn", expectation="BLOCKED_crawl_delay")], PublicRSSAdapter(transport))
    feed = report["feeds"][0]
    assert feed["status"] == "BLOCKED" and "crawl-delay" in feed["check"]["message"] and feed["expectation_met"] is True
    assert feed["robots"]["decision"] == "deny" and feed["robots"]["decision_reason"] == "crawl_delay"
    assert feed["robots"]["crawl_delay"] == 10 and feed["robots"]["saved"] == "robots/example.com.txt"
    assert (tmp_path / "out" / "robots" / "example.com.txt").read_bytes().startswith(b"User-agent")
    assert all(url == ROBOTS for url, _ in transport.calls)  # the feed itself was never requested


def test_not_verified_fail_and_parse_diagnostic(tool, tmp_path, rss):
    empty = rss.split(b"<item>")[0] + b"</channel></rss>"
    fake = FakeRSSAdapter({
        FEED: FeedError("RSS 요청 시간이 초과되었습니다.", ErrorKind.TIMEOUT),
        "https://boom.example/rss": RuntimeError("SECRET-RAW"),
        "https://empty.example/rss": empty,
        "https://html.example/rss": b"<!DOCTYPE html><html><body>not rss SECRET-BODY</body></html>",
    })
    report = review(tool, tmp_path, [
        candidate("slow"), candidate("boom", "https://boom.example/rss"),
        candidate("empty", "https://empty.example/rss"), candidate("html", "https://html.example/rss"),
    ], fake)
    slow, boom, empty_feed, html = report["feeds"]
    assert (slow["status"], slow["reason"], slow["expectation_met"]) == ("NOT VERIFIED", "timeout", None)
    assert (boom["status"], boom["reason"], boom["error_type"]) == ("FAIL", "RuntimeError", "RuntimeError")
    assert boom["check"]["kind"] == "network" and boom["check"]["message"] == tool.RAW_FAILURE_MESSAGE
    assert boom["expectation_met"] is False
    assert (empty_feed["status"], empty_feed["check"]["kind"]) == ("NOT VERIFIED", "empty")
    assert html["status"] == "NOT VERIFIED" and html["check"]["kind"] == "parse"
    assert html["parse_diagnostic"]["root_tag"] == "html" and html["parse_diagnostic"]["bytes"] > 0
    assert set(html["parse_diagnostic"]) >= {"bozo_exception", "declared_encoding", "root_tag", "bytes"}
    text = (tmp_path / "out" / "feed-review.json").read_text(encoding="utf-8")
    assert "SECRET" not in text
    assert report["summary"]["FAIL"] == 1 and report["summary"]["NOT VERIFIED"] == 3
    assert report["summary"]["by_kind"] == {"empty": 1, "network": 1, "parse": 1, "timeout": 1}


def test_preflight_failure_and_budget_never_touch_the_adapter(tool, tmp_path, rss):
    fake = FakeRSSAdapter({FEED: rss})
    candidates = [candidate("ok"), candidate("off", "https://off.example/rss", enabled=False)]
    report = review(tool, tmp_path, candidates, fake, dns_check=lambda: "FAIL(dns)")
    assert fake.calls == [] and report["network"]["dns_preflight"] == "FAIL(dns)"
    ok, off = report["feeds"]
    assert (ok["status"], ok["reason"], ok["attempted"], ok["expectation_met"]) == ("NOT VERIFIED", "network_preflight", False, None)
    assert (off["status"], off["reason"]) == ("NOT VERIFIED", "not_enabled")
    assert report["summary"]["by_reason"] == {"network_preflight": 1, "not_enabled": 1}
    report = review(tool, tmp_path, [candidate("ok")], fake, max_seconds=0)
    assert fake.calls == [] and report["feeds"][0]["reason"] == "budget"
    assert report["feeds"][0]["status"] == "NOT VERIFIED" and report["feeds"][0]["attempted"] is False


def test_duplicate_urls_share_one_source(tool, tmp_path, rss):
    fake = FakeRSSAdapter({FEED: rss})
    report = review(tool, tmp_path, [candidate("first"), candidate("again")], fake)
    first, again = report["feeds"]
    assert first["status"] == "PASS" and (again["reason"], again["attempted"]) == ("duplicate_url", False)


# --------------------------------------------------------------------------- notices and CLI


def test_notice_format_and_chunking(tool, capsys):
    tool.notice("FeedReview", {"ko": "한국어\n줄", "pct": "100%"})
    line = capsys.readouterr().out.strip()
    assert line.startswith("::notice title=FeedReview::") and "\n" not in line
    assert "\\n" in line and "%25" in line and "한국어" in line  # JSON escapes the newline, % is encoded
    assert tool.encode_notice("a\r\nb") == '"a\\r\\nb"' and tool.encode_notice({"p": "5%"}) == '{"p":"5%25"}'
    tool.notice("FeedReview big", {"blob": "x" * 5000})
    line = capsys.readouterr().out.strip()
    assert line == '::notice title=FeedReview big::{"truncated":true,"title":"FeedReview big"}'
    items = [{"id": f"feed-{i:03d}", "msg": "x" * 150} for i in range(200)]
    chunks = tool.chunk_items(items)
    assert sum(len(chunk) for chunk in chunks) == 200 and len(chunks) > 1
    assert all(len(tool.encode_notice(chunk).encode()) <= 4000 for chunk in chunks)
    assert tool.chunk_items([]) == []


def test_notices_stay_within_limits(tool, tmp_path, rss, capsys):
    feeds = {f"https://host{i}.example/rss": (rss if i % 3 else FeedError("robots", ErrorKind.ROBOTS)) for i in range(40)}
    fake = FakeRSSAdapter(feeds)
    candidates = [candidate(f"feed-{i:02d}", url) for i, url in enumerate(feeds)]
    report = review(tool, tmp_path, candidates, fake)
    capsys.readouterr()
    tool.emit_notices(report)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("::notice ")]
    assert 1 <= len(lines) <= 10 and lines[0].startswith("::notice title=FeedReview::")
    titles = []
    for line in lines:
        title, payload = line[len("::notice title="):].split("::", 1)
        assert title.startswith("FeedReview") and len(payload.encode()) <= 4000
        json.loads(payload.replace("%0A", "\n").replace("%0D", "\r").replace("%25", "%"))
        titles.append(title)
    assert report["summary"]["PASS"] == 26 and report["summary"]["BLOCKED"] == 14
    assert any(t.startswith("FeedReview PASS") for t in titles)
    assert any(t.startswith("FeedReview BLOCKED") for t in titles)
    assert any(t.startswith("FeedReview robots") for t in titles)


def test_cli_exit_zero_without_network(tool, tmp_path):
    out = tmp_path / "cloud"
    command = [sys.executable, str(TOOL), "--mode", "cloud", "--output", str(out), "--max-seconds", "5",
               "--preflight-host", "localhost", "--only", "google-news-kr-top,github-blog"]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert completed.returncode == 0, completed.stderr
    assert "::notice title=FeedReview::" in completed.stdout
    report = json.loads((out / "feed-review.json").read_text(encoding="utf-8"))
    assert report["network"]["dns_preflight"].startswith("FAIL(") and report["summary"]["attempted"] == 0
    assert [f["id"] for f in report["feeds"]] == ["google-news-kr-top", "github-blog"]
    assert all(f["status"] == "NOT VERIFIED" and f["reason"] == "network_preflight" for f in report["feeds"])
    assert report["mode"] == "cloud" and report["article_bodies_fetched"] is False
    assert tool.main(["--mode", "windows", "--output", str(tmp_path / "w"), "--candidates", str(tmp_path / "missing.json")]) == 0
    broken = json.loads((tmp_path / "w" / "feed-review.json").read_text(encoding="utf-8"))
    assert broken["error_type"] == "FileNotFoundError" and broken["summary"]["feeds"] == 0
