"""TikTok namespaces over existing current-user DPAPI kernels; no environment override."""
import json
import re
import sys
from pathlib import Path

from pydantic import SecretStr

from newsflow.intelligence.credentials import AIKeyStore

from .production_dpapi import (
    FakeProductionCipherProtector,
    ProductionVaultError,
    _owner_sid,
    _ProductionDPAPIFileKernel,
)
from .tiktok_protocol import DesktopConfig, TikTokError, production_enabled
from .vault import _DPAPI, VaultError


class TikTokClientStore(AIKeyStore):
    FILE = "tiktok-desktop-client.dpapi"
    ENV = "NEWSFLOW_UNUSED_TIKTOK_CLIENT"
    ENTROPY = b"NewsFlowAI:TikTok:desktop-client"

    @classmethod
    def validate(cls, raw):
        try:
            value = json.loads(raw)
            if set(value) != {"client_key", "client_secret", "port"}:
                raise ValueError
            DesktopConfig(value["client_key"], SecretStr(value["client_secret"]), value["port"])
            return raw
        except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
            raise TikTokError("config") from None

    def status(self):
        state = super().status()
        stored = self.path.is_file() and not self.path.is_symlink() and not self.path.is_junction()
        return {**state, "configured": stored, "stored": stored, "environment": False,
                "source": "stored" if stored else None}

    def key(self):
        if not self.status()["configured"]:
            raise TikTokError("config")
        return super().key()

    def config(self):
        try:
            value = json.loads(self.key())
            return DesktopConfig(value["client_key"], SecretStr(value["client_secret"]), value["port"])
        except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
            raise TikTokError("config") from None


def tiktok_key(value):
    return isinstance(value, str) and bool(re.fullmatch(r"tiktok:[1-9][0-9]{0,18}", value))


class TikTokVault:
    def __init__(self, root: Path, *, synthetic=False, protector=None):
        self.root, self.synthetic, self.protector, self.kernel = root, synthetic, protector, None
        if protector is not None and (not synthetic or type(protector) is not FakeProductionCipherProtector):
            raise TikTokError("storage")

    def _backend(self):
        if not self.synthetic and not production_enabled():
            raise TikTokError("blocked")
        if self.kernel is None:
            if self.protector:
                cipher, sid, native = self.protector, "NF-TEST-SID-tiktok", False
            else:
                if sys.platform != "win32":
                    raise TikTokError("storage")
                cipher, sid, native = _DPAPI(), _owner_sid(), True
            self.kernel = _ProductionDPAPIFileKernel(self.root, cipher, sid, native=native,
                                                    synthetic_only=self.synthetic, account_validator=tiktok_key)
        return self.kernel

    def write_reserved(self, key, identity, reference, bundle, *, operation_id):
        try:
            backend = self._backend()
            backend.write_reserved(key, identity, reference, bundle, operation_id=operation_id)
            if backend.read(key, identity, reference, check_expiry=True) != bundle:
                raise TikTokError("storage")
        except (ProductionVaultError, VaultError):
            raise TikTokError("storage") from None

    def load(self, key, identity, reference, *, allow_expired=False):
        try:
            return self._backend().read(key, identity, reference, check_expiry=not allow_expired)
        except (ProductionVaultError, VaultError):
            raise TikTokError("storage") from None
