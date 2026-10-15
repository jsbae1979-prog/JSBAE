"""Real setup BAT/wizard/recovery and 30/45/60s local MP4s. No external service calls."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import wave
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from ci_autopilot_validation import database_evidence, notice, open_job, submit, wait_job
from ci_validation import BASE, HTTP, ROOT, child_env, start, stop


def state(root: Path) -> dict:
    with sqlite3.connect(root / 'newsflow.db') as db:
        row = db.execute("SELECT value FROM app_settings WHERE key='easy_setup'").fetchone()
        return json.loads(row[0]) if row else {}


def run(mode: str, output: Path, executable: str | None, result: dict) -> None:
    from playwright.sync_api import sync_playwright

    from newsflow.video.tts import WindowsTTS, wav_duration

    with TemporaryDirectory(prefix='newsflow-setup-') as directory:
        root = Path(directory) / '사용자 데이터 공백' / 'NewsFlowAI'
        env = child_env()
        if mode == 'windows':
            env['LOCALAPPDATA'] = str(root.parent)
            # Real setup.bat, including package/bootstrap and DB initialization. Idempotent.
            for _ in range(2):
                checked = subprocess.run(['cmd.exe', '/d', '/c', str(ROOT / 'setup.bat')],
                                         cwd=ROOT, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=240, check=False)
                assert checked.returncode == 0, 'setup.bat failed (raw output withheld)'
            result['setup_bat'] = 'PASS (twice; dependency and DB initialization)'
        else:
            env['NEWSFLOW_DATA_DIR'] = str(root)
            checked = subprocess.run([sys.executable, '-m', 'newsflow.easy_setup'], cwd=ROOT, env=env,
                                     capture_output=True, timeout=60, check=False)
            assert checked.returncode == 0
            result['setup_bat'] = 'NOT VERIFIED (Cloud Linux; setup CLI executed)'
        command = ['cmd.exe', '/d', '/c', str(ROOT / 'run.bat')] if mode == 'windows' else [sys.executable, '-m', 'newsflow.main']
        # Real missing-font error, then recover without resetting DB or preferences.
        healthy_font = env.get('NEWSFLOW_FONT_PATH')
        env['NEWSFLOW_FONT_PATH'] = str(root / '없는 글꼴.ttf')
        process = start(command, env, 180)
        with sync_playwright() as pw:
            opts = {'headless': True}
            if executable:
                opts['executable_path'] = executable
            elif mode == 'windows':
                opts['channel'] = 'chrome'
            if mode == 'cloud':
                opts['args'] = ['--no-sandbox']
            browser = pw.chromium.launch(**opts)
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.set_default_timeout(60000)
            external, errors = set(), []
            page.on('pageerror', lambda e: errors.append(type(e).__name__))
            page.on('request', lambda r: external.add(urlsplit(r.url).netloc) if r.url.startswith(('http:', 'https:')) and not r.url.startswith(BASE + '/') and r.url != BASE else None)
            try:
                page.goto(BASE + '/setup')
                page.screenshot(path=str(output / 'wizard-welcome.png'), full_page=True)
                submit(page, page.locator('form[action="/setup/check"]'), '/setup/check')
                assert page.locator('.readiness-list').get_by_text('확인 필요', exact=True).count() >= 1
                page.screenshot(path=str(output / 'setup-error.png'), full_page=True)
                for step in range(1, 7):
                    form = page.locator('form[action="/setup/step"]')
                    assert form.locator('input[name="step"]').input_value() == str(step)
                    if step == 4:
                        form.locator('[name="duration"]').select_option('45')
                    if step == 5:
                        form.locator('[name="font_size"]').select_option('56')
                        form.locator('[name="subtitle_y"]').select_option('1280')
                        page.screenshot(path=str(output / 'wizard-voice-subtitle.png'), full_page=True)
                    if step == 6:
                        page.screenshot(path=str(output / 'wizard-storage.png'), full_page=True)
                        form.locator('[name="storage_confirmed"]').check()
                    submit(page, form, '/setup/step')
                with page.expect_response(lambda r: r.url.endswith('/setup/step') and r.request.method == 'POST') as response:
                    page.locator('form[action="/setup/step"] button').click()
                assert response.value.status == 422
                assert not state(root)['completed']
                saved = state(root)
                stop(process)
                if healthy_font:
                    env['NEWSFLOW_FONT_PATH'] = healthy_font
                else:
                    env.pop('NEWSFLOW_FONT_PATH', None)
                process = start(command, env, 180)
                assert state(root) == saved
                page.goto(BASE + '/setup')
                submit(page, page.locator('form[action="/setup/step"]'), '/setup/step')
                assert state(root)['completed']
                assert state(root)['values']['font_size'] == '56'
                page.screenshot(path=str(output / 'wizard-completed.png'), full_page=True)
                result['wizard'] = 'PASS (7 steps, real missing-font failure, restart, retry, persisted settings)'
                for width, zoom in [(320, '100%'), (1440, '200%')]:
                    page.set_viewport_size({'width': width, 'height': 1000})
                    for path in ['/setup', '/simple-settings', '/videos']:
                        page.goto(BASE + path)
                        page.evaluate('(zoom)=>document.documentElement.style.zoom=zoom', zoom)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                    page.screenshot(path=str(output / f'layout-{width}.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                page.goto(BASE + '/setup')
                jobs = []
                for duration in (30, 45, 60):
                    if duration == 30:
                        submit(page, page.locator('form[action="/setup/test-production"]'), '/setup/test-production')
                    else:
                        page.goto(BASE + '/autopilot/start')
                        form = page.locator('form[action="/autopilot/start"]')
                        form.locator('input[name="mode"][value="easy"]').check()
                        form.locator(f'input[name="duration"][value="{duration}"]').check()
                        form.locator('select[name="source"]').select_option('sample')
                        submit(page, form, '/autopilot/start')
                    job_id = page.url.rsplit('/', 1)[1]
                    job = wait_job(job_id, 'completed', timeout=900)
                    open_job(page, job_id)
                    video = page.locator('video')
                    video.wait_for()
                    video.evaluate('async v=>{v.muted=true; await v.play()}')
                    page.wait_for_function('() => document.querySelector("video").currentTime >= 1')
                    assert video.evaluate('v=>v.error===null && v.videoWidth===1080 && v.videoHeight===1920')
                    video.evaluate('v=>v.pause()')
                    page.screenshot(path=str(output / f'video-{duration}s.png'), full_page=True)
                    path = output / f'setup-{duration}s.mp4'
                    path.write_bytes(HTTP().get(f'/video/jobs/{job["render_job_id"]}/file'))
                    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)], capture_output=True, check=True, timeout=30)
                    meta = json.loads(probe.stdout)
                    streams = {s['codec_type']: s for s in meta['streams']}
                    v, a = streams['video'], streams['audio']
                    assert v['codec_name'] == 'h264' and a['codec_name'] == 'aac'
                    assert (v['width'], v['height']) == (1080, 1920)
                    assert abs(float(meta['format']['duration']) - duration) < .2
                    assert abs(float(v['start_time']) - float(a['start_time'])) < .1
                    assert abs(float(v['duration']) - float(a['duration'])) < .15
                    with sqlite3.connect(root / 'newsflow.db') as db:
                        row = db.execute('SELECT font_size,position_y,cues FROM subtitle_tracks WHERE project_id=?', (job['video_project_id'],)).fetchone()
                        assert row[:2] == (56, 1280)
                        cues = json.loads(row[2])
                        assert cues[0]['start_ms'] == 0 and cues[-1]['end_ms'] == duration * 1000
                        assert all(x['end_ms'] == y['start_ms'] for x,y in pairwise(cues))
                    jobs.append({'duration': duration, 'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                 'h264_aac_1080x1920': 'PASS', 'browser_playback': 'PASS', 'stream_timing': 'PASS',
                                 'subtitle_style_and_cues': 'PASS', 'audio': 'silent review; speech sync NOT VERIFIED'})
                result['videos'] = jobs
                page.goto(BASE + '/videos')
                assert page.locator('video').count() == 3
                page.screenshot(path=str(output / 'video-library.png'), full_page=True)
                before = database_evidence(root)
                stop(process)
                process = start(command, env, 180)
                assert database_evidence(root) == before and state(root)['completed']
                page.goto(BASE + '/videos')
                assert page.locator('video').count() == 3
                result['restart_preservation'] = 'PASS (wizard, existing news, three MP4s and local queue)'
                result['database'] = before
                safety = json.loads(HTTP().get('/api/oauth/safety'))
                assert safety['mode'] == 'OFFLINE/BLOCKED'
                assert all(safety[k] == 0 for k in ('real_authorization_requests', 'real_token_exchange_calls', 'real_refresh_calls', 'real_revoke_calls'))
                result['oauth_safety'] = safety
                assert not external and not errors
                result['browser_external_requests'] = 0
                result['browser_errors'] = 0
                result['layout'] = 'PASS (320px and CSS zoom 200%); native browser zoom NOT VERIFIED'
                if mode == 'windows':
                    tts = WindowsTTS()
                    voices = [v for v in tts.voice_details() if v['culture'].lower().startswith('ko-')]
                    result['korean_voice_count'] = len(voices)
                    if voices:
                        sample = output / 'korean-speech.wav'
                        tts.synthesize('안녕하세요. 뉴스 영상 제작을 시작합니다.', sample, voices[0]['name'], 15)
                        with wave.open(str(sample)) as wav:
                            assert any(wav.readframes(wav.getnframes()))
                        result['korean_speech'] = f'PASS (non-silent WAV {wav_duration(sample):.2f}s); human quality NOT VERIFIED'
                    else:
                        result['korean_speech'] = 'NOT VERIFIED (runner has no installed Korean SAPI voice)'
                else:
                    result['korean_speech'] = 'NOT VERIFIED (Cloud Linux)'
                result['outcome'] = 'PASS with explicit unverified items'
            finally:
                browser.close()
                stop(process)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['cloud', 'windows'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result = {'outcome': 'FAIL', 'mode': args.mode, 'human_quality': 'NOT VERIFIED', 'Windows11_user_PC': 'NOT VERIFIED'}
    try:
        run(args.mode, args.output, args.browser_executable, result)
    finally:
        (args.output / 'easysetup-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        for key, value in result.items():
            notice('EasySetup ' + key, value if isinstance(value, dict) else {'value': value})


if __name__ == '__main__':
    main()
