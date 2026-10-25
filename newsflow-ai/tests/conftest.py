from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from newsflow.config import Settings
from newsflow.main import create_app
from newsflow.news.rss_adapter import FakeRSSAdapter

pytest_plugins = ("oauth_protocol_fixtures",)


@pytest.fixture
def rss() -> bytes:
    return (Path(__file__).parent / "fixtures" / "normal.xml").read_bytes()


@pytest.fixture
def fake(rss: bytes) -> FakeRSSAdapter:
    return FakeRSSAdapter({"https://example.com/rss": rss})


@pytest.fixture
def app(tmp_path: Path, fake: FakeRSSAdapter, step13_isolation):
    return create_app(Settings(data_dir=tmp_path / "test-data"), fake)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def csrf(client) -> str:
    client.get("/")
    return client.cookies["newsflow_csrf"]
