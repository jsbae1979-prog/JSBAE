"""Scoped presentation checks: isolated records, synthetic keys, no provider or OS mutations."""
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect
from test_cloud_workspace_flow import local_server
from test_news_publish_modern import guarded_context, snapshot
from test_settings_simplification import configured, synthetic_stores
from test_single_workspace import save_values
from test_usability_browser import (
    browser,
    instagram_ui,
    studio_ui,
    unified,
    visual,
    youtube_media,
    youtube_ui,
)
from test_youtube_gui import forbid_external_calls  # noqa: F401

from newsflow.db.models import ProductionSchedule, PublishDraft, PublishJob, ScheduledRun, SocialMetric
from newsflow.intelligence.settings import write_studio_settings

__all__ = ['browser', 'instagram_ui', 'studio_ui', 'unified', 'visual', 'youtube_media', 'youtube_ui']


@pytest.fixture(autouse=True)
def no_workers_or_real_startup(monkeypatch, app):
    monkeypatch.setattr('newsflow.scheduler.service.Scheduler.start', lambda self: None)
    monkeypatch.setattr('newsflow.publishing.calendar.PublishingCalendar.start', lambda self: None)
    def no_mutation(*args, **kwargs):
        raise AssertionError('Must not register OS tasks')
    app.state.startup_service = SimpleNamespace(view=lambda: {
        'status':'disabled','revision':'synthetic','prepared':True,'message':'합성 Windows 시작 설정'},
        change=no_mutation)


def output_dir(tmp_path):
    path = Path(os.environ.get('NEWSFLOW_ANALYTICS_SETTINGS_EVIDENCE', str(tmp_path)))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize('path', ['/analytics','/simple-settings','/schedules','/operations'])
def test_empty_pages_are_read_only_and_keep_security(client, app, path):
    before = snapshot(app)
    response = client.get(path)
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert 'analytics-settings-modern.css' in response.text
    assert snapshot(app) == before


def test_settings_tabs_models_dialogs_and_form_ownership(visual, browser, tmp_path):
    app, _ids = visual
    stores = synthetic_stores(app)
    configured(app, 'openai')
    configured(app, 'claude_api')
    write_studio_settings(app.state.sessions, 'claude_api', 'claude-sonnet-4-6')
    save_values(app, video_default_voice='offline-silence',autopilot_source='feeds',
                autopilot_acquisition_policy='rss')
    before, keys = snapshot(app), {key:store.path.read_bytes() for key,store in stores.items()}
    output = output_dir(tmp_path)
    with local_server(app) as origin:
        context, page, external, mutations, errors = guarded_context(browser, origin)
        for width in [1440,1024,390]:
            page.set_viewport_size({'width':width,'height':1000})
            response = page.goto(origin+'/simple-settings#connections')
            assert response is None or response.status == 200  # A hash-only tab change has no HTTP response.
            if response is None:
                assert page.reload().status == 200
            expect(page.locator('.settings-modern')).to_have_count(1)
            expect(page.locator('[role=tab]')).to_have_count(6)
            expect(page.locator('[name=provider][form=production-preferences]')).to_have_value('claude_api')
            form = page.locator('#production-preferences')
            names = form.evaluate('e=>[...e.elements].map(n=>n.name).filter(Boolean)')
            assert {'csrf_token','provider','acquisition_policy','model','voice','video_provider',
                    'source','duration','category','period','platform','rate','pause_ms'} <= set(names)
            expect(page.locator('[data-ai-provider=claude_api]')).to_be_visible()
            expect(page.locator('[data-ai-provider=openai]')).to_be_hidden()
            expect(page.locator('[name=model][form=production-preferences]')).to_have_value('claude-sonnet-4-6')
            page.locator('[name=provider][form=production-preferences]').select_option('openai')
            expect(page.locator('[name=model][form=production-preferences]')).to_have_value('gpt-4.1-mini')
            page.locator('[name=provider][form=production-preferences]').select_option('claude_api')
            expect(page.locator('[name=model][form=production-preferences]')).to_have_value('claude-sonnet-4-6')
            expect(page.locator('.settings-savebar')).to_have_css('position','static')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.evaluate("()=>window.scrollTo({top:0,behavior:'instant'})")
            page.screenshot(path=str(output/f'settings-ai-{width}.png'),full_page=True)
            # A different tab must preserve pending default edits and all form owners.
            page.get_by_text('제작 기본값',exact=True).click()
            page.locator('[name=duration][form=production-preferences]').select_option('45')
            expect(page.locator('#production-unsaved')).to_be_visible()
            page.get_by_role('tab',name='기본 음성',exact=True).click()
            expect(page.locator('[name=voice][form=production-preferences]')).to_have_value('offline-silence')
            page.get_by_role('tab',name='뉴스·대본 AI',exact=True).click()
            expect(page.locator('[name=duration][form=production-preferences]')).to_have_value('45')
            page.get_by_role('button',name='변경 취소',exact=True).click()
            expect(page.locator('[name=duration][form=production-preferences]')).to_have_value('30')
            expect(page.locator('#production-unsaved')).to_be_hidden()
            page.get_by_role('button',name='전체 준비 상태',exact=True).click()
            expect(page.locator('#settings-diagnostics')).to_have_attribute('open','')
            expect(page.locator('#pipeline-status [data-stage]')).to_have_count(7)
            page.get_by_role('button',name='제작 진단 닫기',exact=True).click()
            expect(page.get_by_role('button',name='전체 준비 상태',exact=True)).to_be_focused()
            page.get_by_role('tab',name='비용 관리',exact=True).click()
            page.locator('[data-settings-open=api-costs-claude_api]').click()
            expect(page.locator('#api-costs-claude_api')).to_have_attribute('open','')
            for name in ['approved','search_enabled','search_approved']:
                expect(page.locator(f'#api-costs-claude_api [name={name}]')).to_be_checked()
            page.locator('#api-costs-claude_api [data-settings-close]').click()
            page.get_by_role('tab',name='게시 계정',exact=True).click()
            expect(page.locator('#accounts')).to_contain_text('계정 연결과 영상 게시 승인은 별개')
            page.get_by_role('tab',name='운영 관리',exact=True).click()
            expect(page.locator('#advanced')).to_be_visible()
            expect(page.locator('#advanced a[href="/schedules"]')).to_be_visible()
            expect(page.locator('#advanced a[href="/operations"]')).to_be_visible()
            page.screenshot(path=str(output/f'settings-operations-{width}.png'),full_page=True)
            page.get_by_role('tab',name='뉴스·대본 AI',exact=True).press('ArrowRight')
            expect(page.get_by_role('tab',name='기본 음성',exact=True)).to_have_attribute('aria-selected','true')
            page.get_by_role('button',name='제작 구성 저장',exact=True).focus()
            expect(page.get_by_role('button',name='제작 구성 저장',exact=True)).to_be_in_viewport()
        assert not external and not mutations and not errors
        context.close()
    assert snapshot(app) == before
    assert {key:store.path.read_bytes() for key,store in stores.items()} == keys


def test_analytics_saved_filters_missing_values_and_synthetic_chart(visual, browser, monkeypatch, tmp_path):
    app, (_draft, render, _failure) = visual
    output = output_dir(tmp_path)
    before = snapshot(app)
    with local_server(app) as origin:
        context,page,external,mutations,errors = guarded_context(browser,origin)
        for width in [1440,1024,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/analytics').status == 200
            expect(page.locator('.analytics-empty')).to_be_visible()
            expect(page.locator('.social-kpis')).to_have_count(0)
            expect(page.locator('.analytics-empty')).to_contain_text('0으로 채우지 않습니다')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output/f'analytics-empty-{width}.png'),full_page=True)
            page.get_by_role('combobox',name='플랫폼',exact=True).select_option('instagram')
            page.get_by_role('button',name='저장 기록 보기',exact=True).click()
            expect(page.get_by_role('combobox',name='플랫폼',exact=True)).to_have_value('instagram')
        assert not external and not mutations and not errors
        context.close()
    assert snapshot(app) == before
    with app.state.sessions.begin() as session:
        account = app.state.youtube.status()['accounts'][0]['id']
        draft = PublishDraft(render_job_id=render,platform='youtube',title='합성 성과 영상',
            description='테스트 자료',hashtags=[],sources={},media_sha256='0'*64)
        session.add(draft)
        session.flush()
        job = PublishJob(draft_id=draft.id,platform='youtube',status='uploaded',
            message='합성 게시 기록',idempotency_key='synthetic-analytics-modern')
        session.add(job)
        session.flush()
        for day,value in [(1,'120'),(2,'80')]:
            session.add(SocialMetric(job_id=job.id,account_id=account,platform='youtube',remote_id='synthetic',
                metric='views',value=value,unit='count',period_start=f'2026-10-{day:02}',
                period_end=f'2026-10-{day:02}',period_basis='America/Los_Angeles',
                published_at=datetime(2026,10,1,tzinfo=UTC),synthetic=True))
    dashboard = app.state.social_analytics.dashboard
    monkeypatch.setattr(app.state.social_analytics,'dashboard',lambda **kw:dashboard(**kw,synthetic=True))
    before = snapshot(app)
    with local_server(app) as origin:
        context,page,external,mutations,errors = guarded_context(browser,origin)
        for width in [1440,1024,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/analytics').status == 200
            expect(page.get_by_text('합성 데이터 · 실제 성과가 아닙니다.',exact=True)).to_be_visible()
            expect(page.locator('.social-kpis')).to_contain_text('200')
            expect(page.locator('.social-kpis')).to_contain_text('—')
            expect(page.get_by_role('img',name='수집된 날짜별 조회수')).to_be_visible()
            expect(page.locator('tbody tr')).to_have_count(2)
            expect(page.locator('form[action="/analytics/collect"] [name=consent]')).not_to_be_checked()
            expect(page.locator('form[action="/analytics/collect"] [name=consent]')).to_have_attribute('required','')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output/f'analytics-data-{width}.png'),full_page=True)
        assert not external and not mutations and not errors
        context.close()
    assert snapshot(app) == before


def test_automation_paused_active_history_and_startup_consent(visual,browser,tmp_path):
    app,_ids = visual
    with app.state.sessions.begin() as session:
        options={'source':'sample','duration':30,'platform':'youtube','voice':'offline-silence'}
        for i,status in enumerate(['paused','active']):
            session.add(ProductionSchedule(id=str(i+1)*32,name=f'합성 {status} 예약',kind='daily',
                local_time='09:00',weekdays=[],options=options,status=status,
                next_run_at=datetime(2026,10,22,tzinfo=UTC) if status=='active' else None))
        session.add(ScheduledRun(id='9'*32,job_id='8'*32,schedule_id='1'*32,
            scheduled_for=datetime(2026,10,20,tzinfo=UTC),options=options,status='unknown',
            message='합성 결과 불명 · 자동 재시도 금지'))
    before = snapshot(app)
    output = output_dir(tmp_path)
    with local_server(app) as origin:
        context,page,external,mutations,errors = guarded_context(browser,origin)
        for width in [1440,1024,390]:
            page.set_viewport_size({'width':width,'height':1000})
            assert page.goto(origin+'/schedules').status == 200
            expect(page.locator('[data-schedule-id]')).to_have_count(2)
            paused = page.locator('[data-schedule-id="'+'1'*32+'"]')
            expect(paused.locator('input[name=consent]')).not_to_be_checked()
            expect(paused.locator('input[name=consent]')).to_have_attribute('required','')
            expect(page.get_by_role('button',name='일시 중지',exact=True)).to_have_count(1)
            expect(page.locator('[data-run-id]')).to_contain_text('자동 재시도 금지')
            expect(page.locator('[data-run-id] form')).to_have_count(0)
            expect(page.locator('.creation-form [name=revision]')).to_have_count(0)
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output/f'schedules-{width}.png'),full_page=True)
            page.locator('.schedule-policy details>summary').press('Enter')
            expect(page.locator('.schedule-policy')).to_contain_text('90초')
            page.goto(origin+'/operations')
            expect(page.locator('.operations-modern')).to_have_count(1)
            for form in page.locator('main form').all():
                expect(form.locator('[name=csrf_token]')).to_have_count(1)
                expect(form.locator('[name=revision]')).to_have_count(1)
                expect(form.locator('[name=consent]')).not_to_be_checked()
                expect(form.locator('[name=consent]')).to_have_attribute('required','')
            for value in page.locator('.operations-review select').all():
                expect(value).to_have_value('NOT VERIFIED')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(output/f'operations-{width}.png'),full_page=True)
        assert not external and not mutations and not errors
        context.close()
    assert snapshot(app) == before
