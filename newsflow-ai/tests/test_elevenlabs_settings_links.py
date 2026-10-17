"""ElevenLabs links and key status use isolated data without external requests."""

import json
import subprocess
import urllib.request

import pytest
from conftest import csrf
from sqlalchemy import select
from test_claude_connection_gui import Document

from newsflow.db.models import AppSetting
from newsflow.gui import production_routes, production_status
from newsflow.intelligence.credentials import FakeCipher
from newsflow.intelligence.settings import _set
from newsflow.video import elevenlabs_tts, supertonic_tts

KEY = "synthetic-elevenlabs-settings-key-0123456789"


@pytest.fixture
def isolated_store(app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Settings display and key saving must not call a provider or CLI")

    monkeypatch.delenv("NEWSFLOW_ELEVENLABS_KEY", raising=False)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(elevenlabs_tts.ElevenLabsTTS, "subscription", forbidden)
    monkeypatch.setattr(elevenlabs_tts.ElevenLabsTTS, "synthesize_timed", forbidden)
    monkeypatch.setattr(supertonic_tts.SupertonicTTS, "voices", lambda self: [])
    for module in (production_status, production_routes):
        monkeypatch.setattr(module, "voice_choice_catalog", lambda: [
            {"name": "offline-silence", "label": "무음", "engine": "offline", "available": True},
            {"name": "elevenlabs", "label": "ElevenLabs", "engine": "elevenlabs", "available": False},
        ])
    store = elevenlabs_tts.ElevenLabsKeys(app.state.video.root, FakeCipher())
    monkeypatch.setattr(elevenlabs_tts, "ElevenLabsKeys", lambda root: store)
    monkeypatch.setattr(production_status, "ElevenLabsKeys", lambda root: store)
    return store


def saved_values(app):
    with app.state.sessions() as session:
        return {row.key: row.value for row in session.scalars(select(AppSetting))}


def official_link(document, panel=None):
    links = document.find("a", href="https://elevenlabs.io/")
    if panel is not None:
        links = [link for link in links if panel in link.ancestors]
    assert len(links) == 1
    assert links[0].attrs["target"] == "_blank"
    assert {"noopener", "noreferrer"} <= set(links[0].attrs["rel"].split())
    assert "ElevenLabs" in "".join(links[0].text)


def status(document, configured, panel=None):
    label = "API Key 등록됨" if configured else "API Key 미등록"
    matches = [node for node in document.find("span") if label in "".join(node.text)
               and (panel is None or panel in node.ancestors)]
    assert len(matches) == 1
    expected = "status-chip--success" if configured else "status-chip--error"
    assert expected in matches[0].attrs["class"].split()


def test_selected_voice_panel_links_to_existing_key_editor_and_displays_saved_key_status(
    client, app, isolated_store,
):
    with app.state.sessions.begin() as session:
        _set(session, "video_default_voice", "elevenlabs")
    before = saved_values(app)
    for configured in (False, True):
        if configured:
            isolated_store.save(KEY)
        response = client.get("/simple-settings")
        assert response.status_code == 200 and KEY not in response.text
        document = Document(response.text)
        panel = document.find("div", **{"data-voice-provider": "elevenlabs"})[0]
        assert "hidden" not in panel.attrs
        official_link(document, panel)
        status(document, configured, panel)
        assert any(panel in node.ancestors for node in document.find("a", href="/video/tts"))
        assert "실제 음성 생성 미검증" in "".join(panel.text)
        assert "무료 플랜은 비상업용" in "".join(panel.text)
    assert saved_values(app) == before
    assert KEY not in json.dumps(before)


def test_tts_key_page_retains_local_key_save_route_and_never_exposes_key(client, app, isolated_store):
    response = client.get("/video/tts")
    assert response.status_code == 200
    document = Document(response.text)
    official_link(document)
    status(document, False)
    form = document.find("form", action="/video/tts/key")[0]
    field = next(node for node in document.find("input", name="api_key") if form in node.ancestors)
    assert field.attrs["type"] == "password" and "value" not in field.attrs
    before = saved_values(app)
    response = client.post("/video/tts/key", data={"csrf_token": csrf(client), "api_key": KEY},
                           follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/video/tts"
    response = client.get("/video/tts")
    assert response.status_code == 200 and KEY not in response.text
    document = Document(response.text)
    status(document, True)
    assert "키 등록과 실제 연결 확인은 별개" in response.text
    assert KEY.encode() not in isolated_store.path.read_bytes()
    assert saved_values(app) == before
