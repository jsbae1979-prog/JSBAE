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

    REASONS: ClassVar[dict[str, str]] = {
        "document": "응답 객체 형식", "provider_error": "공급사 오류 응답",
        "response_status": "공급사 완료 상태", "news_results": "기사 목록 형식",
        "structure_limit": "기사 목록 크기·깊이", "no_valid_articles": "유효한 기사 항목 없음",
        "response_size": "응답 크기", "credential_echo": "응답 보안 검사",
        "json_decode": "JSON 응답 형식", "request_config": "요청 설정",
        "transport": "응답 수신", "storage": "기사 저장", "unknown": "상세 미확인",
    }

    def __init__(self, code: str, *, reason: str = "unknown"):
        self.code = code if code in self.MESSAGES else "bad_response"
        self.reason = reason if reason in self.REASONS else "unknown"
        detail = " 확인 필요" if self.reason != "unknown" else ""
        super().__init__(self.MESSAGES[self.code] +
                         (" (" + self.REASONS[self.reason] + detail + ")" if detail else ""))

    def diagnostics(self):
        # Fixed enums only: never supplier prose, article URLs, headers or keys.
        return {"reason": self.reason}


def parse_result(document: dict, *, region: str = "kr", language: str = "ko") -> tuple[list[CollectedArticle], dict]:
    """Parse independent articles; reject unsafe items without discarding valid siblings.

    Public contract: https://serpapi.com/google-news-api (news_results/highlight/stories).
    Absent optional values stay unknown; no article fetch or new search is made.
    """
    if not isinstance(document, dict):
        raise SerpApiError("bad_response", reason="document")
    if "error" in document:
        message = document["error"]
        message = message.lower() if isinstance(message, str) else ""
        if "invalid api key" in message:
            raise SerpApiError("auth_failed")
        if any(s in message for s in ("run out of searches", "search limit", "rate limit")):
            raise SerpApiError("usage_limited")
        raise SerpApiError("bad_response", reason="provider_error")
    metadata = document.get("search_metadata", {})
    if not isinstance(metadata, dict) or metadata.get("status") != "Success":
        raise SerpApiError("bad_response", reason="response_status")
    entries = document.get("news_results")
    if not isinstance(entries, list):
        raise SerpApiError("bad_response", reason="news_results")
    if len(entries) > 200:
        raise SerpApiError("bad_response", reason="structure_limit")
    articles, seen, visited, skipped = [], set(), 0, {}

    def reject(reason):
        skipped[reason] = skipped.get(reason, 0) + 1

    def walk(rows: list, depth: int = 0):
        nonlocal visited
        if depth > 4:
            raise SerpApiError("bad_response", reason="structure_limit")
        for row in rows:
            visited += 1
            if visited > 400:
                raise SerpApiError("bad_response", reason="structure_limit")
            if not isinstance(row, dict):
                reject("item_shape")
                continue
            if row.get("link"):
                try:
                    if not isinstance(row["link"], str) or not isinstance(row.get("title"), str):
                        raise TypeError
                    # An article anchor is not a different source. Validate its
                    # public URL with the unchanged URL policy after removing only the anchor.
                    link = row["link"].split("#", 1)[0]
                    url = validate_url(link)
                    source = row.get("source")
                    if source is not None and not isinstance(source, dict):
                        raise TypeError
                    publisher = (source or {}).get("name") or (source or {}).get("title") or "출처 미확인"
                    title = plain(row["title"], 500)
                    summary = row.get("snippet")
                    if summary is None: summary = row.get("summary")
                    if summary is None: summary = ""
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
                except FeedError:
                    reject("article_url")
                except (ValueError, TypeError, AttributeError):
                    reject("article_fields")
            elif not row.get("highlight") and not row.get("stories"):
                reject("missing_article")
            highlight = row.get("highlight")
            if highlight is not None:
                walk([highlight], depth + 1)
            stories = row.get("stories")
            if stories is not None:
                if isinstance(stories, list): walk(stories, depth + 1)
                else: reject("stories_shape")

    walk(entries)
    if not articles:
        raise SerpApiError("bad_response", reason="no_valid_articles") if skipped else SerpApiError("empty")
    return articles, {"engine": "google_news", "language": language, "region": region.upper(),
                      "response_status": "Success", "local_request_attempts": 1,
                      "provider_billed_credits": None, "summary_missing": sum(not a.summary for a in articles),
                      "skipped_items": sum(skipped.values()), "skip_reasons": skipped}


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
            raise SerpApiError("bad_response", reason="response_size")
        return bytes(body)

    def search(self, timeout: int = 20, *, region: str = "kr", language: str = "ko", query: str | None = None):
        if (region, language) not in {("kr", "ko"), ("us", "en"), ("uk", "en"), ("jp", "ja"), ("br", "pt")}:
            raise SerpApiError("bad_response", reason="request_config")
        if query is not None and (not isinstance(query, str) or not 1 <= len(query) <= 600):
            raise SerpApiError("bad_response", reason="request_config")
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
            if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
                raise SerpApiError("bad_response", reason="response_size")
            if key.encode() in raw:
                raise SerpApiError("bad_response", reason="credential_echo")
            try:
                document = json.loads(raw)
            except (ValueError, UnicodeError):
                raise SerpApiError("bad_response", reason="json_decode") from None
            return parse_result(document, region=region, language=language)
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
            raise SerpApiError("bad_response", reason="transport") from None
