"""Simple topic picking and explicitly expanded batch controls; Fake AI only."""
import os
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile, script
from newsflow.character.kling import DEFAULTS, O3
from newsflow.character.queue import EpisodeQueue
from newsflow.character.registry import CharacterRegistry
from newsflow.character.topics import TopicStore

CAPTURE_DIR = Path(os.environ['NEWSFLOW_CHARACTER_CAPTURE_DIR']) if os.environ.get('NEWSFLOW_CHARACTER_CAPTURE_DIR') else None


class NoSecretKey:
    def status(self): return {'configured': True}
    def key(self): raise AssertionError('Synthetic UI tests cannot read real keys')


class FakeTopics:
    response_received = True
    last_estimated_usd = '0'
    def __init__(self): self.calls = []; self.script_calls = []
    def topics(self, character, count, existing, **kwargs):
        assert kwargs['consent'] is True and count == 1
        self.calls.append({'character_id': character['id'], 'count': count, **kwargs})
        return [{'topic': '합성 캐릭터가 우산을 거꾸로 펼친 아침', 'category': '일상', 'joke_type': '반전'}]
    def generate(self, instruction, payload, schema, options, **kwargs):
        assert kwargs['consent'] is True and 'image_bytes' not in kwargs
        self.script_calls.append(payload['character']['name_ko'])
        return schema.model_validate(script(payload['target_seconds'], payload['character']['name_ko']))


@pytest.fixture
def topic_data(app):
    registry = CharacterRegistry(app.state.config.data_dir, app.state.image_studio)
    saved = registry.save(profile('합성 느긋한 토끼', 'rabbit'), app.state.image_studio.asset_bytes(image()))
    other = registry.save(profile('합성 고양이', 'cat'), app.state.image_studio.asset_bytes(image('green')))
    store = TopicStore(app.state.config.data_dir)
    rows = []
    for topic, status in [
        ('출근 준비를 하다가 머그컵 대신 화분을 가져온 아침', 'new'),
        ('점심시간에 가장 작은 도시락을 끝까지 지키는 캐릭터', 'scripted'),
        ('비 오는 날 작은 우산을 모두에게 양보하는 하루', 'produced'),
        ('청소를 시작했지만 낮잠이 더 중요해진 오후', 'skipped'),
    ]:
        row = store.add(saved['id'], topic)
        rows.append(store.update_status(saved['id'], row['id'], status))
    store.add(other['id'], '다른 캐릭터에게만 속한 주제')
    fake = FakeTopics()
    app.state.character_authoring = fake
    app.state.api_keys = {'claude_api': NoSecretKey()}
    return {'profile': saved, 'other': other, 'registry': registry, 'store': store, 'rows': rows, 'fake': fake}


def open_topics(page, origin, data):
    page.goto(origin + '/studio/characters')
    page.get_by_role('button', name='내 캐릭터', exact=True).click()
    page.get_by_label('저장된 캐릭터', exact=True).select_option('profile:' + data['profile']['id'])
    panel = page.locator('.character-topic-tools')
    panel.locator(':scope > summary').click()
    expect(panel.get_by_role('button', name=data['rows'][0]['topic'], exact=True)).to_be_visible()
    return panel


def context_for(browser, origin):
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin + '/') else route.abort())
    return context


def test_simple_topic_selection_manual_save_and_compact_layout(app, browser, topic_data, tmp_path):
    data = topic_data
    with local_server(app) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []; errors = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        panel = open_topics(page, origin, data)
        expect(panel.get_by_label(data['rows'][0]['topic'] + ' 대기열 선택', exact=True)).not_to_be_visible()
        expect(panel.get_by_label(data['rows'][0]['topic'] + ' 상태', exact=True)).not_to_be_visible()
        expect(panel.get_by_role('combobox', name='저장된 대기열', exact=True)).not_to_be_visible()
        expect(panel.get_by_text('CSV 주제 가져오기', exact=True)).not_to_be_visible()
        panel.get_by_role('button', name=data['rows'][1]['topic'], exact=True).click()
        expect(page.get_by_label('스토리 주제', exact=True)).to_have_value(data['rows'][1]['topic'])
        assert not posts and not data['fake'].calls
        for row in data['rows']: assert row['id'] not in panel.inner_text()
        for raw in ('scripted', 'produced', 'skipped'): assert raw not in panel.inner_text()
        manual = '합성 캐릭터가 첫 눈을 보고 천천히 장갑을 찾는 하루'
        page.get_by_label('스토리 주제', exact=True).fill(manual)
        panel.get_by_role('button', name='입력한 주제 저장', exact=True).click()
        expect(panel.get_by_role('button', name=manual, exact=True)).to_be_visible()
        assert len(posts) == 1 and posts[0].endswith('/topics/manual')
        assert data['store'].list(data['profile']['id'])[-1]['topic'] == manual
        assert not data['fake'].calls and not app.state.character.listing()
        out = CAPTURE_DIR or tmp_path / 'captures'; out.mkdir(parents=True, exist_ok=True)
        for width, height in [(1920, 1080), (1366, 768)]:
            page.set_viewport_size({'width': width, 'height': height})
            panel.scroll_into_view_if_needed()
            assert panel.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            expect(panel.get_by_role('button', name='입력한 주제 저장', exact=True)).to_be_visible()
            page.screenshot(path=str(out / f'character-simple-topics-{width}x{height}.png'), full_page=True)
        panel.get_by_label('주제 생성 유료 요청에 동의합니다.', exact=True).check()
        page.get_by_label('저장된 캐릭터', exact=True).select_option('profile:' + data['other']['id'])
        expect(panel.get_by_role('button', name='다른 캐릭터에게만 속한 주제', exact=True)).to_be_visible()
        expect(panel.get_by_label('주제 생성 유료 요청에 동의합니다.', exact=True)).not_to_be_checked()
        expect(panel.get_by_role('button', name=manual, exact=True)).to_have_count(0)
        assert len(posts) == 1 and not errors
        context.close()


def test_topic_generation_still_requires_explicit_paid_consent(app, browser, topic_data):
    data = topic_data
    with local_server(app) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        panel = open_topics(page, origin, data)
        button = panel.get_by_role('button', name='주제 자동 생성', exact=True)
        expect(button).to_be_disabled()
        panel.get_by_label('주제 개수', exact=True).fill('1')
        assert not posts and not data['fake'].calls
        panel.get_by_label('주제 생성 유료 요청에 동의합니다.', exact=True).check()
        expect(button).to_be_enabled(); button.click()
        expect(panel.get_by_role('button', name='합성 캐릭터가 우산을 거꾸로 펼친 아침', exact=True)).to_be_visible()
        expect(button).to_be_disabled()
        expect(panel.get_by_label('주제 생성 유료 요청에 동의합니다.', exact=True)).not_to_be_checked()
        assert len(posts) == 1 and posts[0].endswith('/topics/generate')
        assert len(data['fake'].calls) == 1 and data['fake'].calls[0]['character_id'] == data['profile']['id']
        assert not app.state.character.listing()
        context.close()


def test_advanced_topics_preserve_batch_status_import_and_quote_approval(app, browser, topic_data, tmp_path):
    data = topic_data; service = app.state.character
    queue_service = EpisodeQueue(app.state.config.data_dir, service, data['registry'], data['store'])
    queue = queue_service.create(data['profile']['id'], [row['id'] for row in data['rows'][:2]],
        {**DEFAULTS, 'video_model': O3, 'native_resolution': 'std', 'duration': 15,
         'sound': 'on', 'script_model': 'claude-sonnet-4-6'}, '5', uuid4().hex)
    for row in queue['rows']:
        job = service.read(row['job_id']); job.update(state='quoted', script=script(15), prompts=[],
            quote_total_usd='0.40', quote_hash='f' * 64)
        job['plan_hash'] = service.plan_hash(job); service.save(job)
    queue['state'] = 'scripts_ready'; queue_service._save(queue)
    blocked = queue_service.create(data['profile']['id'], [data['rows'][2]['id']],
        queue['settings'], '5', uuid4().hex)
    blocked['state'] = 'blocked'; queue_service._save(blocked)
    with local_server(app) as origin:
        context = context_for(browser, origin); page = context.new_page(); posts = []
        page.on('request', lambda r: posts.append(r.url) if r.method == 'POST' else None)
        panel = open_topics(page, origin, data)
        page.get_by_label('영상 길이', exact=True).select_option('15')
        panel.get_by_text('고급 · 일괄 제작·기록 관리', exact=True).click()
        first = data['rows'][0]
        select = panel.get_by_label(first['topic'] + ' 대기열 선택', exact=True)
        expect(select).to_be_visible(); select.check()
        status = panel.get_by_label(first['topic'] + ' 상태', exact=True)
        expect(status).to_be_visible(); status.select_option('skipped')
        expect(status).to_have_value('skipped')
        assert data['store'].list(data['profile']['id'])[0]['status'] == 'skipped'
        panel.locator('.character-batch > summary').click()
        scripts = panel.get_by_role('button', name='선택한 주제 대본 생성', exact=True)
        expect(scripts).to_be_disabled()
        panel.get_by_label('선택한 1편의 유료 대본 생성에 동의합니다.', exact=True).check()
        expect(scripts).to_be_enabled()
        panel.get_by_label('선택한 1편의 유료 대본 생성에 동의합니다.', exact=True).uncheck()
        panel.locator('.character-queue > summary').click()
        panel.get_by_role('combobox', name='저장된 대기열', exact=True).select_option(queue['id'])
        approval = panel.get_by_role('button', name='견적 승인 후 순차 영상 생성', exact=True)
        expect(approval).to_be_disabled()
        expect(panel.get_by_text('공식 견적 합계: US$0.80', exact=True)).to_be_visible()
        panel.get_by_label('이번 대기열 영상 승인 한도 (USD)', exact=True).fill('0.79')
        panel.get_by_label('각 대본·견적을 검토했고 합계 비용에 동의합니다.', exact=True).check()
        expect(approval).to_be_disabled()
        panel.get_by_label('이번 대기열 영상 승인 한도 (USD)', exact=True).fill('0.80')
        expect(approval).to_be_enabled()
        panel.get_by_label('각 대본·견적을 검토했고 합계 비용에 동의합니다.', exact=True).uncheck()
        expect(approval).to_be_disabled()
        for raw in [queue['id'], 'scripts_ready', *[row['job_id'] for row in queue['rows']]]:
            assert raw not in panel.inner_text()
        out = CAPTURE_DIR or tmp_path / 'captures'; out.mkdir(parents=True, exist_ok=True)
        for width, height in [(1920, 1080), (1366, 768)]:
            page.set_viewport_size({'width': width, 'height': height})
            assert panel.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
            assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
            page.screenshot(path=str(out / f'character-advanced-topics-{width}x{height}.png'), full_page=True)
        panel.get_by_label('각 대본·견적을 검토했고 합계 비용에 동의합니다.', exact=True).check()
        panel.get_by_label('선택한 1편의 유료 대본 생성에 동의합니다.', exact=True).check()
        panel.get_by_role('combobox', name='저장된 대기열', exact=True).select_option(blocked['id'])
        expect(panel.get_by_role('button', name='승인한 영상 이어서 제작', exact=True)).to_have_count(0)
        expect(panel.get_by_role('button', name='견적 승인 후 순차 영상 생성', exact=True)).to_have_count(0)
        assert 'blocked' not in panel.inner_text() and blocked['id'] not in panel.inner_text()
        expect(panel.get_by_label('선택한 1편의 유료 대본 생성에 동의합니다.', exact=True)).not_to_be_checked()
        panel.get_by_role('combobox', name='저장된 대기열', exact=True).select_option(queue['id'])
        expect(panel.get_by_label('각 대본·견적을 검토했고 합계 비용에 동의합니다.', exact=True)).not_to_be_checked()
        expect(panel.get_by_role('button', name='견적 승인 후 순차 영상 생성', exact=True)).to_be_disabled()
        blocked['state'] = 'unknown'; queue_service._save(blocked)
        panel.get_by_role('combobox', name='저장된 대기열', exact=True).select_option(blocked['id'])
        expect(panel.get_by_role('button', name='승인한 영상 이어서 제작', exact=True)).to_have_count(0)
        expect(panel.get_by_role('button', name='견적 승인 후 순차 영상 생성', exact=True)).to_have_count(0)
        assert 'unknown' not in panel.inner_text()
        panel.get_by_role('combobox', name='저장된 대기열', exact=True).select_option(queue['id'])
        panel.get_by_text('CSV 주제 가져오기', exact=True).click()
        panel.get_by_label('번호, 카테고리, 주제', exact=True).fill('번호,카테고리,주제\n1,일상,합성 캐릭터가 작은 우체통을 발견한 오후')
        panel.get_by_role('button', name='CSV 가져오기', exact=True).click()
        expect(panel.get_by_role('button', name='합성 캐릭터가 작은 우체통을 발견한 오후', exact=True)).to_be_visible()
        assert len(posts) == 2 and posts[0].endswith('/status') and posts[1].endswith('/topics/import')
        assert not data['fake'].calls
        assert queue_service.get(queue['id'])['state'] == 'scripts_ready'
        assert all(service.read(row['job_id'])['state'] == 'quoted' for row in queue['rows'])
        panel.get_by_label('이번 대기열 영상 승인 한도 (USD)', exact=True).fill('0.80')
        panel.get_by_label('각 대본·견적을 검토했고 합계 비용에 동의합니다.', exact=True).check()
        panel.get_by_label('선택한 1편의 유료 대본 생성에 동의합니다.', exact=True).check()
        scripts.click()
        expect(panel.get_by_label('선택한 1편의 유료 대본 생성에 동의합니다.', exact=True)).not_to_be_checked()
        saved_queues = queue_service.list()
        assert len(saved_queues) == 3 and len(data['fake'].script_calls) == 1
        created = next(row for row in saved_queues if row['id'] not in {queue['id'], blocked['id']})
        picker = panel.get_by_role('combobox', name='저장된 대기열', exact=True)
        expect(picker).to_have_value(created['id'])
        expect(picker.locator(f"option[value='{created['id']}']")).to_have_count(1)
        assert len(posts) == 4 and posts[2].endswith('/queues/create') and posts[3].endswith('/scripts')
        assert not any(url.endswith('/approve-videos') or url.endswith('/advance') for url in posts)
        context.close()
