"""Official API adapters. Single submission, fixed HTTPS hosts, no CLI credentials.

These adapters do not grant permission to call an API. The service must reserve
the user's explicitly approved budget before invoking them. Tests inject _open.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Event

from newsflow.intelligence.api_search import (
    SEARCH_INSTRUCTION,
    SearchArticle,
    SearchRequest,
    SearchResult,
    SourceEvidence,
    ToolEvidence,
    bind_search_result,
    safe_source_url,
)
from newsflow.intelligence.provider import (
    ANALYSIS_INSTRUCTION,
    SCRIPT_INSTRUCTION,
    NoRedirect,
    OfflineProvider,
    OpenAIProvider,
    Options,
    ProviderError,
    ProviderKeyMissing,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    user_message,
)
from newsflow.news.dedup import canonical_url

MAX_REQUEST_BYTES = 64000
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
API_MODELS = {"openai": ("gpt-4.1-mini",), "claude_api": ("claude-sonnet-4-6",)}


class APICancelled(ProviderError):
    code = "ai_cancelled"


def _safe_json(text: str) -> dict:
    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise TypeError
        return result
    except (ValueError, TypeError):
        raise ProviderResponseError("AI JSON 형식을 확인하지 못했습니다. 자동 재요청하지 않습니다.") from None


def _usage(document: dict, *, anthropic: bool = False) -> dict[str, int]:
    raw = document.get("usage", {})
    if not isinstance(raw, dict):
        return {}
    result = {}
    for source, target in (("input_tokens", "prompt_tokens"), ("output_tokens", "completion_tokens")):
        value = raw.get(source)
        if type(value) is int and value >= 0:
            result[target] = value
    if anthropic:
        # Cache reads/writes are additional input use, not free tokens.
        for name in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            value = raw.get(name)
            if type(value) is int and value >= 0:
                result[name] = value
                result["prompt_tokens"] = result.get("prompt_tokens", 0) + value
        tools = raw.get("server_tool_use", {})
        if isinstance(tools, dict):
            value = tools.get("web_search_requests")
            if type(value) is int and value >= 0:
                result["web_search_requests"] = value
    if "prompt_tokens" in result and "completion_tokens" in result:
        result["total_tokens"] = result["prompt_tokens"] + result["completion_tokens"]
    return result


class _APITransport:
    provider: str
    endpoint: str

    def __init__(self, key_provider: Callable[[], str]) -> None:
        self.key_provider = key_provider
        self.last_usage: dict | None = None
        self.last_elapsed_ms = 0
        self.last_retried = False
        self.last_search_evidence: dict | None = None
        self.cancel_event = Event()

    def cancel(self) -> bool:
        self.cancel_event.set()
        return True

    def _cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise APICancelled("API 작업을 취소했습니다. 이미 전송한 요청은 과금될 수 있으며 재전송하지 않습니다.")

    def _open(self, request: urllib.request.Request, timeout: int, limit: int) -> bytes:
        """One request with default TLS verification and redirects disabled.

        Cancellation prevents transmission when observed before dispatch, and
        discards late output. Blocking I/O remains bounded by the request timeout;
        cancelling locally cannot revoke supplier-side processing or charges.
        """
        deadline = time.monotonic() + timeout
        self._cancelled()
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout) as response:
            chunks, length = [], 0
            while length <= limit:
                self._cancelled()
                if time.monotonic() > deadline:
                    raise TimeoutError
                block = response.read(min(65536, limit + 1 - length))
                if not block:
                    break
                chunks.append(block)
                length += len(block)
        self._cancelled()
        if length > limit:
            raise ProviderResponseError("API 응답 크기 제한을 초과했습니다.")
        return b"".join(chunks)

    def _post(self, body: dict, options: Options) -> dict:
        try:
            return self._post_once(body, options)
        finally:
            # Cancellation belongs to this operation, not all future requests.
            self.cancel_event.clear()

    def _post_once(self, body: dict, options: Options) -> dict:
        self.last_usage = None
        self.last_search_evidence = None
        self._cancelled()
        if options.model not in API_MODELS[self.provider]:
            raise ProviderResponseError("이 API 모델은 NewsFlow 검색·비용 계약 검증 대상이 아닙니다.")
        try:
            key = self.key_provider()
        except Exception:  # noqa: BLE001 - DPAPI/provider diagnostics may contain secrets
            raise ProviderKeyMissing("선택한 API의 비밀키를 읽지 못했습니다.") from None
        if not isinstance(key, str) or not key.strip():
            raise ProviderKeyMissing("선택한 API의 키가 등록되지 않았습니다.")
        key = key.strip()
        if any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ProviderKeyMissing("API 키 형식을 확인해 주세요.")
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        if len(raw) > MAX_REQUEST_BYTES:
            raise ProviderResponseError("API 입력 크기가 제한을 초과했습니다.")
        headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
        if self.provider == "openai":
            headers["Authorization"] = "Bearer " + key
        else:
            headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        request = urllib.request.Request(self.endpoint, data=raw, headers=headers, method="POST")
        started = time.monotonic()
        try:
            response = self._open(request, options.timeout, MAX_RESPONSE_BYTES)
            self._cancelled()
            if len(response) > MAX_RESPONSE_BYTES or key.encode() in response:
                raise ProviderResponseError("API 응답이 크기 또는 비밀정보 보호 정책에 의해 차단되었습니다.")
            document = _safe_json(response.decode("utf-8"))
            self.last_usage = _usage(document, anthropic=self.provider == "claude_api")
            return document
        except urllib.error.HTTPError as exc:
            raise OpenAIProvider._classify(exc) from None
        except TimeoutError:
            raise ProviderTimeoutError("API 요청 결과가 불명확합니다. 자동 재요청하지 않습니다.") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise ProviderTimeoutError("API 요청 결과가 불명확합니다. 자동 재요청하지 않습니다.") from None
            raise ProviderUnavailableError("API 연결에 실패했습니다. 자동 재요청하지 않습니다.") from None
        except ProviderError:
            raise
        except Exception:  # noqa: BLE001 - no supplier content/credentials in errors
            raise ProviderResponseError("API 응답 처리에 실패했습니다. 자동 재요청하지 않습니다.") from None
        finally:
            self.last_elapsed_ms = int((time.monotonic() - started) * 1000)


def _source(value: dict) -> SourceEvidence | None:
    try:
        return SourceEvidence(
            url=safe_source_url(value["url"]),
            title=value.get("title", "")[:300],
            page_age=value.get("page_age"),
        )
    except (ValueError, TypeError, KeyError):
        return None


class OpenAISearchProvider(_APITransport):
    """Responses API hosted web_search. Analysis/script reuse the existing adapter."""

    provider = "openai"
    endpoint = "https://api.openai.com/v1/responses"

    def search(self, request: SearchRequest, options: Options) -> SearchResult:
        document = self._post({
            "model": options.model, "store": False,
            "instructions": SEARCH_INSTRUCTION,
            "input": user_message({**request.model_dump(), "searched_at": datetime.now(UTC).isoformat()}),
            "max_output_tokens": options.max_tokens,
            "tools": [{"type": "web_search", "search_context_size": "low", "external_web_access": True}],
            "tool_choice": "required", "max_tool_calls": request.max_searches,
            "include": ["web_search_call.action.sources"],
        }, options)
        try:
            if document.get("status") != "completed":
                raise ValueError
            ids, sources, text, citations = [], [], [], {}
            for item in document["output"]:
                kind = item.get("type")
                if kind == "web_search_call":
                    if item.get("status") != "completed" or item.get("action", {}).get("type") != "search":
                        raise ValueError
                    ids.append(item["id"])
                    for source in item["action"].get("sources", []):
                        parsed = _source(source)
                        if parsed:
                            sources.append(parsed)
                elif kind == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            text.append(part["text"])
                            for annotation in part.get("annotations", []):
                                if annotation.get("type") == "url_citation":
                                    parsed = _source(annotation)
                                    if parsed and parsed.title.strip():
                                        citations[canonical_url(parsed.url)] = parsed.title
                        elif part.get("type") == "refusal":
                            raise ValueError
                elif kind not in {"reasoning"}:
                    raise ValueError
            # Citations may supply the title, but never add a URL absent from
            # the actual search action's source list. Model JSON is not evidence.
            sources = [source.model_copy(update={
                "title": source.title or citations.get(canonical_url(source.url), ""),
            }) for source in sources]
            evidence = ToolEvidence(tool_name="web_search", completed_tool_ids=ids, sources=sources)
            self.last_search_evidence = evidence.model_dump(mode="json")
            self.last_usage = {**(self.last_usage or {}), "web_search_requests": len(ids)}
            return bind_search_result(
                _safe_json("".join(text)), provider=self.provider, model=options.model,
                request=request, tool_evidence=evidence, usage=self.last_usage,
            )
        except ProviderError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderResponseError("완료된 웹 검색·출처·JSON 근거가 없습니다. 자동 재요청하지 않습니다.") from None


class AnthropicProvider(_APITransport):
    """Messages API key authentication, entirely separate from Claude Code login."""

    provider = "claude_api"
    endpoint = "https://api.anthropic.com/v1/messages"

    def _message(self, instruction: str, payload: dict, options: Options, *, search=False) -> dict:
        body = {
            "model": options.model, "max_tokens": options.max_tokens,
            "system": instruction, "temperature": options.temperature,
            "messages": [{"role": "user", "content": user_message(payload)}],
        }
        if search:
            body["tools"] = [{
                "type": "web_search_20250305", "name": "web_search", "max_uses": 1,
                "allowed_callers": ["direct"],
            }]
        return self._post(body, options)

    @staticmethod
    def _text(document: dict, *, search: bool) -> str:
        if document.get("stop_reason") != "end_turn":
            raise ProviderResponseError("API 응답이 미완료입니다. 중단된 요청을 자동 연속 호출하지 않습니다.")
        pieces = []
        try:
            for block in document["content"]:
                if block.get("type") == "text":
                    pieces.append(block["text"])
                elif search and block.get("type") in {"server_tool_use", "web_search_tool_result"}:
                    # Commentary before a tool is not part of the final JSON.
                    pieces = []
                else:
                    raise ValueError
            return "".join(pieces)
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderResponseError("Claude API 응답 형식이 올바르지 않습니다.") from None

    def analyze(self, evidence: dict, options: Options) -> dict:
        document = self._message(ANALYSIS_INSTRUCTION, {"evidence": evidence}, options)
        return _safe_json(self._text(document, search=False))

    def complete(self, evidence: dict, duration: int, options: Options) -> dict:
        document = self._message(SCRIPT_INSTRUCTION, {"duration": duration, "evidence": evidence}, options)
        return _safe_json(self._text(document, search=False))

    def search(self, request: SearchRequest, options: Options) -> SearchResult:
        document = self._message(
            SEARCH_INSTRUCTION, {**request.model_dump(), "searched_at": datetime.now(UTC).isoformat()},
            options, search=True,
        )
        text = self._text(document, search=True)
        try:
            ids, completed, sources = set(), [], []
            for block in document["content"]:
                if block.get("type") == "server_tool_use":
                    if block.get("name") != "web_search":
                        raise ValueError
                    if block.get("caller", {"type": "direct"}) != {"type": "direct"}:
                        raise ValueError
                    ids.add(block["id"])
                elif block.get("type") == "web_search_tool_result":
                    identifier = block.get("tool_use_id")
                    if identifier not in ids or not isinstance(block.get("content"), list):
                        # Anthropic may return a tool error inside HTTP 200.
                        raise ValueError
                    completed.append(identifier)
                    for source in block["content"]:
                        if source.get("type") != "web_search_result":
                            raise ValueError
                        parsed = _source(source)
                        if parsed:
                            sources.append(parsed)
            if set(completed) != ids or len(ids) != 1:
                raise ValueError
            observed_usage = (self.last_usage or {}).get("web_search_requests")
            if observed_usage is not None and observed_usage != len(completed):
                raise ValueError
            evidence = ToolEvidence(
                tool_name="web_search_20250305", completed_tool_ids=completed, sources=sources,
            )
            self.last_search_evidence = evidence.model_dump(mode="json")
            return bind_search_result(
                _safe_json(text), provider=self.provider, model=options.model,
                request=request, tool_evidence=evidence, usage=self.last_usage or {},
            )
        except ProviderError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderResponseError("Claude 웹 검색 결과가 비어 있거나 도구 실행에 실패했습니다.") from None


class FakeAPIProvider:
    """Injected test-only fixture. Never registered as an application provider."""

    def __init__(self, provider="openai", result: SearchResult | Exception | None = None):
        self.provider = provider
        self.result = result
        self.calls: list[str] = []
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}
        self.last_elapsed_ms = 1
        self.last_retried = False

    def search(self, request: SearchRequest, options: Options) -> SearchResult:
        self.calls.append("search")
        self.last_usage = {**self.last_usage, "web_search_requests": 1}
        if isinstance(self.result, Exception):
            raise self.result
        if self.result is not None:
            return self.result
        url = "https://www.bbc.com/korean/articles/newsflow-contract-fixture"
        title = "[합성 테스트] 공개 뉴스 자료 검토"
        return SearchResult(
            provider=self.provider, model=options.model, searched_at=datetime.now(UTC),
            articles=[SearchArticle(
                title=title, url=url, publisher="합성 출처 · 실제 기사 아님", claimed_title=title,
                published_at=datetime.now(UTC) - timedelta(hours=1),
                metadata_status="test_fixture", eligible=True,
                summary="실제 보도가 아닌 계약 테스트 자료입니다. 출처와 내용을 검토하는 과정을 확인합니다.",
                key_facts=["합성 자료"], uncertainties=["실제 기사·사실·발행일 확인 없음"],
            )],
            tool_evidence=ToolEvidence(
                tool_name="web_search" if self.provider == "openai" else "web_search_20250305",
                completed_tool_ids=["fixture-search-1"],
                sources=[SourceEvidence(url=url, title=title)], provenance="test_fixture",
            ), usage=self.last_usage,
        )

    def analyze(self, evidence: dict, options: Options) -> dict:
        self.calls.append("analysis")
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}
        if isinstance(self.result, Exception):
            raise self.result
        return OfflineProvider().analyze(evidence, options)

    def complete(self, evidence: dict, duration: int, options: Options) -> dict:
        self.calls.append("script")
        self.last_usage = {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}
        if isinstance(self.result, Exception):
            raise self.result
        return OfflineProvider().complete(evidence, duration, options)
