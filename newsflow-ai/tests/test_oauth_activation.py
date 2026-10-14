"""Production entry points must reject forged approval before any I/O."""

from unittest.mock import patch

import pytest
from pydantic import SecretStr
from test_oauth_protocol import installed_document

from newsflow.oauth.activation import require_production_activation
from newsflow.oauth.contracts import OAuthBlocked
from newsflow.oauth.production import DesktopClientConfig, GoogleHTTPSOAuthTransport, GoogleSystemBrowser
from newsflow.oauth.providers import InstagramOAuthAdapter, YouTubeOAuthAdapter


@pytest.fixture
def desktop_config():
    return DesktopClientConfig.from_installed_json(installed_document())


@pytest.mark.parametrize("operation", ["token", "revoke", "invalid"])
def test_direct_official_https_transport_denies_before_tls_dns_or_request(operation, monkeypatch):
    monkeypatch.setenv("NEWSFLOW_PRODUCTION_ACTIVATION", "true")
    monkeypatch.setenv("NEWSFLOW_OAUTH_USER_APPROVED", "true")
    with patch("newsflow.oauth.production.build_opener") as opener, patch("socket.getaddrinfo") as dns:
        with pytest.raises(OAuthBlocked):
            GoogleHTTPSOAuthTransport().post(operation, {"code": "nf-synthetic-code-test"})
        opener.assert_not_called()
        dns.assert_not_called()


def test_system_browser_denies_before_browser_open_even_with_forged_environment(monkeypatch):
    monkeypatch.setenv("NEWSFLOW_PRODUCTION_ACTIVATION", "true")
    with patch("webbrowser.open") as browser:
        with pytest.raises(OAuthBlocked):
            GoogleSystemBrowser().open(SecretStr("https://accounts.google.com/o/oauth2/v2/auth?state=fixture"))
        browser.assert_not_called()


def test_google_provider_factory_constructs_only_inert_official_protocol(desktop_config):
    with patch("webbrowser.open") as browser, patch("newsflow.oauth.production.build_opener") as opener:
        protocol = YouTubeOAuthAdapter(feature_enabled=True, user_approved=True).configured_protocol(desktop_config)
        with pytest.raises(OAuthBlocked):
            protocol.begin("youtube:1", open_browser=True)
        browser.assert_not_called()
        opener.assert_not_called()


def test_instagram_cannot_inherit_google_protocol(desktop_config):
    with pytest.raises(OAuthBlocked):
        InstagramOAuthAdapter(feature_enabled=True, user_approved=True).configured_protocol(desktop_config)


def test_production_gate_accepts_no_runtime_approval_argument():
    with pytest.raises(OAuthBlocked):
        require_production_activation()
    with pytest.raises(TypeError):
        require_production_activation(user_approved=True)
