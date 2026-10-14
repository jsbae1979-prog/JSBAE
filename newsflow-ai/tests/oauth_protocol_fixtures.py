"""Shared synthetic protocol fixtures registered once for whole-suite collection."""

import pytest
from oauth_protocol_server import FakeOAuthHTTPServer

from newsflow.oauth.production import DesktopClientConfig, GoogleOAuthProtocol, SyntheticLoopbackTransport


def installed_document(**changes):
    installed = {
        "client_id": "nf-synthetic-desktop.apps.googleusercontent.com",
        "client_secret": "nf-synthetic-client-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
    installed.update(changes)
    return {"installed": installed}


@pytest.fixture
def config():
    return DesktopClientConfig.from_installed_json(installed_document())


@pytest.fixture
def server():
    fake = FakeOAuthHTTPServer()
    fake.start()
    try:
        yield fake
    finally:
        fake.close()


@pytest.fixture
def protocol(config, server):
    return GoogleOAuthProtocol(config, SyntheticLoopbackTransport(server.base_url), synthetic=True)
