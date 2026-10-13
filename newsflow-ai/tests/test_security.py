import socket

import pytest
from conftest import csrf

from newsflow.config import Settings
from newsflow.news.rss_adapter import (
    PublicRSSAdapter,
    Response,
    URLPolicyError,
    public_addresses,
    validate_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/rss",
        "http://127.0.0.1/rss",
        "http://[::1]/rss",
        "http://169.254.169.254/latest",
        "http://10.0.0.1/rss",
        "http://192.168.1.1/rss",
        "https://user:pass@example.com/rss",
        "https://example.com:8443/rss",
        "javascript:alert(1)",
        "https://example.com/rss?api_key=secret",
        "https://example.com/\nheader",
        "https://example.com\\@localhost/rss",
    ],
)
def test_ssrf_syntax(url):
    with pytest.raises(URLPolicyError):
        validate_url(url)


def test_dns_private_and_mixed(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(URLPolicyError):
        public_addresses("example.com", 443)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **kw: [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("10.0.0.1", 443))],
    )
    with pytest.raises(URLPolicyError):
        public_addresses("example.com", 443)


def test_redirect_revalidated():
    class Redirect:
        def get(self, url, timeout):
            if url.endswith("robots.txt"):
                return Response(404, b"")
            return Response(302, b"", "http://127.0.0.1/admin")

    with pytest.raises(URLPolicyError):
        PublicRSSAdapter(Redirect()).fetch("https://example.com/rss", 1)


def test_csrf_origin_host_and_validation(client):
    assert client.post("/collection").status_code == 403
    token = csrf(client)
    assert client.post("/collection", data={"csrf_token": "forged"}).status_code == 403
    assert (
        client.post(
            "/collection", data={"csrf_token": token}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    assert client.get("/", headers={"Host": "evil.example"}).status_code == 400
    assert (
        client.post(
            "/settings/sources",
            data={"csrf_token": token, "name": "bad", "url": "http://127.0.0.1/rss", "permission": "true"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/settings/sources", data={"csrf_token": token, "name": "test", "url": "https://example.com/rss"}
        ).status_code
        == 422
    )
    assert client.get("/news?sort=bad").status_code == 422
    assert client.get("/news?source=-1").status_code == 422
    assert client.get("/news?start=wrong").status_code == 422
    assert client.get("/news?category=bad").status_code == 422


def test_no_public_binding():
    with pytest.raises(ValueError):
        Settings(host="0.0.0.0")
    with pytest.raises(ValueError):
        Settings(port=80)
    with pytest.raises(ValueError):
        Settings(secret_key="short")


def test_multicast_block_and_ipv6_authority():
    with pytest.raises(URLPolicyError):
        validate_url("http://224.0.0.1/rss")
    assert validate_url("https://[2606:4700:4700::1111]/rss").startswith("https://[")


def test_connection_uses_validated_ip_and_tls_hostname(monkeypatch):
    from newsflow.news.rss_adapter import PinnedConnection

    calls = {}
    sock = object()

    def connect(address, timeout):
        calls["address"] = address
        return sock

    class Context:
        def wrap_socket(self, actual, server_hostname):
            assert actual is sock
            calls["hostname"] = server_hostname
            return sock

    monkeypatch.setattr(socket, "create_connection", connect)
    monkeypatch.setattr("ssl.create_default_context", lambda: Context())
    connection = PinnedConnection("example.com", "8.8.8.8", 443, 5, True)
    connection.connect()
    assert calls == {"address": ("8.8.8.8", 443), "hostname": "example.com"}


def test_unicode_csrf_rejected_not_server_error(client):
    csrf(client)
    assert client.post("/collection", data={"csrf_token": "잘못된토큰"}).status_code == 403
