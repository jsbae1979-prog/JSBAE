"""Fixed-host SerpApi Google News adapter; bounded GET, no redirects/retries or article fetches."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import ClassVar

from newsflow.intelligence.credentials import AIKeyStore
from newsflow.intelligence.provider import NoRedirect

from .collector import CollectedArticle, plain
from .dedup import canonical_url
from .rss_adapter import MAX_BYTES, FeedError, validate_url
from .thumbnails import thumbnail_url

SOURCE_URL = "https://serpapi.com/google-news-api"
ENDPOINT = "https://serpapi.com/search.json"


class SerpApiKeys(AIKeyStore):
    FILE = "serpapi-key.dpapi"
    ENV = "NEWSFLOW_SERPAPI_KEY"
    ENTROPY = b"NewsFlowAI:serpapi-google-news-key"


class SerpApiError(Exception):
    MESSAGES: ClassVar[dict[str, str]] = {
        "key_missing": "SerpApi 키를 등록해 주세요.",
        "auth_failed": "SerpApi 키 인증에 실패했습니다.",
        "usage_limited": "SerpApi 요청 한도·크레딧을 확인해 주세요.",
        "timeout_unknown": "SerpApi 요청 시간이 초과되어 결과를 확인하지 못했습니다. 자동 재요청하지 않습니다.",
        "network_unknown": "SerpApi 응답을 확인하지 못했습니다. 자동 재요청하지 않습니다.",
        "bad_response": "SerpApi 결과 형식·출처를 확인하지 못했습니다. 자동 재요청하지 않습니다.",
        "empty": "SerpApi에 뉴스 결과가 없습니다.",
        "http_failed": "SerpApi 요청에 실패했습니다. 자동 재요청하지 않습니다.",
        "trends_unavailable": "급상승 자료를 확인하지 못해 유료 뉴스 조회를 시작하지 않았습니다.",
    }

    def __init__(self, code: str):
        self.code = code if code in self.MESSAGES else "bad_response"
        super().__init__(self.MESSAGES[self.code])


def parse_result(document: dict, *, region: str = "kr", language: str = "ko") -> tuple[list[CollectedArticle], dict]:
    """Only explicit ISO dates and publisher links; absent summaries/dates stay unknown."""
    if not isinstance(document, dict):
        raise SerpApiError("bad_response")
    if "error" in document:
        message = document["error"]
        message = message.lower() if isinstance(message, str) else ""
        if "invalid api key" in message:
            raise SerpApiError("auth_failed")
        if any(s in message for s in ("run out of searches", "search limit", "rate limit")):
            raise SerpApiError("usage_limited")
        raise SerpApiError("bad_response")
    metadata = document.get("search_metadata", {})
    if not isinstance(metadata, dict) or metadata.get("status") != "Success":
        raise SerpApiError("bad_response")
    entries = document.get("news_results")
    if not isinstance(entries, list) or len(entries) > 200:
        raise SerpApiError("bad_response")
    articles, seen, visited = [], set(), 0

    def walk(rows: list, depth: int = 0):
        nonlocal visited
        if depth > 4:
            raise SerpApiError("bad_response")
        for row in rows:
            visited += 1
            if visited > 400 or not isinstance(row, dict):
                raise SerpApiError("bad_response")
            if row.get("link"):
                try:
                    if not isinstance(row["link"], str) or not isinstance(row.get("title"), str):
                        raise TypeError
                    url = validate_url(row["link"])
                    publisher = row.get("source", {}).get("name", "출처 미확인")
                    title = plain(row["title"], 500)
                    summary = row.get("snippet", row.get("summary", ""))
                    if not title or not isinstance(publisher, str) or not isinstance(summary, str):
                        raise ValueError
                    published = None
                    value = row.get("iso_date")
                    if isinstance(value, str):
                        try:
                            date = datetime.fromisoformat(value)
                            if date.tzinfo is not None:
                                published = date.astimezone(UTC)
                        except ValueError:
                            pass
                    canonical = canonical_url(url)
                    if canonical not in seen:
                        articles.append(CollectedArticle(title, url, plain(publisher, 200) or "출처 미확인",
                                                         plain(summary, 2000), published,
                                                         thumbnail_url(row.get("thumbnail")) or
                                                         thumbnail_url(row.get("thumbnail_small"))))
                        seen.add(canonical)
                except (FeedError, ValueError, TypeError, AttributeError):
                    raise SerpApiError("bad_response") from None
            if "highlight" in row:
                walk([row["highlight"]], depth + 1)
            if "stories" in row:
                if not isinstance(row["stories"], list):
                    raise SerpApiError("bad_response")
                walk(row["stories"], depth + 1)

    walk(entries)
    if not articles:
        raise SerpApiError("empty")
    # Never keep provider response URLs: those can contain keys or arbitrary destinations.
    return articles, {"engine": "google_news", "language": language, "region": region.upper(),
                      "response_status": "Success", "local_request_attempts": 1,
                      "provider_billed_credits": None, "summary_missing": sum(not a.summary for a in articles)}


class SerpApiAdapter:
    def __init__(self, keys: SerpApiKeys):
        self.keys = keys

    def _open(self, request, timeout):
        deadline = time.monotonic() + timeout
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            body = bytearray()
            while len(body) <= MAX_BYTES:
                if time.monotonic() > deadline:
                    raise TimeoutError
                chunk = response.read(min(65536, MAX_BYTES + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise SerpApiError("bad_response")
        return bytes(body)

    def search(self, timeout: int = 20, *, region: str = "kr", language: str = "ko", query: str | None = None):
        if (region, language) not in {("kr", "ko"), ("us", "en"), ("uk", "en"), ("jp", "ja"), ("br", "pt")}:
            raise SerpApiError("bad_response")
        if query is not None and (not isinstance(query, str) or not 1 <= len(query) <= 600):
            raise SerpApiError("bad_response")
        try:
            key = self.keys.key()
            if not key:
                raise SerpApiError("key_missing")
            key = self.keys.validate(key)
            params = {"engine": "google_news", "hl": language, "gl": region,
                      "api_key": key, "output": "json", "no_cache": "false"}
            if query:
                params["q"] = query
            request = urllib.request.Request(ENDPOINT + "?" + urllib.parse.urlencode(params),
                                             headers={"Accept": "application/json", "Accept-Encoding": "identity"})
            raw = self._open(request, max(1, min(60, timeout)))
            if len(raw) > MAX_BYTES or key.encode() in raw:
                raise SerpApiError("bad_response")
            return parse_result(json.loads(raw), region=region, language=language)
        except SerpApiError:
            raise
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise SerpApiError("auth_failed" if code in {401, 403} else "usage_limited" if code in {402, 429}
                               else "http_failed") from None
        except TimeoutError:
            raise SerpApiError("timeout_unknown") from None
        except urllib.error.URLError as exc:
            raise SerpApiError("timeout_unknown" if isinstance(exc.reason, TimeoutError) else "network_unknown") from None
        except Exception:  # noqa: BLE001 - credentials/URLs/provider bodies never reach callers
            raise SerpApiError("bad_response") from None
