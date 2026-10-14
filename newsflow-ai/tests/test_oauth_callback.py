"""Actual local HTTP callbacks with synthetic codes; no Google authentication."""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
from dataclasses import FrozenInstanceError, replace
from datetime import timedelta
from urllib.parse import urlencode, urlsplit

import pytest
from pydantic import SecretStr

from newsflow.oauth.callback import CallbackError, LoopbackCallbackListener, SyntheticLoopbackCallback
from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE, OAuthBlocked
from newsflow.oauth.session import pkce_s256

_READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"


@pytest.fixture
def listener():
    with SyntheticLoopbackCallback() as callback:
        launch = callback.start("youtube:1", scopes=(YOUTUBE_UPLOAD_SCOPE, _READ_SCOPE))
        yield callback, launch


def params(launch, *, code="nf-synthetic-code-initial"):
    return [("state", launch.request.state.get_secret_value()), ("code", code)]


def request(launch, *, values=None, headers=None, target=None, method="GET"):
    parsed = urlsplit(launch.redirect_uri)
    connection = http.client.HTTPConnection("127.0.0.1", parsed.port, timeout=3)
    path = target if target is not None else parsed.path + "?" + urlencode(
        params(launch) if values is None else values,
    )
    connection.request(method, path, headers=headers or {})
    try:
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


def raw_request(launch, payload):
    parsed = urlsplit(launch.redirect_uri)
    with socket.create_connection(("127.0.0.1", parsed.port), timeout=3) as connection:
        connection.sendall(payload)
        chunks = []
        while chunk := connection.recv(4096):
            chunks.append(chunk)
        return b"".join(chunks)


def test_actual_loopback_callback_returns_bound_s256_result_without_reflecting_secrets(listener, capfd):
    callback, launch = listener
    assert urlsplit(launch.redirect_uri).hostname == "127.0.0.1"
    assert urlsplit(launch.redirect_uri).port != 8765
    assert launch.request.redirect_uri == launch.redirect_uri
    status, body, headers = request(launch)
    assert status == 200
    result = callback.wait(1)
    result.assert_valid("youtube:1")
    assert result.redirect_uri == launch.redirect_uri
    assert result.account_key == "youtube:1"
    assert result.scopes == (YOUTUBE_UPLOAD_SCOPE, _READ_SCOPE)
    assert result.code.get_secret_value() == "nf-synthetic-code-initial"
    assert pkce_s256(result.verifier.get_secret_value()) == launch.request.code_challenge
    assert result.code_challenge == launch.request.code_challenge
    assert headers["Cache-Control"] == "no-store"
    assert headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "Location" not in headers and "Access-Control-Allow-Origin" not in headers
    rendered = repr(result) + repr(launch) + repr(callback.evidence()) + body.decode() + repr(headers)
    assert result.code.get_secret_value() not in rendered
    assert result.verifier.get_secret_value() not in rendered
    assert launch.request.state.get_secret_value() not in rendered
    assert capfd.readouterr() == ("", "")
    assert callback.evidence()["real_oauth_requests"] == 0
    assert callback.evidence()["real_sns_upload_requests"] == 0
    assert callback.evidence()["registered_uri_verified"] is False


def test_callback_result_delivered_once_and_http_replay_rejected(listener):
    callback, launch = listener
    assert request(launch)[0] == 200
    callback.wait(1)
    assert request(launch)[0] == 409
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.code == "reused"
    assert callback.evidence()["synthetic_callbacks_accepted"] == 1


def test_simultaneous_valid_callbacks_accept_exactly_one(listener):
    callback, launch = listener
    barrier = threading.Barrier(3)
    results = []

    def receive():
        barrier.wait()
        results.append(request(launch)[0])

    threads = [threading.Thread(target=receive) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert sorted(results) == [200, 409]
    callback.wait(1).assert_valid("youtube:1")


@pytest.mark.parametrize(
    "host",
    ["attacker.invalid", "localhost", "127.0.0.1", "127.0.0.1:8765", "127.0.0.1.evil.invalid", "[::1]"],
)
def test_invalid_host_rejected_without_burning_valid_state(listener, host):
    callback, launch = listener
    status, body, _ = request(launch, headers={"Host": host})
    assert status == 400 and launch.request.state.get_secret_value().encode() not in body
    assert request(launch)[0] == 200
    callback.wait(1).assert_valid("youtube:1")


@pytest.mark.parametrize("origin", ["null", "https://attacker.invalid", "http://127.0.0.1:8765"])
def test_external_or_unconfigured_origin_cannot_consume_callback(listener, origin):
    callback, launch = listener
    assert request(launch, headers={"Origin": origin})[0] == 400
    assert request(launch)[0] == 200
    callback.wait(1).assert_valid("youtube:1")


def test_explicit_fake_loopback_origin_is_allowed_but_never_becomes_cors_permission():
    with SyntheticLoopbackCallback() as callback:
        launch = callback.start("youtube:1", allowed_origin="http://127.0.0.1:54321")
        status, _, headers = request(launch, headers={"Origin": "http://127.0.0.1:54321"})
        assert status == 200 and "Access-Control-Allow-Origin" not in headers
        callback.wait(1).assert_valid("youtube:1")


@pytest.mark.parametrize(
    "origin",
    ["https://127.0.0.1:9999", "http://localhost:9999", "http://127.0.0.1:9999/",
     "http://127.0.0.1:9999#fragment", "http://user@127.0.0.1:9999", "http://127.0.0.1:9999?x=1"],
)
def test_untrusted_synthetic_origin_configuration_rejected_before_binding(origin):
    with SyntheticLoopbackCallback() as callback, pytest.raises(CallbackError) as error:
        callback.start("youtube:1", allowed_origin=origin)
    assert error.value.code == "invalid_input"


def test_duplicate_host_and_origin_headers_rejected_without_consuming(listener):
    callback, launch = listener
    parsed = urlsplit(launch.redirect_uri)
    query = urlencode(params(launch))
    host = f"127.0.0.1:{parsed.port}"
    for extra in (f"Host: {host}\r\n", "Origin: null\r\nOrigin: null\r\n"):
        payload = f"GET /oauth/callback?{query} HTTP/1.1\r\nHost: {host}\r\n{extra}\r\n".encode()
        assert raw_request(launch, payload).startswith(b"HTTP/1.0 400")
    assert request(launch)[0] == 200
    callback.wait(1)


@pytest.mark.parametrize(
    "case,code",
    [("duplicate-code", "callback_invalid"),
     ("unknown-field", "callback_invalid"), ("both-code-error", "callback_invalid"),
     ("empty-code", "callback_invalid"), ("foreign-code", "callback_invalid"),
     ("control-code", "callback_invalid"), ("error-description-with-code", "callback_invalid"),
     ("other-account-field", "callback_invalid")],
)
def test_invalid_callback_consumed_fail_closed_without_any_network_exchange(listener, case, code):
    callback, launch = listener
    values = params(launch)
    if case == "duplicate-code":
        values.append(("code", "nf-synthetic-code-second"))
    elif case == "unknown-field":
        values.append(("redirect_uri", "https://attacker.invalid"))
    elif case == "both-code-error":
        values.append(("error", "access_denied"))
    elif case == "empty-code":
        values[1] = ("code", "")
    elif case == "foreign-code":
        values[1] = ("code", "actual-format-code-is-forbidden")
    elif case == "control-code":
        values[1] = ("code", "nf-synthetic-code-\x00")
    elif case == "error-description-with-code":
        values.append(("error_description", "nf-synthetic-error-sensitive"))
    else:
        values.append(("account_key", "youtube:2"))
    status, body, _ = request(launch, values=values)
    assert status == 400 and b"nf-synthetic" not in body
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.code == code
    assert request(launch)[0] == 409
    assert callback.evidence()["real_oauth_requests"] == 0


@pytest.mark.parametrize("case", ["wrong-state", "no-state", "duplicate-state"])
def test_unauthenticated_callback_rejected_without_burning_legitimate_pending_login(listener, case):
    callback, launch = listener
    values = params(launch)
    if case == "wrong-state":
        values[0] = ("state", "X" * 43)
    elif case == "no-state":
        values.pop(0)
    else:
        values.append(values[0])
    assert request(launch, values=values)[0] == 400
    assert callback.evidence()["synthetic_callbacks_accepted"] == 0
    assert request(launch)[0] == 200
    callback.wait(1).assert_valid("youtube:1")


@pytest.mark.parametrize("error_name,code", [("access_denied", "cancelled"), ("provider_error", "provider_error")])
def test_provider_cancellation_and_error_emit_no_secret_error_description(listener, error_name, code, capfd):
    callback, launch = listener
    values = [params(launch)[0], ("error", error_name), ("error_description", "nf-synthetic-error-secret")]
    status, body, _ = request(launch, values=values)
    assert status == 400 and b"secret" not in body
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.code == code
    assert "secret" not in str(error.value) and capfd.readouterr() == ("", "")


def test_provider_optional_scope_authuser_prompt_never_change_bound_permissions_or_account(listener):
    callback, launch = listener
    values = [*params(launch), ("scope", "openid"), ("authuser", "99"), ("prompt", "consent")]
    assert request(launch, values=values)[0] == 200
    result = callback.wait(1)
    assert result.account_key == "youtube:1" and result.scopes == (YOUTUBE_UPLOAD_SCOPE, _READ_SCOPE)
    result.assert_valid("youtube:1")


@pytest.mark.parametrize(
    "target",
    ["/foreign", "//attacker.invalid/oauth/callback", "http://attacker.invalid/oauth/callback",
     "/oauth/callback#fragment", "/oauth/callback?state=%GG", "/oauth/callback?bad=%FF"],
)
def test_invalid_paths_or_query_syntax_do_not_reflect_or_consume_callback(listener, target):
    callback, launch = listener
    status, body, headers = request(launch, target=target)
    assert status == 400 and target.encode() not in body
    assert "Location" not in headers
    assert request(launch)[0] == 200
    callback.wait(1)


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "HEAD", "OPTIONS"])
def test_only_get_callback_is_supported(listener, method):
    callback, launch = listener
    assert request(launch, method=method)[0] == 405
    assert request(launch)[0] == 200
    callback.wait(1)


@pytest.mark.parametrize("headers", [{"Transfer-Encoding": "chunked"}, {"Content-Length": "1"}])
def test_get_request_body_or_transfer_encoding_rejected(listener, headers):
    callback, launch = listener
    assert request(launch, headers=headers)[0] == 400
    assert request(launch)[0] == 200
    callback.wait(1)


def test_callback_wait_timeout_consumes_and_late_response_cannot_become_success(listener):
    callback, launch = listener
    with pytest.raises(CallbackError) as error:
        callback.wait(0.01)
    assert error.value.code == "callback_timeout"
    assert request(launch)[0] == 409
    assert callback.evidence()["synthetic_callbacks_accepted"] == 0


def test_callback_expiration_without_http_request_is_not_success():
    with SyntheticLoopbackCallback() as callback:
        launch = callback.start("youtube:1", ttl_seconds=0.02)
        with pytest.raises(CallbackError) as error:
            callback.wait(1)
        assert error.value.code == "expired"
        assert request(launch)[0] == 409


def test_expired_callback_received_over_http_is_rejected():
    with SyntheticLoopbackCallback() as callback:
        launch = callback.start("youtube:1", ttl_seconds=0.01)
        threading.Event().wait(0.02)
        assert request(launch)[0] == 410
        with pytest.raises(CallbackError) as error:
            callback.wait(1)
        assert error.value.code == "expired"


def test_explicit_local_cancellation_consumes_callback(listener):
    callback, launch = listener
    callback.cancel()
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.code == "cancelled" and request(launch)[0] == 409


def test_mismatching_pkce_verifier_never_yields_result(listener):
    callback, launch = listener
    callback._verifier = SecretStr("X" * 43)
    assert request(launch)[0] == 400
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.code == "callback_invalid"


@pytest.mark.parametrize("case", ["account", "scope", "uri", "code", "verifier", "challenge", "expiry", "session", "mode", "seal"])
def test_callback_result_proof_prevents_forged_binding_before_token_exchange(listener, case):
    callback, launch = listener
    assert request(launch)[0] == 200
    result = callback.wait(1)
    changes = {
        "account": {"account_key": "youtube:2"}, "scope": {"scopes": (YOUTUBE_UPLOAD_SCOPE,)},
        "uri": {"redirect_uri": "http://127.0.0.1:12345/oauth/callback"},
        "code": {"code": SecretStr("nf-synthetic-code-spliced")},
        "verifier": {"verifier": SecretStr("X" * 43)}, "challenge": {"code_challenge": "X" * 43},
        "expiry": {"expires_at": result.expires_at + timedelta(hours=1)},
        "session": {"session_id": "0" * 32}, "mode": {"mode": "production"}, "seal": {"_seal": b""},
    }
    forged = replace(result, **changes[case])
    with pytest.raises(CallbackError) as error:
        forged.assert_valid(forged.account_key)
    assert error.value.code == "callback_invalid"
    result.assert_valid("youtube:1")


def test_valid_callback_proof_cannot_bind_another_account(listener):
    callback, launch = listener
    assert request(launch)[0] == 200
    result = callback.wait(1)
    with pytest.raises(CallbackError) as error:
        result.assert_valid("youtube:2")
    assert error.value.code == "account_mismatch"
    with pytest.raises(FrozenInstanceError):
        result.account_key = "youtube:2"


@pytest.mark.parametrize("part", ["line", "header", "count", "fields"])
def test_bounded_http_parser_rejects_large_inputs_without_logging_sensitive_values(listener, part, capfd):
    callback, launch = listener
    port = urlsplit(launch.redirect_uri).port
    host = f"Host: 127.0.0.1:{port}\r\n"
    if part == "line":
        payload = f"GET /oauth/callback?secret={'X' * 5000} HTTP/1.1\r\n{host}\r\n".encode()
        expected = b"414"
    elif part == "header":
        payload = f"GET /oauth/callback HTTP/1.1\r\n{host}X-Secret: {'X' * 9000}\r\n\r\n".encode()
        expected = b"431"
    elif part == "count":
        payload = (f"GET /oauth/callback HTTP/1.1\r\n{host}" + "X-Secret: sensitive\r\n" * 40 + "\r\n").encode()
        expected = b"431"
    else:
        payload = ("GET /oauth/callback?" + "&".join(f"field{i}=sensitive" for i in range(9))
                   + f" HTTP/1.1\r\n{host}\r\n").encode()
        expected = b"400"
    response = raw_request(launch, payload)
    assert response.startswith(b"HTTP/1.0 " + expected)
    assert b"sensitive" not in response and b"X-Secret" not in response
    assert capfd.readouterr() == ("", "")
    assert request(launch)[0] == 200
    callback.wait(1)


def test_conflicting_local_port_is_fail_closed_and_never_auto_changed():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        port = occupied.getsockname()[1]
        with SyntheticLoopbackCallback() as callback, pytest.raises(CallbackError) as error:
            callback.start("youtube:1", port=port)
        assert error.value.code == "port_conflict"


def test_another_local_process_cannot_bind_listener_port(listener):
    _, launch = listener
    port = urlsplit(launch.redirect_uri).port
    script = (
        "import json,socket,sys\n"
        "s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\n"
        "try:\n"
        " s.bind(('127.0.0.1',int(sys.argv[1])))\n"
        "except OSError:\n"
        " print(json.dumps({'bind_denied':True}))\n"
        "else:\n"
        " print(json.dumps({'bind_denied':False}))\n"
        "finally:\n"
        " s.close()\n"
    )
    result = subprocess.run([sys.executable, "-c", script, str(port)], capture_output=True, text=True,
                            timeout=10, check=True)
    assert json.loads(result.stdout) == {"bind_denied": True}
    assert result.stderr == ""


@pytest.mark.skipif(os.name != "nt", reason="Native Windows SO_EXCLUSIVEADDRUSE requires Windows runner")
def test_windows_callback_socket_uses_exclusive_bind(listener):
    callback, _ = listener
    assert callback._server.socket.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) == 1


@pytest.mark.parametrize(
    "kwargs",
    [{"port": 8765}, {"port": 80}, {"port": True}, {"port": -1}, {"ttl_seconds": 0},
     {"ttl_seconds": 301}, {"scopes": ("openid",)}, {"scopes": (YOUTUBE_UPLOAD_SCOPE,) * 2},
     {"scopes": (None,)}, {"scopes": []}],
    ids=["gui-port", "privileged-port", "boolean-port", "negative-port", "zero-ttl", "long-ttl",
         "wrong-scope", "duplicate-scope", "invalid-scope", "mutable-scopes"],
)
def test_listener_configuration_fail_closed(kwargs):
    with SyntheticLoopbackCallback() as callback, pytest.raises(CallbackError) as error:
        callback.start("youtube:1", **kwargs)
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("account", ["youtube:0", "youtube:01", "instagram:1", "youtube:1/../../", None])
def test_listener_rejects_invalid_account_binding(account):
    with SyntheticLoopbackCallback() as callback, pytest.raises(CallbackError) as error:
        callback.start(account)
    assert error.value.code == "invalid_input"


def test_production_start_blocked_before_socket_bind_despite_forged_approval(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("A production callback must never bind")

    monkeypatch.setattr(socket.socket, "bind", forbidden)
    monkeypatch.setenv("NEWSFLOW_PRODUCTION_OAUTH", "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_APPROVED", "true")
    with LoopbackCallbackListener() as callback, pytest.raises(OAuthBlocked):
        callback.start("youtube:1")
    assert callback.evidence()["mode"] == "OFFLINE/BLOCKED"


def test_listener_close_ends_server_and_invalidates_pending_result():
    callback = SyntheticLoopbackCallback()
    launch = callback.start("youtube:1")
    callback.close()
    assert not callback._thread.is_alive()
    with pytest.raises((OSError, http.client.HTTPException)):
        request(launch)
    with pytest.raises(CallbackError) as error:
        callback.wait(1)
    assert error.value.code == "cancelled"
    with pytest.raises(CallbackError) as restart:
        callback.start("youtube:1")
    assert restart.value.code == "reused"
