"""Official local Claude Code CLI adapter. Never reads or copies authentication files."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Lock

from .provider import (
    ANALYSIS_INSTRUCTION,
    SCRIPT_INSTRUCTION,
    Options,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from .schema import Analysis, Script

CONNECTION_MESSAGES = {
    "unchecked": "연결 상태를 확인해 주세요. 페이지를 여는 것만으로 CLI를 실행하지 않습니다.",
    "checking": "연결 확인 중입니다. 잠시 후 다시 확인해 주세요.",
    "not_installed": "설치 필요 · 공식 설치 안내에서 Windows 설치 방법을 확인하세요.",
    "version_check": "CLI 버전 확인 필요 · 2.1.259 이상이 필요합니다. 자동 업데이트하지 않습니다.",
    "login_required": "공식 로그인 필요 · 아래 버튼으로 CLI의 공식 로그인 창을 여세요.",
    "ready": "로컬 실행 준비 완료 · 설치·버전·구독 인증 확인 결과입니다.",
    "approval_required": "인증 확인됨 · NewsFlow AI에서 해당 과금 방식 사용 승인 필요. 자동 전환하지 않습니다.",
    "auth_error": "인증 오류 · 공식 CLI에서 계정 상태를 확인한 뒤 다시 확인하세요.",
    "timeout": "연결 확인 시간이 초과되었습니다. 자동 재시도하지 않습니다.",
    "check_failed": "상태 확인 실패 · 실행 파일과 공식 CLI 상태를 확인하세요.",
    "login_running": "공식 로그인 창이 열려 있습니다. 그 창에서 직접 완료하거나 취소한 뒤 연결을 다시 확인하세요.",
    "login_started": "공식 로그인 창을 열었습니다. 로그인 후 연결 다시 확인을 눌러 주세요.",
    "login_failed": "로그인 창 실행 실패 · 일반 사용자 터미널에서 claude auth login을 실행하세요.",
    "login_cancelled": "공식 로그인이 취소되었거나 완료되지 않았습니다. 필요할 때 다시 진행하세요.",
    "manual_login": "이 환경에서는 일반 사용자 터미널에서 claude auth login을 직접 실행하세요.",
}


def connection_state(state, *, installed=False, authenticated=False, version=None):
    return {"state": state, "installed": installed, "authenticated": authenticated,
            "ready": state == "ready", "version": version, "message": CONNECTION_MESSAGES[state],
            "checked_at": datetime.now(UTC).isoformat() if state != "unchecked" else None}


class ProviderBillingApprovalError(ProviderError):
    code = "ai_billing_approval"


class ProviderCancelled(ProviderError):
    code = "ai_cancelled"


def cli_path() -> Path | None:
    candidates = [os.environ.get("NEWSFLOW_CLAUDE_CLI", ""), shutil.which("claude") or "",
                  str(Path.home() / ".local/bin/claude.exe")]
    # Store Desktop keeps its official CLI outside PATH. Only inspect executable
    # names in known installation folders, never Desktop credentials or cookies.
    roots = [Path.home() / "AppData/Roaming/Claude/claude-code",
             Path.home() / "AppData/Local/Packages/Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude/claude-code"]
    versions = []
    for root in roots:
        if root.is_dir():
            for path in root.glob("*/*/claude.exe"):
                version = path.parent.parent.name
                if re.fullmatch(r"\d+\.\d+\.\d+", version):
                    versions.append((tuple(map(int, version.split("."))), str(path)))
    candidates.extend(path for _, path in sorted(versions, reverse=True))
    for candidate in candidates:
        path = Path(candidate)
        # Batch files need a shell; require the official native executable on Windows.
        if candidate and path.is_file() and (os.name != "nt" or path.suffix.lower() == ".exe"):
            return path.resolve()
    return None


def cli_env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if key.upper() == "CLAUDE_CONFIG_DIR" or (
                not key.upper().startswith(("ANTHROPIC_", "CLAUDE_", "CLAUDECODE"))
                and not key.upper().endswith(("_KEY", "_TOKEN", "_PASSWORD", "_SECRET")))}


class ClaudeCodeProvider:
    def __init__(self):
        self.lock = Lock()
        self.control = Lock()
        self.cancel_event: Event | None = None
        self.last_usage = None
        self.last_elapsed_ms = 0

    def cancel(self) -> bool:
        with self.control:
            if self.cancel_event is None:
                return False
            self.cancel_event.set()
            return True

    @staticmethod
    def status() -> dict:
        # Observe the CLI's own authentication context, without changing its methods.
        # Execution retains the app's separate subscription-only cost guard.
        path = cli_path()
        if path is None:
            return connection_state("not_installed")
        version_text = None
        try:
            version = subprocess.run([str(path), "--version"], capture_output=True, timeout=10,
                                     env=os.environ.copy(), shell=False, check=False)
            match = re.search(rb"(\d+)\.(\d+)\.(\d+)", version.stdout[:4096])
            if version.returncode or len(version.stdout) > 4096 or not match:
                return connection_state("version_check", installed=True)
            version_text = match.group().decode()
            if tuple(map(int, match.groups())) < (2, 1, 259):
                return connection_state("version_check", installed=True, version=version_text)
            auth = subprocess.run([str(path), "auth", "status"], capture_output=True, timeout=10,
                                  env=os.environ.copy(), shell=False, check=False)
            if len(auth.stdout) > 16384:
                raise ValueError
            value = json.loads(auth.stdout)
            if not isinstance(value, dict) or type(value.get("loggedIn")) is not bool:
                raise ValueError
            method = value.get("authMethod")
            if auth.returncode == 0 and value["loggedIn"]:
                if not isinstance(method, str) or method == "none":
                    raise ValueError
                return connection_state("ready" if method == "claude.ai" else "approval_required",
                                        installed=True, authenticated=True, version=version_text)
            if auth.returncode == 1 and not value["loggedIn"]:
                return connection_state("login_required", installed=True, version=version_text)
            return connection_state("auth_error", installed=True, version=version_text)
        except subprocess.TimeoutExpired:
            return connection_state("timeout", installed=True, version=version_text)
        except (OSError, ValueError, TypeError):
            return connection_state("check_failed", installed=True, version=version_text)

    @staticmethod
    def command(path: Path, schema: dict, instruction: str, model: str) -> list[str]:
        return [str(path), "-p", "--output-format", "json", "--json-schema", json.dumps(schema),
                "--restricted", "--tools", "", "--disallowedTools", "mcp__*",
                "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
                "--permission-prompts", "none", "--disable-slash-commands", "--no-chrome",
                "--no-session-persistence", "--max-turns", "3", "--model", model,
                "--system-prompt", instruction]

    def _request(self, payload: dict, schema_type, instruction: str, options: Options) -> dict:
        if not self.lock.acquire(blocking=False):
            raise ProviderUnavailableError("Claude Code 작업이 이미 실행 중입니다.")
        cancel = Event()
        with self.control:
            self.cancel_event = cancel
        started = time.monotonic()
        self.last_usage = None
        try:
            status = self.status()
            if not status["ready"]:
                if status.get("state") == "approval_required":
                    raise ProviderBillingApprovalError("인증 확인됨 · 해당 과금 방식 사용 승인 필요")
                raise ProviderAuthError("Claude Code 설치·구독 인증을 확인하세요.")
            if cancel.is_set():
                raise ProviderCancelled("Claude 요청 취소")
            if time.monotonic() - started > options.timeout:
                raise ProviderTimeoutError("Claude 인증 확인 시간 초과 · 추론 미실행")
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            if len(data) > 64000:
                raise ProviderResponseError("뉴스 자료가 너무 큽니다.")
            model = options.model if options.model.startswith(("claude-", "sonnet", "opus", "haiku")) else "sonnet"
            self.last_model = model
            with tempfile.TemporaryDirectory(prefix="newsflow-claude-") as folder:  # noqa: SIM117
                # Empty cwd and stdin payload keep project files and news text out of argv.
                with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors, tempfile.TemporaryFile() as inputs:
                    inputs.write(data)
                    inputs.seek(0)
                    with subprocess.Popen(self.command(cli_path(), schema_type.model_json_schema(), instruction, model),
                                          cwd=folder, env=cli_env(), shell=False, stdin=inputs,
                                          stdout=output, stderr=errors) as process:
                        try:
                            while process.poll() is None:
                                if cancel.is_set():
                                    raise ProviderCancelled("Claude 요청 취소 · 계정 사용량이 발생했을 수 있습니다.")
                                if time.monotonic() - started > options.timeout:
                                    raise ProviderTimeoutError("Claude 요청 시간 초과 · 자동 재시도하지 않습니다.")
                                if output.tell() > 262144 or errors.tell() > 65536:
                                    raise ProviderResponseError("Claude 응답 크기 초과")
                                cancel.wait(0.05)
                        finally:
                            if process.poll() is None:
                                process.kill()
                                process.wait(timeout=10)
                        output.seek(0)
                        raw = output.read(262145)
                        if len(raw) > 262144:
                            raise ProviderResponseError("Claude 응답 크기 초과")
                        try:
                            envelope = json.loads(raw)
                            if not isinstance(envelope, dict):
                                raise TypeError
                        except (ValueError, UnicodeError, TypeError):
                            raise ProviderResponseError("Claude JSON 응답 확인 실패") from None
                        if process.returncode or envelope.get("is_error"):
                            # Classify in memory only; never log/store raw errors or account metadata.
                            text = str(envelope.get("result", "")).lower()
                            if any(word in text for word in ("rate", "limit", "quota")):
                                raise ProviderRateLimitError("Claude 계정 사용량 제한")
                            if any(word in text for word in ("login", "auth", "credential")):
                                raise ProviderAuthError("Claude 계정 인증 실패")
                            raise ProviderResponseError("Claude 실행 실패 · 자동 재시도하지 않습니다.")
                        try:
                            result = schema_type.model_validate(envelope["structured_output"]).model_dump()
                        except (ValueError, KeyError, TypeError):
                            raise ProviderResponseError("Claude 구조화 결과 검증 실패") from None
                        usage = envelope.get("usage", {})
                        if not isinstance(usage, dict) or any(
                            type(usage.get(key, 0)) is not int or not 0 <= usage.get(key, 0) <= 10_000_000
                            for key in ("input_tokens", "output_tokens")
                        ):
                            raise ProviderResponseError("Claude 사용량 응답 확인 실패")
                        self.last_usage = {"prompt_tokens": usage.get("input_tokens", 0),
                                           "completion_tokens": usage.get("output_tokens", 0)}
                        self.last_usage["total_tokens"] = sum(self.last_usage.values())
                        return result
        except OSError:
            raise ProviderUnavailableError("Claude Code 실행 파일을 확인하세요.") from None
        finally:
            self.last_elapsed_ms = int((time.monotonic() - started) * 1000)
            with self.control:
                self.cancel_event = None
            self.lock.release()

    def analyze(self, evidence: dict, options: Options) -> dict:
        return self._request({"evidence": evidence}, Analysis, ANALYSIS_INSTRUCTION, options)

    def complete(self, evidence: dict, duration: int, options: Options) -> dict:
        return self._request({"duration": duration, "evidence": evidence}, Script, SCRIPT_INSTRUCTION, options)


class ClaudeLogin:
    """One explicitly requested official login window; never captures its streams."""

    def __init__(self):
        self.lock = Lock()
        self.process = None

    def check(self):
        if not self.lock.acquire(blocking=False):
            return connection_state("checking")
        try:
            if self.process is not None and self.process.poll() is None:
                return connection_state("login_running", installed=True)
            exit_code = self.process.poll() if self.process is not None else None
            self.process = None
            result = ClaudeCodeProvider.status()
            if exit_code not in (None, 0) and result["state"] == "login_required":
                return connection_state("login_cancelled", installed=True, version=result["version"])
            return result
        finally:
            self.lock.release()

    def start(self, *, consent=False):
        if not consent:
            raise ValueError("공식 로그인 창 열기에 동의해 주세요.")
        if not self.lock.acquire(blocking=False):
            return connection_state("checking")
        try:
            if self.process is not None and self.process.poll() is None:
                return connection_state("login_running", installed=True)
            result = ClaudeCodeProvider.status()
            # No re-login when ready or another valid authentication method is present.
            if result["state"] != "login_required":
                return result
            if os.name != "nt":
                return connection_state("manual_login", installed=True)
            path = cli_path()
            if path is None:
                return connection_state("not_installed")
            self.process = subprocess.Popen(
                [str(path), "auth", "login"], cwd=str(Path.home()), env=os.environ.copy(),
                shell=False, creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            return connection_state("login_started", installed=True)
        except OSError:
            return connection_state("login_failed", installed=True)
        finally:
            self.lock.release()


CLAUDE_PROVIDER = ClaudeCodeProvider()
CLAUDE_LOGIN = ClaudeLogin()
