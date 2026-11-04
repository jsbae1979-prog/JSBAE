"""Current registered-profile edits never overwrite saved-job snapshots or concurrent changes."""
from copy import deepcopy
from hashlib import sha256
from urllib.parse import parse_qs
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.registry import CharacterRegistry, CharacterProfile
from bat_distribution.operation import OperatingRequests


def profile_values(row):
    return {key: deepcopy(row[key]) for key in CharacterProfile.model_fields}


@pytest.fixture
def revised_profile(app):
    state = app.state
    registry = CharacterRegistry(state.config.data_dir, state.image_studio)
    original_image = image('blue')
    original = registry.save(profile('과거 합성 토끼'), state.image_studio.asset_bytes(original_image))
    job_id, _ = state.character.create_episode('정원의 느긋한 아침', '5', reference=original_image,
        settings={**DEFAULTS, 'video_model': O3, 'native_resolution': 'std', 'duration': 15,
                  'sound': 'on', 'script_model': 'claude-sonnet-4-6'}, request_id=uuid4().hex, profile=original)
    values = profile_values(original)
    values.update(name_ko='현재 합성 토끼', personality='최근 수정한 차분한 성격')
    latest = registry.save(values, state.image_studio.asset_bytes(image('green')),
        identifier=original['id'], expected_revision=original['revision'])
    job = deepcopy(state.character.read(job_id))
    reference = sha256((state.character.folder(job_id) / 'reference.png').read_bytes()).hexdigest()
    return {'registry': registry, 'original': original, 'latest': latest, 'job_id': job_id,
            'job': job, 'reference': reference}


def context_for(browser, origin):
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    return context


def assert_history_unchanged(app, data):
    assert app.state.character.read(data['job_id']) == data['job']
    assert sha256((app.state.character.folder(data['job_id']) / 'reference.png').read_bytes()).hexdigest() == data['reference']


def test_historical_job_edit_opens_current_profile_and_saves_matching_revision(app, browser, revised_profile):
    data = revised_profile
    with local_server(OperatingRequests(app)) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r) if r.method == 'POST' else None)
        page.goto(origin + '/studio/characters?job_id=' + data['job_id'])
        expect(page.get_by_role('img', name='선택한 캐릭터 참조 이미지', exact=True)).to_have_attribute(
            'src', f'/api/studio/characters/{data["job_id"]}/reference')
        page.get_by_role('button', name='특징 수정', exact=True).click()
        dialog = page.get_by_role('dialog', name='캐릭터 특징 수정', exact=True)
        expect(dialog.get_by_role('textbox', name='캐릭터 이름', exact=True)).to_have_value(data['latest']['name_ko'])
        expect(dialog.get_by_role('textbox', name='성격', exact=True)).to_have_value(data['latest']['personality'])
        dialog.get_by_role('textbox', name='성격', exact=True).fill('이번에 직접 수정한 침착한 성격')
        dialog.get_by_role('button', name='캐릭터 저장', exact=True).click()
        expect(dialog).to_have_count(0)
        after = data['registry'].get(data['latest']['id'])
        assert after['revision'] == 3 and after['personality'] == '이번에 직접 수정한 침착한 성격'
        assert after['asset'] == data['latest']['asset'] != data['original']['asset']
        assert len(posts) == 1 and posts[0].url.endswith('/profiles/save')
        sent = parse_qs(posts[0].post_data or '')
        assert sent['revision'] == ['2'] and sent['identifier'] == [data['latest']['id']]
        assert sent['asset'] == [data['latest']['asset']]
        assert_history_unchanged(app, data)
        context.close()


def test_concurrent_profile_edit_keeps_user_draft_and_reports_conflict_without_retry(app, browser, revised_profile):
    data = revised_profile
    with local_server(OperatingRequests(app)) as origin:
        context = context_for(browser, origin); page = context.new_page(); requests = []
        page.on('request', lambda r: requests.append(r))
        page.goto(origin + '/studio/characters?job_id=' + data['job_id'])
        page.get_by_role('button', name='특징 수정', exact=True).click()
        dialog = page.get_by_role('dialog', name='캐릭터 특징 수정', exact=True)
        expect(dialog.get_by_role('textbox', name='성격', exact=True)).to_have_value(data['latest']['personality'])
        dialog.get_by_role('textbox', name='성격', exact=True).fill('저장 충돌 후에도 남아야 하는 입력')
        concurrent_values = profile_values(data['latest'])
        concurrent_values['personality'] = '다른 창에서 먼저 저장한 성격'
        concurrent = data['registry'].save(concurrent_values, data['latest']['asset'],
            identifier=data['latest']['id'], expected_revision=data['latest']['revision'])
        before_save = len(requests)
        dialog.get_by_role('button', name='캐릭터 저장', exact=True).click()
        expect(dialog.get_by_role('alert')).to_have_text(
            '다른 곳에서 캐릭터 정보가 변경되었습니다. 입력한 내용은 유지했습니다. 최신 정보를 확인한 뒤 다시 수정하세요.')
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role('textbox', name='성격', exact=True)).to_have_value('저장 충돌 후에도 남아야 하는 입력')
        expect(dialog.get_by_role('button', name='캐릭터 저장', exact=True)).to_be_enabled()
        after_requests = requests[before_save:]
        saves = [r for r in after_requests if r.method == 'POST']
        reads = [r for r in after_requests if r.url.endswith('/api/studio/characters/profiles') and r.method == 'GET']
        assert len(saves) == 1 and saves[0].url.endswith('/profiles/save') and len(reads) == 1
        assert parse_qs(saves[0].post_data or '')['revision'] == ['2']
        assert data['registry'].get(data['latest']['id']) == concurrent
        assert_history_unchanged(app, data)
        context.close()


def test_new_draft_from_historical_job_uses_current_registered_profile(app, browser, revised_profile):
    data = revised_profile
    with local_server(OperatingRequests(app)) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.goto(origin + '/studio/characters?job_id=' + data['job_id'])
        page.get_by_role('button', name='작업 이력', exact=True).click()
        page.get_by_role('dialog', name='작업 이력', exact=True).get_by_role('button', name='새 작업', exact=True).click()
        expect(page.get_by_role('img', name='선택한 캐릭터 참조 이미지', exact=True)).to_have_attribute(
            'src', '/image-studio/assets/' + data['latest']['asset'])
        expect(page.locator('.character-profile-summary strong')).to_have_text(data['latest']['name_ko'])
        expect(page.locator('.character-profile-summary p')).to_have_text(data['latest']['personality'])
        assert not posts and data['registry'].get(data['latest']['id']) == data['latest']
        assert_history_unchanged(app, data)
        context.close()
