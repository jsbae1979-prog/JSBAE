"""Isolated Chrome UI: Fake estimates only; no operating data or external network."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_higgsfield_model_pricing import MODEL, no_remote_or_workers, pricing, snapshot
from test_model_picker_browser import browser

__all__ = ['browser', 'no_remote_or_workers', 'pricing']


def test_automatic_price_registration_consent_failure_and_narrow_layout(app, pricing, browser, tmp_path):
    _service, sender, _keys = pricing
    evidence=Path(os.environ.get('NEWSFLOW_MODEL_PRICING_EVIDENCE',str(tmp_path)))
    evidence.mkdir(parents=True,exist_ok=True)
    external,mutations,errors=[],[],[]
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1440,'height':1000},locale='ko-KR')
        def guard(route):
            parsed=urlsplit(route.request.url)
            if parsed.netloc != urlsplit(origin).netloc:
                external.append(parsed.netloc);route.abort()
            elif route.request.method != 'GET' and parsed.path != '/video-ai-settings/models':
                mutations.append(parsed.path);route.abort()
            else:
                route.continue_()
        context.route('**/*',guard)
        page=context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        assert page.goto(origin+'/video-ai-settings').status==200
        assert sender.calls==[]
        page.locator('#video-ai-model-management>summary').click()
        form=page.locator('#video-ai-model-new')
        expect(form.locator('[name=pricing_mode]')).to_have_value('official')
        expect(form.locator('[name=price_per_second]')).to_have_attribute('readonly','')
        expect(form.locator('[name=estimate_consent]')).not_to_be_checked()
        form.locator('[name=path]').fill(MODEL)
        form.locator('[name=label]').fill('합성 Kling 가격')
        form.locator('[name=durations]').fill('5,10')
        expect(form.locator('[data-model-quote-count]')).to_contain_text('2회')
        form.get_by_role('button',name='견적 조회 후 모델 추가',exact=True).click()
        assert sender.calls==[]  # native required consent prevents POST
        form.locator('[name=estimate_consent]').check()
        form.get_by_role('button',name='견적 조회 후 모델 추가',exact=True).click()
        page.wait_for_url('**/video-ai-settings?saved=model')
        assert len(sender.calls)==2
        page.locator('#video-ai-model-management>summary').click()
        row=page.locator('.model-row')
        expect(row.locator('[name=price_per_second]')).to_have_value('0.056')
        expect(row.locator('[data-model-price-evidence]')).to_contain_text('5초 $0.280')
        expect(row.locator('[data-model-price-evidence]')).to_contain_text('10초 $0.560')
        expect(page.locator('#video-ai-job-limit')).to_have_value('5')
        expect(page.locator('#video-ai-monthly-limit')).to_have_value('20')
        before=snapshot(app)
        # Existing prices stay manual by default: merely opening the screen cannot requery.
        expect(row.locator('[name=pricing_mode]')).to_have_value('manual')
        row.locator('[name=pricing_mode]').select_option('official')
        expect(row.locator('[name=estimate_consent]')).not_to_be_checked()
        row.locator('[name=estimate_consent]').check()
        row.locator('[name=resolution]').select_option('1080p')
        expect(row.locator('[name=estimate_consent]')).not_to_be_checked()
        expect(row.locator('[data-price-conditions-changed]')).to_be_visible()
        for width in [1440,600,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            row.locator('[name=pricing_mode]').focus()
            page.screenshot(path=str(evidence/f'pricing-{width}.png'))
        assert snapshot(app)==before and len(sender.calls)==2
        sender.status=401
        row.locator('[name=estimate_consent]').check()
        row.get_by_role('button',name='견적 조회 후 모델 저장',exact=True).click()
        expect(row.locator('[data-submit-error]')).to_contain_text('기존 모델·가격을 유지')
        expect(row.locator('[name=price_per_second]')).to_have_value('0.056')
        assert snapshot(app)==before and len(sender.calls)==3
        page.screenshot(path=str(evidence/'failed-lookup-390.png'))
        assert not external and not mutations and not errors
        context.close()
    (evidence/'browser-result.json').write_text(json.dumps({
        'widths':[1440,600,390],'fake_estimates':3,'generation_requests':0,
        'external_requests':external,'unexpected_mutations':mutations,'page_errors':errors,
    },indent=2),encoding='utf-8')
