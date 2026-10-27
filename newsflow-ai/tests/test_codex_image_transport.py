"""In-memory child pipes only. No CLI process, accounts, HTTP or live image calls."""
import json
import time
from io import StringIO
from pathlib import Path
from threading import Event

import pytest

from newsflow.publishing import codex_image_rpc as wire
from newsflow.publishing import codex_images as native

SECRET = "SECRET_RAW_CREDENTIAL_AND_RESPONSE_MUST_NOT_APPEAR"


class Input(StringIO):
    def __init__(self):
        super().__init__()
        self.sent = []
    def write(self, value):
        self.sent.append(value)
        return super().write(value)


class Child:
    def __init__(self, stdout="", stderr="", exit_code=None):
        self.stdin, self.stdout, self.stderr = Input(), StringIO(stdout), StringIO(stderr)
        self.exit_code = exit_code
        self.terminations = self.kills = 0
    def poll(self):
        return self.exit_code
    def terminate(self):
        self.terminations += 1
        self.exit_code = -15
    def wait(self, timeout):
        return self.exit_code
    def kill(self):
        self.kills += 1


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    def denied(*a, **k):
        pytest.fail("No real subprocess or network in transport tests")
    monkeypatch.setattr(wire.subprocess, "Popen", denied)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", denied)


def start(monkeypatch, child, *, cancel=None, seconds=1):
    monkeypatch.setattr(wire.subprocess, "Popen", lambda *a, **k: child)
    return wire.ImageRPC(Path("fixture-codex.exe"), Path("fixture-cwd"), native.image_config(),
                         time.monotonic() + seconds, cancel or Event())


@pytest.mark.parametrize("stderr,stdout,code,category", [
    (f"Error loading config: unknown field {SECRET}", "", "codex_image_config_error", "unknown_config_field"),
    ("Error: config.toml: unknown configuration field `computer_use.windows.always_allowed_app_ids`",
     "", "codex_image_config_error", "unknown_config_field"),
    (f"TOML parse error invalid type {SECRET}", "", "codex_image_config_error", "config_invalid"),
    (f"unexpected argument {SECRET}", "", "codex_image_argument_error", "invalid_argument"),
    (f"{SECRET}", "", "codex_image_startup_error", None),
    (f"{SECRET}", f"not json {SECRET}\n", "codex_image_protocol_error", None),
    ("", "[]\n", "codex_image_protocol_error", None),
])
def test_start_failure_classified_without_storing_raw(monkeypatch, stderr, stdout, code, category):
    child = Child(stdout=stdout, stderr=stderr, exit_code=2)
    with pytest.raises(wire.ImageTransportError) as caught:
        start(monkeypatch, child)
    error = caught.value
    assert error.code == code and error.diagnostics["stage"] == "initialize"
    assert error.diagnostics["exit_code"] == 2 and error.diagnostics["stopped_by_app"] is False
    if category:
        assert category in error.diagnostics["stderr_categories"]
    assert SECRET not in json.dumps(error.diagnostics) + str(error)
    assert child.terminations == child.kills == 0
    assert child.stdin.closed and child.stdout.closed and child.stderr.closed
    assert not any('"method": "account/read"' in s for s in child.stdin.sent)


@pytest.mark.parametrize("error,code", [(PermissionError(13, SECRET), "codex_image_permission_denied"),
    (FileNotFoundError(2, SECRET), "codex_image_executable_missing")])
def test_spawn_error_does_not_leak_os_message(monkeypatch, error, code):
    def fail(*a, **k):
        raise error
    monkeypatch.setattr(wire.subprocess, "Popen", fail)
    with pytest.raises(wire.ImageTransportError) as caught:
        wire.ImageRPC(Path("fixture.exe"), Path("fixture-cwd"), {}, time.monotonic()+1, Event())
    assert caught.value.code == code
    assert caught.value.diagnostics["stage"] == "launch"
    assert SECRET not in json.dumps(caught.value.diagnostics) + str(caught.value)


def test_jsonrpc_error_code_and_category_only(monkeypatch):
    packet = {"id": 1, "error": {"code": -32602, "message": f"unknown field {SECRET}",
                                  "data": {"token": SECRET}}}
    with pytest.raises(wire.ImageTransportError) as caught:
        start(monkeypatch, Child(stdout=json.dumps(packet)+"\n", exit_code=1))
    assert caught.value.code == "codex_image_config_error"
    assert caught.value.diagnostics["rpc_error_code"] == -32602
    assert SECRET not in json.dumps(caught.value.diagnostics)


def test_no_progress_timeout_distinct_from_original_process_exit(monkeypatch):
    child = Child(stderr=SECRET)
    with pytest.raises(wire.ImageTransportError) as caught:
        start(monkeypatch, child, seconds=.03)
    assert caught.value.code == "codex_image_timeout"
    assert caught.value.diagnostics["stopped_by_app"] is True
    assert "exit_code" not in caught.value.diagnostics  # Don't mislabel our terminate as the root cause.
    assert child.terminations == 1


def test_stderr_cap_drains_without_raw_storage(monkeypatch):
    child = Child(stderr="x" * 80000 + SECRET, exit_code=2)
    with pytest.raises(wire.ImageTransportError) as caught:
        start(monkeypatch, child)
    assert caught.value.diagnostics["stderr_truncated"] is True
    assert len(json.dumps(caught.value.diagnostics)) < 500
    assert SECRET not in json.dumps(caught.value.diagnostics)


def test_successful_init_and_launch_security_contract(monkeypatch):
    child = Child(stdout='{"id":1,"result":{"serverInfo":"fixture"}}\n')
    launched = []
    def launch(command, **kwargs):
        launched.append((command, kwargs))
        return child
    monkeypatch.setattr(wire.subprocess, "Popen", launch)
    monkeypatch.setenv("OPENAI_API_KEY", SECRET)
    server = wire.ImageRPC(Path("fixture.exe"), Path("fixture-cwd"), native.image_config(),
                            time.monotonic()+1, Event())
    command, args = launched[0]
    assert command[:4] == ["fixture.exe", "app-server", "--listen", "stdio://"]
    assert "--strict-config" not in command  # Effective security guard remains mandatory, not a parser retry.
    assert args["shell"] is False and args["stderr"] == wire.subprocess.PIPE
    assert "OPENAI_API_KEY" not in args["env"]
    first = json.loads(child.stdin.sent[0])
    assert first["params"]["capabilities"]["experimentalApi"] is True
    assert json.loads(child.stdin.sent[1])["method"] == "initialized"
    server.close()
    assert child.terminations == 1


def test_server_tool_request_still_denied(monkeypatch):
    packets = [{"id": 1, "result": {}}, {"id": 99, "method": "item/commandExecution/requestApproval",
                                         "params": {"command": SECRET}}]
    child = Child(stdout="".join(json.dumps(p)+"\n" for p in packets))
    server = start(monkeypatch, child)
    with pytest.raises(wire.ImageTransportError) as caught:
        server.next_event()
    assert caught.value.code == "codex_isolation"
    assert "-32601" in child.stdin.sent[-1]
    assert SECRET not in json.dumps(caught.value.diagnostics)


def test_diagnostics_allowlist_drops_values_and_unknown_fields():
    raw = {"stage": SECRET, "exception": SECRET, "protocol": "invalid_json", "exit_code": 2,
           "rpc_error_code": SECRET, "stderr_categories": [SECRET, "config_invalid"], "stderr": SECRET,
           "key": SECRET, "windows_error": True, "os_errno": -1}
    safe = wire.safe_diagnostics(raw)
    assert safe == {"protocol": "invalid_json", "exit_code": 2, "stderr_categories": ["config_invalid"]}
    assert SECRET not in json.dumps(safe)
