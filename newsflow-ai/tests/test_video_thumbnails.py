"""Thumbnail requests remain local, bounded and behind the existing media validation."""

import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from newsflow.db.models import ContentDraft, IntelligenceRun, RenderJob, VideoProject
from newsflow.video import thumbnails
from newsflow.video.engine import RenderError


def test_first_frame_cached_and_invalidated_without_writing_media(tmp_path, monkeypatch):
    source = tmp_path / "video.mp4"
    source.write_bytes(b"original")
    binary = tmp_path / "ffmpeg.exe"
    binary.touch()
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout=b"\x89PNG\r\n\x1a\nframe"))
    monkeypatch.setattr(thumbnails.subprocess, "run", run)
    first = thumbnails.thumbnail(source, binary)
    assert thumbnails.thumbnail(source, binary) == first
    assert run.call_count == 1
    args, kwargs = run.call_args
    assert args[0][args[0].index("-protocol_whitelist") + 1] == "file,pipe"
    assert args[0][args[0].index("-frames:v") + 1] == "1"
    assert kwargs["timeout"] == 10 and kwargs["shell"] is False
    assert source.read_bytes() == b"original"
    source.write_bytes(b"replacement")
    thumbnails.thumbnail(source, binary)
    assert run.call_count == 2


@pytest.mark.parametrize("result", [b"bad", b"\x89PNG\r\n\x1a\n" + b"a" * 512_000], ids=["invalid", "oversize"])
def test_bad_or_oversized_frame_rejected(tmp_path, monkeypatch, result):
    path = tmp_path / "test.mp4"
    path.write_bytes(b"test")
    monkeypatch.setattr(thumbnails.subprocess, "run", Mock(return_value=SimpleNamespace(returncode=0, stdout=result)))
    with pytest.raises(RenderError):
        thumbnails.thumbnail(path, path)


def test_timeout_has_no_internal_error_details(tmp_path, monkeypatch):
    path = tmp_path / "test.mp4"
    path.write_bytes(b"test")
    monkeypatch.setattr(thumbnails.subprocess, "run", Mock(side_effect=subprocess.TimeoutExpired("secret-path", 10)))
    with pytest.raises(RenderError, match="미리보기") as error:
        thumbnails.thumbnail(path, path)
    assert "secret-path" not in str(error.value)


def test_thumbnail_route_rechecks_media_state_and_path(client, app, monkeypatch):
    output = "video-" + "1" * 32 + ".mp4"
    with app.state.sessions.begin() as session:
        run = IntelligenceRun(kind="script", status="success", provider="offline", options={},
                              evidence={}, result={}, message="fixture")
        session.add(run)
        session.flush()
        draft = ContentDraft(run_id=run.id, duration=30, content={}, sources={})
        session.add(draft)
        session.flush()
        project = VideoProject(draft_id=draft.id, title="fixture", duration=30, snapshot={}, sources={})
        session.add(project)
        session.flush()
        render = RenderJob(project_id=project.id, status="success", output_name=output,
                           metadata_json={"playable": True})
        session.add(render)
        session.flush()
        identifier = render.id
    target = app.state.video.outputs / output
    target.write_bytes(b"fixture")
    frame = Mock(return_value=b"\x89PNG\r\n\x1a\nframe")
    monkeypatch.setattr(thumbnails, "thumbnail", frame)
    response = client.get(f"/video/jobs/{identifier}/thumbnail")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert "no-store" in response.headers["cache-control"]  # global security middleware keeps responses uncached
    with app.state.sessions.begin() as session:
        session.get(RenderJob, identifier).status = "failed"
    assert client.get(f"/video/jobs/{identifier}/thumbnail").status_code == 404
    with app.state.sessions.begin() as session:
        row = session.get(RenderJob, identifier)
        row.status = "success"
        row.output_name = "../outside.mp4"
    assert client.get(f"/video/jobs/{identifier}/thumbnail").status_code == 404
    assert frame.call_count == 1


def test_missing_thumbnail_does_not_execute_ffmpeg(client, monkeypatch):
    frame = Mock()
    monkeypatch.setattr(thumbnails, "thumbnail", frame)
    assert client.get("/video/jobs/99999/thumbnail").status_code == 404
    frame.assert_not_called()
