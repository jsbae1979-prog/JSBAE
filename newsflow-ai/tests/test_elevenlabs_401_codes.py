"""Bounded, allowlisted 401 diagnostics; all keys, streams and requests are synthetic."""

import io
import json
import urllib.error
import urllib.request

import pytest
import test_elevenlabs_voices as voice_tests

from newsflow.video.elevenlabs_voices import MAX_ERROR_BYTES, VoiceListError, http_error_code

catalog = voice_tests.catalog
no_real_network = voice_tests.no_real_network
KEY = voice_tests.KEY


def error_body(detail):
    return json.dumps({"detail": detail, "api_key": KEY, "headers": {"xi-api-key": KEY}}).encode()


@pytest.mark.parametrize(("body", "expected"), [
    (error_body({"code": "invalid_api_key", "message": KEY}), "invalid_api_key"),
    (error_body({"status": "invalid_api_key", "message": KEY}), "invalid_api_key"),
    (error_body({"code": "insufficient_permissions", "message": KEY}), "insufficient_permissions"),
    (error_body({"status": "missing_permissions", "message": KEY}), "missing_permissions"),
    (error_body({"code": "missing_api_key"}), "missing_api_key"),
    (error_body({"code": "quota_exceeded"}), "quota_exceeded"),
    (error_body({"code": "insufficient_permissions", "status": "invalid_api_key"}), "insufficient_permissions"),
    (error_body({"code": KEY, "status": "invalid_api_key"}), "unrecognized"),
    (error_body({"code": "NEW_VENDOR_CODE", "message": KEY}), "unrecognized"),
    (error_body({"code": ["invalid_api_key", KEY]}), "unrecognized"),
    (error_body({"code": {"secret": KEY}}), "unrecognized"),
    (error_body({"code": None, "status": "invalid_api_key"}), "unavailable"),
    (error_body({"message": "invalid_api_key " + KEY}), "unavailable"),
    (error_body(KEY), "unavailable"),
    (error_body([{"code": "invalid_api_key"}]), "unavailable"),
    (b"<html>401 " + KEY.encode() + b"</html>", "unavailable"),
    (b"{bad-json", "unavailable"),
    (b"\xff\xfeinvalid", "unavailable"),
    (b"", "unavailable"),
    (b"[[]]", "unavailable"),
    (error_body({"code": "invalid_api_key"}) + b" " * MAX_ERROR_BYTES, "unavailable"),
], ids=["modern-key", "legacy-key", "modern-permission", "legacy-permission", "missing-key", "quota",
        "modern-wins", "secret-code-no-legacy-fallback", "unknown", "list-code", "object-code",
        "null-code", "do-not-parse-message", "string-detail", "list-detail", "html", "invalid-json",
        "invalid-encoding", "empty", "array-root", "oversize"])
def test_only_known_codes_can_leave_error_parser(body, expected, catalog, monkeypatch):
    calls, limits, streams = [], [], []

    class ErrorStream(io.BytesIO):
        def read(self, size=-1):
            limits.append(size)
            return super().read(size)

    def fake_open(*args, **kwargs):
        calls.append(1)
        stream = ErrorStream(body)
        streams.append(stream)
        raise urllib.error.HTTPError("https://api.elevenlabs.io?secret=" + KEY, 401, KEY,
                                     {"Authorization": KEY}, stream)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", fake_open)
    key_bytes = catalog.keys.path.read_bytes()
    with pytest.raises(VoiceListError) as exc:
        catalog.load()
    assert calls == [1] and limits == [MAX_ERROR_BYTES + 1] and streams[0].closed
    assert exc.value.http_status == 401 and exc.value.provider_error_code == expected
    assert expected in str(exc.value) and KEY not in str(exc.value)
    assert "secret=" not in str(exc.value)
    catalog.record_failure(exc.value)
    record = json.loads(next((catalog.root / "diagnostics").glob("*.json")).read_text())
    assert record["provider_error_code"] == expected and record["provider_http_status"] == 401
    assert KEY not in json.dumps(record) and "message" not in record and "headers" not in record
    assert catalog.keys.path.read_bytes() == key_bytes and not (catalog.root / "voices.json").exists()


def test_error_read_failure_preserves_http_status_closes_stream_and_never_exposes_exception():
    class FailedStream(io.BytesIO):
        def read(self, size=-1):
            raise TimeoutError(KEY)

    stream = FailedStream()
    error = urllib.error.HTTPError("https://api.elevenlabs.io", 401, KEY, {}, stream)
    code = http_error_code(error)
    assert code == "unavailable" and stream.closed
    failure = VoiceListError("http", 401, code)
    assert "HTTP 401" in str(failure) and KEY not in str(failure)


def test_error_constructor_rejects_unrecognized_direct_code(catalog):
    failure = VoiceListError("http", 401, KEY)
    assert failure.provider_error_code == "unrecognized" and KEY not in str(failure)
    catalog.record_failure(failure)
    assert KEY not in next((catalog.root / "diagnostics").glob("*.json")).read_text()
