"""Account preparation UI remains local even with forged approval or environment flags."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from conftest import csrf

from newsflow.db.models import PlatformAccount
from newsflow.gui import publishing_routes
from newsflow.oauth.contracts import OAuthError
from newsflow.oauth.service import AccountConnectionService
from newsflow.publishing.service import PublishingService


@pytest.fixture
def oauth_account(app) -> int:
    identifier = PublishingService(app.state.sessions, app.state.video.outputs).add_account(
        "youtube", "검토 채널 <script>alert(1)</script>", "youtube_channel"
    )
    with app.state.sessions.begin() as session:
        session.get(PlatformAccount, identifier).credential_ref = "private-vault-reference-never-display"
    return identifier


def assert_real_oauth_disabled(client) -> None:
    status = client.get("/api/oauth/safety").json()
    assert status["mode"] == "OFFLINE/BLOCKED"
    assert status["feature_enabled"] is False
    assert status["user_approval"] is False
    assert status["phase_allows_real"] is False
    assert all(
        status[name] == 0
        for name in (
            "real_authorization_requests",
            "real_token_exchange_calls",
            "real_refresh_calls",
            "real_revoke_calls",
        )
    )


def test_oauth_account_page_escapes_labels_and_hides_credentials(client, oauth_account, monkeypatch):
    secret = "synthetic-oauth-secret-never-in-html"
    monkeypatch.setenv("NEWSFLOW_OAUTH_CLIENT_SECRET", secret)
    response = client.get("/publishing")
    assert response.status_code == 200
    assert 'id="oauth-account-' + str(oauth_account) + '"' in response.text
    assert "검토 채널 &lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert "OFFLINE/BLOCKED" in response.text and "실제 계정 연결 아님" in response.text
    assert "youtube.upload" in response.text and "실계정 권한" in response.text
    assert secret not in response.text and "private-vault-reference-never-display" not in response.text
    assert re.search(r'class="oauth-start-disabled"[^>]*disabled[^>]*aria-disabled="true"', response.text)
    assert not re.search(
        r'<input[^>]*name="(?:access_token|refresh_token|client_secret|authorization_code)"', response.text
    )
    assert "accounts.google.com/o/oauth" not in response.text
    assert "facebook.com/dialog/oauth" not in response.text
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "form-action 'self'" in response.headers["Content-Security-Policy"]
    assert_real_oauth_disabled(client)


def test_prepare_and_disconnect_prepare_preserve_unconnected_account(client, app, oauth_account):
    token = csrf(client)
    headers = {"Origin": "http://127.0.0.1"}
    for action in ("prepare", "disconnect-prepare"):
        response = client.post(
            f"/publishing/accounts/{oauth_account}/oauth/{action}",
            data={"csrf_token": token},
            headers=headers,
        )
        assert response.status_code == 200
        assert "OFFLINE/BLOCKED" in response.text and "실제 계정 연결 아님" in response.text
        assert 'data-can-connect="false"' in response.text
        with app.state.sessions() as session:
            assert session.get(PlatformAccount, oauth_account).status == "not_connected"
        card = next(
            c for c in AccountConnectionService(app.state.sessions).cards() if c["id"] == oauth_account
        )
        assert card["can_connect"] is False and card["token_exposed"] is False
        assert (
            card["connection_status"]
            == {
                "prepare": "prepared",
                "disconnect-prepare": "disconnect_prepared",
            }[action]
        )
    assert_real_oauth_disabled(client)


@pytest.mark.parametrize("action", ["prepare", "disconnect-prepare", "start"])
@pytest.mark.parametrize("violation", ["missing_csrf", "null_origin", "cross_origin"])
def test_oauth_posts_keep_csrf_and_origin_protection(client, oauth_account, action, violation):
    token = csrf(client)
    data = {"local_action": "prepare"} if violation == "missing_csrf" else {"csrf_token": token}
    origin = {"null_origin": "null", "cross_origin": "https://example.com"}.get(violation, "http://127.0.0.1")
    response = client.post(
        f"/publishing/accounts/{oauth_account}/oauth/{action}", data=data, headers={"Origin": origin}
    )
    assert response.status_code == 403
    assert_real_oauth_disabled(client)


def test_forged_start_body_query_and_env_do_not_authorize_connection(client, oauth_account, monkeypatch):
    token = csrf(client)
    for name in (
        "NEWSFLOW_OAUTH_ENABLED",
        "NEWSFLOW_OAUTH_USER_APPROVAL",
        "NEWSFLOW_REAL_SNS_ENABLED",
        "NEWSFLOW_OAUTH_FEATURE_ENABLED",
    ):
        monkeypatch.setenv(name, "1")
    monkeypatch.setenv("NEWSFLOW_OAUTH_MODE", "LIVE")
    reflected_secret = "synthetic-request-secret-never-reflected"
    response = client.post(
        f"/publishing/accounts/{oauth_account}/oauth/start?approved=true&mode=live&code={reflected_secret}",
        data={
            "csrf_token": token,
            "approved": "true",
            "user_approval": "true",
            "feature_enabled": "true",
            "mode": "live",
            "client_secret": reflected_secret,
        },
        headers={"Origin": "http://127.0.0.1"},
    )
    assert response.status_code == 423
    assert response.json() == {"detail": "Phase 4B-1에서는 실제 OAuth 계정 연결이 차단됩니다."}
    assert reflected_secret not in response.text
    assert "Location" not in response.headers
    assert_real_oauth_disabled(client)


def test_start_route_cannot_be_enabled_by_provider_return_value(client, oauth_account, monkeypatch):
    token = csrf(client)
    blocked_start = Mock(return_value=None)
    fake = SimpleNamespace(blocked_start=blocked_start)
    monkeypatch.setattr(publishing_routes, "account_connection_service", lambda _request: fake)
    response = client.post(f"/publishing/accounts/{oauth_account}/oauth/start", data={"csrf_token": token})
    assert response.status_code == 423
    blocked_start.assert_called_once_with(oauth_account)


@pytest.mark.parametrize("action,status", [("prepare", 422), ("disconnect-prepare", 422), ("start", 423)])
@pytest.mark.parametrize("value", ["synthetic-secret-account-identifier", str(2**63), "-999"])
def test_invalid_account_ids_have_fixed_errors_without_reflection(client, action, status, value):
    token = csrf(client)
    response = client.post(f"/publishing/accounts/{value}/oauth/{action}", data={"csrf_token": token})
    assert response.status_code == status and value not in response.text
    assert_real_oauth_disabled(client)


@pytest.mark.parametrize(
    "action,method", [("prepare", "prepare"), ("disconnect-prepare", "disconnect_prepare")]
)
def test_oauth_service_errors_are_fixed_and_do_not_reflect_raw_details(
    client, oauth_account, monkeypatch, action, method
):
    token = csrf(client)
    raw = "synthetic-provider-error-secret"
    fake = SimpleNamespace(**{method: Mock(side_effect=OAuthError(raw))})
    monkeypatch.setattr(publishing_routes, "account_connection_service", lambda _request: fake)
    response = client.post(f"/publishing/accounts/{oauth_account}/oauth/{action}", data={"csrf_token": token})
    assert response.status_code == 422 and raw not in response.text


@pytest.mark.parametrize("state", ["connected", "expired", "revoked", "error", "disconnect_prepared"])
def test_fake_connection_states_never_display_real_readiness(client, monkeypatch, state):
    card = {
        "id": 45,
        "platform": "instagram",
        "label": "합성 상태 <img src=x onerror=alert(1)>",
        "account_type": "professional_creator",
        "status": "not_connected",
        "connection_status": state,
        "mode": "FAKE",
        "error_message": "합성 오류 <script>alert(1)</script>" if state == "error" else "",
        "expires_at": datetime(2026, 10, 14, tzinfo=UTC),
        "permissions": ("synthetic.permission",),
        "permissions_verified": True,
        "can_connect": False,
        "token_exposed": False,
        "credential_ref": "do-not-display-card-vault-reference",
        "access_token": "do-not-display-card-token",
    }
    fake = SimpleNamespace(cards=lambda: [card])
    monkeypatch.setattr(publishing_routes, "account_connection_service", lambda _request: fake)
    response = client.get("/publishing")
    assert response.status_code == 200
    assert f'data-connection-status="{state}"' in response.text
    assert 'data-can-connect="false"' in response.text and "실제 계정 연결 아님" in response.text
    assert "Instagram 로그인 방식·전문 계정 자격·필요 권한: NOT VERIFIED" in response.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in response.text
    assert "<script>alert(1)</script>" not in response.text
    assert card["credential_ref"] not in response.text and card["access_token"] not in response.text
    assert "실계정 권한 미검증" in response.text


def test_no_oauth_callback_or_authorize_route_exposes_raw_inputs(client):
    secret = "synthetic-authorization-code"
    for route in ("/oauth/callback", "/publishing/oauth/callback", "/oauth/authorize"):
        response = client.get(route, params={"code": secret, "state": secret})
        assert response.status_code == 404 and secret not in response.text
    response = client.get("/api/oauth/safety", params={"access_token": secret, "approved": "true"})
    assert response.status_code == 200 and secret not in response.text
    assert_real_oauth_disabled(client)
