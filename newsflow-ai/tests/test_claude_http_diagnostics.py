"""Rejected Fake HTTP requests retain safe classifications, never remote text."""
import io
import json
from urllib.error import HTTPError

import pytest
from test_api_settings import reserve
from test_api_settings import sessions as sessions  # noqa: PLC0414
from test_api_settings import store as store  # noqa: PLC0414
from test_claude_analysis_response import analyze, latest
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414

from newsflow.intelligence.api_settings import APISettingsError
from newsflow.intelligence.provider import (
    AnalysisResponseError,
    Options,
    ProviderAuthError,
    ProviderHTTPResponseError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from newsflow.intelligence.service import IntelligenceError

SECRET = "SECRET_KEY_AND_REMOTE_BODY_MUST_NOT_PERSIST"


@pytest.mark.parametrize("body,extra", [
    ({"error": {"type": "invalid_request_error", "message": "Schema is too complex for compilation. " + SECRET}},
     {"error_type": "invalid_request_error", "request_issue": "schema_complexity", "request_fields": ["schema"]}),
    ({"error": {"type": "invalid_request_error",
               "message": "Compiled grammar is too large. Simplify your schema. " + SECRET}},
     {"error_type": "invalid_request_error", "request_issue": "schema_complexity", "request_fields": ["schema"]}),
    ({"error": {"type": "invalid_request_error", "message": "Invalid JSON schema: " + SECRET}},
     {"error_type": "invalid_request_error", "request_issue": "schema_invalid", "request_fields": ["schema"]}),
    ({"error": {"type": "invalid_request_error",
               "message": "output_config.format.schema: enum or $ref unsupported. " + SECRET}},
     {"error_type": "invalid_request_error", "request_fields": ["$ref", "enum", "output_config", "schema"]}),
    ({"error": {"type": "invalid_request_error", "message": "some_model_value=" + SECRET}},
     {"error_type": "invalid_request_error"}),
    ({"error": {"type": "invalid_request_error",
               "message": "Your credit balance is too low to access the Anthropic API. " + SECRET}},
     {"error_type": "invalid_request_error", "request_issue": "credit_balance_low"}),
    ({"error": {"type": "invalid_request_error",
               "message": "Invalid input quoting 'Your credit balance is too low'. " + SECRET}},
     {"error_type": "invalid_request_error"}),
    ({"error": {"type": "invalid_request_error", "message": SECRET}},
     {"error_type": "invalid_request_error"}),
    ({"error": {"type": SECRET, "message": SECRET}}, {}),
    ({"error": [SECRET]}, {}),
    ([SECRET], {}),
    ("not-json-" + SECRET, {}),
    ("x" * 9000, {}),
])
def test_rejected_request_is_stored_safely_once_and_unknown_usage_is_preserved(state, monkeypatch, body, extra):
    raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    requests = []

    def reject(request, timeout, limit):
        requests.append(request)
        raise HTTPError(request.full_url, 400, SECRET, {}, io.BytesIO(raw))

    monkeypatch.setattr(state["adapter"], "_open", reject)
    with pytest.raises(IntelligenceError) as caught:
        analyze(state)
    run, reservation = latest(state)
    assert caught.value.code == "ai_bad_response"
    assert run.result == {"analysis_failure": {
        "failure_reason": "request_rejected", "http_status": 400, **extra}}
    assert reservation.status == "unknown" and reservation.estimated_usd is None
    assert SECRET not in json.dumps(run.result) + run.message + str(caught.value)
    if extra.get("request_issue") == "credit_balance_low":
        assert "크레딧 부족" in run.message and "Billing" in run.message
    else:
        assert "크레딧 부족" not in run.message
    assert len(requests) == 1 and not state["adapter"].last_retried
    with pytest.raises(APISettingsError):
        reserve(state["budget"], state["store"], f"intelligence:{run.id}")
    assert len(requests) == 1


@pytest.mark.parametrize("status,error_type", [
    (401, ProviderAuthError), (403, ProviderAuthError),
    (429, ProviderRateLimitError), (500, ProviderUnavailableError),
])
def test_auth_rate_and_server_classification_remains_unchanged(state, monkeypatch, status, error_type):
    calls = []

    def reject(request, *_args):
        calls.append(1)
        raise HTTPError(request.full_url, status, SECRET, {}, io.BytesIO(SECRET.encode()))

    monkeypatch.setattr(state["adapter"], "_open", reject)
    with pytest.raises(error_type) as caught:
        state["adapter"].analyze({"articles": []}, Options("claude-sonnet-4-6", timeout=300))
    assert len(calls) == 1 and SECRET not in str(caught.value)


def test_diagnostics_sanitize_mutated_attributes():
    failure = AnalysisResponseError("request_rejected", http_status=400, error_type="invalid_request_error")
    failure.http_details.update(http_status=True, error_type=SECRET, request_issue={"key": SECRET}, raw=SECRET)
    failure.http_details["request_fields"] = [SECRET, {"key": SECRET}, 42]
    failure.args = (SECRET,)
    assert failure.diagnostics() == {"failure_reason": "request_rejected"}
    assert SECRET not in str(failure.safe_copy())
    http_failure = ProviderHTTPResponseError(400, "invalid_request_error")
    http_failure.details["raw"] = SECRET
    assert http_failure.diagnostics() == {"http_status": 400, "error_type": "invalid_request_error"}
