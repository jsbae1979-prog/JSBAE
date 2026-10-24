"""Image-only App Server transport with bounded, value-free failure diagnostics.

The RSS transport is unchanged. Raw stderr/JSON-RPC error messages exist only in
the classifier's memory; no excerpts, paths, account data or values are retained.
"""
import json
import queue
import subprocess
from collections import deque
from threading import Event, Thread

from newsflow.intelligence import codex
from newsflow.intelligence.provider import ProviderError, ProviderResponseError, ProviderTimeoutError

STAGES = {"launch", "initialize", "config", "account", "usage", "capability", "models", "thread", "turn", "rpc"}
CATEGORIES = {
    "config_invalid", "unknown_config_field", "invalid_argument", "permission_denied",
    "sandbox_unavailable", "login_required", "network_error", "usage_limited",
}
PROTOCOL = {"invalid_json", "non_object", "response_limit", "queue_limit", "read_error"}
EXCEPTIONS = {"PermissionError", "FileNotFoundError", "BrokenPipeError", "OSError", "ValueError",
              "ProviderResponseError", "ProviderUnavailableError", "ProviderTimeoutError", "CodexError"}
TOOL_MODES = {"direct", "code_mode", "code_mode_only", "unspecified", "unknown"}
TURN_STATUSES = {"completed", "failed", "interrupted", "cancelled", "inProgress"}
TEXT_OUTCOMES = {"tool_unavailable", "image_unsupported", "refusal", "other_text"}
TURN_ERRORS = {"contextWindowExceeded", "sessionBudgetExceeded", "usageLimitExceeded", "rateLimitExceeded",
               "internalServerError", "unauthorized", "badRequest", "sandboxError", "other"}


def safe_diagnostics(value):
    """Whitelist every stored value; never trust even a transport exception's fields."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for name, choices in (("stage", STAGES), ("protocol", PROTOCOL), ("exception", EXCEPTIONS),
                          ("tool_mode", TOOL_MODES), ("turn_status", TURN_STATUSES),
                          ("text_outcome", TEXT_OUTCOMES), ("turn_error", TURN_ERRORS)):
        if isinstance(value.get(name), str) and value[name] in choices:
            result[name] = value[name]
    for name, low, high in (("exit_code", -(2**31), 2**32-1), ("rpc_error_code", -32768, 32767),
                            ("os_errno", 0, 4096), ("windows_error", 0, 65535),
                            ("image_started", 0, 256), ("image_completed", 0, 256), ("agent_messages", 0, 256)):
        number = value.get(name)
        if type(number) is int and low <= number <= high:
            result[name] = number
    categories = value.get("stderr_categories")
    if isinstance(categories, list):
        result["stderr_categories"] = sorted({c for c in categories if isinstance(c, str) and c in CATEGORIES})
    for name in ("stderr_truncated", "stopped_by_app"):
        if type(value.get(name)) is bool:
            result[name] = value[name]
    return result


def categories(text):
    """Match fixed phrases, never extract a field name/value or raw sentence."""
    lower = text.lower()
    rules = {
        "unknown_config_field": ("unknown field", "unknown configuration field", "unrecognized field", "unrecognised field"),
        "config_invalid": ("error loading config", "invalid config", "error parsing", "toml parse error", "invalid type"),
        "invalid_argument": ("unexpected argument", "unrecognized option", "invalid value", "unknown option"),
        "permission_denied": ("access is denied", "access denied", "permission denied", "os error 5", "액세스가 거부"),
        "sandbox_unavailable": ("sandbox unavailable", "failed to initialize sandbox", "sandbox setup failed"),
        "login_required": ("not logged in", "login required", "authentication required"),
        "network_error": ("connection refused", "connection reset", "dns error", "certificate verify failed"),
        "usage_limited": ("usage limit exceeded", "rate limit exceeded"),
    }
    return {key for key, phrases in rules.items() if any(p in lower for p in phrases)}


class ImageTransportError(codex.CodexError):
    def __init__(self, code, diagnostic):
        self.diagnostics = safe_diagnostics(diagnostic)
        super().__init__(code)


class ImageRPC(codex.RPC):
    """Image-only compatibility; require image_guard before account/thread calls.

    0.163 rejects the desktop's documented always_allowed_app_ids under strict
    parsing. Use the official default parser without modifying the shared config;
    start_image_server must still validate every required effective safety value.
    This is not a retry/fallback. The news/RSS transport keeps its strict parser.
    """
    def __init__(self, path, cwd, config, deadline, cancel):
        command = [str(path), "app-server", "--listen", "stdio://"]
        for key, value in config.items():
            command.extend(["-c", key + "=" + json.dumps(value)])
        self.deadline, self.cancel = deadline, cancel
        self.closed, self.process, self.reader, self.error_reader = False, None, None, None
        self.events, self.pending, self.number = queue.Queue(maxsize=256), deque(), 0
        self.overflow = Event()
        self.diagnostic = {"stage": "launch", "stderr_categories": [], "stderr_truncated": False,
                           "stopped_by_app": False}
        try:
            self.process = subprocess.Popen(command, cwd=str(cwd), env=codex.cli_env(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.reader = Thread(target=self._read, daemon=True)
            self.error_reader = Thread(target=self._read_errors, daemon=True)
            self.reader.start()
            self.error_reader.start()
            self.call("initialize", {"clientInfo": {"name": "newsflow_ai", "title": "NewsFlow AI", "version": "0.1"},
                                     "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized"})
        except ImageTransportError:
            raise
        except (ProviderError, OSError, ValueError) as error:
            raise self.failure(error) from None

    def _read_errors(self):
        total, tail = 0, ""
        try:
            while chunk := self.process.stderr.readline(4096):
                total += len(chunk)
                if total <= 65536:
                    found = categories(tail + chunk)
                    self.diagnostic["stderr_categories"] = sorted(set(self.diagnostic["stderr_categories"]) | found)
                    tail = chunk[-256:]
                else:
                    # Continue draining the pipe without retaining or classifying extra content.
                    self.diagnostic["stderr_truncated"] = True
                    tail = ""
        except (OSError, ValueError):
            pass

    def _read(self):
        total = 0
        try:
            while line := self.process.stdout.readline(18_000_001):
                total += len(line)
                if len(line) > 18_000_000 or total > 28_000_000:
                    self.diagnostic["protocol"] = "response_limit"
                    self.overflow.set()
                    return
                try:
                    item = json.loads(line)
                except ValueError:
                    self.diagnostic["protocol"] = "invalid_json"
                    self.overflow.set()
                    return
                if not isinstance(item, dict):
                    self.diagnostic["protocol"] = "non_object"
                    self.overflow.set()
                    return
                self.events.put_nowait(item)
        except (OSError, ValueError, queue.Full) as error:
            self.diagnostic["protocol"] = "queue_limit" if isinstance(error, queue.Full) else "read_error"
            self.overflow.set()

    def call(self, method, params):
        self.diagnostic["stage"] = {
            "initialize": "initialize", "config/read": "config", "account/read": "account",
            "account/rateLimits/read": "usage", "modelProvider/capabilities/read": "capability",
            "model/list": "models", "thread/start": "thread", "turn/start": "turn",
        }.get(method, "rpc")
        try:
            return super().call(method, params)
        except ImageTransportError:
            raise
        except (ProviderError, OSError, ValueError) as error:
            raise self.failure(error) from None

    def next_event(self):
        try:
            item = super().next_event()
        except (ProviderError, OSError, ValueError) as error:
            raise self.failure(error) from None
        error = item.get("error")
        if isinstance(error, dict):
            self.diagnostic["rpc_error_code"] = error.get("code")
            message = error.get("message")
            if isinstance(message, str):
                found = categories(message[:65536])
                self.diagnostic["stderr_categories"] = sorted(set(self.diagnostic["stderr_categories"]) | found)
        return item

    def failure(self, error):
        self.diagnostic["exception"] = type(error).__name__
        self.diagnostic["os_errno"] = getattr(error, "errno", None)
        self.diagnostic["windows_error"] = getattr(error, "winerror", None)
        self.close()
        flags = set(self.diagnostic["stderr_categories"])
        if isinstance(error, codex.CodexError) and error.code != "codex_rpc":
            code = error.code  # Preserve cancellation and isolation decisions.
        elif isinstance(error, ProviderTimeoutError):
            code = "codex_image_timeout"
        elif self.diagnostic.get("windows_error") == 5 or isinstance(error, PermissionError):
            code = "codex_image_permission_denied"
        elif flags & {"config_invalid", "unknown_config_field"}:
            code = "codex_image_config_error"
        elif "invalid_argument" in flags:
            code = "codex_image_argument_error"
        elif "protocol" in self.diagnostic or isinstance(error, ProviderResponseError):
            code = "codex_image_protocol_error"
        elif self.diagnostic.get("rpc_error_code") is not None:
            code = "codex_image_rpc_error"
        elif isinstance(error, FileNotFoundError):
            code = "codex_image_executable_missing"
        elif self.diagnostic.get("stage") in {"launch", "initialize"}:
            code = "codex_image_startup_error"
        else:
            code = "codex_image_transport_error"
        return ImageTransportError(code, self.diagnostic)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process is None:
            return
        exit_code = self.process.poll()
        if exit_code is not None:
            self.diagnostic["exit_code"] = exit_code
        else:
            self.diagnostic["stopped_by_app"] = True
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()  # Only this adapter's owned child.
                self.process.wait(timeout=5)
        for reader in (self.reader, self.error_reader):
            if reader:
                reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except OSError:
                pass
