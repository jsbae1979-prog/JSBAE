"""Run the existing BAT in a new Windows TEMP profile; no user PC or accounts.

Only this process's children are stopped. No installer/OS task/OAuth action occurs.
"""
from __future__ import annotations

import argparse
import json
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from ci_validation import HTTP, ROOT, child_env, start, stop


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Windows runner required; Cloud is not a BAT execution')
    root = args.root.resolve()
    if root.exists() or not root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        parser.error('Use a new Windows TEMP directory only')
    # Refuse a pre-existing service before any lifecycle operation.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 8765))
    root.mkdir(parents=True)
    env = child_env()
    for name in list(env):
        if name.startswith('NEWSFLOW_') or name in {'OPENAI_API_KEY','ANTHROPIC_API_KEY','ANTHROPIC_AUTH_TOKEN','CLAUDE_CODE_OAUTH_TOKEN'}:
            env.pop(name, None)
    env['LOCALAPPDATA'] = str(root / '사용자 App Data')
    env['PYTHONUTF8'] = '1'
    data = Path(env['LOCALAPPDATA']) / 'NewsFlowAI'
    command = ['cmd.exe','/d','/c',str(ROOT / 'run.bat')]
    process = None
    result = {'status':'FAIL','python':sys.version.split()[0], 'actual_run_bat':False,
              'actual_paid_api_oauth_sns':0,'user_windows_pc':'NOT VERIFIED'}
    try:
        process = start(command, env, 180)
        result['actual_run_bat'] = True
        assert data.is_dir() and (data/'newsflow.db').is_file()
        assert not (ROOT/'data'/'newsflow.db').exists(), 'CI source tree must not contain an operational database'
        routes = ['/','/create','/news','/videos','/queue','/simple-settings','/health']
        for route in routes:
            HTTP().get(route)
        # Synthetic persisted setting only; no user/credential data.
        with sqlite3.connect(data/'newsflow.db') as db:
            db.execute("INSERT INTO app_settings (key,value) VALUES ('ci_cloud_connect','synthetic-preserved')")
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        duplicate = subprocess.run(command,check=False,cwd=ROOT,env=env,stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=45)
        assert duplicate.returncode != 0
        assert any(marker in duplicate.stdout.decode('utf-8',errors='replace') for marker in ('이미 run.bat','포트'))
        log_path = data / 'logs/execution.log'
        prior_stops = log_path.read_text(encoding='utf-8').count('server_stop')
        process.send_signal(signal.CTRL_BREAK_EVENT)
        process.wait(timeout=45)
        # cmd.exe can exit before its Python child's finally block has flushed.
        # Match the existing CI compatibility tool: observe actual cleanup, not parent exit.
        deadline = time.monotonic() + 30
        while log_path.read_text(encoding='utf-8').count('server_stop') <= prior_stops:
            assert time.monotonic() < deadline, 'server_stop not recorded after CTRL_BREAK'
            time.sleep(.1)
        process = start(command, env, 180)
        for route in routes:
            HTTP().get(route)
        with sqlite3.connect(data/'newsflow.db') as db:
            assert db.execute("SELECT value FROM app_settings WHERE key='ci_cloud_connect'").fetchone()[0]=='synthetic-preserved'
            assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert db.execute('SELECT COUNT(*) FROM publish_jobs').fetchone()[0]==0
            assert db.execute('SELECT COUNT(*) FROM platform_accounts WHERE credential_ref IS NOT NULL').fetchone()[0]==0
        result.update(status='PASS',routes=routes,loopback_port=8765,default_localappdata=True,
                      unicode_spaces_path=True,duplicate_run='blocked',shutdown='CTRL_BREAK with server_stop',
                      restart='same SQLite marker and integrity_check; no app migration edits',
                      paid_services='not configured; no OAuth/upload calls')
    finally:
        if process is not None:
            stop(process)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
