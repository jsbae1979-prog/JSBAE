"""Leaving a saved job keeps the selected registered character's own reference."""
from copy import deepcopy
from pathlib import Path
import os
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.registry import CharacterRegistry
from bat_distribution.operation import OperatingRequests


CAPTURE_DIR = Path(os.environ['NEWSFLOW_CHARACTER_CAPTURE_DIR']) if os.environ.get('NEWSFLOW_CHARACTER_CAPTURE_DIR') else None

class NoSecret:
    def status(self): return {'configured': True}
    def key(self): raise AssertionError('No real credentials in reference selection tests')


@pytest.mark.parametrize('new_path', ['history', 'failed_story'])
def test_saved_job_to_new_story_keeps_profile_image_and_never_mixes_characters(app, browser, new_path):
    registry = CharacterRegistry(app.state.config.data_dir, app.state.image_studio)
    cases = []
    for name, species, color in [('합성 토끼', 'rabbit', 'blue'), ('합성 고양이', 'cat', 'green')]:
        raw = image(color)
        saved = registry.save(profile(name, species), app.state.image_studio.asset_bytes(raw))
        job_id, _ = app.state.character.create_episode(name + '의 정원 정리', '5', reference=raw,
            settings={**DEFAULTS, 'video_model': O3, 'native_resolution': 'std', 'duration': 15,
                      'sound': 'on', 'script_model': 'claude-sonnet-4-6'}, request_id=uuid4().hex, profile=saved)
        cases.append((saved, job_id))
    app.state.api_keys = {'claude_api': NoSecret()}
    before = {row['id']: deepcopy(row) for row in app.state.character.listing()}
    with local_server(OperatingRequests(app)) as origin:
        context = browser.new_context(viewport={'width': 1366, 'height': 768})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        context.route('**/api/studio/characters/auto-story', lambda route: route.fulfill(status=409, json={'detail': '합성 스토리 요청 실패'}))
        page = context.new_page(); posts = []; errors = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        for saved, job_id in cases:
            page.goto(origin + '/studio/characters?job_id=' + job_id)
            picture = page.get_by_role('img', name='선택한 캐릭터 참조 이미지', exact=True)
            expect(picture).to_have_attribute('src', f'/api/studio/characters/{job_id}/reference')
            expect(picture).to_have_js_property('complete', True)
            assert picture.evaluate('(e)=>e.naturalWidth>0')
            if new_path == 'history':
                page.get_by_role('button', name='작업 이력', exact=True).click()
                page.get_by_role('dialog', name='작업 이력', exact=True).get_by_role('button', name='새 작업', exact=True).click()
            else:
                page.get_by_role('button', name='스토리 자동 생성하기', exact=False).click()
                expect(page.get_by_role('alert')).to_contain_text('스토리 요청 결과를 확인하지 못했습니다.')
                page.get_by_role('button', name='새 스토리 입력', exact=True).click()
            expect(page.get_by_label('스토리 주제', exact=True)).to_have_value('')
            expect(picture).to_have_attribute('src', '/image-studio/assets/' + saved['asset'])
            expect(picture).to_have_js_property('complete', True)
            assert picture.evaluate('(e)=>e.naturalWidth>0')
            page.get_by_role('button', name='내 캐릭터', exact=True).click()
            picker = page.get_by_label('저장된 캐릭터', exact=True)
            expect(picker).to_have_value('profile:' + saved['id'])
            page.get_by_role('button', name='참조 이미지 크게 보기', exact=True).click()
            modal = page.get_by_role('dialog', name='참조 이미지 미리보기', exact=True)
            expect(modal.get_by_role('img')).to_have_attribute('src', '/image-studio/assets/' + saved['asset'])
            modal.get_by_role('button', name='닫기', exact=True).click()
            other = next(row for row, _ in cases if row['id'] != saved['id'])
            picker.select_option('profile:' + other['id'])
            expect(picture).to_have_attribute('src', '/image-studio/assets/' + other['asset'])
            expect(picture).to_have_js_property('complete', True)
            assert picture.evaluate('(e)=>e.naturalWidth>0')
        if CAPTURE_DIR:
            CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
            page.locator('h1').click()
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(CAPTURE_DIR / ('selected-reference-'+new_path+'-1366x768.png')), full_page=True)
        assert len(posts) == (4 if new_path == 'failed_story' else 0)
        assert all(url.endswith('/character') or url.endswith('/characters/auto-story') for url in posts)
        if new_path == 'failed_story':
            assert sum(url.endswith('/character') for url in posts) == 2
            assert sum(url.endswith('/characters/auto-story') for url in posts) == 2
        assert not errors
        context.close()
    after = {row['id']: row for row in app.state.character.listing()}
    assert before == {identifier: after[identifier] for identifier in before}
    added = [row for identifier, row in after.items() if identifier not in before]
    assert len(added) == (2 if new_path == 'failed_story' else 0)
    assert all(row['state'] == 'needs_script' and row['script'] is None for row in added)
    assert len(registry.list()) == 2
