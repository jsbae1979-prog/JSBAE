"""Read public vendor documentation only; never authenticate or call a publishing API."""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

HOSTS = {"developers.google.com", "support.google.com", "developers.facebook.com", "about.fb.com"}
MAX_BODY = 2 * 1024 * 1024
PAGE_TIMEOUT = 10.0
MAX_EXCERPTS = 6000
KEYWORDS = (
    "youtube.upload",
    "containssyntheticmedia",
    "is_ai_generated",
    "video_url",
    "instagram_business_content_publish",
    "instagram_business_basic",
    "instagram_content_publish",
    "instagram_basic",
    "quota",
    "unverified",
    "audit",
    "shorts",
    "three-minute",
    "3 minutes",
    "square",
    "vertical",
    "professional",
    "business account",
    "creator",
    "facebook page",
    "reels",
    "resumable",
    "publicly",
    "accessible",
    "duration",
    "mp4",
    "h.264",
    "aac",
    "frames",
    "fps",
    "maximum",
    "minimum",
    "caption",
    "hashtag",
    "oauth",
    "scope",
    "redirect",
    "refresh token",
    "pkce",
    "synthetic",
    "altered",
    "disclose",
    "ai-generated",
    "ai info",
    "label",
    "manipulated",
)
EXPECTED = {
    "yt_upload": ("videos.insert", "upload", "quota"),
    "yt_resource": ("snippet", "videostatus", "containssyntheticmedia"),
    "yt_oauth": ("oauth", "installed", "redirect"),
    "yt_shorts": ("shorts", "three-minute", "vertical"),
    "yt_encoding": ("mp4", "h.264", "aac"),
    "yt_ai": ("altered", "synthetic", "disclose"),
    "yt_quota": ("quota", "upload", "video"),
    "ig_login": ("instagram login", "professional", "instagram_business"),
    "ig_publish": ("content publishing", "reels", "video_url"),
    "ig_fb": ("content publishing", "reels", "video_url"),
    "ig_reels": ("content publishing", "reels", "video_url"),
    "meta_ai": ("ai-generated", "label", "manipulated"),
}


class PolicyError(Exception):
    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(kind)


def allowed_url(value: str) -> str:
    """Only fixed official documentation hosts/paths; never disclose rejected input."""
    try:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in HOSTS
            or parsed.username
            or parsed.password
            or parsed.fragment
            or parsed.port not in (None, 443)
            or "\\" in value
            or any(ord(char) < 32 for char in value)
        ):
            raise PolicyError("documentation_url_policy")
        prefix = {
            "developers.google.com": "/youtube/",
            "support.google.com": "/youtube/answer/",
            "developers.facebook.com": "/docs/",
            "about.fb.com": "/news/",
        }[parsed.hostname]
        if not parsed.path.startswith(prefix):
            raise PolicyError("documentation_path_policy")
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        if any(key != "hl" or val not in {"en", "en-US", "ko"} for key, val in query):
            raise PolicyError("documentation_query_policy")
    except (ValueError, TypeError) as exc:
        raise PolicyError("documentation_url_policy") from exc
    return value


class DocRedirect(urllib.request.HTTPRedirectHandler):
    """Close redirect bodies and revalidate destination without reading unlimited HTML."""

    def __init__(self, deadline: float) -> None:
        self.deadline, self.count = deadline, 0

    def http_error_302(self, req, fp, code, msg, headers):
        fp.close()
        self.count += 1
        if self.count > 4:
            raise PolicyError("redirect_limit")
        target = urllib.parse.urljoin(req.full_url, headers.get("Location", ""))
        try:
            allowed_url(target)
        except PolicyError as exc:
            raise PolicyError("redirect_not_allowed") from exc
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        request = urllib.request.Request(target, headers=doc_headers(), method="GET")
        return self.parent.open(request, timeout=remaining)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


class DocText(HTMLParser):
    """Keep visible document text and omit scripts, navigation and forms."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip, self.main, self.in_title = 0, 0, False
        self.parts: list[str] = []
        self.main_parts: list[str] = []
        self.title: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "nav", "footer", "form", "noscript"}:
            self.skip += 1
        if tag in {"main", "article"}:
            self.main += 1
        if tag == "title":
            self.in_title = True
        if tag in {"p", "li", "div", "h1", "h2", "h3", "tr", "pre", "br"}:
            self.handle_data("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "nav", "footer", "form", "noscript"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"main", "article"}:
            self.main = max(0, self.main - 1)
        if tag == "title":
            self.in_title = False
        if tag in {"p", "li", "div", "h1", "h2", "h3", "tr", "pre"}:
            self.handle_data("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title.append(data)
        if not self.skip:
            self.parts.append(data)
            if self.main:
                self.main_parts.append(data)


def doc_headers() -> dict[str, str]:
    return {
        "User-Agent": "NewsFlowAI-Phase4A-OfficialDocumentationResearch/1.0",
        "Accept": "text/html",
        "Accept-Encoding": "identity",
    }


def safe_failure(exc: BaseException) -> str:
    if isinstance(exc, PolicyError):
        return exc.kind
    if isinstance(exc, urllib.error.HTTPError):
        return "http_error"
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLError):
        return "tls_validation"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(reason, socket.gaierror):
        return "dns"
    # Only classify the message; never copy provider URLs, proxy credentials or bodies.
    if "Tunnel connection failed" in str(reason):
        return "proxy_connect_denied"
    return "network_or_document_error"


def research_page(item: dict) -> dict:
    result = {
        "key": str(item.get("key", "unknown"))[:80],
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "transport": "NOT VERIFIED",
        "content": "NOT VERIFIED",
        "policy_verification": "NOT VERIFIED; captured excerpts require human review",
        "status_code": None,
        "title": "",
        "excerpts": [],
    }
    deadline = time.monotonic() + PAGE_TIMEOUT
    try:
        url = allowed_url(item["url"])
        result["url"] = url
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()), DocRedirect(deadline)
        )
        request = urllib.request.Request(url, headers=doc_headers(), method="GET")
        with opener.open(request, timeout=PAGE_TIMEOUT) as response:
            result["status_code"] = response.status
            result["final_url"] = allowed_url(response.url)
            if response.status != 200:
                raise PolicyError("unexpected_http_status")
            if response.headers.get_content_type() not in {"text/html", "application/xhtml+xml"}:
                raise PolicyError("not_html_document")
            chunks: list[bytes] = []
            size = 0
            while True:
                if response.fp is None:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                # Apply the remaining wall-clock budget to each SSL body read.
                response.fp.raw._sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_BODY + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BODY:
                    raise PolicyError("document_too_large")
            charset = response.headers.get_content_charset() or "utf-8"
        raw = b"".join(chunks)
        parser = DocText()
        parser.feed(raw.decode(charset, errors="replace"))
        result["transport"] = "PASS; HTTPS 200 with default certificate validation"
        result["title"] = " ".join("".join(parser.title).split())[:250]
        text = "".join(parser.main_parts or parser.parts)
        lines = [" ".join(line.split()) for line in text.splitlines()]
        normalized = " ".join(lines).casefold()
        expected = EXPECTED.get(result["key"], ())
        matches = [word for word in expected if word in normalized]
        result["matched_document_cues"] = matches
        result["visible_document_characters"] = len(text)
        title_lower = result["title"].casefold()
        if (
            len(text.strip()) < 500
            or len(matches) < 2
            or any(word in title_lower for word in ("log in", "login", "access denied", "error", "captcha"))
        ):
            result["failure_kind"] = "document_content_not_available_or_unconfirmed"
            return result
        excerpts: list[str] = []
        for index, line in enumerate(lines):
            if line and any(word in line.casefold() for word in KEYWORDS):
                excerpt = " ".join(lines[max(0, index - 1) : index + 3])[:900]
                excerpt = excerpt[: MAX_EXCERPTS - sum(map(len, excerpts))]
                if excerpt and excerpt not in excerpts:
                    excerpts.append(excerpt)
                if sum(map(len, excerpts)) >= MAX_EXCERPTS:
                    break
        result["excerpts"] = excerpts
        result["content"] = "PASS; document cues and bounded visible excerpts captured"
        result["excerpt_method"] = "Visible text with whitespace normalized; no factual interpretation"
        return result
    except (PolicyError, OSError, ValueError, LookupError) as exc:
        result["failure_kind"] = safe_failure(exc)
        if isinstance(exc, urllib.error.HTTPError):
            result["status_code"] = exc.code
            exc.close()
        return result


def notice(result: dict) -> None:
    budget = 1000
    while True:
        payload = {**result, "pages": []}
        for page in result["pages"]:
            shortened = dict(page)
            shortened["excerpts"] = [" ".join(page["excerpts"])[:budget]] if page["excerpts"] else []
            payload["pages"].append(shortened)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        encoded = encoded.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        if len(encoded.encode("utf-8")) < 45000 or budget <= 100:
            break
        budget //= 2
    print("::notice title=NewsFlow official docs::" + encoded)
    for page in result["pages"]:
        encoded_page = json.dumps(page, ensure_ascii=False, separators=(",", ":"))
        encoded_page = encoded_page.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        if len(encoded_page.encode("utf-8")) >= 45000:
            raise PolicyError("page_annotation_size_limit")
        safe_key = "".join(char for char in page["key"] if char.isalnum() or char in "_-")[:80] or "unknown"
        print("::notice title=NewsFlow official docs: " + safe_key + "::" + encoded_page)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    project = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--sources",
        type=Path,
        default=project / "docs/reports/phase4a_evidence/publishing_official_sources.json",
    )
    parser.add_argument("--output", type=Path, default=Path("validation-output/official-web-research.json"))
    args = parser.parse_args()
    source = json.loads(args.sources.read_text(encoding="utf-8"))
    pages = source["official_web_pages"]
    if not isinstance(pages, list) or not 1 <= len(pages) <= 12:
        raise SystemExit("Official documentation input must contain 1-12 public source pages.")
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(research_page, pages))
    result = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "run": "COMPLETED; page verification is reported separately",
        "scope": "Public official documentation GET requests only; no credentials, cookies or login",
        "sns_login_calls": 0,
        "sns_publish_calls": 0,
        "network_settings_changed": False,
        "tls_validation": "Default verified HTTPS context; no bypass",
        "maximum_page_bytes": MAX_BODY,
        "page_deadline_seconds": PAGE_TIMEOUT,
        "workers": 4,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "pages": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    notice(result)


if __name__ == "__main__":
    main()
