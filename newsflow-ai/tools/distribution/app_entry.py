"""Unlaunched private frozen candidate. Ordinary product security, no test Guard."""
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys

def main():
    if not getattr(sys,'frozen',False):raise SystemExit('Frozen internal candidate only')
    bundle=Path(sys._MEIPASS).resolve()
    expected=json.loads((bundle/'media-integrity.json').read_text(encoding='utf8'))
    for name,variable in [('ffmpeg.exe','NEWSFLOW_FFMPEG'),('ffprobe.exe','NEWSFLOW_FFPROBE')]:
        path=bundle/'media'/name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected[name]:
            raise SystemExit('Bundled media integrity check failed')
        os.environ[variable]=str(path)
    no_browser = sys.argv[1:] == ['--no-browser']
    if len(sys.argv) > 1 and not no_browser:
        if sys.argv[1:3] != ['-m','newsflow.video.windows_sapi']:
            raise SystemExit('Unsupported packaged operation')
        sys.argv = [sys.argv[0], *sys.argv[3:]]
        from newsflow.video.windows_sapi import main as voice_main
        raise SystemExit(voice_main())
    from newsflow.distribution.launch import run
    try:
        run(open_browser=not no_browser)
    except KeyboardInterrupt:
        # Uvicorn re-raises the console signal after its lifespan cleanup.
        # A user-requested normal close must not become a bootloader error.
        pass

if __name__=='__main__':
    multiprocessing.freeze_support();main()
