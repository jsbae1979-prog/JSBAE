"""Operational preparation UI stays informational and cannot activate services."""

from __future__ import annotations

import http.client
import re
import socket
import urllib.request
import webbrowser
from unittest.mock import Mock

import pytest
from conftest import csrf
from sqlalchemy import func, select

from newsflow.db.models import PlatformAccount, PublishAttempt, PublishJob
from newsflow.oauth.callback import LoopbackCallbackListener
from newsflow.oauth.identity import YouTubeIdentityAdapter
from newsflow.oauth.production_dpapi import ProductionWindowsCredentialVault
from newsflow.oauth.production_vault import ProductionCredentialBoundary
from newsflow.publishing.service import PublishingService


@pytest.fixture
def operations_account(app) -> int:
    return PublishingService(app.state.sessions, app.state.video.outputs).add_account(
        "youtube", "합성 운영 기반 검토 채널", "youtube_channel"
    )


def test_operations_readiness_marks_code_prepared_but_real_services_blocked(client):
    response = client.get("/api/oauth/operations-readiness")
    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == "4B-2B" and data["mode"] == "OFFLINE/BLOCKED"
    assert data["production_activation"] is False
    for key in (
        "real_login_allowed", "real_token_exchange_allowed", "real_identity_lookup_allowed",
        "real_publishing_allowed",
    ):
        assert data[key] is False
    assert data["callback"]["binding"] == "127.0.0.1"
    assert data["callback"]["registered_uri_match"] == "exact"
    assert data["callback"]["listener_started_by_gui"] is False
    assert data["callback"]["real_provider_connected"] is False
    assert data["youtube_identity"]["real_account"] == "NOT VERIFIED"
    assert data["youtube_identity"]["connection_on_error"] == "blocked"
    assert data["production_vault"]["boundary"] == "Windows current-user DPAPI"
    assert data["production_vault"]["validation_data"] == "synthetic_only"
    assert data["production_vault"]["real_credentials_allowed"] is False
    assert data["instagram"]["login"] == "blocked"
    assert data["instagram"]["official_requirements"] == "NOT VERIFIED"
    assert response.headers["Cache-Control"] == "no-store"


def test_operations_panel_keeps_real_connect_button_disabled(client, operations_account):
    response = client.get("/publishing")
    assert response.status_code == 200 and "운영 OAuth 기반 · 실제 서비스 차단" in response.text
    panel = re.search(r'<div[^>]*id="oauth-operations-readiness"[^>]*>', response.text)
    assert panel is not None and 'data-phase="4B-2B"' in panel.group()
    for attribute in (
        "production-activation", "listener-started", "real-identity-lookup-allowed",
        "real-credentials-allowed",
    ):
        assert f'data-{attribute}="false"' in panel.group()
    assert "실제 채널 NOT VERIFIED" in response.text
    assert "실제 토큰 저장·조회 차단" in response.text
    assert "조회 실패·결과 불명은 연결 준비 차단" in response.text
    assert "계정 인증과 게시 승인은 별도입니다." in response.text
    assert re.search(
        rf'class="oauth-start-disabled"[^>]*data-account-id="{operations_account}"[^>]*disabled',
        response.text,
    )
    assert 'action="/oauth/callback"' not in response.text
    assert 'action="/api/oauth/operations-readiness"' not in response.text
    assert "form-action 'self'" in response.headers["Content-Security-Policy"]


def test_operations_readiness_does_not_create_listener_browser_network_or_vault(
    client, app, operations_account, monkeypatch
):
    sentinels = []
    for target, name in (
        (socket.socket, "bind"), (webbrowser, "open"), (urllib.request, "urlopen"),
        (http.client.HTTPSConnection, "request"), (ProductionCredentialBoundary, "__init__"),
        (ProductionWindowsCredentialVault, "__init__"), (LoopbackCallbackListener, "start"),
        (YouTubeIdentityAdapter, "lookup"),
    ):
        sentinel = Mock(side_effect=AssertionError("operational preparation is read only"))
        monkeypatch.setattr(target, name, sentinel)
        sentinels.append(sentinel)
    token = csrf(client)
    assert client.get("/api/oauth/operations-readiness").status_code == 200
    assert client.get("/publishing").status_code == 200
    assert client.post(
        f"/publishing/accounts/{operations_account}/oauth/start",
        data={"csrf_token": token, "production_activation": "true", "approved": "true"},
    ).status_code == 423
    for sentinel in sentinels:
        sentinel.assert_not_called()
    with app.state.sessions() as session:
        account = session.get(PlatformAccount, operations_account)
        assert account.status == "not_connected" and not account.api_ready
        assert account.credential_ref is None and account.scopes == []
        assert session.scalar(select(func.count()).select_from(PublishJob)) == 0
        assert session.scalar(select(func.count()).select_from(PublishAttempt)) == 0


@pytest.mark.parametrize("setting", [
    "NEWSFLOW_OAUTH_PRODUCTION_ACTIVATION", "NEWSFLOW_OAUTH_ENABLED",
    "NEWSFLOW_OAUTH_USER_APPROVAL", "NEWSFLOW_REAL_SNS_ENABLED",
    "NEWSFLOW_OAUTH_CALLBACK_ENABLED", "NEWSFLOW_OAUTH_IDENTITY_ENABLED",
    "NEWSFLOW_PRODUCTION_VAULT_ENABLED",
])
def test_operational_flags_cannot_enable_production(client, operations_account, monkeypatch, setting):
    before = client.get("/api/oauth/operations-readiness").json()
    safety = client.get("/api/oauth/safety").json()
    monkeypatch.setenv(setting, "true")
    response = client.get("/api/oauth/operations-readiness", params={setting: "true", "approved": "true"})
    assert response.json() == before
    token = csrf(client)
    blocked = client.post(
        f"/publishing/accounts/{operations_account}/oauth/start?{setting}=true",
        data={"csrf_token": token, setting: "true", "approved": "true"},
    )
    assert blocked.status_code == 423 and "Location" not in blocked.headers
    assert client.get("/api/oauth/safety").json() == safety


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_operations_readiness_cannot_accept_activation_commands(client, method):
    before = client.get("/api/oauth/operations-readiness").json()
    token = csrf(client)
    response = client.request(
        method.upper(), "/api/oauth/operations-readiness",
        content=f"csrf_token={token}&approved=true",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 405
    assert client.get("/api/oauth/operations-readiness").json() == before


@pytest.mark.parametrize("path", ["/api/oauth/operations-readiness", "/publishing"])
def test_operations_view_never_reflects_callback_or_secret_input(client, path, monkeypatch):
    values = {
        "code": "synthetic-private-callback-code",
        "state": "synthetic-private-callback-state",
        "access_token": "synthetic-private-access-token",
        "refresh_token": "synthetic-private-refresh-token",
        "client_secret": "synthetic-private-client-secret",
    }
    for key, value in values.items():
        monkeypatch.setenv("NEWSFLOW_" + key.upper(), value)
    response = client.get(path, params=values)
    assert response.status_code == 200
    assert all(value not in response.text for value in values.values())
    assert "accounts.google.com/o/oauth" not in response.text
    assert "api.instagram.com/oauth" not in response.text
    assert not re.search(
        r'<input[^>]*name="(?:code|state|access_token|refresh_token|client_secret)"', response.text
    )


def test_local_preparation_remains_unconnected_after_operations_view(client, app, operations_account):
    token = csrf(client)
    for action in ("prepare", "disconnect-prepare"):
        response = client.post(
            f"/publishing/accounts/{operations_account}/oauth/{action}",
            data={"csrf_token": token}, follow_redirects=False,
        )
        assert response.status_code == 303 and response.headers["Location"] == "/publishing"
        assert client.get("/api/oauth/operations-readiness").json()["production_activation"] is False
    with app.state.sessions() as session:
        account = session.get(PlatformAccount, operations_account)
        assert account.credential_ref is None and account.status == "not_connected"
        assert not account.api_ready


@pytest.mark.parametrize("origin", ["null", "https://example.com", "http://localhost:8765"])
def test_operational_phase_preserves_exact_origin_csrf(client, operations_account, origin):
    token = csrf(client)
    response = client.post(
        f"/publishing/accounts/{operations_account}/oauth/prepare",
        data={"csrf_token": token}, headers={"Origin": origin},
    )
    assert response.status_code == 403
    assert client.get("/api/oauth/operations-readiness").json()["production_activation"] is False


@pytest.mark.parametrize("path", ["/oauth/callback", "/oauth/authorize", "/api/oauth/token"])
def test_default_app_does_not_dispatch_callback_or_code_exchange(client, path):
    private = "synthetic-inactive-auth-code"
    response = client.get(path, params={"code": private, "state": private})
    assert response.status_code == 404 and private not in response.text
