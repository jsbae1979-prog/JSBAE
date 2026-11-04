"""Removing queue controls leaves historical queues, jobs and media untouched."""
from copy import deepcopy
from hashlib import sha256
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


def context_for(browser, origin):
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    return context


def assert_sources_preserved(app, data):
    assert {job['id']: job for job in app.state.character.listing()} == data['jobs_before']
    assert data['topics'].list(data['profile']['id']) == data['topics_before']
    assert {job_id: sha256((app.state.character.folder(job_id) / 'reference.png').read_bytes()).hexdigest()
            for job_id in data['jobs_before']} == data['media_before']


def test_single_topic_screen_hides_queue_actions_without_loading_or_changing_history(app, browser, queues_data):
    data = queues_data
    with local_server(OperatingRequests(app)) as origin:
        context = context_for(browser, origin); page = context.new_page(); requests = []
        page.on('request', lambda r: requests.append(r))
        page.goto(origin + '/studio/characters')
        page.get_by_role('button', name='내 캐릭터', exact=True).click()
        page.get_by_label('저장된 캐릭터', exact=True).select_option('profile:' + data['profile']['id'])
        panel = page.locator('.character-topic-tools')
        panel.locator(':scope > summary').click()
        for row in data['rows']:
            expect(panel.get_by_role('button', name=row['topic'], exact=True)).to_be_visible()
        for selector in ('.character-topic-advanced', '.character-topic-manage', '.character-batch', '.character-queue', '.character-topic-import'):
            expect(panel.locator(selector)).to_have_count(0)
        expect(page.get_by_role('button', name='대기열 삭제', exact=True)).to_have_count(0)
        expect(page.get_by_role('combobox', name='저장된 대기열', exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='견적 승인 후 순차 영상 생성', exact=True)).to_have_count(0)
        expect(page.get_by_role('button', name='승인한 영상 이어서 제작', exact=True)).to_have_count(0)
        panel.get_by_role('button', name=data['rows'][1]['topic'], exact=True).click()
        expect(page.get_by_label('스토리 주제', exact=True)).to_have_value(data['rows'][1]['topic'])
        assert not any(r.method == 'POST' or '/queues' in r.url for r in requests)
        assert {row['id'] for row in data['queues'].list()} == {row['id'] for row in data['cases']}
        for before in data['cases']:
            assert data['queues'].get(before['id']) == before
        assert_sources_preserved(app, data)
        context.close()
