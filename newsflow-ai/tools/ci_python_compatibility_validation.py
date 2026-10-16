"""Windows BAT/Chrome smoke test. Keeps the selected local data and generated video."""
from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from ci_autopilot_validation import begin, media_evidence, open_job, wait_job
from ci_easysetup_validation import submit
from ci_validation import BASE, ROOT, child_env, start, stop


def main() -> None:
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', action='store_true', help='Recheck the preserved completed smoke job')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('Windows required')
    args.output.mkdir(parents=True, exist_ok=True)
    env = child_env()
    env['NEWSFLOW_DATA_DIR'] = str(args.data_dir.resolve())
    env.pop('NEWSFLOW_VIDEO_AI_KEY', None)
    env['NEWSFLOW_LIVE_TEST'] = env['NEWSFLOW_AI_LIVE_TEST'] = '0'
    command = ['cmd.exe', '/d', '/c', str(ROOT / 'run.bat')]
    result = {'python': sys.version, 'outcome': 'FAIL', 'shutdown': 'NOT VERIFIED'}
    process = start(command, env, 180)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='chrome', headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            errors, external = [], []
            page.on('pageerror', lambda error: errors.append(type(error).__name__))
            page.on('request', lambda request: external.append(request.url.split('/')[2])
                    if request.url.startswith(('http:', 'https:')) and not request.url.startswith(BASE + '/') else None)
            page.goto(BASE)
            assert page.get_by_role('navigation', name='주 메뉴').is_visible()
            page.screenshot(path=str(args.output / 'dashboard.png'))
            if args.resume:
                with closing(sqlite3.connect(args.data_dir / 'newsflow.db')) as db:
                    wizard = json.loads(db.execute("SELECT value FROM app_settings WHERE key='easy_setup'").fetchone()[0])
                    assert wizard['completed']
                    identifier = db.execute("SELECT id FROM autopilot_jobs WHERE status='completed' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
                result['wizard'] = 'PASS (preserved seven-step completion)'
            else:
                page.goto(BASE + '/setup')
                for step in range(1, 8):
                    form = page.locator('form[action="/setup/step"]')
                    assert form.locator('[name=step]').input_value() == str(step)
                    if step == 6:
                        form.locator('[name=storage_confirmed]').check()
                    submit(page, form, '/setup/step')
                result['wizard'] = 'PASS (seven steps)'
                identifier = begin(page)
            job = wait_job(identifier, 'completed', timeout=900)
            assert job['publish_draft_id']
            open_job(page, identifier)
            result['mp4'] = media_evidence(page, job, args.output, 'local-30s.mp4')
            page.screenshot(path=str(args.output / 'video.png'))
            for path in ('/videos', '/queue', '/operations'):
                assert page.goto(BASE + path).status == 200
            with closing(sqlite3.connect(args.data_dir / 'newsflow.db')) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                assert db.execute('SELECT DISTINCT provider FROM intelligence_runs').fetchall() == [('offline',)]
                assert db.execute('SELECT count(*) FROM publish_jobs').fetchone()[0] == 0
                assert db.execute('SELECT count(*) FROM publish_attempts').fetchone()[0] == 0
            hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (args.data_dir / 'outputs' / 'videos').glob('*.mp4')}
            assert hashes
            # CTRL_BREAK reaches the BAT, launcher, venv redirector and app process group.
            log_path = args.data_dir / "logs" / "execution.log"
            prior_stops = log_path.read_text(encoding="utf-8").count("server_stop")
            process.send_signal(signal.CTRL_BREAK_EVENT)
            process.wait(timeout=30)
            deadline = time.monotonic() + 30
            while log_path.read_text(encoding='utf-8').count('server_stop') <= prior_stops:
                assert time.monotonic() < deadline, 'graceful server cleanup deadline'
                time.sleep(0.1)
            result['shutdown'] = 'PASS (CTRL_BREAK process group, server_stop logged)'
            process = start(command, env, 180)
            open_job(page, identifier)
            assert page.locator('video').count() == 1
            assert all(Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest
                       for name, digest in hashes.items())
            with closing(sqlite3.connect(args.data_dir / 'newsflow.db')) as db:
                assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert not errors and not external
            result.update(outcome='PASS', restart='PASS (SQLite and MP4 hashes)', browser='Google Chrome',
                          external_browser_requests=0, javascript_errors=0, actual_run_bat='PASS')
            browser.close()
    finally:
        stop(process)
        (args.output / 'local-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
