"""AI API key storage for the GUI: current-user Windows DPAPI file or environment variable.

The key is never written to the database, logs, templates or error messages. Outside
Windows no cipher is available, so saving fails closed and only the environment
variable remains. Tests inject a fake cipher; the production path uses the same
DPAPI wrapper as the synthetic credential vault.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Protocol

ENV_NAME = "NEWSFLOW_AI_API_KEY"
_FILE = "ai-key.dpapi"
_KEY = re.compile(r"[A-Za-z0-9_\-.:]{20,256}\Z")


class CredentialError(Exception):
    """Safe message only; never includes key material or native error text."""


class Cipher(Protocol):
    def protect(self, payload: bytearray, entropy: bytearray) -> bytearray: ...
    def unprotect(self, payload: bytearray, entropy: bytearray) -> bytearray: ...


def _entropy(label: bytes = b"NewsFlowAI:Phase5C:ai-api-key") -> bytearray:
    return bytearray(hashlib.sha256(label).digest())


def _native_cipher() -> Cipher:
    if sys.platform != "win32":
        raise CredentialError("키 저장은 Windows 계정 보호 저장소(DPAPI)가 있는 Windows에서만 지원합니다.")
    from newsflow.oauth.vault import _DPAPI, VaultError

    try:
        native = _DPAPI()
    except VaultError:
        raise CredentialError("Windows 계정 보호 저장소를 사용할 수 없습니다.") from None

    class Wrapped:
        def protect(self, payload: bytearray, entropy: bytearray) -> bytearray:
            try:
                return native.protect(payload, entropy)
            except VaultError:
                raise CredentialError("키를 보호 저장소에 저장하지 못했습니다.") from None

        def unprotect(self, payload: bytearray, entropy: bytearray) -> bytearray:
            try:
                return native.unprotect(payload, entropy)
            except VaultError:
                raise CredentialError("저장된 키를 읽지 못했습니다. 키를 다시 저장하세요.") from None

    return Wrapped()


class AIKeyStore:
    # Subclasses (Phase 5D video provider key) change only these constants.
    FILE = _FILE
    ENV = ENV_NAME
    PATTERN = _KEY
    ENTROPY = b"NewsFlowAI:Phase5C:ai-api-key"
    FORMAT_MESSAGE = "API 키 형식을 확인하세요. 공백 없이 20자 이상이어야 합니다."

    def __init__(self, data_dir: Path, cipher: Cipher | None = None) -> None:
        self.path = data_dir / self.FILE
        self._cipher = cipher

    def _get_cipher(self) -> Cipher:
        if self._cipher is None:
            self._cipher = _native_cipher()
        return self._cipher

    @classmethod
    def validate(cls, key: str) -> str:
        key = key.strip()
        if not cls.PATTERN.fullmatch(key):
            raise CredentialError(cls.FORMAT_MESSAGE)
        return key

    def status(self) -> dict:
        stored = self.path.is_file() and not self.path.is_symlink()
        environment = bool(os.environ.get(self.ENV, "").strip())
        source = "stored" if stored else "environment" if environment else None
        return {
            "configured": source is not None, "source": source, "stored": stored, "environment": environment,
            "storage_supported": sys.platform == "win32" or self._cipher is not None,
        }

    def key(self) -> str:
        """Stored GUI key wins over the environment so a cleared key is really cleared."""
        if self.path.is_file() and not self.path.is_symlink():
            payload = bytearray(self.path.read_bytes())
            if not 0 < len(payload) <= 8192:
                raise CredentialError("저장된 키 파일이 손상되었습니다. 키를 다시 저장하세요.")
            plain = self._get_cipher().unprotect(payload, _entropy(self.ENTROPY))
            try:
                return self.validate(bytes(plain).decode("utf-8"))
            except UnicodeDecodeError:
                raise CredentialError("저장된 키 파일이 손상되었습니다. 키를 다시 저장하세요.") from None
            finally:
                for index in range(len(plain)):
                    plain[index] = 0
        return os.environ.get(self.ENV, "").strip()

    def save(self, key: str) -> None:
        key = self.validate(key)
        cipher = self._get_cipher()
        plain = bytearray(key.encode("utf-8"))
        try:
            protected = cipher.protect(plain, _entropy(self.ENTROPY))
        finally:
            for index in range(len(plain)):
                plain[index] = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.FILE + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(bytes(protected))
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt":
                temporary.chmod(0o600)
            os.replace(temporary, self.path)
        except FileExistsError:
            raise CredentialError("다른 저장 작업이 진행 중입니다. 잠시 후 다시 시도하세요.") from None
        except OSError:
            temporary.unlink(missing_ok=True)
            raise CredentialError("키 파일을 저장하지 못했습니다. 데이터 폴더 권한을 확인하세요.") from None

    def clear(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            raise CredentialError("키 파일을 삭제하지 못했습니다. 데이터 폴더 권한을 확인하세요.") from None


class AnthropicKeyStore(AIKeyStore):
    """Anthropic API credentials are separate from OpenAI and Claude Code login."""

    FILE = "anthropic-api-key.dpapi"
    ENV = "NEWSFLOW_ANTHROPIC_API_KEY"
    ENTROPY = b"NewsFlowAI:Step3:anthropic-api-key"


class FakeCipher:
    """Deterministic reversible transform for tests; not a real cipher."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def protect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        if self.fail:
            raise CredentialError("키를 보호 저장소에 저장하지 못했습니다.")
        return bytearray(b"FAKE" + bytes(b ^ 0x5A for b in payload))

    def unprotect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        if self.fail or not payload.startswith(b"FAKE"):
            raise CredentialError("저장된 키를 읽지 못했습니다. 키를 다시 저장하세요.")
        return bytearray(b ^ 0x5A for b in payload[4:])
