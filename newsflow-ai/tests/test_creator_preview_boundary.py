"""The review launcher refuses existing data and blocks outbound/OS side effects."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_preview_refuses_existing_directory_without_touching_files(tmp_path):
    marker = tmp_path / "existing-user-data.txt"
    marker.write_bytes(b"existing data must be preserved")
    result = subprocess.run([sys.executable, str(ROOT / "tools/ui_preview.py"), "--data-dir", str(tmp_path)],
                            cwd=ROOT, capture_output=True, timeout=30, check=False)
    assert result.returncode == 2
    assert marker.read_bytes() == b"existing data must be preserved"
    assert not (tmp_path / "newsflow.db").exists()


def test_preview_boundary_blocks_external_dns_and_authentication_processes():
    program = """
import os, runpy, socket, subprocess
module = runpy.run_path('tools/ui_preview.py')
module['install_boundary']()
assert 'NEWSFLOW_AI_API_KEY' not in os.environ
for operation in [lambda: socket.getaddrinfo('never-resolve.example.com',443),
                  lambda: subprocess.Popen(['powershell.exe','-Command','blocked'])]:
    try:
        operation()
    except OSError:
        pass
    else:
        raise AssertionError('Preview boundary did not block a side effect')
"""
    env = dict(os.environ, NEWSFLOW_AI_API_KEY="synthetic-only-must-be-removed")
    result = subprocess.run([sys.executable, "-c", program], cwd=ROOT, env=env, capture_output=True, timeout=30, check=False)
    assert result.returncode == 0
    assert b"synthetic-only" not in result.stdout + result.stderr
