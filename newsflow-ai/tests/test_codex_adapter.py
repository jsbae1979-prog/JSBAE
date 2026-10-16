"""Codex adapter contracts without account access, subprocesses, or inference."""

import json
import queue
import time
from collections import deque
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest

from newsflow.intelligence import codex
from newsflow.intelligence.provider import (
    OfflineProvider,
    Options,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from newsflow.intelligence.schema import Analysis, Script

EVIDENCE = {
    "articles": [{"id": 1, "title": "합성 시험 뉴스", "url": "https://example.com/news/1"}],
    "groups": [[1]],
}
OPTIONS = Options(model="default")


def effective_config(web=False):
    """Expand the public launch configuration into config/read's nested shape."""
    result = {}
    for dotted, value in codex.config_for(web).items():
        target = result
        parts = dotted.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    result.setdefault("mcp_servers", {})
    result.setdefault("hooks", {})
    return result


class FakeRPC:
    def __init__(self, answer=None, *, account_type="chatgpt", limits=None, events=None):
        self.account_type = account_type
        self.limits = {"ordinaryUsageAllowed": True} if limits is None else limits
        self.calls, self.sent = [], []
        self.closed = False
        self.pending = deque()
        self.cancel = None
        self.failure = None
        self.events = deque(events or [
            {"method": "item/completed", "params": {
                "item": {"type": "agentMessage", "text": json.dumps(answer, ensure_ascii=False)},
            }},
            {"method": "thread/tokenUsage/updated", "params": {
                "tokenUsage": {"last": {"inputTokens": 11, "outputTokens": 7}},
            }},
            {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
        ])

    def call(self, method, params):
        self.calls.append((method, params))
        if method == "account/read":
            return {"account": {"type": self.account_type} if self.account_type else None}
        if method == "account/rateLimits/read":
            return self.limits
        if method == "model/list":
            return {"data": [{"model": "fixture-model", "isDefault": True}]}
        if method == "thread/start":
            return {
                "thread": {"id": "fixture-thread"}, "model": params["model"],
                "modelProvider": "openai", "approvalPolicy": "never",
                "approvalsReviewer": "user", "sandbox": {"type": "readOnly", "networkAccess": False},
                "instructionSources": [], "cwd": params["cwd"],
            }
        if method == "turn/start":
            return {"turn": {"id": "fixture-turn"}}
        raise AssertionError("Unexpected RPC: " + method)

    def next_event(self):
        if self.failure:
            raise self.failure
        if self.cancel and self.cancel.is_set():
            raise codex.CodexError("codex_cancelled")
        return self.events.popleft()

    def send(self, item):
        self.sent.append(item)

    def close(self):
        self.closed = True


@pytest.fixture
def connect(monkeypatch):
    monkeypatch.setattr(codex, "cli_path", lambda: Path("fixture-codex.exe"))
    monkeypatch.setattr(codex.CodexProvider, "version", staticmethod(lambda _: codex.TESTED_VERSION))

    def install(server):
        provider = codex.CodexProvider()
        starts = []

        def start(path, cwd, deadline, cancel, web=False):
            starts.append({"cwd": cwd, "deadline": deadline, "web": web})
            server.cancel = cancel
            return server

        monkeypatch.setattr(codex, "start_isolated", start)
        return provider, starts

    return install


def test_status_without_cli_never_starts_server(monkeypatch):
    monkeypatch.setattr(codex, "cli_path", lambda: None)
    monkeypatch.setattr(codex, "start_isolated", lambda *_: pytest.fail("Unexpected server"))
    status = codex.CodexProvider().status()
    assert status["state"] == "not_installed"
    assert status["ready"] is False and status["web_search_verified"] is False


@pytest.mark.parametrize("account_type,limits,expected", [
    ("chatgpt", {"ordinaryUsageAllowed": True}, "ready"),
    (None, {}, "login_required"),
    ("apiKey", {}, "approval_required"),
    ("chatgpt", {"ordinaryUsageAllowed": False}, "usage_blocked"),
    ("chatgpt", {}, "usage_blocked"),
    ("chatgpt", {"ordinaryUsageAllowed": 1}, "usage_blocked"),
])
def test_status_distinguishes_authentication_and_usage(connect, account_type, limits, expected):
    server = FakeRPC(account_type=account_type, limits=limits)
    provider, _ = connect(server)
    status = provider.status()
    assert status["state"] == expected
    assert status["ready"] is (expected == "ready")
    assert status["web_search_verified"] is False
    assert server.closed
    assert not any(method in {"thread/start", "turn/start"} for method, _ in server.calls)


@pytest.mark.parametrize("error,expected", [
    (codex.CodexError("codex_isolation"), "isolation_blocked"),
    (ProviderTimeoutError("PRIVATE"), "timeout"),
    (OSError("PRIVATE"), "failed"),
])
def test_status_errors_are_safe_and_not_retried(connect, monkeypatch, error, expected):
    provider, _ = connect(FakeRPC())
    attempts = []

    def unavailable(*args):
        attempts.append(args)
        raise error

    monkeypatch.setattr(codex, "start_isolated", unavailable)
    status = provider.status()
    assert status["state"] == expected
    assert "PRIVATE" not in json.dumps(status)
    assert len(attempts) == 1


@pytest.mark.parametrize("output,returncode", [
    (b"codex-cli 0.999.0\n", 0),
    (b"codex-cli " + codex.TESTED_VERSION.encode() + b" extra", 0),
    (b"PRIVATE", 1),
])
def test_version_guard_rejects_unverified_binary(monkeypatch, output, returncode):
    monkeypatch.setattr(codex.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output, returncode=returncode))
    with pytest.raises(codex.CodexError, match="codex_version"):
        codex.CodexProvider.version(Path("fixture.exe"))


def test_version_guard_accepts_only_inspected_version(monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 5
        return SimpleNamespace(stdout=("codex-cli " + codex.TESTED_VERSION + "\n").encode(), returncode=0)

    monkeypatch.setattr(codex.subprocess, "run", run)
    assert codex.CodexProvider.version(Path("fixture.exe")) == codex.TESTED_VERSION
    assert calls == [["fixture.exe", "--version"]]


def test_child_env_preserves_official_home_and_excludes_billing_secrets(monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "official-existing-home")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "SESSION_TOKEN", "APP_SECRET", "APP_PASSWORD", "OPENAI_BASE_URL"):
        monkeypatch.setenv(name, "PRIVATE")
    env = codex.cli_env()
    assert env["CODEX_HOME"] == "official-existing-home"
    assert "PRIVATE" not in env.values()


@pytest.mark.parametrize("web", [False, True])
def test_effective_configuration_allows_only_requested_research_mode(web):
    config = effective_config(web)
    codex.configuration_guard(config, web)
    assert config["features"]["shell_tool"] is False
    assert config["features"]["hooks"] is False
    assert config["features"]["plugins"] is False
    assert config["features"]["unbounded_connection_retries"] is False
    assert config["web_search"] == ("live" if web else "disabled")


@pytest.mark.parametrize("unsafe", ["missing_feature", "unbounded_retries", "mcp", "hooks", "notify", "endpoint", "provider", "web", "sandbox"])
def test_configuration_guard_fails_closed(unsafe):
    config = effective_config()
    if unsafe == "missing_feature":
        config["features"].pop("shell_tool")
    elif unsafe == "unbounded_retries":
        config["features"]["unbounded_connection_retries"] = True
    elif unsafe == "mcp":
        config["mcp_servers"] = {"fixture": {"enabled": True}}
    elif unsafe == "hooks":
        config["hooks"] = {"SessionStart": [{"hooks": [{"command": "PRIVATE"}]}]}
    elif unsafe == "notify":
        config["notify"] = ["fixture-command"]
    elif unsafe == "endpoint":
        config["openai_base_url"] = "https://example.com/unapproved"
    elif unsafe == "provider":
        config["model_provider"] = "unapproved"
    elif unsafe == "web":
        config["web_search"] = "live"
    elif unsafe == "sandbox":
        config["sandbox_mode"] = "danger-full-access"
    with pytest.raises(codex.CodexError, match="codex_isolation"):
        codex.configuration_guard(config, False)


@pytest.mark.parametrize("method", ["analyze", "complete"])
def test_structured_rss_request_preserves_input_and_has_no_implicit_tools(connect, method):
    answer = (OfflineProvider().analyze(EVIDENCE, OPTIONS) if method == "analyze"
              else OfflineProvider().complete(EVIDENCE, 30, OPTIONS))
    server = FakeRPC(answer)
    provider, starts = connect(server)
    result = (provider.analyze(EVIDENCE, OPTIONS) if method == "analyze"
              else provider.complete(EVIDENCE, 30, OPTIONS))
    assert result == answer and len(starts) == 1 and starts[0]["web"] is False
    assert server.closed and not starts[0]["cwd"].exists()
    assert provider.last_usage == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert provider.last_web_events == [] and provider.cancel() is False
    thread = next(params for name, params in server.calls if name == "thread/start")
    turn = next(params for name, params in server.calls if name == "turn/start")
    assert thread["ephemeral"] is True and thread["sandbox"] == "read-only"
    assert thread["approvalPolicy"] == "never"
    assert "untrusted" in thread["developerInstructions"]
    assert "No tools or web search" in thread["developerInstructions"]
    assert json.loads(turn["input"][0]["text"])["evidence"] == EVIDENCE
    assert turn["outputSchema"]["additionalProperties"] is False
    assert turn["serviceTierForTurn"] == "default"
    assert [name for name, _ in server.calls].count("turn/start") == 1


@pytest.mark.parametrize("account_type,limits,code", [
    ("apiKey", {}, "codex_billing"),
    (None, {}, "codex_auth"),
    ("chatgpt", {}, "codex_usage"),
    ("chatgpt", {"ordinaryUsageAllowed": False}, "codex_usage"),
])
def test_auth_and_usage_failure_prevent_inference(connect, account_type, limits, code):
    server = FakeRPC(account_type=account_type, limits=limits)
    provider, starts = connect(server)
    with pytest.raises(codex.CodexError, match=code):
        provider.analyze(EVIDENCE, OPTIONS)
    assert len(starts) == 1 and server.closed
    assert not any(name in {"model/list", "thread/start", "turn/start"} for name, _ in server.calls)


@pytest.mark.parametrize("kind", ["commandExecution", "mcpToolCall", "collabAgentToolCall", "hookPrompt", "futureTool", "webSearch"])
def test_unexpected_tool_items_stop_turn_without_replay(connect, kind):
    server = FakeRPC(events=[{"method": "item/started", "params": {"item": {"type": kind}}}])
    provider, starts = connect(server)
    with pytest.raises(codex.CodexError, match="codex_isolation"):
        provider.analyze(EVIDENCE, OPTIONS)
    assert len(starts) == 1 and server.closed
    assert [name for name, _ in server.calls].count("turn/start") == 1
    assert any(item.get("method") == "turn/interrupt" for item in server.sent)


@pytest.mark.parametrize("answer", ["not json", "{}", '{"overview":"ok","comparisons":[],"unexpected":true}'])
def test_invalid_structured_answer_is_not_accepted_or_replayed(connect, answer):
    server = FakeRPC()
    server.events[0]["params"]["item"]["text"] = answer
    provider, starts = connect(server)
    with pytest.raises(ProviderResponseError):
        provider.analyze(EVIDENCE, OPTIONS)
    assert len(starts) == 1 and server.closed
    assert [name for name, _ in server.calls].count("turn/start") == 1


@pytest.mark.parametrize("failure", [ProviderTimeoutError(), codex.CodexError("codex_cancelled")])
def test_interrupted_turn_cleans_up_without_retry(connect, failure):
    server = FakeRPC()
    server.failure = failure
    provider, starts = connect(server)
    with pytest.raises(type(failure)):
        provider.complete(EVIDENCE, 30, OPTIONS)
    assert len(starts) == 1 and server.closed and provider.cancel() is False
    assert not provider.lock.locked()
    assert [name for name, _ in server.calls].count("turn/start") == 1
    assert any(item.get("method") == "turn/interrupt" for item in server.sent)


def test_busy_provider_prevents_duplicate_inference(connect):
    provider, starts = connect(FakeRPC())
    provider.lock.acquire()
    try:
        assert provider.status()["state"] == "busy"
        with pytest.raises(codex.CodexError, match="codex_busy"):
            provider.analyze(EVIDENCE, OPTIONS)
    finally:
        provider.lock.release()
    assert starts == []


def test_cancel_marks_only_current_request_and_releases_lock(connect, monkeypatch):
    server = FakeRPC()
    provider, _ = connect(server)
    next_event = server.next_event

    def cancelled_event():
        assert provider.cancel() is True
        return next_event()

    monkeypatch.setattr(server, "next_event", cancelled_event)
    with pytest.raises(codex.CodexError, match="codex_cancelled"):
        provider.analyze(EVIDENCE, OPTIONS)
    assert provider.cancel() is False and not provider.lock.locked()
    assert server.closed


def rpc_waiter():
    rpc = codex.RPC.__new__(codex.RPC)
    rpc.deadline, rpc.cancel = time.monotonic() + 2, Event()
    rpc.events, rpc.pending, rpc.number = queue.Queue(), deque(), 0
    rpc.overflow = Event()
    rpc.process = SimpleNamespace(poll=lambda: None)
    sent = []
    rpc.send = sent.append
    return rpc, sent


def test_rpc_refuses_server_tool_and_approval_requests():
    rpc, sent = rpc_waiter()
    rpc.events.put({"id": 10, "method": "item/commandExecution/requestApproval", "params": {"secret": "PRIVATE"}})
    with pytest.raises(codex.CodexError, match="codex_isolation"):
        rpc.next_event()
    assert sent[0]["id"] == 10 and sent[0]["error"]["code"] == -32601
    assert "PRIVATE" not in json.dumps(sent)


@pytest.mark.parametrize("failure", ["cancel", "timeout", "overflow", "exit"])
def test_rpc_wait_is_bounded(failure):
    rpc, _ = rpc_waiter()
    if failure == "cancel":
        rpc.cancel.set()
        error = codex.CodexError
    elif failure == "timeout":
        rpc.deadline = time.monotonic() - 1
        error = ProviderTimeoutError
    elif failure == "overflow":
        rpc.overflow.set()
        error = ProviderResponseError
    else:
        rpc.process.poll = lambda: 1
        error = ProviderUnavailableError
    with pytest.raises(error):
        rpc.next_event()


def test_rpc_remote_error_is_sanitized_and_not_replayed():
    rpc, sent = rpc_waiter()
    rpc.events.put({"id": 1, "error": {"code": -32000, "message": "PRIVATE token"}})
    with pytest.raises(codex.CodexError, match="codex_rpc") as caught:
        rpc.call("turn/start", {})
    assert "PRIVATE" not in str(caught.value)
    assert len(sent) == 1


@pytest.mark.parametrize("model", [Analysis, Script])
def test_output_schema_has_closed_objects_and_required_fields(model):
    schema = codex.strict_schema(model)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    for definition in schema.get("$defs", {}).values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
            assert set(definition["required"]) == set(definition["properties"])
