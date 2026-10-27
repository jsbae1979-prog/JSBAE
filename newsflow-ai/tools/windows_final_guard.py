"""No vendor requests or login browser launches in the isolated regression comparison."""
import http.client
import ipaddress
import os
import socket
import webbrowser

import pytest


@pytest.fixture(scope='session', autouse=True)
def no_external_services():
    with pytest.MonkeyPatch.context() as patch:
        safe = {'NEWSFLOW_DATA_DIR', 'NEWSFLOW_FONT_PATH', 'NEWSFLOW_TEST_BROWSER_EXECUTABLE',
                'NEWSFLOW_VALIDATION_OUTPUT', 'NEWSFLOW_SETTINGS_EVIDENCE', 'NEWSFLOW_STUDIO_POLISH_EVIDENCE'}
        for key in tuple(os.environ):
            if (key.startswith('NEWSFLOW_') and key not in safe) or key in {
                'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'CLAUDE_CODE_OAUTH_TOKEN'}:
                patch.delenv(key)

        def deny(*args, **kwargs):
            raise AssertionError('External services and OAuth are forbidden in Windows UI validation')

        original = socket.create_connection

        def connect(address, *args, **kwargs):
            try:
                allowed = ipaddress.ip_address(address[0]).is_loopback
            except ValueError:
                allowed = address[0] == 'localhost'
            if not allowed:
                return deny()
            return original(address, *args, **kwargs)

        patch.setattr(socket, 'create_connection', connect)
        patch.setattr('urllib.request.OpenerDirector.open', deny)
        patch.setattr(http.client.HTTPSConnection, 'connect', deny)
        patch.setattr('httpx.HTTPTransport.handle_request', deny)
        patch.setattr('httpx.AsyncHTTPTransport.handle_async_request', deny)
        patch.setattr(webbrowser, 'open', deny)
        yield
