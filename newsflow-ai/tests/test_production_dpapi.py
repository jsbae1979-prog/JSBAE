"""Production file semantics using synthetic data; native DPAPI is Windows only."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from newsflow.oauth import production_dpapi as module
from newsflow.oauth.contracts import OAuthBlocked
from newsflow.oauth.production_dpapi import (
    FakeProductionCipherProtector,
    ProductionVaultError,
    ProductionWindowsCredentialVault,
    SyntheticProductionCredentialVault,
)
from newsflow.publishing.auth import TokenBundle

KEY = "youtube:1"
IDENTITY = hashlib.sha256(b"nf-synthetic-identity-channel-one").hexdigest()
TEST_KEY = hashlib.sha256(b"nf-test-production-cipher-key-001").digest()


def bundle(suffix: str = "first", *, seconds: int = 3600) -> TokenBundle:
    return TokenBundle(access_token=SecretStr("nf-synthetic-access-" + suffix),
                       refresh_token=SecretStr("nf-synthetic-refresh-" + suffix),
                       expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
                       scopes=("https://www.googleapis.com/auth/youtube.upload",))


def make_vault(root: Path, *, owner: str = "one") -> SyntheticProductionCredentialVault:
    return SyntheticProductionCredentialVault(root, protector=FakeProductionCipherProtector(TEST_KEY),
                                               owner_sid="NF-TEST-SID-" + owner)


@pytest.fixture
def store(tmp_path):
    return make_vault(tmp_path / "한글 공백" / "운영 인증정보")


@pytest.mark.parametrize("operation", ["store", "load", "delete", "reserve", "write", "inventory",
                                       "exists", "orphans", "pending", "cleanup-pending"])
def test_real_facade_denies_before_backend_or_filesystem(monkeypatch, tmp_path, operation):
    root = tmp_path / "must not exist"
    actual = ProductionWindowsCredentialVault(root)
    monkeypatch.setenv("NEWSFLOW_OAUTH_PRODUCTION", "1")
    monkeypatch.setenv("NEWSFLOW_OAUTH_APPROVED", "true")
    monkeypatch.setattr(module, "_DPAPI", lambda: pytest.fail("must not construct a real backend"))
    # Even a future accidental change to just the shared gate remains insufficient.
    monkeypatch.setattr(module, "require_production_activation", lambda: None)
    actions = {
        "store": lambda: actual.store(KEY, IDENTITY, bundle()),
        "load": lambda: actual.load(KEY, IDENTITY, "1" * 32),
        "delete": lambda: actual.delete(KEY, IDENTITY, "1" * 32),
        "reserve": actual.reserve_reference,
        "write": lambda: actual.write_reserved(KEY, IDENTITY, "1" * 32, bundle(), operation_id="2" * 32),
        "inventory": actual.inventory,
        "exists": lambda: actual.reference_exists("1" * 32),
        "orphans": lambda: actual.cleanup_orphan("1" * 32, KEY, IDENTITY, "a" * 64, "2" * 32),
        "pending": actual.pending_inventory,
        "cleanup-pending": lambda: actual.cleanup_pending("file", KEY, IDENTITY, "a" * 64, "2" * 32),
    }
    with pytest.raises(OAuthBlocked):
        actions[operation]()
    assert not root.exists()


def test_reserved_reference_write_ciphertext_verify_and_restart(store):
    reference, operation = store.reserve_reference(), uuid4().hex
    original = bundle()
    assert not store.reference_exists(reference)
    store.write_reserved(KEY, IDENTITY, reference, original, operation_id=operation)
    assert store.reference_exists(reference)
    assert store.load(KEY, IDENTITY, reference) == original
    raw = (store._kernel._root / (reference + ".pcred")).read_bytes()
    assert original.access_token.get_secret_value().encode() not in raw
    assert original.refresh_token.get_secret_value().encode() not in raw
    assert b"nf-synthetic-" not in raw
    restarted = make_vault(store._kernel._root)
    assert restarted.load(KEY, IDENTITY, reference) == original
    evidence = restarted.inventory()
    assert len(evidence) == 1
    assert evidence[0].reference == reference
    assert evidence[0].operation_id == operation
    assert evidence[0].file_digest == hashlib.sha256(raw).hexdigest()
    assert reference not in repr(evidence)


@pytest.mark.parametrize("kind", ["account", "platform", "identity", "owner"])
def test_identity_account_and_owner_bound_ciphertext(store, kind):
    reference = store.store(KEY, IDENTITY, bundle())
    victim = make_vault(store._kernel._root, owner="other") if kind == "owner" else store
    key = {"account": "youtube:2", "platform": "instagram:1"}.get(kind, KEY)
    digest = "f" * 64 if kind == "identity" else IDENTITY
    with pytest.raises(ProductionVaultError):
        victim.load(key, digest, reference)
    with pytest.raises(ProductionVaultError):
        victim.delete(key, digest, reference)
    assert store.load(KEY, IDENTITY, reference)


@pytest.mark.parametrize("field", ["access_token", "refresh_token"])
def test_synthetic_facade_rejects_real_format_before_crypto(store, monkeypatch, field):
    value = bundle()
    setattr(value, field, SecretStr("prohibited-service-token-placeholder"))
    monkeypatch.setattr(store._kernel._protector, "protect", lambda *_: pytest.fail("must not encrypt"))
    with pytest.raises(ProductionVaultError) as raised:
        store.store(KEY, IDENTITY, value)
    assert "prohibited" not in str(raised.value)
    assert not list(store._kernel._root.glob("*.pcred"))


@pytest.mark.parametrize("reference", ["../outside", "1" * 31, "A" * 32, "1" * 32 + ".pcred"])
def test_reference_path_traversal_rejected(store, reference):
    with pytest.raises(ProductionVaultError):
        store.write_reserved(KEY, IDENTITY, reference, bundle(), operation_id=uuid4().hex)


@pytest.mark.parametrize("digest", ["", "a" * 63, "A" * 64, "../outside"])
def test_identity_digest_validation(store, digest):
    with pytest.raises(ProductionVaultError):
        store.store(KEY, digest, bundle())


def test_duplicate_reserved_reference_never_overwrites(store):
    ref = store.store(KEY, IDENTITY, bundle())
    before = (store._kernel._root / (ref + ".pcred")).read_bytes()
    with pytest.raises(ProductionVaultError):
        store.write_reserved(KEY, IDENTITY, ref, bundle("replacement"), operation_id=uuid4().hex)
    assert (store._kernel._root / (ref + ".pcred")).read_bytes() == before
    assert not list(store._kernel._root.glob(".*.pending"))


def test_concurrent_immutable_publication_has_one_winner(store):
    reference = store.reserve_reference()
    operation = uuid4().hex

    def write(index):
        try:
            make_vault(store._kernel._root).write_reserved(KEY, IDENTITY, reference,
                                                           bundle(str(index)), operation_id=operation)
            return True
        except ProductionVaultError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(write, range(4))) == 1
    assert store.load(KEY, IDENTITY, reference)
    assert not list(store._kernel._root.glob(".*.pending"))


def test_expired_read_blocks_but_owned_delete_is_possible(store, monkeypatch):
    original = bundle()
    ref = store.store(KEY, IDENTITY, original)

    class FutureClock:
        @staticmethod
        def now(_zone):
            return original.expires_at + timedelta(seconds=1)

    monkeypatch.setattr(module, "datetime", FutureClock)
    with pytest.raises(ProductionVaultError):
        store.load(KEY, IDENTITY, ref)
    assert store.load(KEY, IDENTITY, ref, allow_expired=True) == original
    store.delete(KEY, IDENTITY, ref)
    assert not store.reference_exists(ref)


@pytest.mark.parametrize("tamper", ["encrypted-body", "account", "identity", "owner", "operation", "reference"])
def test_envelope_and_encrypted_body_tampering_rejects_without_cleanup(store, tamper):
    ref = store.store(KEY, IDENTITY, bundle())
    path = store._kernel._root / (ref + ".pcred")
    raw = bytearray(path.read_bytes())
    prefix = len(module._HEADER)
    header_size = struct.unpack(">I", raw[prefix:prefix + 4])[0]
    metadata = json.loads(raw[prefix + 4:prefix + 4 + header_size])
    if tamper == "encrypted-body":
        raw[-1] ^= 1
    else:
        name = {"account": "account_key", "identity": "identity_digest", "owner": "owner_digest",
                "operation": "operation_id", "reference": "reference"}[tamper]
        metadata[name] = "youtube:2" if tamper == "account" else "f" * len(metadata[name])
        header = store._kernel._canonical(metadata)
        raw = bytearray(module._HEADER + struct.pack(">I", len(header)) + header + raw[prefix + 4 + header_size:])
    path.write_bytes(raw)
    with pytest.raises(ProductionVaultError):
        store.load(KEY, IDENTITY, ref)
    with pytest.raises(ProductionVaultError):
        store.inventory()
    assert path.exists()


def test_orphan_cleanup_requires_exact_operation_account_identity_and_file_digest(store):
    ref, operation = store.reserve_reference(), uuid4().hex
    store.write_reserved(KEY, IDENTITY, ref, bundle(), operation_id=operation)
    item = store.inventory()[0]
    for key, identity, digest, op in [("youtube:2", IDENTITY, item.file_digest, operation),
                                     (KEY, "f" * 64, item.file_digest, operation),
                                     (KEY, IDENTITY, "f" * 64, operation),
                                     (KEY, IDENTITY, item.file_digest, uuid4().hex)]:
        with pytest.raises(ProductionVaultError):
            store.cleanup_orphan(ref, key, identity, digest, op)
        assert store.reference_exists(ref)
    store.cleanup_orphan(ref, KEY, IDENTITY, item.file_digest, operation)
    assert not store.reference_exists(ref)


@pytest.mark.parametrize("published", [False, True], ids=["before-hardlink", "after-hardlink"])
def test_crash_left_pending_ciphertext_requires_explicit_provenance_cleanup(store, published):
    reference, operation = store.reserve_reference(), uuid4().hex
    store.write_reserved(KEY, IDENTITY, reference, bundle(), operation_id=operation)
    final = store._kernel._root / (reference + ".pcred")
    filename = "." + reference + "." + uuid4().hex + ".pending"
    pending = store._kernel._root / filename
    if published:
        os.link(final, pending)
        assert store.load(KEY, IDENTITY, reference)
    else:
        final.rename(pending)
        assert not store.reference_exists(reference)
    item = store.pending_inventory()[0]
    assert item.pending_filename == filename and item.operation_id == operation
    with pytest.raises(ProductionVaultError):
        store.cleanup_pending(filename, KEY, IDENTITY, "0" * 64, operation)
    assert pending.exists()
    store.cleanup_pending(filename, KEY, IDENTITY, item.file_digest, operation)
    assert not pending.exists()
    if published:
        assert store.load(KEY, IDENTITY, reference)


def test_unknown_or_corrupt_files_never_deleted(store):
    unknown = store._kernel._root / "user-existing-file.dat"
    unknown.write_bytes(b"user data")
    assert store.inventory() == ()
    bad = store._kernel._root / (uuid4().hex + ".pcred")
    bad.write_bytes(b"corrupt synthetic ciphertext")
    with pytest.raises(ProductionVaultError):
        store.inventory()
    assert unknown.read_bytes() == b"user data" and bad.exists()


def test_file_io_failures_redacted_and_temporary_cleaned(store, monkeypatch):
    def fail(*_args):
        raise PermissionError("private-path/token-value/password")

    monkeypatch.setattr(module.os, "link", fail)
    with pytest.raises(ProductionVaultError) as raised:
        store.store(KEY, IDENTITY, bundle())
    assert "private" not in str(raised.value) and "token-value" not in repr(raised.value)
    assert not list(store._kernel._root.glob(".*.pending"))


def test_mutable_crypto_buffers_cleared_after_write_and_read(store, monkeypatch):
    protector = store._kernel._protector
    protect, unprotect = protector.protect, protector.unprotect
    observed = []

    def tracked_protect(plaintext, entropy):
        output = protect(plaintext, entropy)
        observed.extend((plaintext, entropy, output))
        return output

    def tracked_unprotect(ciphertext, entropy):
        output = unprotect(ciphertext, entropy)
        observed.extend((ciphertext, entropy, output))
        return output

    monkeypatch.setattr(protector, "protect", tracked_protect)
    monkeypatch.setattr(protector, "unprotect", tracked_unprotect)
    ref = store.store(KEY, IDENTITY, bundle())
    assert store.load(KEY, IDENTITY, ref)
    assert observed and all(not any(buffer) for buffer in observed)


def test_lock_file_reparse_marker_never_touches_outside_file(store, monkeypatch, tmp_path):
    target = tmp_path / "existing user file"
    target.write_bytes(b"private user bytes")
    lock_path = store._kernel._root / ".production-vault.lock"
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda candidate: candidate == lock_path or original(candidate))
    with pytest.raises(ProductionVaultError):
        store.store(KEY, IDENTITY, bundle())
    assert target.read_bytes() == b"private user bytes"


def test_symlink_ciphertext_refused(store, tmp_path, monkeypatch):
    target = tmp_path / "outside"
    target.write_bytes(b"user existing bytes")
    reference = store.reserve_reference()
    path = store._kernel._root / (reference + ".pcred")
    try:
        path.symlink_to(target)
    except OSError:
        # CI may lack symlink privilege. Still exercise rejection rather than
        # silently returning PASS without running the security decision branch.
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda candidate: candidate == path or original(candidate))
    with pytest.raises(ProductionVaultError):
        store.delete(KEY, IDENTITY, reference)
    assert target.read_bytes() == b"user existing bytes"


@pytest.mark.parametrize("kind", ["is_symlink", "is_junction"])
def test_directory_reparse_marker_refused(tmp_path, monkeypatch, kind):
    target = tmp_path / "redirected root"
    original = getattr(Path, kind)
    monkeypatch.setattr(Path, kind, lambda path: path == target or original(path))
    with pytest.raises(ProductionVaultError):
        make_vault(target)
    assert not target.exists()


def test_native_mode_unavailable_never_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(module.sys, "platform", "linux")
    with pytest.raises(ProductionVaultError):
        SyntheticProductionCredentialVault(tmp_path / "not-created")
    assert not (tmp_path / "not-created").exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Native production-kernel DPAPI needs Windows; Cloud NOT VERIFIED")
def test_real_windows_production_dpapi_restart_tampering_account_binding(tmp_path):
    root = tmp_path / "한글 공백" / "production credentials"
    store = SyntheticProductionCredentialVault(root)
    original = bundle()
    reference = store.store(KEY, IDENTITY, original)
    assert original.access_token.get_secret_value().encode() not in (root / (reference + ".pcred")).read_bytes()
    restarted = SyntheticProductionCredentialVault(root)
    assert restarted.load(KEY, IDENTITY, reference) == original
    with pytest.raises(ProductionVaultError):
        restarted.load("youtube:2", IDENTITY, reference)
    with pytest.raises(ProductionVaultError):
        restarted.load(KEY, "f" * 64, reference)
    evidence = restarted.inventory()[0]
    restarted.cleanup_orphan(reference, KEY, IDENTITY, evidence.file_digest, evidence.operation_id)
    assert not restarted.reference_exists(reference)
