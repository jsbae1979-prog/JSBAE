"""Native Windows production-kernel tests with disposable synthetic data only.

The alternate principal test is limited to disposable GitHub Actions runners.
Passwords exist only in this process memory, never command arguments/logs/files.
Failure to establish an independent, loaded DPAPI context is NOT VERIFIED; a
foreign ciphertext rejection only counts after its own roundtrip succeeded.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from pydantic import SecretStr

from newsflow.oauth.contracts import OAuthBlocked
from newsflow.oauth.production_dpapi import (
    ProductionVaultError,
    ProductionWindowsCredentialVault,
    SyntheticProductionCredentialVault,
    _owner_sid,
)
from newsflow.oauth.vault import _DPAPI, VaultError, _clear
from newsflow.publishing.auth import TokenBundle

KEY = "youtube:1"
IDENTITY = hashlib.sha256(b"nf-synthetic-native-identity-one").hexdigest()
_STAGE = "platform-check"


def _bundle(suffix: str) -> TokenBundle:
    return TokenBundle(access_token=SecretStr("nf-synthetic-access-" + suffix),
                       refresh_token=SecretStr("nf-synthetic-refresh-" + suffix),
                       expires_at=datetime.now(UTC) + timedelta(hours=1),
                       scopes=("https://www.googleapis.com/auth/youtube.upload",))


def _blocked(action: Callable[[], object], error: type[Exception] = ProductionVaultError) -> None:
    try:
        action()
    except error:
        return
    raise AssertionError("blocked synthetic check unexpectedly allowed")


def _child() -> int:
    try:
        request = json.loads(sys.stdin.read(8193))
        value = SyntheticProductionCredentialVault(Path(request["root"])).load(
            request["account"], request["identity"], request["reference"],
        )
        if hashlib.sha256(value.access_token.get_secret_value().encode()).hexdigest() != request["digest"]:
            return 1
        print(json.dumps({"subprocess_read": "PASS"}))
        return 0
    except Exception:  # noqa: BLE001 - no raw native/path/credential error in child output
        print(json.dumps({"subprocess_read": "FAIL"}))
        return 1


def _restart(root: Path, reference: str, expected: TokenBundle) -> None:
    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child"], shell=False,
        input=json.dumps({"root": str(root), "account": KEY, "identity": IDENTITY, "reference": reference,
                          "digest": hashlib.sha256(expected.access_token.get_secret_value().encode()).hexdigest()}),
        text=True, capture_output=True, timeout=20, check=False,
    )
    if child.returncode != 0 or json.loads(child.stdout) != {"subprocess_read": "PASS"}:
        raise AssertionError("isolated synthetic process read failed")


@contextmanager
def _profile_privileges() -> Iterator[bool]:
    """Temporarily enable already-held process privileges only on the test runner."""
    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", ctypes.c_uint32), ("HighPart", ctypes.c_int32)]

    class TokenPrivileges(ctypes.Structure):
        _fields_ = [("PrivilegeCount", ctypes.c_uint32), ("Luid", Luid), ("Attributes", ctypes.c_uint32)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    advapi.OpenProcessToken.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    advapi.LookupPrivilegeValueW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.POINTER(Luid)]
    advapi.AdjustTokenPrivileges.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                           ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    token = ctypes.c_void_p()
    previous = []
    try:
        ready = bool(advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x28, ctypes.byref(token)))
        if ready:
            for name in ("SeBackupPrivilege", "SeRestorePrivilege"):
                requested, old = TokenPrivileges(), TokenPrivileges()
                requested.PrivilegeCount, requested.Attributes = 1, 2
                if not advapi.LookupPrivilegeValueW(None, name, ctypes.byref(requested.Luid)):
                    ready = False
                    break
                length = ctypes.c_uint32()
                ctypes.set_last_error(0)
                if not advapi.AdjustTokenPrivileges(token, False, ctypes.byref(requested), ctypes.sizeof(old),
                                                   ctypes.byref(old), ctypes.byref(length)):
                    ready = False
                    break
                previous.append(old)
                if ctypes.get_last_error() == 1300:
                    ready = False
                    break
        yield ready
    finally:
        for old in reversed(previous):
            if not advapi.AdjustTokenPrivileges(token, False, ctypes.byref(old), 0, None, None):
                raise AssertionError("temporary test-process privilege restoration failed")
        if token:
            kernel.CloseHandle(token)


def _token_sid(advapi: ctypes.CDLL, kernel: ctypes.CDLL, token: ctypes.c_void_p) -> str:
    """Get an alternate SID for deterministic profile cleanup before impersonation."""
    advapi.GetTokenInformation.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p,
                                          ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    size = ctypes.c_uint32()
    advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
    if not 0 < size.value <= 65536:
        raise AssertionError("alternate principal identity validation failed")
    buffer = ctypes.create_string_buffer(size.value)
    if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
        raise AssertionError("alternate principal identity validation failed")
    pointer = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
    text = ctypes.c_wchar_p()
    try:
        if not advapi.ConvertSidToStringSidW(pointer, ctypes.byref(text)) or not text.value:
            raise AssertionError("alternate principal identity validation failed")
        return text.value
    finally:
        if text:
            kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))


def _alternate_windows_user() -> dict:
    result = {"different_Windows_user_DPAPI": "NOT VERIFIED", "different_user_own_roundtrip": "NOT VERIFIED",
              "alternate_principal_cleanup": "NOT VERIFIED"}
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_OS") != "Windows":
        result["different_user_limitation"] = "Requires a disposable Windows Actions runner; no user PC changes."
        return result

    class UserInfo(ctypes.Structure):
        _fields_ = [("name", ctypes.c_wchar_p), ("password", ctypes.c_wchar_p),
                    ("password_age", ctypes.c_uint32), ("priv", ctypes.c_uint32),
                    ("home_dir", ctypes.c_wchar_p), ("comment", ctypes.c_wchar_p),
                    ("flags", ctypes.c_uint32), ("script_path", ctypes.c_wchar_p)]

    class ProfileInfo(ctypes.Structure):
        _fields_ = [("dwSize", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                    ("lpUserName", ctypes.c_wchar_p), ("lpProfilePath", ctypes.c_wchar_p),
                    ("lpDefaultPath", ctypes.c_wchar_p), ("lpServerName", ctypes.c_wchar_p),
                    ("lpPolicyPath", ctypes.c_wchar_p), ("hProfile", ctypes.c_void_p)]

    net = ctypes.WinDLL("netapi32", use_last_error=True)  # type: ignore[attr-defined]
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    userenv = ctypes.WinDLL("userenv", use_last_error=True)  # type: ignore[attr-defined]
    net.NetUserAdd.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p,
                              ctypes.POINTER(ctypes.c_uint32)]
    net.NetUserAdd.restype = ctypes.c_uint32
    net.NetUserDel.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    net.NetUserDel.restype = ctypes.c_uint32
    advapi.LogonUserW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                 ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    advapi.ImpersonateLoggedOnUser.argtypes = [ctypes.c_void_p]
    advapi.RevertToSelf.argtypes = []
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    userenv.LoadUserProfileW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProfileInfo)]
    userenv.UnloadUserProfile.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    userenv.DeleteProfileW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
    name = "nfVault" + uuid4().hex[:10]
    password = ctypes.create_unicode_buffer("Nf1!" + secrets.token_urlsafe(40))
    info = UserInfo(name, ctypes.cast(password, ctypes.c_wchar_p), 0, 1, None,
                    "Disposable NewsFlow synthetic DPAPI validation", 0x10201, None)
    token = ctypes.c_void_p()
    profile = ProfileInfo()
    profile.dwSize, profile.dwFlags, profile.lpUserName = ctypes.sizeof(profile), 1, name
    created = loaded = impersonated = False
    alternate_sid = None
    plaintext = bytearray(b"nf-synthetic-different-user-DPAPI-proof")
    entropy = bytearray(hashlib.sha256(b"nf-synthetic-production-native-context").digest())
    parent_ciphertext = _DPAPI().protect(plaintext, entropy)
    own_ciphertext = bytearray()
    own_plaintext = bytearray()
    parameter_error = ctypes.c_uint32()
    try:
        status = net.NetUserAdd(None, 1, ctypes.byref(info), ctypes.byref(parameter_error))
        if status != 0:
            result["different_user_limitation"] = "Disposable alternate principal provisioning unavailable."
            return result
        created = True
        if not advapi.LogonUserW(name, ".", password, 2, 0, ctypes.byref(token)):
            result["different_user_limitation"] = "Disposable alternate principal logon unavailable."
            return result
        alternate_sid = _token_sid(advapi, kernel, token)
        with _profile_privileges() as privileges_ready:
            if not privileges_ready or not userenv.LoadUserProfileW(token, ctypes.byref(profile)):
                result["different_user_limitation"] = "Alternate DPAPI user profile could not be loaded with existing process privileges."
                return result
            loaded = True
            try:
                parent_sid = _owner_sid()
                if not advapi.ImpersonateLoggedOnUser(token):
                    result["different_user_limitation"] = "Disposable alternate principal impersonation unavailable."
                    return result
                impersonated = True
                if _owner_sid() != alternate_sid or alternate_sid == parent_sid:
                    raise AssertionError("alternate identity did not change")
                try:
                    own_ciphertext = _DPAPI().protect(plaintext, entropy)
                    own_plaintext = _DPAPI().unprotect(own_ciphertext, entropy)
                except VaultError:
                    result["different_user_limitation"] = "Loaded alternate user DPAPI context could not prove its own roundtrip."
                    return result
                if own_plaintext != plaintext:
                    raise AssertionError("alternate context own roundtrip mismatch")
                result["different_user_own_roundtrip"] = "PASS"
                try:
                    foreign = _DPAPI().unprotect(parent_ciphertext, entropy)
                except VaultError:
                    result["different_Windows_user_DPAPI"] = "PASS"
                else:
                    _clear(foreign)
                    raise AssertionError("different Windows user could decrypt owner ciphertext")
                return result
            finally:
                if impersonated and not advapi.RevertToSelf():
                    raise AssertionError("alternate principal impersonation cleanup failed")
                impersonated = False
                if not userenv.UnloadUserProfile(token, profile.hProfile):
                    raise AssertionError("alternate principal profile unload failed")
                loaded = False
    finally:
        ctypes.memset(password, 0, ctypes.sizeof(password))
        for buffer in (plaintext, entropy, parent_ciphertext, own_ciphertext, own_plaintext):
            _clear(buffer)
        if impersonated and not advapi.RevertToSelf():
            # A failed impersonation revert is a hard failure, not a skipped test.
            raise AssertionError("alternate principal impersonation cleanup failed")
        if loaded and not userenv.UnloadUserProfile(token, profile.hProfile):
            raise AssertionError("alternate principal profile unload failed")
        if token:
            kernel.CloseHandle(token)
        if alternate_sid is not None and not userenv.DeleteProfileW(alternate_sid, None, None) and ctypes.get_last_error() not in (2, 3):
            raise AssertionError("alternate principal profile deletion failed")
        if created:
            if net.NetUserDel(None, name) != 0:
                raise AssertionError("alternate principal deletion failed")
            result["alternate_principal_cleanup"] = "PASS"


def validate() -> dict:
    global _STAGE
    result = {"platform": sys.platform, "credential_kind": "synthetic only", "real_service_tokens": 0,
              "real_oauth_calls": 0, "real_publish_calls": 0, "Windows11_user_PC": "NOT VERIFIED"}
    if sys.platform != "win32":
        result.update(result="NOT VERIFIED", current_user_DPAPI="NOT VERIFIED (requires Windows)")
        return result
    base = Path(os.environ.get("LOCALAPPDATA", ""))
    if not base.is_absolute():
        raise AssertionError("configured LOCALAPPDATA absolute path is required")
    with TemporaryDirectory(prefix="NewsFlow AI 한글 운영 합성-", dir=base) as directory:
        root = Path(directory) / "NewsFlowAI" / "production credentials"
        _STAGE = "native-construction"
        vault = SyntheticProductionCredentialVault(root)
        original = _bundle("native-first")
        reference, operation = vault.reserve_reference(), uuid4().hex
        _STAGE = "native-write-and-read"
        vault.write_reserved(KEY, IDENTITY, reference, original, operation_id=operation)
        assert vault.load(KEY, IDENTITY, reference) == original
        assert b"nf-synthetic-" not in (root / (reference + ".pcred")).read_bytes()
        _STAGE = "new-process-read"
        _restart(root, reference, original)
        result.update(current_user_DPAPI="PASS", separate_production_cipher_kernel="PASS",
                      disk_ciphertext="PASS", same_user_new_process="PASS", Korean_space_path="PASS")
        _STAGE = "account-identity-binding"
        _blocked(lambda: vault.load("youtube:2", IDENTITY, reference))
        _blocked(lambda: vault.load(KEY, "f" * 64, reference))
        _blocked(lambda: vault.delete("instagram:1", IDENTITY, reference))
        result["account_identity_binding"] = "PASS"
        _STAGE = "production-activation-block"
        protected = ProductionWindowsCredentialVault(root / "real-never-created")
        for action in (lambda: protected.store(KEY, IDENTITY, original),
                       lambda: protected.load(KEY, IDENTITY, reference),
                       lambda: protected.delete(KEY, IDENTITY, reference)):
            _blocked(action, OAuthBlocked)
        assert not (root / "real-never-created").exists()
        result["real_service_storage_blocked"] = "PASS"
        _STAGE = "native-rotation-and-delete"
        replacement = vault.store(KEY, IDENTITY, _bundle("native-replacement"))
        item = next(entry for entry in vault.inventory() if entry.reference == reference)
        _blocked(lambda: vault.cleanup_orphan(reference, KEY, IDENTITY, item.file_digest, uuid4().hex))
        vault.cleanup_orphan(reference, KEY, IDENTITY, item.file_digest, operation)
        assert not vault.reference_exists(reference)
        _restart(root, replacement, _bundle("native-replacement"))
        result["rotation_provenance_and_delete"] = "PASS"
        _STAGE = "native-tamper-quarantine"
        corrupted = bytearray((root / (replacement + ".pcred")).read_bytes())
        corrupted[-1] ^= 1
        (root / (replacement + ".pcred")).write_bytes(corrupted)
        _blocked(lambda: vault.load(KEY, IDENTITY, replacement))
        _blocked(vault.inventory)
        assert vault.reference_exists(replacement)
        result["tampered_ciphertext_quarantined"] = "PASS"
        assert not list(root.glob(".*.pending"))
        result["temporary_cleanup"] = "PASS"
    _STAGE = "alternate-windows-principal"
    result.update(_alternate_windows_user())
    assert not Path(directory).exists()
    result.update(owned_test_data_cleanup="PASS", result="PASS")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        return _child()
    if args.output is None:
        parser.error("--output is required")
    try:
        result, code = validate(), 0
    except Exception:  # noqa: BLE001 - no raw principal/password/token/path errors in CI output
        result, code = {"result": "FAIL", "error": "Synthetic production vault validation failed safely.",
                        "stage": _STAGE, "real_service_tokens": 0, "real_oauth_calls": 0,
                        "real_publish_calls": 0}, 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    notice = json.dumps(result, ensure_ascii=True, separators=(",", ":"))
    assert len(notice.encode()) < 3500
    print("::notice title=NewsFlow production credential vault::" + notice)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
