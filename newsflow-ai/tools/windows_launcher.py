"""Windows double-click bootstrap. Dependency failures are fatal and output is redacted."""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from newsflow.paths import default_data_dir, prepare_data_dir


class LaunchError(Exception):
    pass


def checked(command: list[str], stage: str, cwd: Path = ROOT) -> None:
    result = subprocess.run(
        command, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False
    )
    if result.returncode:
        raise LaunchError(
            f"{stage} 실패 (종료 코드 {result.returncode}). 인터넷/Python/설치 권한을 확인하세요."
        )


def fingerprint(root: Path) -> str:
    digest = hashlib.sha256(str(sys.version_info[:2]).encode())
    for name in ("pyproject.toml", "requirements-dev.lock"):
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def ensure_environment(root: Path = ROOT) -> Path:
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        checked([sys.executable, "-m", "venv", str(root / ".venv")], "가상환경 생성", root)
    checked(
        [str(python), "-c", "import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)"],
        "가상환경 Python 3.12 확인",
        root,
    )
    marker = root / ".venv" / ".newsflow-installed"
    expected = fingerprint(root)
    if not marker.exists() or marker.read_text(encoding="ascii") != expected:
        print("필요한 패키지를 설치합니다. 설치 완료 전에는 서버를 시작하지 않습니다.")
        # Isolated pip ignores credentials/config in pip environment; raw output never enters logs.
        checked(
            [
                str(python),
                "-m",
                "pip",
                "--isolated",
                "install",
                "--disable-pip-version-check",
                "-c",
                str(root / "requirements-dev.lock"),
                "-e",
                str(root),
            ],
            "의존성 설치",
            root,
        )
        checked([str(python), "-m", "pip", "--isolated", "check"], "의존성 검사", root)
        marker.write_text(expected, encoding="ascii")
    checked([str(python), "-m", "pip", "--isolated", "check"], "의존성 검사", root)
    return python


@contextmanager
def launch_lock(path: Path) -> Iterator[None]:
    import msvcrt

    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise LaunchError("이미 run.bat가 실행 중입니다. 기존 창을 먼저 종료하세요.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def main() -> int:
    setup_only = sys.argv[1:] == ["--setup-only"]
    if sys.argv[1:] and not setup_only:
        print("지원하지 않는 실행 옵션입니다.")
        return 1
    if sys.platform != "win32" or sys.version_info[:2] != (3, 12):
        print("Windows 11과 Python 3.12에서 run.bat를 실행하세요.")
        return 1
    try:
        data_dir = default_data_dir()
        prepare_data_dir(data_dir)
        with launch_lock(ROOT / ".launch.lock"):
            python = ensure_environment()
            legacy = ROOT / "data" / "newsflow.db"
            if (
                legacy.is_file()
                and not (data_dir / "newsflow.db").exists()
                and legacy.parent.resolve() != data_dir.resolve()
            ):
                raise LaunchError(
                    "기존 data/newsflow.db가 있습니다. README의 migrate_data 명령으로 안전하게 이전한 후 다시 실행하세요."
                )
            if setup_only:
                return subprocess.run(
                    [str(python), "-m", "newsflow.easy_setup"], cwd=ROOT, check=False,
                ).returncode
            print("처음 실행하면 홈의 '처음 설정하기'에서 영상 도구와 한국어 음성을 점검하세요.")
            # Fail before launching another server; the runtime additionally holds its bound socket.
            port = int(os.getenv("NEWSFLOW_PORT", "8765"))
            if not 1024 <= port <= 65535:
                raise LaunchError("포트 설정은 1024~65535여야 합니다. 기본값은 8765입니다.")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as exc:
                    raise LaunchError(
                        "포트가 사용 중입니다. 기존 서버를 종료하세요. 자동으로 다른 포트를 선택하지 않습니다."
                    ) from exc
            env = os.environ.copy()
            env["NEWSFLOW_DATA_DIR"] = str(data_dir)
            print(f"GUI 주소: http://127.0.0.1:{port} · 종료: Ctrl+C")
            result = subprocess.run([str(python), "-m", "newsflow.main"], cwd=ROOT, env=env, check=False)
            return result.returncode
    except (LaunchError, OSError, ValueError):
        # Only our safe error messages, never arbitrary exception text, are exposed.
        exc = sys.exception()
        message = (
            str(exc)
            if isinstance(exc, LaunchError)
            else "실행 환경 또는 저장 경로를 확인하세요. README 오류 해결을 참고하세요."
        )
        print(message)
        if "data_dir" in locals():
            try:
                with (data_dir / "logs" / "launcher.log").open("a", encoding="utf-8") as log:
                    log.write(message + "\n")
            except OSError:
                pass
        return 1
    except KeyboardInterrupt:
        print("사용자가 프로그램을 종료했습니다.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
