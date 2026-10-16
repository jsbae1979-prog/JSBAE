"""Explicit, non-destructive migration of the Phase 1 database and session key."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory

from filelock import FileLock

from .paths import default_data_dir, prepare_data_dir


def migrate_data(source: Path, target: Path) -> None:
    source, target = source.resolve(), target.resolve()
    if source == target or source in target.parents or target in source.parents:
        raise ValueError("원본과 대상은 서로 분리된 폴더여야 합니다.")
    if not (source / "newsflow.db").is_file():
        raise ValueError("원본 newsflow.db가 없습니다.")
    prepare_data_dir(target)
    with ExitStack() as stack:
        for root in sorted((source, target), key=str):
            # Cooperate with both current server locks and collection locks.
            for lock in sorted(root.glob("server-*.lock")):
                stack.enter_context(FileLock(str(lock)).acquire(timeout=0))
            stack.enter_context(FileLock(str(root / "collection.lock")).acquire(timeout=0))
            stack.enter_context(FileLock(str(root / "migration.lock")).acquire(timeout=0))
            stack.enter_context(FileLock(str(root / "scheduler.lock")).acquire(timeout=0))
            stack.enter_context(FileLock(str(root / "autopilot.lock")).acquire(timeout=0))
        if any(
            (target / name).exists()
            for name in ("newsflow.db", "newsflow.db-wal", "newsflow.db-shm", "session.key")
        ):
            raise ValueError("대상에 DB 또는 세션 키가 있어 덮어쓰지 않습니다.")
        with TemporaryDirectory(prefix="migration-", dir=target) as staging:
            temporary = Path(staging)
            with (
                closing(
                    sqlite3.connect((source / "newsflow.db").as_uri() + "?mode=ro", uri=True)
                ) as original,
                closing(sqlite3.connect(temporary / "newsflow.db")) as backup,
            ):
                original.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise ValueError("원본 DB 무결성을 확인하지 못했습니다.")
                if backup.execute("SELECT version_num FROM alembic_version").fetchone() not in {
                    ("0001",),
                    ("0002",),
                    ("0003",),
                    ("0004",),
                    ("0005",),
                    ("0006",),
                    ("0007",),
                    ("0008",),
                    ("0009",),
                    ("0010",),
                    ("0011",),
                    ("0012",),
                    ("0013",),
                }:
                    raise ValueError("지원하지 않는 DB 버전입니다.")
                if backup.execute("SELECT version_num FROM alembic_version").fetchone() in {("0012",), ("0013",)}:
                    # A copied DB must not create a second active schedule in another data folder.
                    backup.execute("UPDATE production_schedules SET status='paused', revision=revision+1 WHERE status='active'")
                    backup.commit()
            key = source / "session.key"
            if key.exists():
                if key.is_symlink() or len(key.read_text(encoding="ascii").strip()) < 32:
                    raise ValueError("원본 세션 키를 확인하세요.")
                shutil.copyfile(key, temporary / "session.key")
            created: list[Path] = []
            try:
                for name in ("newsflow.db", "session.key"):
                    if not (temporary / name).exists():
                        continue
                    destination = target / name
                    with destination.open("xb") as handle:
                        created.append(destination)
                        if os.name != "nt":
                            destination.chmod(0o600)
                        with (temporary / name).open("rb") as original_file:
                            shutil.copyfileobj(original_file, handle)
            except Exception:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
    # Original DB, WAL and key remain untouched. No automatic deletion.


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 1 데이터 복사 이전; 원본 보존/대상 덮어쓰기 금지")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path)
    args = parser.parse_args()
    try:
        migrate_data(args.source, args.target or default_data_dir())
    except Exception:  # noqa: BLE001 -- do not print raw SQLite/path/secret exceptions
        print("이전 실패: 서버 종료, 원본 DB, 대상 기존 데이터, 폴더 권한과 DB 버전을 확인하세요.")
        raise SystemExit(1) from None
    print("DB·설정·세션 키 이전 완료. 원본은 보존되었습니다. 복사본의 예약은 일시 중지됩니다. 기타 사용자 파일은 별도로 백업하세요.")


if __name__ == "__main__":
    main()
