"""Official local Claude Code CLI adapter. Never reads or copies authentication files."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
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
            if not key.upper().startswith(("ANTHROPIC_", "CLAUDE_", "CLAUDECODE"))
            and not key.upper().endswith(("_KEY", "_TOKEN", "_PASSWORD", "_SECRET"))}


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
        path = cli_path()
        if path is None:
            return {"installed": False, "ready": False, "message": "Claude Code CLI 미설치 또는 경로 미확인"}
        try:
            version = subprocess.run([str(path), "--version"], capture_output=True, timeout=10,
                                     env=cli_env(), shell=False, check=False)
            match = re.search(rb"(\d+)\.(\d+)\.(\d+)", version.stdout[:4096])
            if version.returncode or not match or tuple(map(int, match.groups())) < (2, 1, 259):
                raise ValueError
            auth = subprocess.run([str(path), "auth", "status"], capture_output=True, timeout=10,
                                  env=cli_env(), shell=False, check=False)
            if len(auth.stdout) > 16384:
                raise ValueError
            value = json.loads(auth.stdout)
            if not isinstance(value, dict):
                raise TypeError
            ready = auth.returncode == 0 and value.get("loggedIn") is True and value.get("authMethod") == "claude.ai"
            return {"installed": True, "ready": ready, "version": match.group().decode(),
                    "message": "Claude 구독 인증 확인" if ready else "공식 CLI에서 Claude 구독 로그인이 필요합니다"}
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError):
            return {"installed": True, "ready": False, "message": "CLI 버전·인증 확인 실패 (2.1.259 이상 필요)"}

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


CLAUDE_PROVIDER = ClaudeCodeProvider()
