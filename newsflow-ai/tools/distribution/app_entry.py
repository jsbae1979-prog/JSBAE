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
    from newsflow.main import run
    run()

if __name__=='__main__':
    multiprocessing.freeze_support();main()
