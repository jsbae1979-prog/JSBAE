"""Static packaging/source integration. No EXE, app launch or provider call."""

import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_source_and_frozen_asset_roots_are_profile_independent(tmp_path, monkeypatch):
    from newsflow.studio import resources

    project = tmp_path / "project"
    monkeypatch.setattr(resources, "__file__", str(project / "src/newsflow/studio/resources.py"))
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "unrelated-user-profile"))
    assert resources.studio_dist_root() == project / "frontend/dist"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    bundle = tmp_path / "bundle/_internal"
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    assert resources.studio_dist_root() == bundle / "frontend/dist"
    assert not resources.studio_dist_root().is_relative_to(tmp_path / "unrelated-user-profile")
    monkeypatch.delattr(sys, "_MEIPASS")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bundle/NewsFlowAI-Technical.exe"))
    assert resources.studio_dist_root() == bundle / "frontend/dist"


def spec_input(tmp_path, monkeypatch, *, frontend=True, unexpected=False):
    project = tmp_path / "source"
    specdir = project / "tools/packaging"
    specdir.mkdir(parents=True)
    legacy = project / "src/newsflow/gui/templates"
    legacy.mkdir(parents=True)
    (legacy / "home.html").write_text("synthetic legacy HTML", encoding="utf-8")
    if frontend:
        dist = project / "frontend/dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text('<div id="root"></div>', encoding="utf-8")
        for name in ["app.js", "app.css", "font.ttf", "art.webp", "OFL.txt"]:
            (dist / "assets" / name).write_bytes(b"synthetic static asset")
        if unexpected:
            (dist / "assets/private.dpapi").write_bytes(b"synthetic forbidden extension")
    media = tmp_path / "media"
    media.mkdir()
    manifest = tmp_path / "technical-media.json"
    manifest.write_text("{}")
    monkeypatch.setenv("NEWSFLOW_BUILD_MEDIA", str(media))
    monkeypatch.setenv("NEWSFLOW_BUILD_MANIFEST", str(manifest))
    seen = {}

    def analysis(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(pure=[], scripts=[], binaries=[], datas=kwargs["datas"])

    globals_ = {
        "SPECPATH": str(specdir),
        "Analysis": analysis,
        "PYZ": lambda *a, **k: None,
        "EXE": lambda *a, **k: None,
        "COLLECT": lambda *a, **k: None,
    }
    spec = Path(__file__).resolve().parents[3] / "tools/packaging/newsflow-technical.spec"
    return spec, globals_, seen


def test_spec_includes_react_and_preserves_legacy_static_assets(tmp_path, monkeypatch):
    spec, globals_, seen = spec_input(tmp_path, monkeypatch)
    runpy.run_path(str(spec), init_globals=globals_)
    targets = {(Path(target) / Path(source).name).as_posix() for source, target in seen["datas"]}
    assert {
        "frontend/dist/index.html",
        "frontend/dist/assets/app.js",
        "frontend/dist/assets/app.css",
        "frontend/dist/assets/font.ttf",
        "frontend/dist/assets/art.webp",
        "frontend/dist/assets/OFL.txt",
    } <= targets
    assert "newsflow/gui/templates/home.html" in targets
    assert "playwright" in seen["excludes"] and "pytest" in seen["excludes"]
    assert all(not source.endswith(".dpapi") for source, _ in seen["datas"])


def test_spec_refuses_missing_react_build(tmp_path, monkeypatch):
    spec, globals_, seen = spec_input(tmp_path, monkeypatch, frontend=False)
    with pytest.raises(SystemExit, match="Build the reviewed React frontend"):
        runpy.run_path(str(spec), init_globals=globals_)
    assert seen == {}


def test_spec_refuses_unexpected_private_payload(tmp_path, monkeypatch):
    spec, globals_, seen = spec_input(tmp_path, monkeypatch, unexpected=True)
    with pytest.raises(SystemExit, match="Unexpected file type"):
        runpy.run_path(str(spec), init_globals=globals_)
    assert seen == {}
