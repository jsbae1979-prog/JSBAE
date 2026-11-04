from pathlib import Path
import os
import socket

import pytest
from fastapi.testclient import TestClient

from newsflow.config import Settings
from newsflow.main import create_app
from newsflow.news.rss_adapter import FakeRSSAdapter

pytest_plugins = ("oauth_protocol_fixtures",)


@pytest.fixture(autouse=True)
def legacy_character_story_format(request, monkeypatch):
    """Existing character fixtures encode the pre-format story rules.

    New jobs normally freeze config/character_story.yaml; tests that check the
    shorts format opt in with the ``story_format`` marker.
    """
    if request.node.get_closest_marker('story_format'):
        return
    from newsflow.character import episode_service
    monkeypatch.setattr(episode_service, 'load_story_format', lambda: None)


@pytest.fixture
def synthetic_app_isolation(monkeypatch, tmp_path, request):
    """Plain pytest's synthetic app boundary; historical Guard plugins retain theirs.

    The common app fixture used to name a fixture available only through a
    separate validation bootstrap. Keep ordinary pytest self-contained without
    changing product guards, enabling external providers or skipping tests.
    """
    if request.config.pluginmanager.hasplugin('step13_fixtures'):
        yield
        return
    root = tmp_path / 'synthetic-environment'
    for name in ('TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA', 'NEWSFLOW_DATA_DIR'):
        folder = root / name.lower()
        folder.mkdir(parents=True)
        monkeypatch.setenv(name, str(folder))
    test_options = {'NEWSFLOW_DATA_DIR', 'NEWSFLOW_SCRIPT_PROMPT_VERSION',
                    'NEWSFLOW_FFMPEG', 'NEWSFLOW_FFPROBE', 'NEWSFLOW_FONT_PATH',
                    'NEWSFLOW_BASELINE_GUI_SOURCE'}
    for name in tuple(os.environ):
        if name.startswith(('NEWSFLOW_', 'OPENAI_', 'ANTHROPIC_', 'ELEVENLABS_', 'HIGGSFIELD_', 'SERPAPI_')) or name in {'HF_KEY','HF_SECRET'}:
            if name not in test_options: monkeypatch.delenv(name, raising=False)
    # Legacy browser evidence writers previously depended on a separate harness.
    # Plain pytest writes screenshots only inside this test's temporary root.
    for name in ('NEWSFLOW_USABILITY_EVIDENCE', 'NEWSFLOW_MODERN_SCRIPT_EVIDENCE',
                 'NEWSFLOW_SMALL_UX_EVIDENCE', 'NEWSFLOW_CONTROL_EVIDENCE',
                 'NEWSFLOW_STUDIO_POLISH_EVIDENCE', 'NEWSFLOW_VIDEO_MODERN_EVIDENCE',
                 'NEWSFLOW_VALIDATION_OUTPUT'):
        folder = root / 'evidence' / name.lower()
        folder.mkdir(parents=True)
        monkeypatch.setenv(name, str(folder))
    connect, connect_ex, resolve = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo

    def local(address):
        return (isinstance(address, tuple) and len(address) >= 2
                and address[0] in {'127.0.0.1', '::1', 'localhost'}
                and address[1] not in {8765, 18768})

    def safe_connect(sock, address):
        if not local(address): raise AssertionError('Synthetic test attempted external/operating network access')
        return connect(sock, address)

    def safe_connect_ex(sock, address):
        if not local(address): raise AssertionError('Synthetic test attempted external/operating network access')
        return connect_ex(sock, address)

    def safe_resolve(host, *args, **kwargs):
        if host not in {'127.0.0.1', '::1', 'localhost', None}:
            raise AssertionError('Synthetic test attempted external DNS')
        return resolve(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, 'connect', safe_connect)
    monkeypatch.setattr(socket.socket, 'connect_ex', safe_connect_ex)
    monkeypatch.setattr(socket, 'getaddrinfo', safe_resolve)
    yield


@pytest.fixture
def rss() -> bytes:
    return (Path(__file__).parent / "fixtures" / "normal.xml").read_bytes()


@pytest.fixture
def fake(rss: bytes) -> FakeRSSAdapter:
    return FakeRSSAdapter({"https://example.com/rss": rss})


@pytest.fixture
def app(tmp_path: Path, fake: FakeRSSAdapter, synthetic_app_isolation):
    app = create_app(Settings(data_dir=tmp_path / "test-data"), fake, automatic_start=False)
    try:
        yield app
    finally:
        # Only this fixture's synthetic app resources, including clients not
        # entered as context managers. No operating process is addressed.
        for name in ('youtube','tiktok','instagram','publishing_calendar','scheduler','video_ai',
                     'autopilot','autopilot_backend','coordinator','video'):
            obj = getattr(app.state, name, None)
            if obj is not None and callable(getattr(obj, 'close', None)): obj.close()
        app.state.engine.dispose()


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        yield client


def csrf(client) -> str:
    client.get("/")
    return client.cookies["newsflow_csrf"]
