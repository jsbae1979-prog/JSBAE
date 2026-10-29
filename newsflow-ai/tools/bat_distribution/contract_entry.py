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
    if not (args.program_root / 'app/validation-launch.json').is_file():
        print('BLOCKED: live Start/Stop adapter is not provisioned.', file=sys.stderr)
        return 2
    try:
        from bat_distribution.windows_live import dispatch
        return dispatch(args.action, args.program_root)
    except Exception as error:
        # Never expose credential data, raw native errors or private paths.
        code = str(error) if type(error).__name__ == 'Blocked' else type(error).__name__
        print('BLOCKED_OR_FAILED: ' + code, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
