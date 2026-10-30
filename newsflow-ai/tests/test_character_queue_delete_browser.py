"""Explicit queue-only deletion against synthetic records and the real React UI."""
from copy import deepcopy
from hashlib import sha256
from urllib.parse import parse_qs
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile, script
from bat_distribution.operation import OperatingRequests
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.queue import EpisodeQueue
from newsflow.character.registry import CharacterRegistry
from newsflow.character.topics import TopicStore


class NoProvider:
    def __getattr__(self, name): raise AssertionError('No provider call is allowed for queue deletion')


class NoSecret:
    def status(self): return {'configured': True}
    def key(self): raise AssertionError('No credential reads in synthetic GUI tests')


@pytest.fixture
def queues_data(app):
    state = app.state
    registry = CharacterRegistry(state.config.data_dir, state.image_studio)
    saved = registry.save(profile('합성 보관 캐릭터'), state.image_studio.asset_bytes(image()))
    topics = TopicStore(state.config.data_dir)
    rows = [topics.add(saved['id'], text) for text in ['느긋한 정원 정리', '바쁜 우체국의 아침', '작은 도시락의 여행']]
    queues = EpisodeQueue(state.config.data_dir, state.character, registry, topics)
    settings = {**DEFAULTS, 'video_model': O3, 'native_resolution': 'std', 'duration': 15,
                'sound': 'on', 'script_model': 'claude-sonnet-4-6'}
    cases = []
    for index, queue_state in enumerate(['scripts_ready', 'scripts_running', 'videos_running']):
        queue = queues.create(saved['id'], [rows[index]['id']], settings, '5', uuid4().hex)
        queue['state'] = queue_state; queues._save(queue)
        for row in queue['rows']:
            job = state.character.read(row['job_id'])
            job.update(state='quoted', script=script(15), prompts=[], quote_total_usd='0.40', quote_hash='f' * 64)
            job['plan_hash'] = state.character.plan_hash(job); state.character.save(job)
        cases.append(queue)
    state.api_keys = {'claude_api': NoSecret()}
    state.character_authoring = NoProvider()
    snapshots = {job['id']: deepcopy(job) for job in state.character.listing()}
    media = {job_id: sha256((state.character.folder(job_id) / 'reference.png').read_bytes()).hexdigest() for job_id in snapshots}
    return {'profile': saved, 'topics': topics, 'rows': rows, 'queues': queues, 'cases': cases,
            'jobs_before': snapshots, 'media_before': media, 'topics_before': topics.list(saved['id'])}


def open_queue(page, origin, data):
    page.goto(origin + '/studio/characters')
    page.get_by_role('button', name='내 캐릭터', exact=True).click()
    page.get_by_label('저장된 캐릭터', exact=True).select_option('profile:' + data['profile']['id'])
    panel = page.locator('.character-topic-tools')
    panel.locator(':scope > summary').click()
    panel.get_by_text('고급 · 일괄 제작·기록 관리', exact=True).click()
    panel.locator('.character-queue > summary').click()
    picker = panel.get_by_role('combobox', name='저장된 대기열', exact=True)
    picker.select_option(data['cases'][0]['id'])
    expect(panel.get_by_text('공식 견적 합계: US$0.40', exact=True)).to_be_visible()
    return panel, picker


def context_for(browser, origin):
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    return context


def assert_sources_preserved(app, data):
    assert {job['id']: job for job in app.state.character.listing()} == data['jobs_before']
    assert data['topics'].list(data['profile']['id']) == data['topics_before']
    assert {job_id: sha256((app.state.character.folder(job_id) / 'reference.png').read_bytes()).hexdigest()
            for job_id in data['jobs_before']} == data['media_before']


def test_queue_delete_cancel_preserves_selection_then_confirm_archives_only_queue(app, browser, queues_data):
    data = queues_data; target = data['cases'][0]
    with local_server(OperatingRequests(app)) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r) if r.method == 'POST' else None)
        panel, picker = open_queue(page, origin, data)
        panel.get_by_role('button', name=data['rows'][0]['topic'], exact=True).click()
        panel.get_by_label(data['rows'][0]['topic'] + ' 대기열 선택', exact=True).check()
        panel.locator('.character-batch > summary').click()
        script_consent = panel.get_by_label('선택한 1편의 유료 대본 생성에 동의합니다.', exact=True)
        script_consent.check()
        topic_consent = panel.get_by_label('주제 생성 유료 요청에 동의합니다.', exact=True)
        topic_consent.check()
        panel.get_by_label('이번 대기열 영상 승인 한도 (USD)', exact=True).fill('0.50')
        video_consent = panel.get_by_label('각 대본·견적을 검토했고 합계 비용에 동의합니다.', exact=True)
        video_consent.check()
        panel.get_by_role('button', name='대기열 삭제', exact=True).click()
        modal = page.get_by_role('dialog', name='제작 대기열 삭제', exact=True)
        expect(modal).to_be_visible()
        expect(modal.get_by_text('선택한 대기열만 목록에서 삭제합니다. 연결된 작업·영상과 저장한 주제는 그대로 남습니다.', exact=True)).to_be_visible()
        modal.get_by_role('button', name='취소', exact=True).click()
        expect(modal).to_have_count(0)
        expect(picker).to_have_value(target['id'])
        expect(script_consent).to_be_checked(); expect(topic_consent).to_be_checked(); expect(video_consent).to_be_checked()
        expect(panel.get_by_label('이번 대기열 영상 승인 한도 (USD)', exact=True)).to_have_value('0.50')
        assert not posts and data['queues'].get(target['id']) == target
        panel.get_by_role('button', name='대기열 삭제', exact=True).click()
        modal.get_by_role('button', name='대기열 삭제 확인', exact=True).click()
        expect(modal).to_have_count(0)
        expect(picker).to_have_value('')
        expect(picker.locator(f"option[value='{target['id']}']")).to_have_count(0)
        expect(panel.get_by_role('button', name='대기열 삭제', exact=True)).to_be_disabled()
        expect(page.get_by_label('스토리 주제', exact=True)).to_have_value(data['rows'][0]['topic'])
        expect(panel.get_by_label(data['rows'][0]['topic'] + ' 대기열 선택', exact=True)).to_be_checked()
        expect(script_consent).not_to_be_checked()
        assert len(posts) == 1 and posts[0].url.endswith('/queues/' + target['id'] + '/delete')
        assert parse_qs(posts[0].post_data or '')['consent'] == ['true']
        assert {row['id'] for row in data['queues'].list()} == {row['id'] for row in data['cases'][1:]}
        page.reload()
        page.get_by_role('button', name='내 캐릭터', exact=True).click()
        page.get_by_label('저장된 캐릭터', exact=True).select_option('profile:' + data['profile']['id'])
        page.locator('.character-topic-tools > summary').click()
        page.get_by_text('고급 · 일괄 제작·기록 관리', exact=True).click()
        page.locator('.character-queue > summary').click()
        expect(page.get_by_role('combobox', name='저장된 대기열', exact=True).locator(f"option[value='{target['id']}']")).to_have_count(0)
        assert_sources_preserved(app, data)
        context.close()


def test_failed_queue_delete_keeps_selected_queue_and_shows_error_without_retry(app, browser, queues_data):
    data = queues_data; target = data['cases'][0]
    with local_server(OperatingRequests(app)) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []
        context.route('**/api/studio/characters/queues/*/delete', lambda route: route.fulfill(status=409, json={'detail': '합성 보관 실패'}))
        page.on('request', lambda r: posts.append(r) if r.method == 'POST' else None)
        panel, picker = open_queue(page, origin, data)
        panel.get_by_role('button', name='대기열 삭제', exact=True).click()
        modal = page.get_by_role('dialog', name='제작 대기열 삭제', exact=True)
        modal.get_by_role('button', name='대기열 삭제 확인', exact=True).click()
        expect(modal.get_by_role('alert')).to_contain_text('합성 보관 실패')
        expect(modal).to_be_visible()
        expect(picker).to_have_value(target['id'])
        assert len(posts) == 1 and data['queues'].get(target['id']) == target
        assert len(data['queues'].list()) == 3
        assert_sources_preserved(app, data)
        modal.get_by_role('button', name='취소', exact=True).click()
        context.close()


def test_running_queue_delete_is_disabled_and_does_not_post(app, browser, queues_data):
    data = queues_data
    with local_server(OperatingRequests(app)) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        panel, picker = open_queue(page, origin, data)
        for queue in data['cases'][1:]:
            picker.select_option(queue['id'])
            expect(picker).to_have_value(queue['id'])
            expect(panel.get_by_role('button', name='대기열 삭제', exact=True)).to_be_disabled()
            expect(page.get_by_role('dialog', name='제작 대기열 삭제', exact=True)).to_have_count(0)
        assert not posts and len(data['queues'].list()) == 3
        assert_sources_preserved(app, data)
        context.close()
