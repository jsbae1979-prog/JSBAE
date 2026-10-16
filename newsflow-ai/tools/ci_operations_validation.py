"""Real browser operations flow, Fake OS registration only; no human quality claims."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from ci_autopilot_validation import submit
from ci_validation import BASE, ROOT, child_env, start, stop


def validate(mode: str, root: Path, output: Path, executable: str | None, result: dict) -> None:
    from playwright.sync_api import sync_playwright
    env = child_env()
    command = [sys.executable,str(ROOT/'tools/ci_fixture_server.py'),'--data-dir',str(root),'--fake-startup']
    process = start(command,env)
    errors, external = [], []
    try:
        with sync_playwright() as p:
            options = {'headless':True}
            if executable:
                options['executable_path'] = executable
            elif mode == 'windows':
                options['channel'] = 'chrome'
            if mode == 'cloud':
                options['args'] = ['--no-sandbox']
            browser = p.chromium.launch(**options)
            page = browser.new_page(viewport={'width':1440,'height':1050},locale='ko-KR')
            page.on('pageerror',lambda error:errors.append(type(error).__name__))
            def guard(route):
                if urlsplit(route.request.url).netloc != '127.0.0.1:8765':
                    external.append('blocked'); route.abort()
                else:
                    route.continue_()
            page.route('**/*',guard)
            page.goto(BASE+'/simple-settings')
            page.get_by_role('link',name='내 PC 운영 점검 · 자동 시작과 사용 결과 →').click()
            assert page.get_by_role('heading',name='내 PC 운영 점검').is_visible()
            page.screenshot(path=str(output/'01-operations.png'),full_page=True)
            form = page.locator('form[action="/operations/startup"]')
            form.locator('[name=revision]').evaluate("element => element.value = '0'.repeat(64)")
            form.locator('[name=consent]').check()
            with page.expect_response(lambda r: r.request.method == 'POST' and urlsplit(r.url).path == '/operations/startup') as failure:
                form.locator('button[type=submit]').click()
            assert failure.value.status == 409
            page.wait_for_function("document.querySelector('[data-submit-error]').textContent.includes('새로고침')")
            page.screenshot(path=str(output/'06-action-error.png'),full_page=True)
            page.goto(BASE+'/operations')
            form = page.locator('form[action="/operations/startup"]')
            assert not form.locator('[name=consent]').is_checked()
            form.locator('[name=consent]').check()
            submit(page,form,'/operations/startup')
            page.wait_for_url(BASE+'/operations?saved=true')
            assert '현재 상태: 등록됨' in page.inner_text('main')
            page.screenshot(path=str(output/'02-consented-fake-startup.png'),full_page=True)
            form = page.locator('form[action="/operations/startup"]')
            form.locator('[name=consent]').check()
            submit(page,form,'/operations/startup')
            assert '현재 상태: 사용 안 함' in page.inner_text('main')
            form = page.locator('form[action="/operations/review"]')
            assert all(select.input_value() == 'NOT VERIFIED' for select in form.locator('select').all())
            form.locator('[name=consent]').check()
            submit(page,form,'/operations/review')
            assert 'KST' in page.inner_text('main')
            with page.expect_download() as info:
                page.get_by_role('link',name='내 점검 결과 내려받기 (JSON)').click()
            download = output/'synthetic-review.json'; info.value.save_as(download)
            review = json.loads(download.read_text(encoding='utf-8'))
            assert set(review['human_review']['items'].values()) == {'NOT VERIFIED'}
            assert str(root) not in download.read_text(encoding='utf-8')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            page.screenshot(path=str(output/'03-mobile.png'),full_page=True)
            page.set_viewport_size({'width':1280,'height':900})
            page.evaluate("document.documentElement.style.zoom='2'")
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
            page.screenshot(path=str(output/'04-zoom200.png'),full_page=True)
            page.evaluate("document.documentElement.style.zoom='1'")
            page.goto(BASE+'/voices')
            assert 'NOT VERIFIED' in page.inner_text('main')
            page.screenshot(path=str(output/'05-voice.png'),full_page=True)
            # Read-only evidence survives a genuine process restart; never register real OS tasks.
            stop(process); process = start(command,env)
            page.goto(BASE+'/operations')
            assert '사용자 직접 입력' in page.inner_text('main')
            assert 'NOT VERIFIED' in page.inner_text('main')
            assert not errors and not external
            result.update(browser='PASS',visible_rejected_post='PASS',fake_register_remove='PASS',review_download_restart='PASS',
                mobile_zoom='PASS',page_errors=errors,external_browser_requests=len(external),
                actual_os_registration=0,paid_ai_calls=0,oauth_sns_calls=0,
                user_pc='NOT VERIFIED',human_korean_audio='NOT VERIFIED')
            browser.close()
        stop(process)
        automatic = [sys.executable, '-c',
            'import sys; from pathlib import Path; from newsflow.main import run; run(automatic_data_dir=Path(sys.argv[1]))', str(root)]
        # Exercise the real runtime invoked by the Windows entry, without registering an OS task.
        env['NEWSFLOW_HOST'], env['NEWSFLOW_PORT'] = '0.0.0.0', '9999'
        process = start(automatic,env)
        assert json.loads((root/'startup-status.json').read_text())['status'] == 'running'
        duplicate = subprocess.run(automatic,env=env,cwd=ROOT,capture_output=True,timeout=20,check=False)
        assert duplicate.returncode == 1
        result['automatic_runtime_loopback_fixed_port_duplicate'] = 'PASS'
        stop(process); process = start(automatic,env)
        result['automatic_runtime_restart'] = 'PASS' 
    finally:
        stop(process)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode',choices=['cloud','windows'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    result = {'mode':args.mode,'outcome':'FAIL','os_adapter':'Fake; never registers an OS task'}
    try:
        with TemporaryDirectory(prefix='newsflow-operations-') as directory:
            validate(args.mode,Path(directory)/'한글 사용자'/'NewsFlowAI',args.output,args.browser_executable,result)
        result['outcome'] = 'PASS'
    finally:
        (args.output/'operations-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
