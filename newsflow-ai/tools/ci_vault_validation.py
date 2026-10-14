"""Native Windows DPAPI checks with disposable synthetic credentials only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import SecretStr

from newsflow.oauth.vault import VaultError, WindowsCredentialVault
from newsflow.publishing.auth import TokenBundle


def _bundle(suffix: str, *, seconds: float = 3600) -> TokenBundle:
    return TokenBundle(
        access_token=SecretStr("nf-synthetic-access-" + suffix),
        refresh_token=SecretStr("nf-synthetic-refresh-" + suffix),
        expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        scopes=("https://www.googleapis.com/auth/youtube.upload",),
    )


def _must_block(action) -> None:
    try:
        action()
    except VaultError:
        return
    raise AssertionError("blocked operation unexpectedly allowed")


def _child() -> int:
    """Input is an opaque reference plus hash, never a plaintext token argument."""
    try:
        request = json.loads(sys.stdin.read(4097))
        vault = WindowsCredentialVault(Path(request["root"]))
        value = vault.load(request["account"], request["reference"])
        digest = hashlib.sha256(value.access_token.get_secret_value().encode()).hexdigest()
        if digest != request["digest"]:
            return 1
        print(json.dumps({"subprocess_read": "PASS"}))
        return 0
    except Exception:  # noqa: BLE001 - redact all credential-boundary errors
        # Captured child output may enter CI logs: no traceback or provider error.
        print(json.dumps({"subprocess_read": "FAIL"}))
        return 1


def _restart_read(root: Path, account: str, reference: str, expected: TokenBundle) -> None:
    request = {
        "root": str(root), "account": account, "reference": reference,
        "digest": hashlib.sha256(expected.access_token.get_secret_value().encode()).hexdigest(),
    }
    child = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        input=json.dumps(request), text=True, capture_output=True, timeout=20, check=False, shell=False,
    )
    if child.returncode != 0 or json.loads(child.stdout) != {"subprocess_read": "PASS"}:
        raise AssertionError("isolated process decryption failed")


def validate() -> dict:
    result = {
        "platform": sys.platform,
        "credential_kind": "synthetic only",
        "real_service_tokens": 0,
        "real_oauth_calls": 0,
        "real_publish_calls": 0,
        "Windows11_user_PC": "NOT VERIFIED",
    }
    if sys.platform != "win32":
        result.update(result="NOT VERIFIED", current_user_DPAPI="NOT VERIFIED (requires Windows)")
        return result
    base_text = os.environ.get("LOCALAPPDATA", "")
    if not base_text or not Path(base_text).is_absolute():
        raise AssertionError("LOCALAPPDATA must be an absolute configured directory")
    base = Path(base_text)
    base.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="NewsFlow AI 한글 합성 인증-", dir=base) as directory:
        root = Path(directory) / "NewsFlowAI" / "credentials"
        vault = WindowsCredentialVault(root)
        original = _bundle("first")
        reference = vault.store("youtube:1", original)
        assert vault.load("youtube:1", reference) == original
        ciphertext = (root / (reference + ".bin")).read_bytes()
        assert b"nf-synthetic-" not in ciphertext
        _restart_read(root, "youtube:1", reference, original)
        result.update(current_user_DPAPI="PASS", disk_ciphertext="PASS", new_python_process_read="PASS",
                      Korean_space_path="PASS")

        other = _bundle("second-account")
        other_ref = vault.store("youtube:2", other)
        instagram = _bundle("instagram-account")
        instagram_ref = vault.store("instagram:3", instagram)
        _must_block(lambda: vault.load("youtube:2", reference))
        _must_block(lambda: vault.delete("youtube:2", reference))
        _must_block(lambda: vault.load("instagram:1", reference))
        assert vault.load("youtube:2", other_ref) == other
        assert vault.load("instagram:3", instagram_ref) == instagram
        result["multiple_account_isolation"] = "PASS"

        replacement = _bundle("replacement")
        replacement_ref = vault.store("youtube:1", replacement)
        vault.delete("youtube:1", reference)
        _must_block(lambda: vault.load("youtube:1", reference))
        _restart_read(root, "youtube:1", replacement_ref, replacement)
        assert vault.load("youtube:2", other_ref) == other
        result["rotation_and_delete"] = "PASS"

        expiring = _bundle("expiry", seconds=1)
        expiring_ref = vault.store("youtube:4", expiring)
        # Actual clock expiration; at most about one second and no fake DPAPI fallback.
        remaining = max(0, (expiring.expires_at - datetime.now(UTC)).total_seconds())
        time.sleep(remaining + 0.05)
        _must_block(lambda: vault.load("youtube:4", expiring_ref))
        assert vault.load("youtube:4", expiring_ref, allow_expired=True) == expiring
        vault.delete("youtube:4", expiring_ref)
        result["expiry_and_expired_delete"] = "PASS"

        corrupted = bytearray((root / (replacement_ref + ".bin")).read_bytes())
        corrupted[len(corrupted) // 2] ^= 1
        (root / (replacement_ref + ".bin")).write_bytes(corrupted)
        _must_block(lambda: vault.load("youtube:1", replacement_ref))
        result["tamper_rejection"] = "PASS"

        prohibited = _bundle("policy-check")
        prohibited.access_token = SecretStr("service-token-prohibited-placeholder")
        _must_block(lambda: vault.store("youtube:5", prohibited))
        result["real_token_storage_blocked"] = "PASS"
        assert not list(root.glob("*.tmp")) and not list(root.glob(".*.tmp"))
        result["atomic_temporary_cleanup"] = "PASS"
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
        result = validate()
        code = 0
    except Exception:  # noqa: BLE001 - redact all credential-boundary errors
        result = {
            "result": "FAIL", "error": "Synthetic Windows credential validation failed safely.",
            "real_service_tokens": 0, "real_oauth_calls": 0, "real_publish_calls": 0,
        }
        code = 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    notice = json.dumps(result, ensure_ascii=True, separators=(",", ":"))
    # Result fields contain no token, opaque reference, path or raw exception.
    assert len(notice.encode()) < 3500
    print("::notice title=NewsFlow credential vault::" + notice)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
