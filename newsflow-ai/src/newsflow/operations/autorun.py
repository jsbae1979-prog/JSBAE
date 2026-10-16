"""Task Scheduler entry: no installer, no browser, no elevated or paid background work."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from ..python_policy import PYTHON_GUIDANCE, supported
from .startup import StartupError, local_service


def record(root: Path, status: str) -> None:
    # Fixed vocabulary only. An unfinished 'starting/running' record never proves current liveness.
    if status not in {'starting','running','stopped','failed'}:
        raise ValueError('status')
    path = root/'startup-status.json'
    temporary = root/('startup-'+uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps({'status':status,'at':datetime.now(UTC).isoformat()}),encoding='utf-8')
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,required=True)
    args = parser.parse_args()
    if sys.platform != 'win32' or not supported():
        print('Windows 11에서 run.bat를 사용하세요. ' + PYTHON_GUIDANCE)
        return 1
    try:
        root = args.data_dir.resolve(strict=True)
        service = local_service(root)
        if (not service.plan.prepared() or Path(sys.executable).resolve() != service.plan.python.resolve()
                or service.view()['status'] != 'enabled'):
            raise StartupError('자동 시작 설정을 다시 확인하세요.')
        with FileLock(str(root/'automatic-start.lock')).acquire(timeout=0):
            record(root,'starting')
            from newsflow.main import run
            try:
                run(automatic_data_dir=root)
            except KeyboardInterrupt:
                record(root,'stopped')
                return 0
            except (SystemExit, Exception):  # noqa: BLE001 -- fixed status only; no secrets in tracebacks
                record(root,'failed')
                print('자동 시작을 마치지 못했습니다. run.bat와 운영 점검에서 포트·설치 상태를 확인하세요.')
                return 1
            record(root,'stopped')
            return 0
    except (StartupError, Timeout, OSError, ValueError):
        print('자동 시작이 차단되었습니다. 중복 실행·설치 변경·작업 설정을 확인하고 run.bat를 실행하세요.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
