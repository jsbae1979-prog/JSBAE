"""BAT entry: old candidates stay inert; explicit synthetic validation only.

Updates remain blocked. No switch weakens OS security or publisher trust.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='NewsFlow AI non-executing BAT development entry')
    parser.add_argument('action', choices=('start', 'stop', 'update'))
    parser.add_argument('program_root', type=Path)
    args = parser.parse_args(argv)
    if (not args.program_root.is_absolute() or '..' in args.program_root.parts
            or str(args.program_root).startswith(('\\\\', '//'))):
        print('BLOCKED: absolute local program path required.', file=sys.stderr)
        return 2
    if args.action == 'update':
        print('BLOCKED: publisher trust and live ZIP installer are not provisioned.', file=sys.stderr)
        return 3
    from bat_distribution.restored_install import restored_paths
    if not ((args.program_root / 'connection.json').is_file()
            or (args.program_root.parent / 'validation-launch.json').is_file()
            or (restored_paths()[0] / 'launch.json').is_file()):
        print('BLOCKED: live Start/Stop adapter is not provisioned.', file=sys.stderr)
        return 2
    try:
        from bat_distribution.windows_live import dispatch
        return dispatch(args.action, args.program_root)
    except Exception as error:
        # Never expose credential data, raw native errors or private paths.
        code = str(error) if type(error).__name__ == 'Blocked' else type(error).__name__
        if code == 'port-unavailable-no-fallback':
            print('지정 포트를 사용할 수 없습니다. 기존 실행을 확인하거나 종료 후 connection.json에서 포트를 명시하세요. 자동으로 변경하지 않습니다.', file=sys.stderr)
        print('BLOCKED_OR_FAILED: ' + code, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
