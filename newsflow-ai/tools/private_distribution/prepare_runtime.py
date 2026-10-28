"""Prepare the unchanged frozen Python/React while native media compiles.

The final builder replaces media/sample resources and checks exact source bytes.
This intermediate bundle is never installed, run or delivered.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--project', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--reviewed-media', type=Path, required=True)
args = parser.parse_args()
project = args.project.resolve()
sys.path.insert(0, str(project / 'tools/distribution'))
from package_contract import ordinary_tree
rows = []
for folder, label in [(project / 'src/newsflow', 'src'), (project / 'frontend/dist', 'frontend')]:
    for file, relative in ordinary_tree(folder, source=True):
        rows.append({'path': label + '/' + str(relative), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
rows.append({'path': 'app_entry.py', 'sha256': hashlib.sha256((project / 'tools/distribution/app_entry.py').read_bytes()).hexdigest()})
result = subprocess.run([sys.executable, '-I', '-B', str(project / 'tools/distribution/build_candidate.py'),
    '--output', str(args.output), '--media-dir', str(args.reviewed_media)])
if result.returncode:
    raise SystemExit(result.returncode)
(args.output / 'runtime-source-index.json').write_text(json.dumps(rows, indent=2))
