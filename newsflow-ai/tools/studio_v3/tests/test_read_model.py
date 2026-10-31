import json
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from newsflow.db.models import AppSetting, Base, IntelligenceRun
from newsflow.gui.studio_v3 import workspace


class MetadataOnly:
    def status(self):
        return {"configured": True}

    def key(self):
        raise AssertionError("Credential decryption forbidden")


def setup(tmp_path):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    state = NS(
        sessions=sessions,
        config=NS(data_dir=tmp_path),
        video=NS(outputs=tmp_path),
        character=NS(listing=list, sessions=sessions),
        image_studio=NS(assets=list, characters=list),
        ai_keys=MetadataOnly(),
        api_keys={"claude_api": MetadataOnly()},
        video_ai=NS(keys=MetadataOnly()),
        image_generation=NS(
            path=lambda _: (_ for _ in ()).throw(AssertionError("No completed image call expected"))
        ),
    )
    return NS(app=NS(state=state)), engine, sessions


def test_empty_readonly_and_no_credentials(tmp_path):
    request, engine, sessions = setup(tmp_path)
    with sessions.begin() as s:
        s.add(AppSetting(key="test-secret-setting", value="SYNTHETIC-SECRET-NOT-RETURNED"))
    with engine.connect() as c:
        before = c.exec_driver_sql("select * from app_settings").fetchall()
    result = workspace(request)
    with engine.connect() as c:
        after = c.exec_driver_sql("select * from app_settings").fetchall()
    assert result["projects"] == [] and result["stats"] == {
        "running": 0,
        "ready": 0,
        "publishDrafts": 0,
        "total": 0,
    }
    assert before == after and "SYNTHETIC-SECRET" not in json.dumps(result)
    assert result["dataOrigin"] == "local-workspace" and all(not x["verified"] for x in result["services"])
    engine.dispose()


@pytest.mark.parametrize("status", ["unknown", "failed", "running", "draft"])
def test_unfinished_image_never_has_media(tmp_path, status):
    request, engine, sessions = setup(tmp_path)
    with sessions.begin() as s:
        s.add(
            IntelligenceRun(
                kind="image_draft",
                status=status,
                provider="openai",
                options={"prompt": "합성 테스트"},
                evidence={},
                result={"filename": "../../secret.dpapi"},
                message="do not expose raw diagnostic",
            )
        )
    result = workspace(request)
    p = result["projects"][0]
    assert p["technicalStatus"] == status and p["mediaUrl"] is None and p["thumbnailUrl"] is None
    assert "secret.dpapi" not in json.dumps(result) and "raw diagnostic" not in json.dumps(result)
    assert p["publishApprovalStatus"] == "separate_approval_required"
    with sessions() as s:
        assert s.scalar(select(IntelligenceRun)).status == status
    engine.dispose()


def test_key_presence_is_not_verified_connection(tmp_path):
    request, engine, _sessions = setup(tmp_path)
    (tmp_path / "tts-elevenlabs-key.dpapi").write_bytes(b"SYNTHETIC-NOT-A-KEY")
    result = workspace(request)
    voice = next(x for x in result["services"] if x["id"] == "elevenlabs")
    assert voice["configured"] and not voice["verified"] and "SYNTHETIC-NOT-A-KEY" not in json.dumps(result)
    engine.dispose()


def test_sample_art_is_explicit_and_never_production_fallback(tmp_path):
    request, engine, sessions = setup(tmp_path)
    with sessions.begin() as s:
        s.add(
            IntelligenceRun(
                kind="image_draft",
                status="unknown",
                provider="openai",
                options={"prompt": "합성"},
                evidence={},
                result={},
                message="",
            )
        )
    assert workspace(request)["projects"][0]["thumbnailUrl"] is None
    request.app.state.studio_synthetic = True
    result = workspace(request)
    assert result["dataOrigin"] == "development-fixtures" and "합성" in result["projects"][0]["sourceLabel"]
    assert result["projects"][0]["mediaUrl"] is None
    engine.dispose()


@pytest.fixture(autouse=True)
def prohibit_network_and_process(monkeypatch):
    import socket
    import subprocess

    def blocked(*args, **kwargs):
        raise AssertionError("No network or external process in read-model tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
