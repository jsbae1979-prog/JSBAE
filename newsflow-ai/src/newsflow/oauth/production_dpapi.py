"""Separate production DPAPI file kernel; real credential entry points are closed.

The public production facade does no filesystem or crypto work in this phase.
Only the explicit synthetic facade exercises the kernel, with NF-prefixed test
credentials. The old Phase 4B-1 synthetic vault is not modified. Directory/file
locks coordinate cooperating processes; Windows deletion additionally keeps an
exclusive native file handle until authenticated, conditional deletion finishes.
Python immutable secret strings cannot guarantee deterministic memory erasure.
"""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import os
import re
import stat
import struct
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Protocol
from uuid import uuid4

from filelock import FileLock

from newsflow.publishing.auth import TokenBundle

from .activation import production_activation_status, require_production_activation
from .contracts import OAuthBlocked, account_key_valid
from .vault import _DPAPI, _clear, _synthetic

_HEX = re.compile(r"[a-f0-9]{32}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_HEADER = b"NF-PRODUCTION-DPAPI\x00\x01"
_MAX_PLAINTEXT = 32768
_MAX_CIPHERTEXT = 131072
_MAX_FILE = _MAX_CIPHERTEXT + 4096
_MAX_INVENTORY = 1000
_ERROR = "운영 인증정보 보관 요청을 안전하게 처리할 수 없습니다. 비밀값은 표시되지 않습니다."


class ProductionVaultError(Exception):
    def __init__(self) -> None:
        super().__init__(_ERROR)


class CipherProtector(Protocol):
    def protect(self, payload: bytearray, entropy: bytearray) -> bytearray: ...
    def unprotect(self, payload: bytearray, entropy: bytearray) -> bytearray: ...


@dataclass(frozen=True)
class CiphertextEvidence:
    reference: str = field(repr=False)
    account_key: str
    identity_digest: str = field(repr=False)
    operation_id: str = field(repr=False)
    file_digest: str = field(repr=False)
    owner_digest: str = field(repr=False)
    pending_filename: str | None = field(default=None, repr=False)


class FakeProductionCipherProtector:
    """Authenticated synthetic test transform, never a production crypto backend.

    This exists solely to run recovery/transaction tests on Cloud. Native Windows
    tests instead use CryptProtectData and CryptUnprotectData. No public production
    entry point accepts this protector or any other activation bypass.
    """

    def __init__(self, test_key: bytes | None = None) -> None:
        self._key = test_key if test_key is not None else os.urandom(32)
        if not isinstance(self._key, bytes) or len(self._key) != 32:
            raise ProductionVaultError()

    def _transform(self, payload: bytes | bytearray, entropy: bytearray, nonce: bytes) -> bytearray:
        output = bytearray(len(payload))
        for offset in range(0, len(payload), 32):
            block = hmac.digest(self._key, bytes(entropy) + nonce + struct.pack(">I", offset // 32), "sha256")
            for index, value in enumerate(payload[offset:offset + 32]):
                output[offset + index] = value ^ block[index]
        return output

    def protect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        nonce = os.urandom(16)
        encoded = self._transform(payload, entropy, nonce)
        tag = hmac.digest(self._key, bytes(entropy) + nonce + encoded, "sha256")
        return bytearray(b"NF-FAKE-CIPHER\x00" + nonce + tag + encoded)

    def unprotect(self, payload: bytearray, entropy: bytearray) -> bytearray:
        prefix = b"NF-FAKE-CIPHER\x00"
        start = len(prefix)
        if not payload.startswith(prefix) or len(payload) <= start + 48:
            raise ProductionVaultError()
        nonce = bytes(payload[start:start + 16])
        tag = bytes(payload[start + 16:start + 48])
        encoded = payload[start + 48:]
        if not hmac.compare_digest(tag, hmac.digest(self._key, bytes(entropy) + nonce + encoded, "sha256")):
            raise ProductionVaultError()
        return self._transform(encoded, entropy, nonce)


def _checked_hex(value: str, *, digest: bool = False) -> str:
    if not isinstance(value, str) or not (_DIGEST if digest else _HEX).fullmatch(value):
        raise ProductionVaultError()
    return value


def _owner_sid() -> str:
    """Get the effective thread/process user SID, not an environment username."""
    if sys.platform != "win32":
        raise ProductionVaultError()
    token = ctypes.c_void_p()
    sid_text = ctypes.c_wchar_p()
    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.GetCurrentThread.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree.restype = ctypes.c_void_p
        advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
        advapi.OpenThreadToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                          ctypes.POINTER(ctypes.c_void_p)]
        advapi.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                               ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        if not advapi.OpenThreadToken(kernel.GetCurrentThread(), 0x0008, True, ctypes.byref(token)) and (
            ctypes.get_last_error() != 1008 or not advapi.OpenProcessToken(
                kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)
            )
        ):
            raise ProductionVaultError()
        required = ctypes.c_uint32()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))
        if not 0 < required.value <= 65536:
            raise ProductionVaultError()
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi.GetTokenInformation(token, 1, buffer, required, ctypes.byref(required)):
            raise ProductionVaultError()
        sid_pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        if not advapi.ConvertSidToStringSidW(sid_pointer, ctypes.byref(sid_text)):
            raise ProductionVaultError()
        value = sid_text.value
        if not isinstance(value, str) or not re.fullmatch(r"S-1-(?:[0-9]+-){1,15}[0-9]+", value):
            raise ProductionVaultError()
        return value
    except Exception:  # noqa: BLE001 - never expose native errors, SID or paths
        raise ProductionVaultError() from None
    finally:
        if sid_text:
            kernel.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if token:
            kernel.CloseHandle(token)


def _directory(root: Path, *, create: bool) -> Path:
    if not root.is_absolute() or ".." in root.parts:
        raise ProductionVaultError()
    if sys.platform == "win32" and not re.fullmatch(r"[A-Za-z]:", root.drive):
        # Local Windows drive only; no UNC, device namespace or network vault.
        raise ProductionVaultError()
    for component in (*reversed(root.parents), root):
        if component.is_symlink() or component.is_junction():
            raise ProductionVaultError()
        if component.exists():
            info = component.lstat()
            if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ProductionVaultError()
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir():
        raise ProductionVaultError()
    return root


@contextmanager
def _cipher_stream(path: Path, *, deleting: bool = False, native: bool = False) -> Iterator[BinaryIO]:
    """Exclusive native Windows handle prevents replacement during validated deletion."""
    # File-handle semantics follow the OS, independently of the chosen cipher.
    # Windows cannot unlink a CRT-open file. Even explicit fake-crypto tests
    # must validate and delete through the same exclusive Windows handle.
    if native or sys.platform == "win32":
        import msvcrt  # Windows-only import; explicit fake Cloud tests never use it.

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                      ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        kernel.CreateFileW.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.SetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                                       ctypes.c_uint32]
        kernel.GetFinalPathNameByHandleW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                                    ctypes.c_uint32, ctypes.c_uint32]
        kernel.GetFinalPathNameByHandleW.restype = ctypes.c_uint32
        access = 0x80000000 | (0x00010000 if deleting else 0)  # GENERIC_READ, DELETE
        handle = kernel.CreateFileW(str(path), access, 0, None, 3, 0x00200080, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ProductionVaultError()
        try:
            # Revalidate the opened handle, closing an ancestor-reparse race
            # between pathname inspection and CreateFileW.
            final_path = ctypes.create_unicode_buffer(32768)
            count = kernel.GetFinalPathNameByHandleW(handle, final_path, len(final_path), 0)
            opened = final_path.value.removeprefix("\\\\?\\")
            if not 0 < count < len(final_path) or os.path.normcase(opened) != os.path.normcase(str(path)):
                raise ProductionVaultError()
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except Exception:  # noqa: BLE001 - handle ownership never leaks a native error
            kernel.CloseHandle(handle)
            raise ProductionVaultError() from None
        with os.fdopen(descriptor, "rb") as stream:
            yield stream
            if deleting:
                disposition = ctypes.c_ubyte(1)  # FILE_DISPOSITION_INFO.DeleteFile is BOOLEAN.
                if not kernel.SetFileInformationByHandle(handle, 4, ctypes.byref(disposition),
                                                          ctypes.sizeof(disposition)):
                    raise ProductionVaultError()
    else:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(path, flags), "rb") as stream:
            before = os.fstat(stream.fileno())
            yield stream
            if deleting:
                after = path.lstat()
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
                ):
                    raise ProductionVaultError()
                path.unlink()


class _ProductionDPAPIFileKernel:
    """Shared file implementation; production is dormant and tests remain NF-only."""

    def __init__(
        self, root: Path, protector: CipherProtector, owner_sid: str, *, native: bool, synthetic_only: bool,
    ) -> None:
        self._root = _directory(Path(root), create=True)
        self._protector, self._native = protector, native
        self._synthetic_only = synthetic_only
        self._owner_digest = hashlib.sha256(("NewsFlowAI:WindowsUser:" + owner_sid).encode()).hexdigest()
        self._lock = FileLock(str(self._root / ".production-vault.lock"), timeout=5)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        _directory(self._root, create=False)
        path = self._root / ".production-vault.lock"
        if path.is_symlink() or path.is_junction():
            raise ProductionVaultError()
        if path.exists():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ProductionVaultError()
        with self._lock:
            _directory(self._root, create=False)
            if path.is_symlink() or path.is_junction():
                raise ProductionVaultError()
            yield

    def _path(self, reference: str) -> Path:
        _checked_hex(reference)
        _directory(self._root, create=False)
        path = self._root / (reference + ".pcred")
        if path.is_symlink() or path.is_junction():
            raise ProductionVaultError()
        return path

    def _pending_path(self, filename: str) -> Path:
        if not isinstance(filename, str) or not re.fullmatch(r"\.[a-f0-9]{32}\.[a-f0-9]{32}\.pending", filename):
            raise ProductionVaultError()
        _directory(self._root, create=False)
        path = self._root / filename
        if path.is_symlink() or path.is_junction():
            raise ProductionVaultError()
        return path

    def _owned_link_pair(self, reference: str, info: os.stat_result) -> bool:
        """Recognize only the exact writer-owned temp/final pair left after a crash."""
        if info.st_nlink != 2:
            return info.st_nlink == 1
        final = self._path(reference)
        if not final.is_file():
            return False
        final_info = final.lstat()
        if (final_info.st_dev, final_info.st_ino) != (info.st_dev, info.st_ino):
            return False
        matches = []
        for path in self._root.glob("." + reference + ".*.pending"):
            pending = self._pending_path(path.name)
            pending_info = pending.lstat()
            if (pending_info.st_dev, pending_info.st_ino) == (info.st_dev, info.st_ino):
                matches.append(path)
        return len(matches) == 1

    def _metadata(self, account_key: str, identity_digest: str, reference: str, operation_id: str) -> dict:
        if not account_key_valid(account_key):
            raise ProductionVaultError()
        _checked_hex(identity_digest, digest=True)
        _checked_hex(reference)
        _checked_hex(operation_id)
        return {"version": 1, "account_key": account_key, "identity_digest": identity_digest,
                "reference": reference, "operation_id": operation_id, "owner_digest": self._owner_digest}

    @staticmethod
    def _canonical(value: dict) -> bytes:
        return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")

    @staticmethod
    def _bundle(bundle: TokenBundle, *, check_expiry: bool) -> None:
        if not isinstance(bundle, TokenBundle) or bundle.expires_at.tzinfo is None:
            raise ProductionVaultError()
        values = [bundle.access_token.get_secret_value()]
        if bundle.refresh_token is not None:
            values.append(bundle.refresh_token.get_secret_value())
        if not all(isinstance(value, str) and 1 <= len(value) <= 4096 and not any(
            ord(char) < 0x20 or ord(char) == 0x7F for char in value
        ) for value in values):
            raise ProductionVaultError()
        if len(bundle.scopes) > 20 or any(not isinstance(scope, str) or not scope or len(scope) > 512
                                         for scope in bundle.scopes):
            raise ProductionVaultError()
        if len(set(bundle.scopes)) != len(bundle.scopes):
            raise ProductionVaultError()
        if check_expiry and bundle.expires_at <= datetime.now(UTC):
            raise ProductionVaultError()

    def write_reserved(
        self, account_key: str, identity_digest: str, reference: str, bundle: TokenBundle, *, operation_id: str,
    ) -> None:
        self._bundle(bundle, check_expiry=True)
        if self._synthetic_only:
            _synthetic(bundle)
        metadata = self._metadata(account_key, identity_digest, reference, operation_id)
        value = {**metadata, "access_token": bundle.access_token.get_secret_value(),
                 "refresh_token": bundle.refresh_token.get_secret_value() if bundle.refresh_token else None,
                 "expires_at": bundle.expires_at.astimezone(UTC).isoformat(), "scopes": list(bundle.scopes)}
        value["integrity"] = hashlib.sha256(self._canonical(value)).hexdigest()
        plaintext = bytearray(self._canonical(value))
        entropy = bytearray(hashlib.sha256(self._canonical(metadata)).digest())
        ciphertext = bytearray()
        temporary = None
        owned = False
        try:
            if len(plaintext) > _MAX_PLAINTEXT:
                raise ProductionVaultError()
            with self._locked():
                destination = self._path(reference)
                ciphertext = self._protector.protect(plaintext, entropy)
                if not 0 < len(ciphertext) <= _MAX_CIPHERTEXT:
                    raise ProductionVaultError()
                header = self._canonical(metadata)
                temporary = self._root / ("." + reference + "." + uuid4().hex + ".pending")
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                descriptor = os.open(temporary, flags, 0o600)
                owned = True
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(_HEADER + struct.pack(">I", len(header)) + header + ciphertext)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Exclusive immutable publication; no overwrite or rename replacement.
                os.link(temporary, destination)
        except Exception:  # noqa: BLE001 - redact crypto, file, lock and path errors
            raise ProductionVaultError() from None
        finally:
            _clear(plaintext)
            _clear(entropy)
            _clear(ciphertext)
            if temporary is not None and owned:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    raise ProductionVaultError() from None

    def _decode(
        self, stream: BinaryIO, reference: str, *, account_key: str | None = None,
        identity_digest: str | None = None, check_expiry: bool = False,
    ) -> tuple[TokenBundle, CiphertextEvidence]:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or not self._owned_link_pair(reference, info) or not 0 < info.st_size <= _MAX_FILE:
            raise ProductionVaultError()
        if getattr(info, "st_file_attributes", 0) & 0x400:
            raise ProductionVaultError()
        raw = bytearray(stream.read(_MAX_FILE + 1))
        plaintext = bytearray()
        entropy = bytearray()
        ciphertext = bytearray()
        try:
            prefix = len(_HEADER)
            if len(raw) <= prefix + 4 or len(raw) > _MAX_FILE or not raw.startswith(_HEADER):
                raise ProductionVaultError()
            header_size = struct.unpack(">I", raw[prefix:prefix + 4])[0]
            if not 0 < header_size <= 2048 or len(raw) <= prefix + 4 + header_size:
                raise ProductionVaultError()
            metadata = json.loads(raw[prefix + 4:prefix + 4 + header_size])
            if not isinstance(metadata, dict) or set(metadata) != {
                "version", "account_key", "identity_digest", "reference", "operation_id", "owner_digest"
            }:
                raise ProductionVaultError()
            expected = self._metadata(metadata["account_key"], metadata["identity_digest"],
                                      reference, metadata["operation_id"])
            if type(metadata["version"]) is not int or metadata != expected:
                raise ProductionVaultError()
            if account_key is not None and metadata["account_key"] != account_key:
                raise ProductionVaultError()
            if identity_digest is not None and not hmac.compare_digest(metadata["identity_digest"], identity_digest):
                raise ProductionVaultError()
            ciphertext = raw[prefix + 4 + header_size:]
            if not 0 < len(ciphertext) <= _MAX_CIPHERTEXT:
                raise ProductionVaultError()
            entropy = bytearray(hashlib.sha256(self._canonical(metadata)).digest())
            plaintext = self._protector.unprotect(ciphertext, entropy)
            if not 0 < len(plaintext) <= _MAX_PLAINTEXT:
                raise ProductionVaultError()
            value = json.loads(plaintext)
            if not isinstance(value, dict) or set(value) != set(metadata) | {
                "access_token", "refresh_token", "expires_at", "scopes", "integrity"
            }:
                raise ProductionVaultError()
            integrity = value.pop("integrity")
            if not isinstance(integrity, str) or not hmac.compare_digest(
                hashlib.sha256(self._canonical(value)).hexdigest(), integrity
            ) or any(value[key] != entry for key, entry in metadata.items()):
                raise ProductionVaultError()
            bundle = TokenBundle.model_validate({key: value[key] for key in (
                "access_token", "refresh_token", "expires_at", "scopes"
            )})
            self._bundle(bundle, check_expiry=check_expiry)
            if self._synthetic_only:
                _synthetic(bundle, check_expiry=check_expiry)
            return bundle, CiphertextEvidence(reference, metadata["account_key"], metadata["identity_digest"],
                                               metadata["operation_id"], hashlib.sha256(raw).hexdigest(),
                                               self._owner_digest)
        except Exception:  # noqa: BLE001 - no plaintext, metadata or attacker errors escape
            raise ProductionVaultError() from None
        finally:
            _clear(raw)
            _clear(plaintext)
            _clear(entropy)
            _clear(ciphertext)

    def read(
        self, account_key: str, identity_digest: str, reference: str, *, check_expiry: bool,
    ) -> TokenBundle:
        if not account_key_valid(account_key):
            raise ProductionVaultError()
        _checked_hex(identity_digest, digest=True)
        try:
            with self._locked(), _cipher_stream(self._path(reference), native=self._native) as stream:
                bundle, _ = self._decode(stream, reference, account_key=account_key,
                                         identity_digest=identity_digest, check_expiry=check_expiry)
                return bundle
        except Exception:  # noqa: BLE001 - redact native/file errors
            raise ProductionVaultError() from None

    def delete(
        self, account_key: str, identity_digest: str, reference: str,
        *, expected_file_digest: str | None = None, expected_operation_id: str | None = None,
    ) -> None:
        if not account_key_valid(account_key):
            raise ProductionVaultError()
        _checked_hex(identity_digest, digest=True)
        if expected_file_digest is not None:
            _checked_hex(expected_file_digest, digest=True)
        if expected_operation_id is not None:
            _checked_hex(expected_operation_id)
        try:
            with self._locked(), _cipher_stream(self._path(reference), deleting=True, native=self._native) as stream:
                _, evidence = self._decode(stream, reference, account_key=account_key, identity_digest=identity_digest)
                if expected_file_digest is not None and not hmac.compare_digest(
                    evidence.file_digest, expected_file_digest
                ):
                    raise ProductionVaultError()
                if expected_operation_id is not None and evidence.operation_id != expected_operation_id:
                    raise ProductionVaultError()
        except Exception:  # noqa: BLE001 - no account, reference or path is disclosed
            raise ProductionVaultError() from None

    def inventory(self) -> tuple[CiphertextEvidence, ...]:
        result = []
        try:
            with self._locked():
                paths = list(self._root.glob("*.pcred"))
                if len(paths) > _MAX_INVENTORY:
                    raise ProductionVaultError()
                for path in sorted(paths):
                    reference = path.stem
                    _checked_hex(reference)
                    with _cipher_stream(self._path(reference), native=self._native) as stream:
                        _, evidence = self._decode(stream, reference)
                        result.append(evidence)
            return tuple(result)
        except Exception:  # noqa: BLE001 - corrupt/foreign files stop cleanup; nothing is deleted
            raise ProductionVaultError() from None

    def reference_exists(self, reference: str) -> bool:
        try:
            with self._locked():
                return self._path(reference).exists()
        except Exception:  # noqa: BLE001 - existence queries cannot disclose filesystem errors
            raise ProductionVaultError() from None

    def pending_inventory(self) -> tuple[CiphertextEvidence, ...]:
        """Authenticate crash-left temporary ciphertexts without modifying anything."""
        result = []
        try:
            with self._locked():
                paths = list(self._root.glob(".*.pending"))
                if len(paths) > _MAX_INVENTORY:
                    raise ProductionVaultError()
                for path in sorted(paths):
                    pending = self._pending_path(path.name)
                    reference = path.name.split(".")[1]
                    with _cipher_stream(pending, native=self._native) as stream:
                        _, item = self._decode(stream, reference)
                        result.append(CiphertextEvidence(item.reference, item.account_key, item.identity_digest,
                                                         item.operation_id, item.file_digest, item.owner_digest,
                                                         path.name))
            return tuple(result)
        except Exception:  # noqa: BLE001 - incomplete or foreign files are quarantined
            raise ProductionVaultError() from None

    def cleanup_pending(
        self, pending_filename: str, account_key: str, identity_digest: str,
        expected_file_digest: str, expected_operation_id: str,
    ) -> None:
        _checked_hex(identity_digest, digest=True)
        _checked_hex(expected_file_digest, digest=True)
        _checked_hex(expected_operation_id)
        try:
            with self._locked(), _cipher_stream(self._pending_path(pending_filename), deleting=True,
                                             native=self._native) as stream:
                reference = pending_filename.split(".")[1]
                _, evidence = self._decode(stream, reference, account_key=account_key, identity_digest=identity_digest)
                if not hmac.compare_digest(evidence.file_digest, expected_file_digest) or evidence.operation_id != expected_operation_id:
                    raise ProductionVaultError()
        except Exception:  # noqa: BLE001 - only an authenticated exact operation may delete a temp
            raise ProductionVaultError() from None


class ProductionWindowsCredentialVault:
    """Dormant production interface. Every operation is denied before backend/IO.

    Future activation must review and explicitly open the phase gate and its
    fixed readiness state; environment variables and GUI flags cannot enable it.
    """

    def __init__(self, root: Path) -> None:
        self._root = root  # No coercion, directory creation, SID, DPAPI or other I/O.
        self._kernel: _ProductionDPAPIFileKernel | None = None

    def _backend(self) -> _ProductionDPAPIFileKernel:
        """Dormant native backend; the phase gate runs before every credential access."""
        require_production_activation()
        if production_activation_status()["production_storage_allowed"] is not True:
            # A replacement gate alone cannot accidentally enable persistence.
            raise OAuthBlocked()
        if sys.platform != "win32":
            raise ProductionVaultError()
        try:
            if self._kernel is None:
                self._kernel = _ProductionDPAPIFileKernel(
                    Path(self._root), _DPAPI(), _owner_sid(), native=True, synthetic_only=False,
                )
            return self._kernel
        except Exception:  # noqa: BLE001 - never relay production native/path errors
            raise ProductionVaultError() from None

    def reserve_reference(self) -> str:
        self._backend()
        return uuid4().hex

    def store(self, account_key: str, identity_digest: str, bundle: TokenBundle) -> str:
        backend = self._backend()
        reference = uuid4().hex
        backend.write_reserved(account_key, identity_digest, reference, bundle, operation_id=uuid4().hex)
        return reference

    def write_reserved(
        self, account_key: str, identity_digest: str, reference: str, bundle: TokenBundle, *, operation_id: str,
    ) -> None:
        self._backend().write_reserved(account_key, identity_digest, reference, bundle, operation_id=operation_id)

    def load(self, account_key: str, identity_digest: str, reference: str, *, allow_expired: bool = False) -> TokenBundle:
        return self._backend().read(account_key, identity_digest, reference, check_expiry=not allow_expired)

    def delete(self, account_key: str, identity_digest: str, reference: str) -> None:
        self._backend().delete(account_key, identity_digest, reference)

    def inventory(self) -> tuple[CiphertextEvidence, ...]:
        return self._backend().inventory()

    def reference_exists(self, reference: str) -> bool:
        return self._backend().reference_exists(reference)

    def pending_inventory(self) -> tuple[CiphertextEvidence, ...]:
        return self._backend().pending_inventory()

    def cleanup_pending(
        self, pending_filename: str, account_key: str, identity_digest: str,
        expected_file_digest: str, expected_operation_id: str,
    ) -> None:
        self._backend().cleanup_pending(pending_filename, account_key, identity_digest,
                                         expected_file_digest, expected_operation_id)

    def cleanup_orphan(
        self, reference: str, account_key: str, identity_digest: str, expected_file_digest: str,
        expected_operation_id: str,
    ) -> None:
        self._backend().delete(account_key, identity_digest, reference, expected_file_digest=expected_file_digest,
                                expected_operation_id=expected_operation_id)


class SyntheticProductionCredentialVault:
    """Explicit NF-only exercises of the separate production kernel.

    Native mode requires real Windows current-user DPAPI; it never silently falls
    back. Portable mode accepts only the known synthetic test protector and a
    synthetic owner label. No caller-provided crypto can accept real service data.
    """

    def __init__(
        self, root: Path, *, protector: FakeProductionCipherProtector | None = None, owner_sid: str | None = None,
    ) -> None:
        try:
            if protector is None:
                if owner_sid is not None or sys.platform != "win32":
                    raise ProductionVaultError()
                backend, sid, native = _DPAPI(), _owner_sid(), True
            else:
                if type(protector) is not FakeProductionCipherProtector or not isinstance(owner_sid, str) or not re.fullmatch(
                    r"NF-TEST-SID-[A-Za-z0-9_-]{1,100}", owner_sid
                ):
                    raise ProductionVaultError()
                backend, sid, native = protector, owner_sid, False
            self._kernel = _ProductionDPAPIFileKernel(root, backend, sid, native=native, synthetic_only=True)
        except Exception:  # noqa: BLE001 - no SID, file path or native exception leaks
            raise ProductionVaultError() from None

    @staticmethod
    def _synthetic_bundle(bundle: TokenBundle, *, check_expiry: bool = True) -> None:
        try:
            _synthetic(bundle, check_expiry=check_expiry)
        except Exception:  # noqa: BLE001 - recognizable synthetic values only
            raise ProductionVaultError() from None

    @staticmethod
    def reserve_reference() -> str:
        return uuid4().hex

    def write_reserved(
        self, account_key: str, identity_digest: str, reference: str, bundle: TokenBundle,
        *, operation_id: str | None = None,
    ) -> None:
        self._synthetic_bundle(bundle)
        self._kernel.write_reserved(account_key, identity_digest, reference, bundle,
                                    operation_id=operation_id if operation_id is not None else uuid4().hex)

    def store(self, account_key: str, identity_digest: str, bundle: TokenBundle) -> str:
        self._synthetic_bundle(bundle)
        reference = self.reserve_reference()
        self.write_reserved(account_key, identity_digest, reference, bundle)
        return reference

    def load(self, account_key: str, identity_digest: str, reference: str, *, allow_expired: bool = False) -> TokenBundle:
        bundle = self._kernel.read(account_key, identity_digest, reference, check_expiry=not allow_expired)
        self._synthetic_bundle(bundle, check_expiry=not allow_expired)
        return bundle

    def delete(self, account_key: str, identity_digest: str, reference: str) -> None:
        # Reject any unexpected real-format ciphertext even before a delete.
        self.load(account_key, identity_digest, reference, allow_expired=True)
        self._kernel.delete(account_key, identity_digest, reference)

    def inventory(self) -> tuple[CiphertextEvidence, ...]:
        evidence = self._kernel.inventory()
        for item in evidence:
            self.load(item.account_key, item.identity_digest, item.reference, allow_expired=True)
        return evidence

    def reference_exists(self, reference: str) -> bool:
        return self._kernel.reference_exists(reference)

    def pending_inventory(self) -> tuple[CiphertextEvidence, ...]:
        return self._kernel.pending_inventory()

    def cleanup_pending(
        self, pending_filename: str, account_key: str, identity_digest: str,
        expected_file_digest: str, expected_operation_id: str,
    ) -> None:
        self._kernel.cleanup_pending(pending_filename, account_key, identity_digest,
                                      expected_file_digest, expected_operation_id)

    def cleanup_orphan(
        self, reference: str, account_key: str, identity_digest: str, expected_file_digest: str,
        expected_operation_id: str,
    ) -> None:
        self.load(account_key, identity_digest, reference, allow_expired=True)
        self._kernel.delete(account_key, identity_digest, reference, expected_file_digest=expected_file_digest,
                             expected_operation_id=expected_operation_id)
