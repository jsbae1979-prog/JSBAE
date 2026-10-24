"""Fake HTTP only; encrypted error detail survives without leaking to ordinary records."""
import io
import json
from urllib.error import HTTPError

import pytest
from test_api_settings import sessions as sessions  # noqa: PLC0414
from test_api_settings import store as store  # noqa: PLC0414
from test_claude_analysis_response import analyze, latest
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414

from newsflow.intelligence.credentials import AnthropicKeyStore, FakeCipher
from newsflow.intelligence.error_diagnostics import ErrorDiagnosticStore
from newsflow.intelligence.provider import AnalysisResponseError
from newsflow.intelligence.service import IntelligenceError, IntelligenceService


def test_unclassified_rejection_survives_only_encrypted_and_bound_to_run(state, tmp_path, monkeypatch):
    secret = state["store"].key()
    message = "Unclassified diagnostic marker with private source excerpt " + secret
    recorder = ErrorDiagnosticStore(tmp_path, FakeCipher())
    state["adapter"].error_recorder = recorder
    calls = []

    def reject(request, *_args):
        calls.append(1)
        body = {"error": {"type": "invalid_request_error", "message": message},
                "private_extra": "MUST_NOT_STORE", "request": {"secret": secret}}
        raise HTTPError(request.full_url, 400, "unsafe status " + secret, {}, io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr(state["adapter"], "_open", reject)
    with pytest.raises(IntelligenceError) as caught:
        analyze(state)
    run, reservation = latest(state)
    diagnostic = run.result["analysis_failure"]
    reference = diagnostic["diagnostic_ref"]
    assert diagnostic["http_status"] == 400 and diagnostic["error_type"] == "invalid_request_error"
    for ordinary in (json.dumps(run.result), run.message, str(caught.value)):
        assert secret not in ordinary and "Unclassified diagnostic marker" not in ordinary
    stored = recorder.read(reference)
    assert stored["message"] == message.replace(secret, "[REDACTED]")
    assert "MUST_NOT_STORE" not in json.dumps(stored) and secret not in json.dumps(stored)
    encrypted = (recorder.root / (reference + ".dpapi")).read_bytes()
    assert secret.encode() not in encrypted and b"Unclassified diagnostic marker" not in encrypted
    assert reservation.status == "unknown" and reservation.estimated_usd is None
    assert calls == [1] and not state["adapter"].last_retried


def test_encrypt_failure_never_writes_plaintext_or_changes_original_error(state, tmp_path, monkeypatch):
    recorder = ErrorDiagnosticStore(tmp_path, FakeCipher(fail=True))
    state["adapter"].error_recorder = recorder
    calls = []

    def reject(request, *_args):
        calls.append(1)
        body = {"error": {"type": "invalid_request_error", "message": "PRIVATE_ERROR_MARKER"}}
        raise HTTPError(request.full_url, 400, "", {}, io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr(state["adapter"], "_open", reject)
    with pytest.raises(IntelligenceError):
        analyze(state)
    run, _ = latest(state)
    assert run.result == {"analysis_failure": {
        "failure_reason": "request_rejected", "http_status": 400, "error_type": "invalid_request_error"}}
    assert calls == [1] and not recorder.root.exists()


def test_unique_files_preserve_previous_failure_and_reject_path_traversal(tmp_path):
    recorder = ErrorDiagnosticStore(tmp_path, FakeCipher())
    kwargs = {"status": 400, "error_type": [], "message": "sk-ant-private-other-key", "secret": ""}
    first, second = recorder.save(**kwargs), recorder.save(**kwargs)
    assert first != second
    assert len(list(recorder.root.glob("*.dpapi"))) == 2
    assert recorder.read(first)["message"] == "[REDACTED]"
    with pytest.raises(ValueError):
        recorder.read("../key")
    with pytest.raises(ValueError):
        recorder.save(**{**kwargs, "message": "가" * 3000})


def test_service_uses_credential_directory_without_loading_key_or_making_request(tmp_path):
    class Store(AnthropicKeyStore):
        def key(self):
            pytest.fail("No key read during construction")
    service = IntelligenceService(None, api_key_stores={"claude_api": Store(tmp_path)})
    provider = service._provider("claude_api")
    assert provider.error_recorder.root == tmp_path / "diagnostics" / "claude-http"
    assert not provider.error_recorder.root.exists()


def test_reference_is_revalidated_on_safe_copy():
    error = AnalysisResponseError("request_rejected", diagnostic_ref="a" * 32)
    assert error.diagnostics()["diagnostic_ref"] == "a" * 32
    error.http_details["diagnostic_ref"] = "../private-key"
    assert "diagnostic_ref" not in error.diagnostics()


def test_windows_dpapi_roundtrip_uses_only_synthetic_error_in_test_directory(tmp_path):
    recorder = ErrorDiagnosticStore(tmp_path)
    reference = recorder.save(status=400, error_type="invalid_request_error",
                              message="SYNTHETIC_PRIVATE_ERROR", secret="SYNTHETIC_PRIVATE")
    assert recorder.read(reference)["message"] == "[REDACTED]_ERROR"
    raw = (recorder.root / (reference + ".dpapi")).read_bytes()
    assert b"ERROR" not in raw and b"SYNTHETIC_PRIVATE" not in raw
