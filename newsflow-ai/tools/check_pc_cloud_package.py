"""Installed distributions must include the pinned UI assets, not just editable sources."""
import os
from pathlib import Path
from zipfile import ZipFile


def test_built_wheel_preserves_every_runtime_static_asset_and_provenance():
    wheel = Path(os.environ["NEWSFLOW_BUILT_WHEEL"])
    static = Path(__file__).resolve().parents[1] / "src/newsflow/static"
    required = [path for path in static.rglob("*") if path.is_file()]
    with ZipFile(wheel) as archive:
        names = set(archive.namelist())
        for path in required:
            member = "newsflow/static/" + path.relative_to(static).as_posix()
            assert member in names, member
            assert archive.read(member) == path.read_bytes(), member
