from __future__ import annotations

import ssl

import pytest
from conftest import csrf

from newsflow.news.collector import parse_feed
from newsflow.news.rss_adapter import ErrorKind, FeedError, PublicRSSAdapter, Response


def test_null_origin_rejected_even_with_valid_csrf(client):
    token = csrf(client)
    assert (
        client.post("/collection", data={"csrf_token": token}, headers={"Origin": "null"}).status_code == 403
    )
    assert (
        client.post(
            "/settings/collection",
            data={"csrf_token": token, "timeout": 5},
            headers={"Origin": "http://127.0.0.1"},
        ).status_code
        == 200
    )


def test_classified_dns_https_timeout_and_parse(monkeypatch):
    from newsflow.news import rss_adapter

    monkeypatch.setattr(rss_adapter.socket, "getaddrinfo", lambda *a, **kw: (_ for _ in ()).throw(OSError()))
    with pytest.raises(FeedError) as error:
        rss_adapter.public_addresses("example.com", 443, 1)
    assert error.value.kind == ErrorKind.DNS
    monkeypatch.setattr(rss_adapter, "public_addresses", lambda *a: ["8.8.8.8"])
    for exception, kind in [
        (ssl.SSLCertVerificationError(), ErrorKind.HTTPS),
        (TimeoutError(), ErrorKind.TIMEOUT),
    ]:

        def fail(*a, exception=exception, **kw):
            raise exception

        monkeypatch.setattr(rss_adapter.PinnedConnection, "request", fail)
        with pytest.raises(FeedError) as error:
            rss_adapter.PublicTransport().get("https://example.com/rss", 1)
        assert error.value.kind == kind
    with pytest.raises(FeedError) as error:
        parse_feed(b"<rss>broken", "test")
    assert error.value.kind == ErrorKind.PARSE


def test_robots_failure_is_not_parse_or_dns():
    class Transport:
        def get(self, url, timeout):
            return Response(403, b"")

    with pytest.raises(FeedError) as error:
        PublicRSSAdapter(Transport()).fetch("https://example.com/rss", 1)
    assert error.value.kind == ErrorKind.ROBOTS


def test_gui_running_and_completion_state(client, app, fake):
    from threading import Event

    from newsflow.db.models import NewsSource

    with app.state.sessions.begin() as session:
        session.add(NewsSource(name="Fixture", url="https://example.com/rss"))
    entered, release = Event(), Event()
    original = fake.fetch

    def fetch(url, timeout):
        entered.set()
        assert release.wait(5)
        return original(url, timeout)

    fake.fetch = fetch
    token = csrf(client)
    response = client.post("/collection", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/dashboard"
    assert entered.wait(5)
    try:
        assert client.get("/api/collection").json()["status"] == "running"
        assert "disabled" in client.get("/dashboard").text
    finally:
        release.set()
    app.state.coordinator.future.result(timeout=5)
    result = client.get("/api/collection").json()
    assert result["status"] == "success" and result["added"] == 3


def test_diagnostic_stores_verified_snapshot(monkeypatch, rss):
    from newsflow import diagnostics

    monkeypatch.setattr(diagnostics, "public_addresses", lambda *args: ["8.8.8.8"])
    calls = []

    def fetch(self, url, timeout):
        calls.append(url)
        return rss

    monkeypatch.setattr(diagnostics.PublicRSSAdapter, "fetch", fetch)
    result = diagnostics.diagnose("https://example.com/rss", 1)
    assert result["rss_store"] == "PASS"
    assert result["article_count"] == 3 and result["collection_status"] == "success"
    assert len(calls) == 1


def test_diagnostic_rejects_secret_url_without_output():
    import os
    import subprocess
    import sys

    sentinel = "DO-NOT-EXPOSE-API-KEY"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "newsflow.diagnostics",
            "--url",
            f"https://example.com/rss?api_key={sentinel}",
        ],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 1
    assert sentinel not in result.stdout + result.stderr


def test_form_fix_preserves_referrer_and_csp_policy(client):
    for path in ("/", "/news", "/settings"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["Referrer-Policy"] == "no-referrer"
        assert "form-action 'self'" in response.headers["Content-Security-Policy"]
