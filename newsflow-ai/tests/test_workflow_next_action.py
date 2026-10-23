"""Read-only presentation contracts; no app/account/database/provider access."""
import html
import re
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from newsflow.gui.routes import kst

TEMPLATES = Path(__file__).resolve().parents[1] / 'src/newsflow/gui/templates'


def render(template, **context):
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    env.filters['kst'] = kst
    env.globals['csrf_field'] = lambda: Markup('')
    macro = (TEMPLATES / 'base.html').read_text(encoding='utf-8').split('<!doctype html>')[0]
    return env.from_string(macro + '{% include "' + template + '" %}').render(**context)


@pytest.mark.parametrize('changes,label', [
    ({'draft_id': 7}, '대본 검토하기'),
    ({'draft_id': 7, 'render_job_id': 9}, '완성 영상 확인하기'),
    ({'analysis_run_id': 4}, '분석 결과 확인하기'),
    ({'status': 'failed', 'draft_id': 7, 'render_job_id': 9}, '중단 원인 확인하기'),
    ({'status': 'unknown', 'analysis_run_id': 4}, '중단 원인 확인하기'),
    ({'status': 'interrupted'}, '중단 원인 확인하기'),
    ({'status': 'completed', 'render_job_id': 9}, '완성 영상 보기'),
    ({'status': 'running', 'render_job_id': 9}, '제작 진행 확인하기'),
    ({'status': 'queued'}, '제작 준비 확인하기'),
    ({'kind': 'collection', 'status_label': '추천 뉴스 검토'}, '추천 뉴스 확인하기'),
    ({'kind': 'collection'}, '수집 뉴스 확인하기'),
    ({'kind': 'collection', 'status': 'running'}, '평가 진행 확인하기'),
    ({'next_action': '영상으로 만들 뉴스 선택'}, '영상으로 만들 뉴스 선택'),
])
def test_action_uses_actual_task_state_and_preserves_existing_target(changes, label):
    focus = {'kind': 'manual', 'status': 'waiting_review', 'status_label': '확인 필요',
             'title': '합성 작업', 'stage': '검토', 'workspace_href': '/ai?draft_id=7',
             'href': '/ai', **changes}
    result = render('workflow_card.html', dashboard={'workflow': {'steps': []},
                    'focus': focus, 'excerpt': ''}, image_posts_available=True)
    action = re.search(r'<a[^>]*data-workflow-next-action[^>]*>(.*?)</a>', result, re.DOTALL)
    assert action and html.unescape(re.sub('<[^>]+>', '', action[1])).strip() == label
    assert 'href="/ai?draft_id=7"' in action[0]
    assert 'href="#production-title"' in result
    assert '작업실 열기' not in result


@pytest.mark.parametrize('kind,updates,href', [
    ('news', {}, '/simple-settings#selected-ai'),
    ('news', {'reason_label': 'RSS 확인 필요'}, '/sources'),
    ('news', {'reason_label': 'RSS 출처 없음'}, '/sources'),
    ('voice', {}, '/simple-settings#selected-voice'),
    ('voice', {'voice_short': 'ElevenLabs'}, '/video/tts'),
    ('video', {}, '/simple-settings#selected-video'),
    ('video', {'video': 'higgsfield'}, '/video-ai-settings'),
])
def test_notice_links_to_related_settings_before_selection(kind, updates, href):
    detail = '저장된 준비 조건을 확인하세요. <비밀값 없음>'
    picker = {'method_label': 'Claude API + RSS', 'method_short': 'Claude API', 'method': 'claude_api|rss',
              'methods': {'claude_api|rss': 'Claude API + RSS'}, 'voice_label': '합성 음성',
              'voice_short': 'Windows', 'voice': 'fixture', 'voices': [], 'video_label': 'FFmpeg',
              'video': 'off', 'saved': False, 'return_to': '/', 'lights': {}, **updates}
    for name in ('news', 'voice', 'video'):
        picker['lights'][name] = {'color': 'yellow', 'label': updates.get('reason_label', '미확인'), 'detail': detail, 'checked_at': None}
    result = render('production_picker.html', production_picker=picker)
    section = re.search(r'<details[^>]*data-production-kind="' + kind + r'".*?</details>', result, re.DOTALL)[0]
    notice = re.search(r'<div[^>]*data-selection-status.*?</div>', section, re.DOTALL)[0]
    assert '확인이 필요해요' in notice and html.escape(detail) in notice
    assert f'data-readiness-settings href="{href}"' in notice
    assert section.index('data-readiness-settings') < section.index('<select')
    assert section.count('data-selection-status') == 1
    assert '실시간 검사 아님' in notice
