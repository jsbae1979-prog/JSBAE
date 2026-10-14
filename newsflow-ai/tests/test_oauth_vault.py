"""Synthetic credentials only; native DPAPI runs separately on Windows CI."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from newsflow.oauth import vault
from newsflow.oauth.vault import FakeCredentialVault, VaultError, WindowsCredentialVault
from newsflow.publishing.auth import TokenBundle


def bundle(suffix: str = "first", *, seconds: int = 3600) -> TokenBundle:
    return TokenBundle(
        access_token=SecretStr("nf-synthetic-access-" + suffix),
        refresh_token=SecretStr("nf-synthetic-refresh-" + suffix),
        expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        scopes=("https://www.googleapis.com/auth/youtube.upload",),
    )


class MockDPAPI:
    """Deterministic authenticated mock; does not establish real DPAPI behavior."""

    def __init__(self) -> None:
        self.buffers: list[bytearray] = []

    def protect(self, plaintext: bytearray, entropy: bytearray) -> bytearray:
        self.buffers.extend((plaintext, entropy))
        encoded = bytes(value ^ 0xA5 for value in plaintext)
        return bytearray(b"mock-dpapi" + hmac.digest(bytes(entropy), encoded, "sha256") + encoded)

    def unprotect(self, ciphertext: bytearray, entropy: bytearray) -> bytearray:
        self.buffers.extend((ciphertext, entropy))
        if len(ciphertext) < 42 or not ciphertext.startswith(b"mock-dpapi"):
            raise RuntimeError("untrusted provider error")
        encoded = ciphertext[42:]
        if not hmac.compare_digest(ciphertext[10:42], hmac.digest(bytes(entropy), encoded, "sha256")):
            raise RuntimeError("untrusted provider error")
        return bytearray(value ^ 0xA5 for value in encoded)


@pytest.fixture
def mocked_windows(monkeypatch, tmp_path):
    mock = MockDPAPI()
    monkeypatch.setattr(vault.sys, "platform", "win32")
    monkeypatch.setattr(vault, "_DPAPI", lambda: mock)
    return WindowsCredentialVault(tmp_path / "한글 공백" / "credentials"), mock


@pytest.mark.parametrize("account", ["youtube:1", "instagram:2"])
def test_fake_account_binding_and_deep_copy(account):
    fake = FakeCredentialVault()
    original = bundle()
    reference = fake.store(account, original)
    original.access_token = SecretStr("nf-synthetic-mutated")
    loaded = fake.load(account, reference)
    assert loaded.access_token.get_secret_value() == "nf-synthetic-access-first"
    loaded.scopes = ("changed",)
    assert fake.load(account, reference).scopes != loaded.scopes
    fake.delete(account, reference)
    with pytest.raises(VaultError):
        fake.load(account, reference)


@pytest.mark.parametrize("account", ["youtube", "youtube:0", "instagram:-1", "other:1", "youtube:01", "youtube:1/.."])
def test_account_key_validation(account):
    with pytest.raises(VaultError):
        FakeCredentialVault().store(account, bundle())


@pytest.mark.parametrize("reference", ["../secret", "0" * 31, "0" * 33, "a" * 32 + ".bin", "A" * 32, ""])
def test_reference_validation(reference):
    with pytest.raises(VaultError):
        FakeCredentialVault().load("youtube:1", reference)


@pytest.mark.parametrize("field", ["access_token", "refresh_token"])
def test_real_credential_rejected_with_safe_error(field):
    value = bundle()
    setattr(value, field, SecretStr("REAL-SERVICE-TOKEN-MUST-NEVER-STORE"))
    with pytest.raises(VaultError) as raised:
        FakeCredentialVault().store("youtube:1", value)
    assert "REAL-SERVICE" not in str(raised.value)
    assert "REAL-SERVICE" not in repr(value)


def test_fake_expiry_refresh_read_and_delete(monkeypatch):
    fake = FakeCredentialVault()
    value = bundle()
    reference = fake.store("youtube:1", value)

    class FutureClock:
        @staticmethod
        def now(zone):
            return value.expires_at + timedelta(seconds=1)

    monkeypatch.setattr(vault, "datetime", FutureClock)
    with pytest.raises(VaultError):
        fake.load("youtube:1", reference)
    assert fake.load("youtube:1", reference, allow_expired=True).expires_at == value.expires_at
    fake.delete("youtube:1", reference)


def test_fake_rotation_and_multi_account_isolation():
    fake = FakeCredentialVault()
    first = fake.store("youtube:1", bundle())
    other = fake.store("youtube:2", bundle("other"))
    replacement = fake.store("youtube:1", bundle("rotated"))
    fake.delete("youtube:1", first)
    assert replacement != first
    assert fake.load("youtube:1", replacement).access_token.get_secret_value().endswith("rotated")
    assert fake.load("youtube:2", other).access_token.get_secret_value().endswith("other")
    with pytest.raises(VaultError):
        fake.load("instagram:1", replacement)
    with pytest.raises(VaultError):
        fake.delete("youtube:2", replacement)


def test_unsupported_platform_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(vault.sys, "platform", "linux")
    monkeypatch.setattr(vault, "_DPAPI", lambda: pytest.fail("must not create a backend"))
    with pytest.raises(VaultError):
        WindowsCredentialVault(tmp_path / "credentials")
    assert not (tmp_path / "credentials").exists()


def test_mocked_windows_ciphertext_atomic_and_cleared(mocked_windows):
    store, mock = mocked_windows
    value = bundle()
    reference = store.store("youtube:1", value)
    files = list(store._root.iterdir())
    assert [path.name for path in files] == [reference + ".bin"]
    assert value.access_token.get_secret_value().encode() not in files[0].read_bytes()
    assert store.load("youtube:1", reference) == value
    assert mock.buffers and all(not any(buffer) for buffer in mock.buffers)


def test_mocked_windows_account_entropy_rejects_cross_account(mocked_windows):
    store, _ = mocked_windows
    reference = store.store("youtube:1", bundle())
    for operation in (store.load, store.delete):
        with pytest.raises(VaultError) as raised:
            operation("youtube:2", reference)
        assert "untrusted" not in str(raised.value)
    assert store.load("youtube:1", reference)


@pytest.mark.parametrize("content", [b"", b"corrupt", b"x" * 131073])
def test_mocked_windows_corrupt_or_oversized_ciphertext(mocked_windows, content):
    store, _ = mocked_windows
    reference = store.store("youtube:1", bundle())
    (store._root / (reference + ".bin")).write_bytes(content)
    with pytest.raises(VaultError):
        store.load("youtube:1", reference)


@pytest.mark.parametrize("content", [b"{}", b"[]", b"not json", b"x" * 32769])
def test_mocked_windows_malformed_plaintext_fails_closed(mocked_windows, monkeypatch, content):
    store, mock = mocked_windows
    reference = store.store("youtube:1", bundle())
    monkeypatch.setattr(mock, "unprotect", lambda *_: bytearray(content))
    with pytest.raises(VaultError):
        store.load("youtube:1", reference)


def test_mocked_windows_cleanup_on_native_or_file_error(mocked_windows, monkeypatch):
    store, _ = mocked_windows

    def failed_link(*_):
        raise OSError("untrusted value/path/password")

    monkeypatch.setattr(vault.os, "link", failed_link)
    with pytest.raises(VaultError) as raised:
        store.store("youtube:1", bundle())
    assert "password" not in str(raised.value)
    assert not list(store._root.iterdir())


def test_mocked_windows_temp_collision_never_deletes_existing_file(mocked_windows, monkeypatch):
    store, _ = mocked_windows
    reference = "1" * 32
    temporary = store._root / ("." + reference + ".tmp")
    temporary.write_bytes(b"existing user data")
    monkeypatch.setattr(vault, "uuid4", lambda: SimpleNamespace(hex=reference))
    with pytest.raises(VaultError):
        store.store("youtube:1", bundle())
    assert temporary.read_bytes() == b"existing user data"


def test_mocked_windows_destination_collision_never_overwrites(mocked_windows, monkeypatch):
    store, _ = mocked_windows
    reference = "1" * 32
    destination = store._root / (reference + ".bin")
    destination.write_bytes(b"existing user data")
    monkeypatch.setattr(vault, "uuid4", lambda: SimpleNamespace(hex=reference))
    with pytest.raises(VaultError):
        store.store("youtube:1", bundle())
    assert destination.read_bytes() == b"existing user data"
    assert len(list(store._root.iterdir())) == 1


def test_mocked_windows_valid_json_corruption_is_rejected(mocked_windows, monkeypatch):
    store, mock = mocked_windows
    original = bundle()
    reference = store.store("youtube:1", original)
    value = json.loads(vault._serialize("youtube:1", original))
    value["access_token"] = "nf-synthetic-corrupted-but-valid-shape"
    monkeypatch.setattr(mock, "unprotect", lambda *_: bytearray(json.dumps(value).encode()))
    with pytest.raises(VaultError):
        store.load("youtube:1", reference)


def test_mocked_windows_expiry_does_not_prevent_owned_delete(mocked_windows, monkeypatch):
    store, _ = mocked_windows
    original = bundle()
    reference = store.store("youtube:1", original)

    class FutureClock:
        @staticmethod
        def now(zone):
            return original.expires_at + timedelta(seconds=1)

    monkeypatch.setattr(vault, "datetime", FutureClock)
    with pytest.raises(VaultError):
        store.load("youtube:1", reference)
    assert store.load("youtube:1", reference, allow_expired=True) == original
    store.delete("youtube:1", reference)
    assert not list(store._root.iterdir())


def test_mocked_windows_real_token_never_reaches_dpapi(mocked_windows, monkeypatch):
    store, mock = mocked_windows
    prohibited = bundle()
    prohibited.refresh_token = SecretStr("real-service-token-placeholder")
    monkeypatch.setattr(mock, "protect", lambda *_: pytest.fail("must not protect real service token"))
    with pytest.raises(VaultError):
        store.store("youtube:1", prohibited)
    assert not list(store._root.iterdir())


@pytest.mark.parametrize("kind", ["is_symlink", "is_junction"])
def test_mocked_windows_reparse_directory_rejected(monkeypatch, tmp_path, kind):
    target = tmp_path / "redirected"
    original = getattr(Path, kind)
    monkeypatch.setattr(vault.sys, "platform", "win32")
    monkeypatch.setattr(Path, kind, lambda self: self == target or original(self))
    with pytest.raises(VaultError):
        WindowsCredentialVault(target)
    assert not target.exists()


def test_dpapi_native_contract_clears_output_and_is_current_user(monkeypatch):
    allocations = []
    flags = []
    freed = []

    class Function:
        def __init__(self, callback):
            self.callback = callback

        def __call__(self, *args):
            return self.callback(*args)

    def transform(data, description, entropy, reserved, prompt, flag, output):
        flags.append(flag)
        assert description is None and reserved is None and prompt is None
        assert entropy._obj.cbData == 32
        memory = (ctypes.c_ubyte * 4)(1, 2, 3, 4)
        allocations.append(memory)
        output._obj.cbData = 4
        output._obj.pbData = ctypes.cast(memory, ctypes.POINTER(ctypes.c_ubyte))
        return 1

    class Crypt:
        CryptProtectData = Function(transform)
        CryptUnprotectData = Function(transform)

    class Kernel:
        LocalFree = Function(lambda pointer: freed.append(pointer))

    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **_: Crypt() if name == "crypt32" else Kernel(),
                        raising=False)
    dpapi = vault._DPAPI()
    entropy = bytearray(hashlib.sha256(b"synthetic context").digest())
    assert dpapi.protect(bytearray(b"safe"), entropy) == bytearray((1, 2, 3, 4))
    assert dpapi.unprotect(bytearray(b"safe"), entropy) == bytearray((1, 2, 3, 4))
    assert flags == [1, 1]  # UI_FORBIDDEN only, never LOCAL_MACHINE (4).
    assert len(freed) == 2
    assert all(list(memory) == [0, 0, 0, 0] for memory in allocations)


@pytest.mark.skipif(sys.platform != "win32", reason="Real current-user DPAPI requires Windows; Cloud NOT VERIFIED")
def test_real_windows_dpapi_synthetic_restart_isolation_rotation(tmp_path):
    store = WindowsCredentialVault(tmp_path / "한글 공백" / "credentials")
    original = bundle()
    reference = store.store("youtube:1", original)
    assert original.access_token.get_secret_value().encode() not in (store._root / (reference + ".bin")).read_bytes()
    restarted = WindowsCredentialVault(store._root)
    assert restarted.load("youtube:1", reference) == original
    with pytest.raises(VaultError):
        restarted.load("instagram:1", reference)
    replacement = restarted.store("youtube:1", bundle("replacement"))
    restarted.delete("youtube:1", reference)
    with pytest.raises(VaultError):
        restarted.load("youtube:1", reference)
    path = store._root / (replacement + ".bin")
    encrypted = bytearray(path.read_bytes())
    encrypted[len(encrypted) // 2] ^= 1
    path.write_bytes(encrypted)
    with pytest.raises(VaultError):
        restarted.load("youtube:1", replacement)
