"""Selected library job opens its own saved character episode, without provider calls."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile, script
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.registry import CharacterRegistry

CAPTURE_DIR = Path(os.environ['NEWSFLOW_CHARACTER_CAPTURE_DIR']) if os.environ.get('NEWSFLOW_CHARACTER_CAPTURE_DIR') else None


@pytest.fixture
def saved_episodes(app):
    registry = CharacterRegistry(app.state.config.data_dir, app.state.image_studio)
    cases = []
    for index, (name, color, species, state) in enumerate([
        ('합성 토끼', 'blue', 'rabbit', 'script_review'),
        ('합성 고양이', 'green', 'cat', 'clips_review'),
    ]):
        raw = image(color)
        saved = registry.save(profile(name, species), app.state.image_studio.asset_bytes(raw))
        topic = name + '의 정원 정리'
        identifier, _ = app.state.character.create_episode(topic, '5', reference=raw,
            settings={**DEFAULTS, 'video_model': O3, 'native_resolution': 'std', 'duration': 15,
                      'sound': 'on', 'script_model': 'claude-sonnet-4-6'},
            request_id=uuid4().hex, profile=saved)
        job = app.state.character.read(identifier)
        job.update(state=state, script=script(15, name), prompts=[], created_at=f'2026-10-01T0{index}:00:00+00:00')
        job['plan_hash'] = app.state.character.plan_hash(job)
        app.state.character.save(job)
        cases.append({'id': identifier, 'name': name, 'topic': topic,
                      'title': name + '의 정원', 'state': state})
    return cases


def check_selected(page, case):
    expect(page.locator('.kling-character-topic textarea')).to_have_value(case['topic'])
    expect(page.get_by_role('img', name='선택한 캐릭터 참조 이미지', exact=True)).to_have_attribute(
        'src', f"/api/studio/characters/{case['id']}/reference")
    expect(page.get_by_role('heading', name='한글 스토리 · ' + case['title'], exact=True)).to_be_visible()
    expect(page.locator('.kling-character-story-result > header .core-state')).to_have_text(
        '대본 검토' if case['state'] == 'script_review' else '장면 검토')


def test_each_library_card_opens_its_selected_character_episode(app, browser, saved_episodes, tmp_path):
    originals = {row['id']: app.state.character.read(row['id']) for row in saved_episodes}
    with local_server(app) as origin:
        context = browser.new_context(viewport={'width': 1366, 'height': 768})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page = context.new_page(); posts = []; errors = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        for case in saved_episodes:
            page.goto(origin + '/studio/library')
            page.locator(f"[data-content-id='own-character:{case['id']}']").click()
            link = page.locator('.mg-library-detail').get_by_role('link', name='제작실로 이동', exact=True)
            expect(link).to_have_attribute('href', f"/studio/characters?job_id={case['id']}")
            link.click()
            expect(page).to_have_url(origin + f"/studio/characters?job_id={case['id']}")
            check_selected(page, case)
            page.reload()
            check_selected(page, case)
        page.go_back()
        expect(page).to_have_url(origin + '/studio/library')
        page.go_forward()
        check_selected(page, saved_episodes[-1])
        out = CAPTURE_DIR or tmp_path / 'captures'; out.mkdir(parents=True, exist_ok=True)
        page.goto(origin + f"/studio/characters?job_id={saved_episodes[0]['id']}")
        check_selected(page, saved_episodes[0])
        for width, height in [(1920, 1080), (1366, 768)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.screenshot(path=str(out / f'character-library-selection-{width}x{height}.png'), full_page=True)
        page.goto(origin + '/studio/characters')
        check_selected(page, saved_episodes[-1])
        assert not posts and not errors
        context.close()
    assert originals == {row['id']: app.state.character.read(row['id']) for row in saved_episodes}


@pytest.mark.parametrize('requested', ['0' * 32, '../../wrong-job', ''])
def test_missing_or_invalid_requested_job_never_selects_another_job(app, browser, saved_episodes, requested):
    with local_server(app) as origin:
        context = browser.new_context(viewport={'width': 1366, 'height': 768})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
        page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.goto(origin + '/studio/characters?job_id=' + requested)
        expect(page.get_by_role('alert')).to_have_text('선택한 작업을 찾을 수 없습니다. 작업 이력에서 다른 작업을 선택하세요.')
        expect(page.locator('.kling-character-topic textarea')).to_have_value('')
        expect(page.get_by_role('img', name='선택한 캐릭터 참조 이미지', exact=True)).to_have_count(0)
        expect(page.locator('.kling-character-story-result')).to_have_count(0)
        expect(page.get_by_role('button', name='스토리 자동 생성하기', exact=False)).to_be_disabled()
        page.get_by_role('button', name='작업 이력', exact=True).click()
        expect(page.get_by_text(saved_episodes[0]['topic'], exact=True)).to_be_visible()
        assert not posts
        context.close()
