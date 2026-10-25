"""Synthetic loopback boundary regressions; no browser, account or supplier connection."""
import http.client
import json
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from pydantic import SecretStr

from newsflow.oauth.tiktok_callback import TikTokCallback
from newsflow.oauth.tiktok_protocol import DesktopConfig, SCOPES, TikTokError, challenge

CONFIG = DesktopConfig('nf-synthetic-client', SecretStr('nf-synthetic-private-secret'))


def start(listener):
    parsed = urlsplit(listener.start(CONFIG).get_secret_value())
    query = parse_qs(parsed.query)
    redirect = urlsplit(query['redirect_uri'][0])
    assert redirect.scheme == 'http' and redirect.hostname == '127.0.0.1'
    assert redirect.path == '/oauth/tiktok/callback/' and redirect.port != 8765
    assert query['code_challenge'] == [challenge(listener.verifier.get_secret_value())]
    assert query['code_challenge_method'] == ['S256']
    return redirect, query


def request(redirect, query, *, method='GET', headers=None, changes=None, path=None):
    values = {'code': 'nf-synthetic-private-code', 'state': query['state'][0], 'scopes': ','.join(SCOPES)}
    values.update(changes or {})
    connection = http.client.HTTPConnection('127.0.0.1', redirect.port, timeout=3)
    try:
        connection.request(method, path or redirect.path + '?' + urlencode(values), headers=headers or {})
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


@pytest.mark.parametrize('bad', ['method', 'long_request', 'large_headers', 'wrong_host', 'origin', 'wrong_state', 'bad_path', 'duplicate_state'])
def test_malformed_callback_is_fixed_safe_and_does_not_consume(bad):
    listener = TikTokCallback(synthetic=True)
    try:
        redirect, query = start(listener)
        options = {}
        if bad == 'method': options['method'] = 'POST'
        if bad == 'long_request': options['path'] = redirect.path + '?private=' + 'x' * 4200
        if bad == 'large_headers': options['headers'] = {'X-Fixture': 'x' * 9000}
        if bad == 'wrong_host': options['headers'] = {'Host': 'outside.invalid'}
        if bad == 'origin': options['headers'] = {'Origin': 'https://outside.invalid'}
        if bad == 'wrong_state': options['changes'] = {'state': 'x' * 43}
        if bad == 'bad_path': options['path'] = '/wrong?' + urlencode({'state': query['state'][0]})
        if bad == 'duplicate_state': options['path'] = redirect.path + '?' + urlencode([('state', query['state'][0]), ('state', query['state'][0]), ('code', 'nf-synthetic-private-code')])
        status, headers, body = request(redirect, query, **options)
        assert 400 <= status < 600
        assert headers['Cache-Control'] == 'no-store'
        assert query['state'][0].encode() not in body and b'nf-synthetic-private-code' not in body
        assert not listener._used
        assert request(redirect, query)[0] == 200
        assert listener.wait().get_secret_value() == 'nf-synthetic-private-code'
        with pytest.raises(TikTokError): listener.wait()
        assert request(redirect, query)[0] == 409
        assert listener._observations['tcp_connections'] >= 2
    finally:
        listener.close()
    assert not listener._thread.is_alive()


def test_observation_counts_are_bounded_and_contain_no_callback_values():
    listener = TikTokCallback(synthetic=True)
    listener._observations['tcp_connections'] = 1_000_000
    listener._observe('tcp_connections')
    listener._observe('nf-synthetic-private-code')
    assert listener._observations['tcp_connections'] == 1_000_000
    assert 'nf-synthetic-private-code' not in json.dumps(listener._observations)
    assert set(listener._observations) == {'tcp_connections', 'http_requests', 'read_failures', 'rejected_requests'}


def test_missing_production_activation_remains_blocked(monkeypatch):
    monkeypatch.setattr('newsflow.oauth.tiktok_callback.production_enabled', lambda: False)
    listener = TikTokCallback()
    with pytest.raises(TikTokError): listener.start(CONFIG)
    assert listener._server is None and listener._thread is None


@pytest.mark.parametrize('port', [8765, -1, True, 65536])
def test_invalid_or_operating_redirect_port_remains_rejected(port):
    with pytest.raises(TikTokError): DesktopConfig('nf-synthetic-client', CONFIG.client_secret, port)
