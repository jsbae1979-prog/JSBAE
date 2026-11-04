"""Reuse the audited current-user DPAPI kernel; no environment-token fallback."""

from uuid import uuid4

from newsflow.oauth.production_dpapi import _owner_sid, _ProductionDPAPIFileKernel
from newsflow.oauth.vault import _DPAPI

from .contracts import MetaError, fingerprint


def local_owner():
    return fingerprint(["windows-user", _owner_sid()])


class MetaVault:
    def __init__(self, root, owner, *, native_factory=None):
        self.root, self.owner, self.kernel = root, owner, None
        self.native_factory = native_factory or _DPAPI

    def backend(self):
        if local_owner() != self.owner:
            raise MetaError("not_found")
        if self.kernel is None:
            self.kernel = _ProductionDPAPIFileKernel(
                self.root,
                self.native_factory(),
                _owner_sid(),
                native=True,
                synthetic_only=False,
                account_validator=lambda key: len(key) == 32 and all(c in "0123456789abcdef" for c in key),
            )
        return self.kernel

    def put(self, key, identity, bundle):
        ref = uuid4().hex
        self.backend().write_reserved(key, identity, ref, bundle, operation_id=uuid4().hex)
        return ref

    def get(self, key, identity, ref):
        return self.backend().read(key, identity, ref, check_expiry=True)

    def delete(self, key, identity, ref):
        backend = self.backend()
        if backend.reference_exists(ref):
            backend.delete(key, identity, ref)
