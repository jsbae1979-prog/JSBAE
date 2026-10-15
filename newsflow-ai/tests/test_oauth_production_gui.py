"""Production-readiness UI is informational and cannot activate OAuth side effects."""

from __future__ import annotations

import http.client
import re
import socket
import urllib.request
import webbrowser
from unittest.mock import Mock

import pytest
from conftest import csrf

from newsflow.db.models import PlatformAccount
from newsflow.oauth.activation import production_activation_status
from newsflow.oauth.production_vault import ProductionCredentialBoundary
from newsflow.publishing.service import PublishingService

EXPECTED_PROVIDERS = {
    "youtube": {
        "client_type": "desktop",
        "oauth_code_status": "implemented_inactive",
        "account_identity": "NOT VERIFIED",
        "production_vault": "inactive",
        "login": "blocked",
    },
    "instagram": {
        "oauth_code_status": "blocked",
        "official_requirements": "NOT VERIFIED",
        "production_vault": "inactive",
        "login": "blocked",
    },
}


@pytest.fixture
def production_gui_account(app) -> int:
    return PublishingService(app.state.sessions, app.state.video.outputs).add_account(
        "youtube", "합성 공개 설정 검토 채널", "youtube_channel"
    )


def test_production_readiness_only_exposes_safe_stage_and_provider_descriptors(client):
    response = client.get("/api/oauth/production-readiness")
    assert response.status_code == 200
    assert response.json() == {**production_activation_status(), "providers": EXPECTED_PROVIDERS}
    assert response.json()["phase"] == "4B-2B"
    assert all(
        response.json()[name] is False
        for name in (
            "production_activation",
            "environment_can_activate",
            "gui_can_activate",
            "browser_login_allowed",
            "token_exchange_allowed",
            "production_storage_allowed",
            "publishing_allowed",
        )
    )
    assert response.headers["Cache-Control"] == "no-store"


def test_readiness_panel_distinguishes_preparation_from_real_verification(client, production_gui_account):
    response = client.get("/publishing")
    assert response.status_code == 200
    assert "PHASE 5C" in response.text and "실운영 OAuth 준비 · 활성화 차단" in response.text
    panel = re.search(r'<div[^>]*id="oauth-production-readiness"[^>]*>', response.text)
    assert panel is not None
    assert 'data-phase="4B-2B"' in panel.group()
    for name in (
        "production-activation",
        "browser-login-allowed",
        "token-exchange-allowed",
        "production-storage-allowed",
    ):
        assert f'data-{name}="false"' in panel.group()
    assert "공개 클라이언트 설정 검증, PKCE와 로컬 응답 처리 코드 준비" in response.text
    assert "NOT VERIFIED · 실제 계정과 채널을 확인하지 않았습니다." in response.text
    assert "기존 합성 토큰 검증용 저장소는 유지합니다." in response.text
    assert "공식 로그인 방식별 권한·계정 자격 확인 전까지 연결을 제공하지 않습니다." in response.text
    assert re.search(
        rf'class="oauth-start-disabled"[^>]*data-account-id="{production_gui_account}"[^>]*disabled[^>]*aria-disabled="true"',
        response.text,
    )
    assert "실제 계정 연결 아님" in response.text
    assert "script-src 'self'" in response.headers["Content-Security-Policy"]
    assert "form-action 'self'" in response.headers["Content-Security-Policy"]


def test_client_values_and_tokens_are_never_displayed_or_reflected(
    client, production_gui_account, monkeypatch
):
    values = {
        "GOOGLE_CLIENT_ID": "synthetic-private-client-value.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "synthetic-private-google-secret",
        "NEWSFLOW_OAUTH_ACCESS_TOKEN": "synthetic-private-access-token",
        "NEWSFLOW_OAUTH_REFRESH_TOKEN": "synthetic-private-refresh-token",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    for path in ("/publishing", "/api/oauth/production-readiness"):
        response = client.get(
            path, params={"client_secret": values["GOOGLE_CLIENT_SECRET"], "approved": "true"}
        )
        assert response.status_code == 200
        assert all(value not in response.text for value in values.values())
        assert not re.search(
            r'<input[^>]*name="(?:client_id|client_secret|access_token|refresh_token|authorization_code)"',
            response.text,
        )
        assert "accounts.google.com/o/oauth" not in response.text


def test_forged_flags_do_not_change_readiness_or_legacy_start(client, production_gui_account, monkeypatch):
    previous_safety = client.get("/api/oauth/safety").json()
    for name in (
        "NEWSFLOW_OAUTH_PRODUCTION_ACTIVATION",
        "NEWSFLOW_OAUTH_ENABLED",
        "NEWSFLOW_OAUTH_USER_APPROVAL",
        "NEWSFLOW_OAUTH_FEATURE_ENABLED",
        "NEWSFLOW_REAL_SNS_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_MODE", "production")
    response = client.get(
        "/api/oauth/production-readiness",
        params={"production_activation": "true", "feature_enabled": "true", "user_approval": "true"},
    )
    assert response.json() == {**production_activation_status(), "providers": EXPECTED_PROVIDERS}
    token = csrf(client)
    blocked = client.post(
        f"/publishing/accounts/{production_gui_account}/oauth/start?production_activation=true",
        data={"csrf_token": token, "production_activation": "true", "approved": "true"},
    )
    assert blocked.status_code == 423 and "Location" not in blocked.headers
    assert client.get("/api/oauth/safety").json() == previous_safety


def test_readiness_endpoint_is_read_only(client):
    token = csrf(client)
    before = client.get("/api/oauth/production-readiness").json()
    response = client.post(
        "/api/oauth/production-readiness",
        data={"csrf_token": token, "production_activation": "true", "client_secret": "synthetic-form-secret"},
    )
    assert response.status_code == 405 and "synthetic-form-secret" not in response.text
    assert client.get("/api/oauth/production-readiness").json() == before


def test_readiness_get_and_blocked_start_have_no_network_browser_or_vault_side_effects(
    client, app, production_gui_account, monkeypatch
):
    operations = (
        (webbrowser, "open"),
        (urllib.request, "urlopen"),
        (http.client.HTTPSConnection, "request"),
        (socket.socket, "bind"),
        (ProductionCredentialBoundary, "__init__"),
    )
    sentinels = []
    for target, name in operations:
        sentinel = Mock(side_effect=AssertionError("readiness must not perform production operations"))
        monkeypatch.setattr(target, name, sentinel)
        sentinels.append(sentinel)
    token = csrf(client)
    assert client.get("/publishing").status_code == 200
    assert client.get("/api/oauth/production-readiness").status_code == 200
    assert (
        client.post(
            f"/publishing/accounts/{production_gui_account}/oauth/start", data={"csrf_token": token}
        ).status_code
        == 423
    )
    for sentinel in sentinels:
        sentinel.assert_not_called()
    with app.state.sessions() as session:
        account = session.get(PlatformAccount, production_gui_account)
        assert account.status == "not_connected" and account.credential_ref is None and not account.api_ready


@pytest.mark.parametrize("violation", ["missing_csrf", "null_origin", "cross_origin"])
def test_new_phase_keeps_start_csrf_and_origin_checks(client, production_gui_account, violation):
    token = csrf(client)
    data = {"production_activation": "true"}
    if violation != "missing_csrf":
        data["csrf_token"] = token
    origin = {"null_origin": "null", "cross_origin": "https://example.com"}.get(violation, "http://127.0.0.1")
    response = client.post(
        f"/publishing/accounts/{production_gui_account}/oauth/start", data=data, headers={"Origin": origin}
    )
    assert response.status_code == 403
    assert client.get("/api/oauth/production-readiness").json()["production_activation"] is False


@pytest.mark.parametrize("path", ["/oauth/authorize", "/oauth/callback", "/publishing/oauth/callback"])
def test_no_production_authorize_or_callback_http_route(client, path):
    raw = "synthetic-code-and-state-never-reflected"
    response = client.get(path, params={"code": raw, "state": raw})
    assert response.status_code == 404 and raw not in response.text
