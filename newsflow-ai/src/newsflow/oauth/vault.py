"""Account-bound, synthetic-only credential storage for Phase 4B-1.

The Windows backend uses current-user DPAPI. It is never replaced by a fake
backend on an unsupported platform. Real service credentials remain prohibited.
Native DPAPI buffers and mutable serialization buffers are cleared after use;
Python immutable strings/SecretStr objects cannot promise deterministic erasure.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from newsflow.publishing.auth import TokenBundle

_ACCOUNT = re.compile(r"(?:youtube|instagram):[1-9][0-9]{0,18}\Z")
_REFERENCE = re.compile(r"[a-f0-9]{32}\Z")
_SYNTHETIC = re.compile(r"nf-synthetic-[A-Za-z0-9_-]{1,240}\Z")
_MAX_PLAINTEXT = 32768
_MAX_CIPHERTEXT = 131072
_ERROR = "인증정보 보관 요청을 안전하게 처리할 수 없습니다."


class VaultError(Exception):
    """Intentionally excludes provider errors, paths and credential values."""

    def __init__(self) -> None:
        super().__init__(_ERROR)


class CredentialVault(Protocol):
    def store(self, account_key: str, bundle: TokenBundle) -> str: ...
    def load(self, account_key: str, reference: str, *, allow_expired: bool = False) -> TokenBundle: ...
    def delete(self, account_key: str, reference: str) -> None: ...


def _account(account_key: str) -> str:
    if not isinstance(account_key, str) or not _ACCOUNT.fullmatch(account_key):
        raise VaultError()
    return account_key


def _reference(reference: str) -> str:
    if not isinstance(reference, str) or not _REFERENCE.fullmatch(reference):
        raise VaultError()
    return reference


def _synthetic(bundle: TokenBundle, *, check_expiry: bool = True) -> None:
    try:
        tokens = [bundle.access_token.get_secret_value()]
        if bundle.refresh_token is not None:
            tokens.append(bundle.refresh_token.get_secret_value())
        valid = all(_SYNTHETIC.fullmatch(value) for value in tokens)
        valid = valid and bundle.expires_at.tzinfo is not None
        valid = valid and len(bundle.scopes) <= 20
        valid = valid and all(len(scope) <= 512 for scope in bundle.scopes)
        if check_expiry:
            valid = valid and bundle.expires_at > datetime.now(UTC)
        if not valid:
            raise VaultError()
    except Exception:  # noqa: BLE001 - redact all credential-boundary errors
        raise VaultError() from None


def _entropy(account_key: str) -> bytearray:
    return bytearray(hashlib.sha256(("NewsFlowAI:Phase4B1:" + account_key).encode()).digest())


def _clear(buffer: bytearray) -> None:
    buffer[:] = b"\0" * len(buffer)


def _serialize(account_key: str, bundle: TokenBundle) -> bytearray:
    _synthetic(bundle)
    try:
        value = {
            "version": 1,
            "account_key": account_key,
            "access_token": bundle.access_token.get_secret_value(),
            "refresh_token": (
                bundle.refresh_token.get_secret_value() if bundle.refresh_token is not None else None
            ),
            "expires_at": bundle.expires_at.isoformat(),
            "scopes": list(bundle.scopes),
        }
        canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        value["integrity"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        result = bytearray(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8"))
    except Exception:  # noqa: BLE001 - redact all credential-boundary errors
        raise VaultError() from None
    if len(result) > _MAX_PLAINTEXT:
        _clear(result)
        raise VaultError()
    return result


def _deserialize(account_key: str, payload: bytearray, *, check_expiry: bool) -> TokenBundle:
    try:
        if not payload or len(payload) > _MAX_PLAINTEXT:
            raise VaultError()
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {
            "version", "account_key", "access_token", "refresh_token", "expires_at", "scopes", "integrity"
        }:
            raise VaultError()
        integrity = value.pop("integrity")
        canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if not isinstance(integrity, str) or not hmac.compare_digest(integrity, expected):
            raise VaultError()
        if type(value["version"]) is not int or value["version"] != 1 or value["account_key"] != account_key:
            raise VaultError()
        bundle = TokenBundle.model_validate({
            name: value[name] for name in ("access_token", "refresh_token", "expires_at", "scopes")
        })
        _synthetic(bundle, check_expiry=check_expiry)
        return bundle
    except Exception:  # noqa: BLE001 - redact all credential-boundary errors
        raise VaultError() from None


class FakeCredentialVault:
    """Synthetic in-memory storage, isolated by platform and local account id."""

    def __init__(self) -> None:
        self._bundles: dict[str, tuple[str, TokenBundle]] = {}

    def store(self, account_key: str, bundle: TokenBundle) -> str:
        _account(account_key)
        _synthetic(bundle)
        reference = uuid4().hex
        self._bundles[reference] = (account_key, bundle.model_copy(deep=True))
        return reference

    def _get(self, account_key: str, reference: str, *, check_expiry: bool) -> TokenBundle:
        _account(account_key)
        _reference(reference)
        value = self._bundles.get(reference)
        if value is None or value[0] != account_key:
            raise VaultError()
        bundle = value[1]
        _synthetic(bundle, check_expiry=check_expiry)
        return bundle.model_copy(deep=True)

    def load(self, account_key: str, reference: str, *, allow_expired: bool = False) -> TokenBundle:
        return self._get(account_key, reference, check_expiry=not allow_expired)

    def delete(self, account_key: str, reference: str) -> None:
        self._get(account_key, reference, check_expiry=False)
        del self._bundles[reference]


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class _DPAPI:
    """Current-user DPAPI only; never CRYPTPROTECT_LOCAL_MACHINE."""

    def __init__(self) -> None:
        try:
            self._crypt = ctypes.WinDLL("crypt32", use_last_error=True)  # type: ignore[attr-defined]
            self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            args = [
                ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_DataBlob),
            ]
            for name in ("CryptProtectData", "CryptUnprotectData"):
                function = getattr(self._crypt, name)
                function.argtypes = args
                function.restype = ctypes.c_int
            self._kernel.LocalFree.argtypes = [ctypes.c_void_p]
            self._kernel.LocalFree.restype = ctypes.c_void_p
        except Exception:  # noqa: BLE001 - redact all credential-boundary errors
            raise VaultError() from None

    def _run(self, payload: bytearray, entropy: bytearray, *, decrypt: bool) -> bytearray:
        data_buffer = (ctypes.c_ubyte * len(payload)).from_buffer(payload)
        entropy_buffer = (ctypes.c_ubyte * len(entropy)).from_buffer(entropy)
        data = _DataBlob(len(payload), ctypes.cast(data_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        context = _DataBlob(len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
        output = _DataBlob()
        function = self._crypt.CryptUnprotectData if decrypt else self._crypt.CryptProtectData
        try:
            # CRYPTPROTECT_UI_FORBIDDEN = 1. Absence of LOCAL_MACHINE binds to current user.
            if not function(ctypes.byref(data), None, ctypes.byref(context), None, None, 1,
                            ctypes.byref(output)):
                raise VaultError()
            maximum = _MAX_PLAINTEXT if decrypt else _MAX_CIPHERTEXT
            if not output.pbData or not 0 < output.cbData <= maximum:
                raise VaultError()
            return bytearray(ctypes.string_at(output.pbData, output.cbData))
        except Exception:  # noqa: BLE001 - redact all credential-boundary errors
            raise VaultError() from None
        finally:
            if output.pbData:
                if 0 < output.cbData <= _MAX_CIPHERTEXT:
                    ctypes.memset(output.pbData, 0, output.cbData)
                self._kernel.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))

    def protect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        return self._run(payload, entropy, decrypt=False)

    def unprotect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        return self._run(payload, entropy, decrypt=True)


def _safe_directory(directory: Path, *, create: bool) -> Path:
    if not directory.is_absolute() or ".." in directory.parts:
        raise VaultError()
    # Inspect every parent; resolve() alone would silently follow an existing symlink.
    for component in (*reversed(directory.parents), directory):
        if component.is_symlink() or component.is_junction():
            raise VaultError()
        if component.exists() and not component.is_dir():
            raise VaultError()
    if create:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not directory.is_dir() or directory.is_symlink():
        raise VaultError()
    return directory


class WindowsCredentialVault:
    """Synthetic-only DPAPI ciphertext files under an explicitly supplied data directory."""

    def __init__(self, root: Path) -> None:
        if sys.platform != "win32":
            raise VaultError()
        try:
            self._root = _safe_directory(Path(root), create=True)
            self._dpapi = _DPAPI()
        except Exception:  # noqa: BLE001 - redact all credential-boundary errors
            raise VaultError() from None

    def _path(self, reference: str) -> Path:
        _reference(reference)
        _safe_directory(self._root, create=False)
        path = self._root / (reference + ".bin")
        if path.is_symlink() or path.is_junction():
            raise VaultError()
        return path

    def store(self, account_key: str, bundle: TokenBundle) -> str:
        _account(account_key)
        plaintext = _serialize(account_key, bundle)
        entropy = _entropy(account_key)
        ciphertext = bytearray()
        temporary: Path | None = None
        temporary_owned = False
        try:
            ciphertext = self._dpapi.protect(plaintext, entropy)
            if not ciphertext or len(ciphertext) > _MAX_CIPHERTEXT:
                raise VaultError()
            reference = uuid4().hex
            destination = self._path(reference)
            temporary = self._root / ("." + uuid4().hex + ".tmp")
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(temporary, flags, 0o600)
            temporary_owned = True
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
            # Creating a hard link is atomic and refuses an existing destination;
            # no rename/replace can overwrite another stored credential.
            os.link(temporary, destination)
            return reference
        except Exception:  # noqa: BLE001 - redact all credential-boundary errors
            raise VaultError() from None
        finally:
            _clear(plaintext)
            _clear(entropy)
            _clear(ciphertext)
            if temporary is not None and temporary_owned:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    raise VaultError() from None

    def _read(self, account_key: str, reference: str, *, check_expiry: bool) -> TokenBundle:
        _account(account_key)
        ciphertext = bytearray()
        plaintext = bytearray()
        entropy = _entropy(account_key)
        try:
            path = self._path(reference)
            flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
            with os.fdopen(os.open(path, flags), "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= _MAX_CIPHERTEXT:
                    raise VaultError()
                ciphertext = bytearray(stream.read(_MAX_CIPHERTEXT + 1))
            if not 0 < len(ciphertext) <= _MAX_CIPHERTEXT:
                raise VaultError()
            plaintext = self._dpapi.unprotect(ciphertext, entropy)
            return _deserialize(account_key, plaintext, check_expiry=check_expiry)
        except Exception:  # noqa: BLE001 - redact all credential-boundary errors
            raise VaultError() from None
        finally:
            _clear(ciphertext)
            _clear(plaintext)
            _clear(entropy)

    def load(self, account_key: str, reference: str, *, allow_expired: bool = False) -> TokenBundle:
        return self._read(account_key, reference, check_expiry=not allow_expired)

    def delete(self, account_key: str, reference: str) -> None:
        # Verify ownership even for expired bundles before deleting the opaque file.
        self._read(account_key, reference, check_expiry=False)
        try:
            self._path(reference).unlink()
        except Exception:  # noqa: BLE001 - redact all credential-boundary errors
            raise VaultError() from None
