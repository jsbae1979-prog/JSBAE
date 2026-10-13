"""Redacted credential contracts; production vault/OAuth deliberately unavailable in Phase 4A."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator

from .adapters import ExternalPublishingDisabled


class TokenBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_token: SecretStr
    refresh_token: SecretStr | None = None
    expires_at: datetime
    scopes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def aware_expiry(self) -> TokenBundle:
        if self.expires_at.tzinfo is None:
            raise ValueError("토큰 만료시각은 timezone 정보가 필요합니다.")
        return self


class CredentialExpired(Exception):
    def __init__(self) -> None:
        super().__init__("인증정보가 만료되었거나 취소되었습니다.")


class CredentialVault(Protocol):
    def store(self, bundle: TokenBundle) -> str: ...
    def load(self, reference: str) -> TokenBundle: ...
    def delete(self, reference: str) -> None: ...


class UnavailableCredentialVault:
    """A real Windows Credential Manager/DPAPI backend requires Phase 4B authorization."""

    def store(self, bundle: TokenBundle) -> str:
        raise ExternalPublishingDisabled()

    def load(self, reference: str) -> TokenBundle:
        raise ExternalPublishingDisabled()

    def delete(self, reference: str) -> None:
        raise ExternalPublishingDisabled()


class FakeCredentialVault:
    """Ephemeral test-only redacted bundles. Never used by GUI or external adapters."""

    def __init__(self) -> None:
        self._bundles: dict[str, TokenBundle] = {}

    def store(self, bundle: TokenBundle) -> str:
        reference = "fake:" + uuid4().hex
        self._bundles[reference] = bundle.model_copy(deep=True)
        return reference

    def load(self, reference: str) -> TokenBundle:
        bundle = self._bundles.get(reference)
        if not bundle or bundle.expires_at <= datetime.now(UTC):
            raise CredentialExpired()
        return bundle.model_copy(deep=True)

    def delete(self, reference: str) -> None:
        self._bundles.pop(reference, None)
