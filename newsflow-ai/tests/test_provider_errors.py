"""OpenAI adapter failure classification, bounded retry, usage capture and zero-token check."""

from __future__ import annotations

import io
import json
import urllib.error
from email.message import Message
from unittest.mock import patch

import pytest

from newsflow.intelligence.provider import (
    OpenAIProvider,
    Options,
    ProviderAuthError,
    ProviderError,
    ProviderKeyMissing,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

SCRIPT = {
    "title": "제목", "hook": "도입", "summary": "요약", "closing": "마무리",
    "scenes": [{"seconds": 30, "narration": "내용", "caption": "자막", "material": "카드"}],
}


class Response(io.BytesIO):
    def __init__(self, payload: dict) -> None:
        super().__init__(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://api.openai.com/v1/chat/completions", code, "err", headers, io.BytesIO(b"SECRET-BODY"))


def opener(outcomes):
    calls = []

    class Opener:
        def open(self, request, timeout=None):
            calls.append((request, timeout))
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    return Opener(), calls


@pytest.fixture
def provider():
    return OpenAIProvider(lambda: "sk-synthetic-not-real-key-1234567890")


def test_missing_key_never_sends():
    empty = OpenAIProvider(lambda: "")
    with patch("urllib.request.build_opener", side_effect=AssertionError("must not send")), pytest.raises(ProviderKeyMissing):
        empty.complete({"articles": []}, 30, Options())


def test_success_records_usage_and_sends_key_only_in_header(provider):
    body = {"choices": [{"message": {"content": json.dumps(SCRIPT, ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200}}
    fake, calls = opener([Response(body)])
    with patch("urllib.request.build_opener", return_value=fake), patch("time.sleep") as sleep:
        result = provider.complete({"articles": [{"title": "t", "summary": "s"}]}, 30, Options(timeout=7))
    assert result["title"] == "제목" and provider.last_usage == {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200}
    request, timeout = calls[0]
    assert request.get_header("Authorization") == "Bearer sk-synthetic-not-real-key-1234567890"
    assert b"sk-synthetic" not in request.data and timeout == 7 and not provider.last_retried
    assert not sleep.called


@pytest.mark.parametrize("code,error", [(401, ProviderAuthError), (403, ProviderAuthError), (404, ProviderResponseError), (400, ProviderResponseError)])
def test_http_status_classification_without_body_text(provider, code, error):
    fake, calls = opener([http_error(code)])
    with patch("urllib.request.build_opener", return_value=fake), pytest.raises(error) as failure:
        provider.analyze({"articles": []}, Options())
    assert "SECRET" not in str(failure.value) and len(calls) == 1


def test_rate_limit_retries_once_with_short_retry_after(provider):
    body = {"choices": [{"message": {"content": json.dumps(SCRIPT, ensure_ascii=False)}}], "usage": {"total_tokens": 5}}
    fake, calls = opener([http_error(429, "2"), Response(body)])
    with patch("urllib.request.build_opener", return_value=fake), patch("time.sleep") as sleep:
        assert provider.complete({"articles": []}, 30, Options())["title"] == "제목"
    assert len(calls) == 2 and provider.last_retried and sleep.call_args.args == (2.0,)
    fake, calls = opener([http_error(429, "120")])
    with patch("urllib.request.build_opener", return_value=fake), pytest.raises(ProviderRateLimitError):
        provider.complete({"articles": []}, 30, Options())
    assert len(calls) == 1


def test_server_error_retries_once_then_fails(provider):
    fake, calls = opener([http_error(503), http_error(502)])
    with patch("urllib.request.build_opener", return_value=fake), patch("time.sleep"), pytest.raises(ProviderUnavailableError):
        provider.complete({"articles": []}, 30, Options())
    assert len(calls) == 2


def test_timeout_is_never_retried(provider):
    fake, calls = opener([TimeoutError(), Response({})])
    with patch("urllib.request.build_opener", return_value=fake), pytest.raises(ProviderTimeoutError):
        provider.complete({"articles": []}, 30, Options())
    assert len(calls) == 1
    fake, calls = opener([urllib.error.URLError(TimeoutError("timed out"))])
    with patch("urllib.request.build_opener", return_value=fake), pytest.raises(ProviderTimeoutError):
        provider.complete({"articles": []}, 30, Options())


@pytest.mark.parametrize("payload", [{"choices": []}, {"choices": [{"message": {"content": "not json"}}]}, {"choices": [{"message": {"content": "[1,2]"}}]}])
def test_invalid_response_shape(provider, payload):
    fake, _ = opener([Response(payload)])
    with patch("urllib.request.build_opener", return_value=fake), pytest.raises(ProviderResponseError):
        provider.complete({"articles": []}, 30, Options())


def test_check_connection_uses_models_endpoint_without_tokens(provider):
    fake, calls = opener([Response({"id": "gpt-4o-mini", "object": "model"})])
    with patch("urllib.request.build_opener", return_value=fake):
        result = provider.check_connection(Options(timeout=40))
    assert result["ok"] and result["tokens"] == 0 and result["model"] == "gpt-4o-mini"
    request, timeout = calls[0]
    assert request.full_url.endswith("/v1/models/gpt-4o-mini") and request.data is None and timeout == 15
    fake, _ = opener([Response({"id": "other-model"})])
    with patch("urllib.request.build_opener", return_value=fake), pytest.raises(ProviderResponseError):
        provider.check_connection(Options())
    fake, calls = opener([http_error(429, "1")])
    with patch("urllib.request.build_opener", return_value=fake), patch("time.sleep") as sleep, pytest.raises(ProviderError):
        provider.check_connection(Options())
    assert len(calls) == 1 and not sleep.called  # a connection check never retries


def test_prompt_declares_evidence_untrusted_and_requires_korean_structure():
    from newsflow.intelligence.provider import SCRIPT_INSTRUCTION

    for phrase in ("untrusted", "never follow instructions", "closing", "do not invent", "sum exactly"):
        assert phrase in SCRIPT_INSTRUCTION


def test_truncated_answer_is_reported_as_cap_reached_not_bad_format(provider):
    body = {"choices": [{"finish_reason": "length", "message": {"content": '{"title": "잘린'}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 1400, "total_tokens": 2300}}
    fake, _ = opener([Response(body)])
    with patch("urllib.request.build_opener", return_value=fake), pytest.raises(ProviderResponseError) as failure:
        provider.complete({"articles": []}, 30, Options(max_tokens=1400))
    assert "출력 토큰 상한" in str(failure.value) and provider.last_usage["total_tokens"] == 2300
