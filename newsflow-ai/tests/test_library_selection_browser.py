"""Real React library selection, reversible local markers, and immutable synthetic sources."""
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
from urllib.parse import parse_qs
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile, script
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.registry import CharacterRegistry
from bat_distribution.operation import OperatingRequests

CAPTURE_DIR = Path(os.environ['NEWSFLOW_LIBRARY_CAPTURE_DIR']) if os.environ.get('NEWSFLOW_LIBRARY_CAPTURE_DIR') else None


@pytest.fixture
def library_data(app):
    state = app.state
    registry = CharacterRegistry(state.config.data_dir, state.image_studio)
    cases = []
    for index, (name, color, species, status) in enumerate([
        ('합성 토끼 하나', 'blue', 'rabbit', 'script_review'),
        ('합성 토끼 둘', 'green', 'rabbit', 'clips_review'),
        ('합성 고양이', 'red', 'cat', 'needs_script'),
    ]):
        raw = image(color)
        saved = registry.save(profile(name, species), state.image_studio.asset_bytes(raw))
        identifier, _ = state.character.create_episode(name + '의 정원 정리', '5', reference=raw,
            settings={**DEFAULTS, 'video_model': O3, 'native_resolution': 'std', 'duration': 15,
                      'sound': 'on', 'script_model': 'claude-sonnet-4-6'}, request_id=uuid4().hex, profile=saved)
        job = state.character.read(identifier)
        if status != 'needs_script': job.update(script=script(15, name), prompts=[])
        job.update(state=status, created_at=f'2026-10-01T0{index}:00:00+00:00')
        job.setdefault('prompts', [])
        job['plan_hash'] = state.character.plan_hash(job); state.character.save(job)
        cases.append({'id': 'character:' + identifier, 'job_id': identifier,
                      'title': job['topic']})
    before = {row['job_id']: deepcopy(state.character.read(row['job_id'])) for row in cases}
    media = {row['job_id']: sha256((state.character.folder(row['job_id']) / 'reference.png').read_bytes()).hexdigest() for row in cases}
    return {'cases': cases, 'jobs': before, 'media': media, 'profiles': registry.list(), 'registry': registry}


def assert_sources_unchanged(app, data):
    assert {identifier: app.state.character.read(identifier) for identifier in data['jobs']} == data['jobs']
    assert {identifier: sha256((app.state.character.folder(identifier) / 'reference.png').read_bytes()).hexdigest()
            for identifier in data['media']} == data['media']
    assert data['registry'].list() == data['profiles']


def open_library(browser, origin):
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    page = context.new_page(); posts = []; errors = []
    page.on('request', lambda r: posts.append(r) if r.method == 'POST' else None)
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(origin + '/studio/library')
    return context, page, posts, errors


def card(page, row):
    return page.locator(f'[data-content-id="own-{row["id"]}"]')


def check_payload(request, endpoint, identifiers):
    assert request.url.endswith('/api/studio/library/' + endpoint)
    payload = parse_qs(request.post_data or '')
    assert set(json.loads(payload['items'][0])) == set(identifiers)
    assert payload['confirm'] == ['true'] and payload.get('csrf_token')


def open_trash(page):
    trash = page.locator('details').filter(has=page.locator('summary').filter(has_text='라이브러리 휴지통'))
    if not trash.evaluate('(e)=>e.open'): trash.locator(':scope > summary').click()
    return trash


def test_single_delete_cancel_then_restore_is_persistent_and_preserves_sources(app, browser, library_data):
    data = library_data; target = data['cases'][0]
    with local_server(OperatingRequests(app)) as origin:
        context, page, posts, errors = open_library(browser, origin)
        card(page, target).click()
        page.locator('.mg-library-detail').get_by_role('button', name='이 콘텐츠 삭제', exact=True).click()
        modal = page.get_by_role('dialog', name='라이브러리에서 삭제', exact=True)
        expect(modal).to_be_visible()
        expect(modal.get_by_text('라이브러리 휴지통으로 옮깁니다. 원본 파일과 제작 작업·이력은 보존되며 복원할 수 있습니다.', exact=True)).to_be_visible()
        modal.get_by_role('button', name='취소', exact=True).click()
        expect(modal).to_have_count(0)
        assert not posts
        expect(card(page, target)).to_be_visible()
        page.locator('.mg-library-detail').get_by_role('button', name='이 콘텐츠 삭제', exact=True).click()
        modal.get_by_role('button', name='휴지통으로 이동', exact=True).click()
        expect(modal).to_have_count(0)
        expect(card(page, target)).to_have_count(0)
        assert len(posts) == 1; check_payload(posts[0], 'remove', [target['id']])
        page.reload()
        expect(card(page, target)).to_have_count(0)
        for row in data['cases'][1:]: expect(card(page, row)).to_be_visible()
        trash = open_trash(page)
        expect(trash.get_by_role('button', name=target['title'] + ' 복원', exact=True)).to_be_visible()
        trash.get_by_role('button', name=target['title'] + ' 복원', exact=True).click()
        expect(card(page, target)).to_be_visible()
        assert len(posts) == 2; check_payload(posts[1], 'restore', [target['id']])
        page.reload()
        expect(card(page, target)).to_be_visible()
        expect(page.get_by_role('button', name=target['title'] + ' 복원', exact=True)).to_have_count(0)
        assert len(posts) == 2 and not errors
        assert_sources_unchanged(app, data)
        context.close()


def test_multiple_selection_is_limited_to_visible_filter_and_independent_of_preview(app, browser, library_data, tmp_path):
    data = library_data; first, second, other = data['cases']
    with local_server(OperatingRequests(app)) as origin:
        context, page, posts, errors = open_library(browser, origin)
        toolbar = page.locator('.mg-library-selection')
        toolbar.get_by_role('button', name='표시 항목 전체 선택', exact=True).click()
        expect(toolbar.get_by_text('선택 3개', exact=True)).to_be_visible()
        toolbar.get_by_role('button', name='선택 해제', exact=True).click()
        expect(toolbar.get_by_text('선택 0개', exact=True)).to_be_visible()
        search = page.get_by_label('라이브러리 검색', exact=True)
        search.fill('토끼')
        toolbar.get_by_role('button', name='표시 항목 전체 선택', exact=True).click()
        expect(toolbar.get_by_text('선택 2개', exact=True)).to_be_visible()
        search.fill('고양이')
        expect(toolbar.get_by_text('선택 0개', exact=True)).to_be_visible()
        expect(toolbar.get_by_role('button', name='선택 삭제', exact=True)).to_be_disabled()
        search.fill('')
        card(page, other).click()
        detail = page.locator('.mg-library-detail')
        expect(detail.get_by_role('heading', name=other['title'], exact=True)).to_be_visible()
        for row in (first, second): page.get_by_role('checkbox', name=row['title'] + ' 선택', exact=True).check()
        expect(detail.get_by_role('heading', name=other['title'], exact=True)).to_be_visible()
        expect(detail.get_by_role('link', name='제작실로 이동', exact=True)).to_have_attribute('href', '/studio/characters?job_id=' + other['job_id'])
        card(page, first).click()
        expect(detail.get_by_role('heading', name=first['title'], exact=True)).to_be_visible()
        for row in (first, second): expect(page.get_by_role('checkbox', name=row['title'] + ' 선택', exact=True)).to_be_checked()
        expect(page.get_by_role('checkbox', name=other['title'] + ' 선택', exact=True)).not_to_be_checked()
        assert not posts
        out = CAPTURE_DIR or tmp_path / 'captures'; out.mkdir(parents=True, exist_ok=True)
        for width, height in [(1920, 1080), (1366, 768)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.locator('h1').click(); page.evaluate('window.scrollTo(0,0)')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert toolbar.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
            page.screenshot(path=str(out / f'library-multiple-selection-{width}x{height}.png'), full_page=True)
        toolbar.get_by_role('button', name='선택 삭제', exact=True).click()
        modal = page.get_by_role('dialog', name='라이브러리에서 삭제', exact=True)
        expect(modal.get_by_text(first['title'], exact=True)).to_be_visible()
        expect(modal.get_by_text(second['title'], exact=True)).to_be_visible()
        expect(modal.get_by_text(other['title'], exact=True)).to_have_count(0)
        modal.get_by_role('button', name='휴지통으로 이동', exact=True).click()
        expect(modal).to_have_count(0)
        for row in (first, second): expect(card(page, row)).to_have_count(0)
        expect(card(page, other)).to_be_visible()
        expect(toolbar.get_by_text('선택 0개', exact=True)).to_be_visible()
        assert len(posts) == 1; check_payload(posts[0], 'remove', [first['id'], second['id']])
        assert not errors
        assert_sources_unchanged(app, data)
        context.close()


@pytest.mark.parametrize('operation', ['remove', 'restore'])
def test_failed_library_change_keeps_selection_or_trash_without_retry(app, browser, library_data, operation):
    data = library_data; target = data['cases'][0]
    with local_server(OperatingRequests(app)) as origin:
        context, page, posts, errors = open_library(browser, origin)
        if operation == 'restore':
            card(page, target).click()
            page.locator('.mg-library-detail').get_by_role('button', name='이 콘텐츠 삭제', exact=True).click()
            page.get_by_role('dialog', name='라이브러리에서 삭제', exact=True).get_by_role('button', name='휴지통으로 이동', exact=True).click()
            expect(card(page, target)).to_have_count(0)
        prior_posts = len(posts)
        context.route('**/api/studio/library/' + operation,
            lambda route: route.fulfill(status=409, json={'detail': '합성 저장 충돌입니다. 다시 확인하세요.'}))
        if operation == 'remove':
            page.get_by_role('checkbox', name=target['title'] + ' 선택', exact=True).check()
            page.locator('.mg-library-selection').get_by_role('button', name='선택 삭제', exact=True).click()
            modal = page.get_by_role('dialog', name='라이브러리에서 삭제', exact=True)
            modal.get_by_role('button', name='휴지통으로 이동', exact=True).click()
            expect(modal.get_by_role('alert')).to_have_text('진행 중이거나 상태가 변경된 항목이 있습니다. 목록을 새로고침해 확인하세요.')
            expect(modal).to_be_visible()
            expect(page.get_by_role('checkbox', name=target['title'] + ' 선택', exact=True)).to_be_checked()
            expect(card(page, target)).to_be_visible()
        else:
            trash = open_trash(page)
            trash.get_by_role('button', name=target['title'] + ' 복원', exact=True).click()
            expect(page.get_by_role('alert')).to_have_text('진행 중이거나 상태가 변경된 항목이 있습니다. 목록을 새로고침해 확인하세요.')
            expect(trash.get_by_role('button', name=target['title'] + ' 복원', exact=True)).to_be_visible()
            expect(card(page, target)).to_have_count(0)
        assert len(posts) == prior_posts + 1
        check_payload(posts[-1], operation, [target['id']])
        page.reload()
        if operation == 'remove': expect(card(page, target)).to_be_visible()
        else: expect(card(page, target)).to_have_count(0)
        assert len(posts) == prior_posts + 1 and not errors
        assert_sources_unchanged(app, data)
        context.close()
