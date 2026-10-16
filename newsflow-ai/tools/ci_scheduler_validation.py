"""Actual browser + app scheduler + FFmpeg with a test-injected clock and synthetic news.

No production clock/activation override. Windows BAT is separately exercised by the
existing CI harness on the same SHA. Never registers an OS scheduled task.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from ci_autopilot_validation import database_evidence, media_evidence, notice, open_job, submit, wait_job
from ci_validation import BASE, HTTP, ROOT, child_env, start, stop


def advance(path: Path, value: str) -> None:
    temporary = path.with_suffix('.new')
    temporary.write_text(value, encoding='utf-8')
    temporary.replace(path)


def rows(root: Path, query: str) -> list:
    with closing(sqlite3.connect(root/'newsflow.db')) as db:
        return db.execute(query).fetchall()


def await_run(root: Path, count: int, status: str | None = None) -> str:
    deadline = time.monotonic()+15
    while time.monotonic() < deadline:
        values = rows(root, 'SELECT job_id,status FROM scheduled_runs ORDER BY created_at')
        if len(values) == count and (status is None or values[-1][1] == status):
            return values[-1][0]
        time.sleep(0.1)
    raise AssertionError('Scheduled occurrence deadline')


def create(page, name: str, minute: str) -> str:
    page.goto(BASE+'/schedules')
    form = page.locator('form[action="/schedules"]')
    form.locator('[name=name]').fill(name)
    form.locator('[name=kind]').select_option('once')
    form.locator('[name=local_time]').fill('09:'+minute)
    form.locator('[name=once_date]').fill('2031-01-02')
    submit(page, form, '/schedules')
    page.wait_for_url(BASE+'/schedules?saved=true')
    card = page.locator('[data-schedule-id]').filter(has=page.get_by_role('heading',name=name,exact=True))
    assert '일시 중지' in card.inner_text()
    return card.get_attribute('data-schedule-id')


def enable(page, identifier: str) -> None:
    card = page.locator(f'[data-schedule-id="{identifier}"]')
    form = card.locator('form').first
    form.locator('[name=consent]').check()
    submit(page,form,f'/schedules/{identifier}/state')
    page.wait_for_url(BASE+'/schedules')
    assert '예약 중' in page.locator(f'[data-schedule-id="{identifier}"]').inner_text()


def validate(mode: str, root: Path, clock: Path, output: Path, executable: str | None, result: dict) -> None:
    from playwright.sync_api import sync_playwright
    env = child_env()
    for key in ('NEWSFLOW_VIDEO_AI_KEY','NEWSFLOW_AI_API_KEY'):
        env.pop(key,None)
    env['NEWSFLOW_LIVE_TEST'] = env['NEWSFLOW_AI_LIVE_TEST'] = '0'
    advance(clock, '2031-01-01T23:59:00+00:00')
    command = [sys.executable,str(ROOT/'tools/ci_fixture_server.py'),'--data-dir',str(root),'--scheduler-clock-file',str(clock)]
    process = start(command,env)
    external: set[str] = set()
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            options: dict = {'headless':True}
            if executable:
                options['executable_path'] = executable
            elif mode == 'windows':
                options['channel'] = 'chrome'
            if mode == 'cloud':
                options['args'] = ['--no-sandbox']
            browser = p.chromium.launch(**options)
            page = browser.new_page(viewport={'width':1440,'height':1050},locale='ko-KR')
            page.set_default_timeout(30000)
            page.on('pageerror',lambda error:errors.append(type(error).__name__))
            def guard(route):
                if urlsplit(route.request.url).netloc != '127.0.0.1:8765':
                    external.add(urlsplit(route.request.url).netloc)
                    route.abort()
                else:
                    route.continue_()
            page.route('**/*',guard)
            page.goto(BASE+'/')
            page.get_by_role('link',name='◷ 자동 제작 예약하기 →').click()
            page.screenshot(path=str(output/'01-reservation-form.png'),full_page=True)
            identifier = create(page,'아침 체험 영상','00')
            assert rows(root,'SELECT COUNT(*) FROM scheduled_runs')[0][0] == 0
            # Wait for a real DOM refresh, then use the recreated form (listener regression).
            page.locator('h1').click()
            page.wait_for_timeout(5500)
            enable(page,identifier)
            page.screenshot(path=str(output/'02-reservation-enabled.png'),full_page=True)
            advance(clock,'2031-01-02T00:00:01+00:00')
            job_id = await_run(root,1)
            open_job(page,job_id)
            page.screenshot(path=str(output/'03-production-running.png'),full_page=True)
            job = wait_job(job_id,'completed')
            await_run(root,1,'completed')
            open_job(page,job_id)
            result['mp4'] = media_evidence(page,job,output,'scheduled-preview.mp4')
            page.screenshot(path=str(output/'04-completed-video.png'),full_page=True)
            page.goto(BASE+'/queue')
            assert page.locator('main').inner_text().find('아직') < 0 or page.locator('video').count() >= 1
            page.screenshot(path=str(output/'05-local-review-queue.png'),full_page=True)
            result['database'] = database_evidence(root)
            before = rows(root,'SELECT id,status FROM scheduled_runs')
            stop(process)
            process = start(command,env)
            page.goto(BASE+'/schedules')
            assert rows(root,'SELECT id,status FROM scheduled_runs') == before
            assert rows(root,'SELECT COUNT(*) FROM autopilot_jobs')[0][0] == 1
            open_job(page,job_id)
            result['restart_mp4'] = media_evidence(page,job,output,'restart-preview.mp4')
            assert result['mp4']['sha256'] == result['restart_mp4']['sha256']
            missed = create(page,'놓친 예약 확인','01')
            enable(page,missed)
            advance(clock,'2031-01-12T00:00:00+00:00')
            await_run(root,2,'skipped')
            assert rows(root,'SELECT COUNT(*) FROM autopilot_jobs')[0][0] == 1
            page.goto(BASE+'/schedules')
            page.locator('#schedule-history').scroll_into_view_if_needed()
            page.screenshot(path=str(output/'06-missed-explanation.png'),full_page=True)
            HTTP().blocked_post('/schedules/'+missed+'/state',422,{'revision':'3','action':'enable'})
            for width,height,zoom,label in [(1440,1000,1,'desktop'),(390,844,1,'mobile'),(1280,900,2,'zoom-200')]:
                page.set_viewport_size({'width':width,'height':height})
                page.goto(BASE+'/schedules')
                page.locator('html').evaluate('(node,zoom)=>node.style.zoom=zoom',zoom)
                dims = page.evaluate('({content:document.documentElement.scrollWidth,viewport:document.documentElement.clientWidth})')
                assert dims['content'] <= dims['viewport']+2, label
                page.screenshot(path=str(output/f'07-{label}.png'),full_page=True)
            assert not external and not errors
            for table in ('video_ai_usage','ai_usage','publish_jobs','publish_attempts','oauth_connections'):
                assert rows(root,f'SELECT COUNT(*) FROM {table}')[0][0] == 0, table
            result.update(browser='PASS',csrf_origin_post='PASS',restart_preservation='PASS',missed_no_catchup='PASS',
                          layouts='PASS (desktop, mobile, CSS zoom 200%)',browser_external_requests=list(external),
                          paid_usage_rows=0,oauth_connections=0,publish_attempts=0,actual_paid_API_calls=0,
                          actual_SNS_calls=0,user_PC_quality='NOT VERIFIED',OS_task_registration=0)
            browser.close()
    finally:
        stop(process)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['cloud','windows'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    if args.mode == 'windows' and sys.platform != 'win32':
        raise SystemExit('Windows runner required')
    args.output.mkdir(parents=True,exist_ok=True)
    result = {'mode':args.mode,'outcome':'FAIL','clock':'synthetic clock injected by test-only fixture; production timer unchanged'}
    try:
        with TemporaryDirectory(prefix='newsflow-schedule-') as directory:
            root = Path(directory)/'한글 사용자'/'NewsFlowAI'
            validate(args.mode,root,Path(directory)/'clock.txt',args.output,args.browser_executable,result)
        result['outcome'] = 'PASS'
    finally:
        (args.output/'scheduler-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        notice('Scheduler GUI',{k:v for k,v in result.items() if k not in {'mp4','restart_mp4','database'}})


if __name__ == '__main__':
    main()
