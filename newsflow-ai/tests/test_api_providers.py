import json
import urllib.error

import pytest

from newsflow.intelligence.api_providers import (
    AnthropicProvider,
    APICancelled,
    OpenAISearchProvider,
)
from newsflow.intelligence.api_search import SearchRequest
from newsflow.intelligence.provider import (
    Options,
    ProviderAuthError,
    ProviderKeyMissing,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)

URL = "https://www.bbc.com/korean/articles/source-contract"
KEY = "unit-test-not-a-credential"


def test_explicit_search_output_limit_9000_is_supported_but_still_bounded():
    assert Options(model="claude-sonnet-4-6", max_tokens=9000).max_tokens == 9000
    assert Options(model="claude-sonnet-4-6", max_tokens=100_000).max_tokens == 100_000
    with pytest.raises(ValueError):
        Options(model="claude-sonnet-4-6", max_tokens=100_001)
    with pytest.raises(ValueError):
        Options(model="gpt-4o-mini", max_tokens=9001)


def article_payload():
    return {"articles": [{
        "title": "테스트 제목", "url": URL, "publisher": "BBC", "published_at": None,
        "summary": "실제 뉴스가 아닌 계약 응답입니다.", "key_facts": ["합성 근거"],
        "related_urls": [], "uncertainties": ["사실 검증 없음"],
    }]}


def openai_response():
    return {
        "status": "completed", "output": [
            {"type": "web_search_call", "id": "ws_1", "status": "completed",
             "action": {"type": "search", "sources": [{"url": URL, "title": "검색 제목"}]}},
            {"type": "message", "content": [{"type": "output_text", "text": json.dumps(article_payload())}]},
        ], "usage": {"input_tokens": 120, "output_tokens": 30},
    }


def anthropic_response():
    return {
        "stop_reason": "end_turn", "content": [
            {"type": "text", "text": "검색을 시작합니다."},
            {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "뉴스"}},
            {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
                {"type": "web_search_result", "url": URL, "title": "검색 제목",
                 "page_age": "2026-10-16", "encrypted_content": "DO_NOT_PERSIST_THIS"},
            ]},
            {"type": "text", "text": json.dumps(article_payload())},
        ], "usage": {"input_tokens": 100, "output_tokens": 50, "server_tool_use": {"web_search_requests": 1}},
    }


def fake_transport(monkeypatch, provider, response):
    calls = []

    def send(request, timeout, limit):
        calls.append((request, timeout, limit))
        if isinstance(response, Exception):
            raise response
        return json.dumps(response).encode()

    monkeypatch.setattr(provider, "_open", send)
    return calls


def test_openai_responses_search_has_one_bounded_tool_and_no_extra_tools(monkeypatch):
    provider = OpenAISearchProvider(lambda: KEY)
    calls = fake_transport(monkeypatch, provider, openai_response())
    result = provider.search(SearchRequest(), Options(model="gpt-4.1-mini"))
    request = calls[0][0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.openai.com/v1/responses"
    assert body["store"] is False and body["max_tool_calls"] == 1
    assert body["tool_choice"] == "required"
    assert body["include"] == ["web_search_call.action.sources"]
    assert len(body["tools"]) == 1 and body["tools"][0]["type"] == "web_search"
    assert KEY not in request.data.decode()
    assert result.usage == {"prompt_tokens": 120, "completion_tokens": 30,
                            "total_tokens": 150, "web_search_requests": 1}
    assert result.articles[0].published_at is None
    assert len(calls) == 1


def test_anthropic_uses_api_key_basic_search_without_code_execution(monkeypatch):
    provider = AnthropicProvider(lambda: KEY)
    calls = fake_transport(monkeypatch, provider, anthropic_response())
    result = provider.search(SearchRequest(), Options(model="claude-sonnet-4-6"))
    request = calls[0][0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.get_header("X-api-key") == KEY
    assert request.get_header("Anthropic-version") == "2023-06-01"
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search",
                              "max_uses": 1, "allowed_callers": ["direct"]}]
    assert "DO_NOT_PERSIST_THIS" not in result.model_dump_json()
    assert result.articles[0].published_at is None
    assert result.tool_evidence.sources[0].page_age == "2026-10-16"


@pytest.mark.parametrize("citation_url,success", [(URL, True), ("https://www.bbc.com/other", False)])
def test_openai_citation_title_only_enriches_an_already_observed_source(monkeypatch, citation_url, success):
    response = openai_response()
    response["output"][0]["action"]["sources"][0].pop("title")
    response["output"][1]["content"][0]["annotations"] = [
        {"type": "url_citation", "url": citation_url, "title": "인용 메타데이터 제목"},
    ]
    provider = OpenAISearchProvider(lambda: KEY)
    fake_transport(monkeypatch, provider, response)
    if success:
        result = provider.search(SearchRequest(), Options(model="gpt-4.1-mini"))
        assert result.articles[0].title == "인용 메타데이터 제목"
        assert not result.articles[0].full_body_verified
    else:
        with pytest.raises(ProviderResponseError):
            provider.search(SearchRequest(), Options(model="gpt-4.1-mini"))


@pytest.mark.parametrize("kind", ["empty", "no_event", "unknown_url", "incomplete", "extra_tool"])
def test_openai_requires_real_tool_result_and_complete_json(monkeypatch, kind):
    response = openai_response()
    if kind == "empty":
        response["output"][0]["action"]["sources"] = []
    elif kind == "no_event":
        response["output"].pop(0)
    elif kind == "unknown_url":
        response["output"][0]["action"]["sources"][0]["url"] = "https://www.bbc.com/not-the-article"
    elif kind == "incomplete":
        response["status"] = "incomplete"
    else:
        response["output"].append({"type": "function_call", "name": "shell"})
    provider = OpenAISearchProvider(lambda: KEY)
    calls = fake_transport(monkeypatch, provider, response)
    with pytest.raises(ProviderResponseError):
        provider.search(SearchRequest(), Options(model="gpt-4.1-mini"))
    assert len(calls) == 1 and not provider.last_retried


@pytest.mark.parametrize("kind", [
    "error_200", "pause_turn", "max_tokens", "no_search", "unpaired", "empty", "code_caller", "usage_mismatch",
])
def test_anthropic_tool_errors_and_incomplete_requests_never_continue(monkeypatch, kind):
    response = anthropic_response()
    if kind == "error_200":
        response["content"][2]["content"] = {"type": "web_search_tool_result_error", "error_code": "unavailable"}
    elif kind in {"pause_turn", "max_tokens"}:
        response["stop_reason"] = kind
    elif kind == "no_search":
        response["content"] = [response["content"][-1]]
    elif kind == "unpaired":
        response["content"][2]["tool_use_id"] = "missing"
    elif kind == "code_caller":
        response["content"][1]["caller"] = {"type": "code_execution_20260120", "tool_id": "exec"}
    elif kind == "usage_mismatch":
        response["usage"]["server_tool_use"]["web_search_requests"] = 0
    else:
        response["content"][2]["content"] = []
    provider = AnthropicProvider(lambda: KEY)
    calls = fake_transport(monkeypatch, provider, response)
    with pytest.raises(ProviderResponseError):
        provider.search(SearchRequest(), Options(model="claude-sonnet-4-6"))
    assert len(calls) == 1


@pytest.mark.parametrize("error,expected", [
    (TimeoutError("secret timeout"), ProviderTimeoutError),
    (urllib.error.HTTPError("https://api.anthropic.com", 401, "secret auth", {}, None), ProviderAuthError),
    (urllib.error.HTTPError("https://api.anthropic.com", 429, "secret limit", {"Retry-After": "1"}, None),
     ProviderRateLimitError),
])
def test_network_errors_are_sanitized_and_never_retried(monkeypatch, error, expected):
    provider = AnthropicProvider(lambda: KEY)
    calls = fake_transport(monkeypatch, provider, error)
    with pytest.raises(expected) as caught:
        provider.analyze({}, Options(model="claude-sonnet-4-6"))
    assert "secret" not in str(caught.value)
    assert len(calls) == 1 and provider.last_retried is False


def test_missing_key_unsupported_model_and_oversized_input_never_send(monkeypatch):
    provider = AnthropicProvider(lambda: "")
    calls = fake_transport(monkeypatch, provider, {})
    with pytest.raises(ProviderKeyMissing):
        provider.analyze({}, Options(model="claude-sonnet-4-6"))
    provider.key_provider = lambda: KEY
    with pytest.raises(ProviderResponseError):
        provider.analyze({}, Options(model="not-reviewed-model"))
    with pytest.raises(ProviderResponseError):
        provider.analyze({"text": "가" * 64000}, Options(model="claude-sonnet-4-6"))
    assert calls == []


def test_cancellation_before_and_after_send_never_accepts_late_result(monkeypatch):
    provider = AnthropicProvider(lambda: KEY)
    calls = fake_transport(monkeypatch, provider, anthropic_response())
    provider.cancel()
    with pytest.raises(APICancelled):
        provider.search(SearchRequest(), Options(model="claude-sonnet-4-6"))
    assert calls == []
    # A completed cancellation does not disable this adapter for all future jobs.
    provider.search(SearchRequest(), Options(model="claude-sonnet-4-6"))
    assert len(calls) == 1
    provider = AnthropicProvider(lambda: KEY)

    def cancel_during_response(*args):
        provider.cancel()
        return json.dumps(anthropic_response()).encode()

    monkeypatch.setattr(provider, "_open", cancel_during_response)
    with pytest.raises(APICancelled):
        provider.search(SearchRequest(), Options(model="claude-sonnet-4-6"))


def test_secret_echo_and_invalid_json_are_not_exposed(monkeypatch):
    provider = AnthropicProvider(lambda: KEY)
    fake_transport(monkeypatch, provider, {"secret": KEY})
    with pytest.raises(ProviderResponseError) as caught:
        provider.analyze({}, Options(model="claude-sonnet-4-6"))
    assert KEY not in str(caught.value)


def test_anthropic_analysis_and_script_use_existing_instructions_without_tools(monkeypatch):
    provider = AnthropicProvider(lambda: KEY)
    response = {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"ok": true}'}],
                "usage": {"input_tokens": 10, "output_tokens": 20}}
    calls = fake_transport(monkeypatch, provider, response)
    assert provider.analyze({"articles": []}, Options(model="claude-sonnet-4-6")) == {"ok": True}
    assert provider.complete({"articles": []}, 45, Options(model="claude-sonnet-4-6")) == {"ok": True}
    bodies = [json.loads(call[0].data) for call in calls]
    assert all("tools" not in body for body in bodies)
    assert json.loads(bodies[1]["messages"][0]["content"])["duration"] == 45
    assert provider.last_usage["total_tokens"] == 30
