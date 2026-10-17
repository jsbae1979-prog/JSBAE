"""Facebook Login account contracts: synthetic transport and isolated SQLite only."""

from dataclasses import replace
from datetime import timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from newsflow.db.models import Base, OAuthConnection, OAuthLifecycleOperation, PlatformAccount, utcnow
from newsflow.db.session import make_engine, session_factory
from newsflow.oauth.instagram import (
    FACEBOOK_SCOPES,
    MODE,
    FacebookGraphIdentity,
    InstagramConnectionError,
    InstagramConnectionService,
    MetaAuthorization,
    _InstagramVault,
)
from newsflow.oauth.production_dpapi import FakeProductionCipherProtector, SyntheticProductionCredentialVault
from newsflow.publishing.auth import TokenBundle


class FakeAuthorization:
    def __init__(self):
        self.calls = 0
        self.error = None
        self.result = MetaAuthorization(
            app_id="100001", page_id="200001",
            user_bundle=TokenBundle(access_token=SecretStr("nf-synthetic-access-instagram-user"),
                                    expires_at=utcnow() + timedelta(hours=1), scopes=FACEBOOK_SCOPES),
            data_access_expires_at=utcnow() + timedelta(days=30),
        )

    def authorize(self, *, scopes):
        assert scopes == FACEBOOK_SCOPES
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


class FakeIdentity:
    def __init__(self):
        self.calls = []
        self.permissions = [{"permission": scope, "status": "granted"} for scope in FACEBOOK_SCOPES]
        self.pages = [{"id": "200001", "name": "Synthetic Page", "tasks": ["CREATE_CONTENT"],
                       "access_token": "nf-synthetic-access-instagram-page",
                       "instagram_business_account": {"id": "300001"}}]
        self.profile = {"id": "300001", "username": "synthetic_news"}
        self.error = None

    def get(self, path, token, fields=""):
        self.calls.append((path, fields))
        if self.error:
            raise self.error
        if path == "me/permissions":
            assert token.get_secret_value() == "nf-synthetic-access-instagram-user"
            return {"data": self.permissions}
        if path == "me/accounts":
            return {"data": self.pages}
        assert token.get_secret_value() == "nf-synthetic-access-instagram-page"
        return self.profile


@pytest.fixture
def service(tmp_path):
    engine = make_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    vault = SyntheticProductionCredentialVault(
        tmp_path / "cipher", protector=FakeProductionCipherProtector(), owner_sid="NF-TEST-SID-instagram",
    )
    result = InstagramConnectionService(session_factory(engine), tmp_path,
                                       authorization_backend=FakeAuthorization(), identity_transport=FakeIdentity(),
                                       vault=vault)
    yield result
    result.close()
    engine.dispose()


def test_default_connection_stays_blocked_without_io_or_account_creation(service, tmp_path):
    default = InstagramConnectionService(service.sessions, tmp_path / "untouched")
    for _ in range(2):
        state = default.status()
        assert state["blocked_reason"] == "auth_relay_required"
        assert not state["connection_supported"] and not state["pending"]
        with pytest.raises(InstagramConnectionError, match="BLOCKED"):
            default.begin(consent=True)
        with pytest.raises(InstagramConnectionError, match="BLOCKED"):
            default.access_for_upload(1, consent=True)
    with service.sessions() as session:
        assert list(session.scalars(select(PlatformAccount))) == []
    assert not (tmp_path / "untouched").exists()
    assert service.authorization.calls == 0 and not service.identity.calls


@pytest.mark.parametrize("action", ["begin", "access"])
def test_explicit_consent_required(service, action):
    with pytest.raises(InstagramConnectionError, match="동의"):
        service.begin() if action == "begin" else service.access_for_upload(1)
    assert service.authorization.calls == 0
    assert not service.identity.calls


def test_native_vault_and_graph_entrypoints_closed_outside_approved_service(tmp_path):
    with pytest.raises(InstagramConnectionError, match="동의"):
        _InstagramVault(tmp_path / "never-created").load("instagram:1", "0" * 64, "1" * 32)
    with pytest.raises(InstagramConnectionError, match="동의"):
        FacebookGraphIdentity().get("me/permissions", SecretStr("nf-synthetic-test"))
    assert not (tmp_path / "never-created").exists()


@pytest.mark.parametrize("task", ["CREATE_CONTENT", "MANAGE", "PROFILE_PLUS_CREATE_CONTENT", "PROFILE_PLUS_FULL_CONTROL"])
def test_page_link_and_permissions_verified_before_encrypted_storage(service, tmp_path, task):
    service.identity.pages[0]["tasks"] = [task]
    account_id = service.begin(consent=True)
    credential = service.access_for_upload(account_id, consent=True)
    assert credential.instagram_id == "300001" and credential.page_id == "200001"
    assert credential.app_id == "100001"
    assert credential.bundle.access_token.get_secret_value() == "nf-synthetic-access-instagram-page"
    assert credential.bundle.refresh_token is None
    assert [path for path, _ in service.identity.calls] == ["me/permissions", "me/accounts", "300001"]
    assert service.accounts()[0]["ready"]
    assert "nf-synthetic-access" not in repr(credential)
    assert "nf-synthetic-access" not in str(service.status())
    with service.sessions() as session:
        account = session.get(PlatformAccount, account_id)
        assert account.api_ready and account.account_type == "professional"
        assert "nf-synthetic" not in account.credential_ref
        assert session.scalar(select(OAuthLifecycleOperation.status)) == "instagram_completed"
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert b"nf-synthetic-access" not in path.read_bytes()


def test_status_and_credential_load_do_not_repeat_graph_queries(service):
    account_id = service.begin(consent=True)
    baseline = len(service.identity.calls)
    for _ in range(3):
        service.status()
        service.accounts()
        service.access_for_upload(account_id, consent=True)
    assert service.authorization.calls == 1 and len(service.identity.calls) == baseline


@pytest.mark.parametrize("scope", FACEBOOK_SCOPES)
def test_missing_permission_blocks_before_page_token_storage(service, scope):
    service.identity.permissions = [row for row in service.identity.permissions if row["permission"] != scope]
    with pytest.raises(InstagramConnectionError, match="권한"):
        service.begin(consent=True)
    assert len(service.identity.calls) == 1
    with service.sessions() as session:
        assert not session.scalar(select(PlatformAccount.credential_ref))
        assert session.scalar(select(OAuthConnection.error_code)) == "permission_denied"


@pytest.mark.parametrize("change,code", [
    ("no_page", "identity_mismatch"), ("duplicate_page", "identity_mismatch"),
    ("no_professional", "professional_required"), ("no_task", "professional_required"),
    ("different_instagram", "identity_mismatch"), ("invalid_username", "response_invalid"),
    ("invalid_token", "response_invalid"),
])
def test_identity_and_professional_errors(service, change, code):
    if change == "no_page":
        service.identity.pages = []
    elif change == "duplicate_page":
        service.identity.pages *= 2
    elif change == "no_professional":
        service.identity.pages[0].pop("instagram_business_account")
    elif change == "no_task":
        service.identity.pages[0]["tasks"] = ["ANALYZE"]
    elif change == "different_instagram":
        service.identity.profile["id"] = "999001"
    elif change == "invalid_username":
        service.identity.profile["username"] = "<script>"
    else:
        service.identity.pages[0]["access_token"] = "private\nheader"
    with pytest.raises(InstagramConnectionError) as error:
        service.begin(consent=True)
    assert error.value.code == code
    assert not service.accounts()[0]["ready"]


def test_data_access_expiry_limits_page_token_and_requires_reconnect(service):
    deadline = utcnow() + timedelta(minutes=5)
    service.authorization.result = replace(service.authorization.result, data_access_expires_at=deadline)
    account_id = service.begin(consent=True)
    assert service.access_for_upload(account_id, consent=True).bundle.expires_at == deadline
    service.authorization.result = replace(service.authorization.result, data_access_expires_at=utcnow())
    with pytest.raises(InstagramConnectionError) as error:
        service.begin(consent=True, account_id=account_id)
    assert error.value.code == "expired"


def test_auth_failure_sanitized_and_not_retried(service):
    service.authorization.error = TimeoutError("SECRET_DO_NOT_ECHO")
    with pytest.raises(InstagramConnectionError) as error:
        service.begin(consent=True)
    assert error.value.code == "outcome_unknown"
    assert "SECRET" not in str(error.value)
    for _ in range(2):
        assert service.status()["accounts"][0]["status"] == "unknown"
        assert service.recover() == 0
    assert service.authorization.calls == 1 and not service.identity.calls


def test_interrupted_connection_quarantined_on_restart(service):
    with service.sessions.begin() as session:
        account = PlatformAccount(platform="instagram", label="Test", account_type="professional")
        session.add(account)
        session.flush()
        session.add(OAuthConnection(account_id=account.id, mode=MODE, status="authorizing"))
    assert service.recover() == 1 and service.recover() == 0
    assert service.accounts()[0]["status"] == "unknown"
    assert not service.authorization.calls and not service.identity.calls


def test_reconnect_cannot_silently_change_account(service):
    account_id = service.begin(consent=True)
    with service.sessions() as session:
        reference = session.get(PlatformAccount, account_id).credential_ref
    service.identity.pages[0]["instagram_business_account"]["id"] = "400001"
    service.identity.profile["id"] = "400001"
    with pytest.raises(InstagramConnectionError) as error:
        service.begin(consent=True, account_id=account_id)
    assert error.value.code == "identity_mismatch"
    with service.sessions() as session:
        assert session.get(PlatformAccount, account_id).credential_ref == reference


def test_stored_connection_cannot_enable_default_production_backend(service, tmp_path):
    account_id = service.begin(consent=True)
    default = InstagramConnectionService(service.sessions, tmp_path)
    assert not default.accounts()[0]["ready"]
    with pytest.raises(InstagramConnectionError) as error:
        default.access_for_upload(account_id, consent=True)
    assert error.value.code == "auth_relay_required"


def test_duplicate_verified_instagram_identity_is_not_added(service):
    service.begin(consent=True)
    with pytest.raises(InstagramConnectionError) as error:
        service.begin(consent=True)
    assert error.value.code == "identity_mismatch"
    assert len([account for account in service.accounts() if account["ready"]]) == 1


def test_selected_identity_metadata_tampering_blocks_token_load(service):
    from newsflow.db.models import AppSetting

    account_id = service.begin(consent=True)
    with service.sessions.begin() as session:
        session.get(AppSetting, f"instagram.id.{account_id}").value = "999000"
    with pytest.raises(InstagramConnectionError) as error:
        service.access_for_upload(account_id, consent=True)
    assert error.value.code == "identity_mismatch"
