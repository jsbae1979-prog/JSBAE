"""BAT template dispatcher. Deliberately has no live application backend.

No environment variable, command flag or edited trust file enables app launch,
process shutdown, extraction or installation through this entry point.
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
    print('BLOCKED: live Start/Stop adapter is not connected; no process was started or stopped.',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
