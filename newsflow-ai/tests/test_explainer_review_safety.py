"""Post-comparison safeguards: synthetic DB, Fake wire and pure timing estimates only."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select
from test_claude_analysis_response import analyze
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import sessions as sessions  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414
from test_claude_analysis_response import store as store  # noqa: PLC0414
from test_explainer_prompts import evidence, interpretive

from newsflow.db.models import APIRequestReservation, ContentDraft, IntelligenceRun, NewsArticle
from newsflow.intelligence.korean import speech_plan, speech_seconds
from newsflow.intelligence.news_usage import api_news_contract, explainer_findings
from newsflow.intelligence.provider import Options
from newsflow.intelligence.service import IntelligenceError
from newsflow.video.production_policy import check_draft


def compact_script():
    value = interpretive()
    value['hook'] = '내 계약도 같을까요?'
    value['closing'] = '함께 계약을 보는 분과 공유하세요.'
    narrations = [
        value['hook'] + ' 합성 자료는 금리 동결을 다룹니다.',
        '기준금리와 계약 금리는 다르므로 내 계약의 조건을 따로 살펴보는 관점이 필요합니다.',
        '금리 소식만으로 내 이자를 단정하지 말고 계약마다 적용 조건을 나눠 살펴보세요.',
        '은행 앱에서 금리 유형과 변경 조건을 확인하세요. ' + value['closing'],
    ]
    for scene, narration, seconds in zip(value['scenes'], narrations, [6, 8, 8, 8]):
        scene.update(narration=narration, seconds=seconds)
    return value


def codes(value, source=None):
    return {n['code'] for n in explainer_findings(value, source or evidence())}


@pytest.mark.parametrize('duration', [30, 45, 60])
@pytest.mark.parametrize('mode', ['QUICK', 'STANDARD'])
@pytest.mark.parametrize('rate', [-5, 0, 5])
def test_scene_unit_ceilings_fit_existing_timing_without_changing_voice(duration, mode, rate):
    contract = api_news_contract(evidence(), mode, duration, speech={'rate': rate, 'pause_ms': 250})
    budgets = contract['scene_narration_budgets']
    assert sum(b['seconds'] for b in budgets) == duration
    assert len(budgets) == (3 if mode == 'QUICK' else 4)
    assert sum(b['maximum_spoken_units'] for b in budgets) <= contract['narration_spoken_units_target']['maximum']
    # A worst-budget Korean narration, with the permitted sentence pauses, fits
    # the existing estimator. No TTS, clipping, speed override or padding occurs.
    for budget in budgets:
        units = budget['maximum_spoken_units']
        text = ('가' * (units // 2) + '. ' + '나' * (units - units // 2) + '.'
                if budget['maximum_sentences'] == 2 else '가' * units + '.')
        assert speech_seconds(text, rate=rate) <= budget['seconds']
    assert contract['speech_estimate']['rate'] == rate
    assert 'scene_narration_budgets' not in api_news_contract(evidence(), mode, duration, version='v1')


@pytest.mark.parametrize('fault,code', [
    ('hook', 'explainer_spoken_hook'), ('duplicate_hook', 'explainer_spoken_hook'),
    ('closing', 'explainer_spoken_closing'), ('duplicate_closing', 'explainer_spoken_closing'),
    ('synthetic', 'explainer_synthetic_context'), ('outlook', 'explainer_outlook_without_source'),
])
def test_observable_broadcast_mismatches_require_review_without_rewriting(fault, code, caplog):
    value = compact_script()
    assert codes(value) == set() and speech_plan(value, 30)['fits']
    if fault == 'hook':
        value['hook'] = '다른 도입 문장입니다.'
    elif fault == 'duplicate_hook':
        value['scenes'][1]['narration'] += ' ' + value['hook']
    elif fault == 'closing':
        value['closing'] = '다른 마무리 문장입니다.'
    elif fault == 'duplicate_closing':
        value['scenes'][1]['narration'] += ' ' + value['closing']
    elif fault == 'synthetic':
        value['scenes'][0]['caption'] = '금리 동결 소식'
    else:
        value['summary'] = '향후 금리 인하 가능성이 열려 있습니다.'
    before = deepcopy(value)
    assert code in codes(value)
    note = next(n for n in explainer_findings(value, evidence()) if n['code'] == code)
    assert note['level'] == 'warning' and 'kind' not in note
    assert value == before
    assert value['summary'] not in caplog.text
    assert explainer_findings(value, {'script_method': 'api_grounded_v1'}) == []


def test_whitespace_does_not_change_spoken_boundaries_or_add_planning_text():
    value = compact_script()
    value['hook'] = value['hook'].replace(' ', '\n')
    value['closing'] = value['closing'].replace(' ', '  ')
    value['analysis']['misconception'] = '합성 자료의 분석 메모'
    value['scenes'][1]['review_notes'] = ['향후 금리 인상 가능성을 추가하지 마세요.']
    assert codes(value) == set()


@pytest.mark.parametrize('source_summary', [
    '향후 금리 인하 가능성이 언급됐다는 제공 자료입니다.',
    '향후 금리 방향은 확인되지 않았습니다.',
])
def test_supplied_outlook_or_explicit_unknown_does_not_assert_new_fact_validation(source_summary):
    source, value = evidence(), compact_script()
    if '가능성' in source_summary:
        source['articles'][0]['summary'] += ' ' + source_summary
    value['summary'] = source_summary
    assert 'explainer_outlook_without_source' not in codes(value, source)
    assert source.get('facts_verified') is None


@pytest.mark.parametrize('title,summary', [
    ('가상현실과 음성 합성 기술', '가상현실 기기와 음성 합성 기술을 소개하는 주제 자료입니다.'),
    ('합성 자료 유포 논란', '연구진이 합성 자료의 유포 문제를 설명한 주제 자료입니다.'),
])
def test_synthetic_media_topic_is_not_itself_a_synthetic_news_fixture(title, summary):
    source = evidence()
    source['articles'] = [{'id': 1, 'title': title, 'summary': summary}]
    value = compact_script()
    value['scenes'][0].update(narration=value['hook'] + ' 기술을 살펴봅니다.', caption='기술 소개')
    assert 'explainer_synthetic_context' not in codes(value, source)


@pytest.mark.parametrize('fault,code', [('hook', 'explainer_spoken_hook'),
                                     ('closing', 'explainer_spoken_closing'),
                                     ('synthetic', 'explainer_synthetic_context'),
                                     ('outlook', 'explainer_outlook_without_source')])
def test_fake_generation_stores_review_and_edit_fixes_it_without_another_call(state, tmp_path, fault, code):
    source = evidence()['articles'][0]
    with state['sessions'].begin() as session:
        article = session.get(NewsArticle, state['article_id'])
        article.title, article.summary = source['title'], source['summary']
    analysis_id = analyze(state)
    good, value = compact_script(), compact_script()
    if fault == 'hook':
        value['hook'] = '다른 도입 문장입니다.'
    elif fault == 'closing':
        value['closing'] = '다른 마무리 문장입니다.'
    elif fault == 'synthetic':
        value['scenes'][0]['caption'] = '금리 동결 소식'
    else:
        value['summary'] = '향후 금리 인하 가능성이 열려 있습니다.'
    state['document']['content'][0]['text'] = json.dumps(value)
    draft_id = state['service'].generate(analysis_id, 30, 'claude_api', True,
                                         Options(model='claude-sonnet-4-6'))
    with state['sessions']() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.content == value and draft.review_status == 'review_required'
        assert any(n['code'] == code and n['level'] == 'warning' for n in draft.review_notes)
        original = deepcopy(session.get(IntelligenceRun, analysis_id).result)
        # This formerly valid 30-second script is held by the new safety finding,
        # not a timing violation. It remains available for human editing.
        assert speech_plan(draft.content, 30)['fits']
        with pytest.raises(IntelligenceError, match='자동 검사 경고'):
            check_draft(state['sessions'], draft, {'speech': {'rate': 0, 'pause_ms': 250}}, tmp_path)
    state['service'].edit(draft_id, 1, good)
    with state['sessions']() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.content == good and draft.revision == 2 and draft.review_status == 'review_required'
        assert code not in {n['code'] for n in draft.review_notes}
        check_draft(state['sessions'], draft, {'speech': {'rate': 0, 'pause_ms': 250}}, tmp_path)
        assert session.get(IntelligenceRun, analysis_id).result == original
        reservations = list(session.scalars(select(APIRequestReservation)))
        assert len(reservations) == 2 and all(r.status == 'success' and r.test_only for r in reservations)
    assert len(state['calls']) == 2 and not state['adapter'].last_retried
    request_source = json.loads(state['calls'][-1]['messages'][0]['content'])['evidence']
    assert request_source['news_usage_contract']['scene_narration_budgets']
