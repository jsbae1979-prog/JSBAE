"""Method B: synthetic A/B sources and Fake wire responses; never real AI quality evidence."""

import json
from copy import deepcopy

import pytest
from sqlalchemy import select
from test_claude_analysis_response import analyze, latest
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import sessions as sessions  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414
from test_claude_analysis_response import store as store  # noqa: PLC0414

from newsflow.db.models import AIUsage, APIRequestReservation, ContentDraft, IntelligenceRun, NewsArticle
from newsflow.intelligence.api_providers import (
    AnthropicProvider,
    _analysis_output_schema,
    _script_output_schema,
)
from newsflow.intelligence.curation import script_json
from newsflow.intelligence.korean import speech_plan
from newsflow.intelligence.news_usage import (
    api_news_contract,
    explainer_findings,
    validate_api_news_script,
    validate_explainer_analysis,
)
from newsflow.intelligence.provider import (
    ANALYSIS_INSTRUCTION_V1,
    SCRIPT_INSTRUCTION_V1,
    OfflineProvider,
    OpenAIProvider,
    Options,
    ProviderOutputLimitError,
    prompt_instruction,
    prompt_options,
    prompt_version,
)
from newsflow.intelligence.schema import Analysis, Script
from newsflow.intelligence.service import IntelligenceError


def evidence():
    # These are artificial fixtures, not verified reporting or investment advice.
    return {'articles': [
        {'id': 1, 'title': '[합성] 한국은행 기준금리 3.00% 동결',
         'summary': '2026-10-22 합성 자료입니다. 한국은행이 기준금리를 3.00%로 유지했습니다. 후속 일정은 제공되지 않았습니다.',
         'sources': [{'url': 'https://example.com/synthetic-rate', 'publisher': '합성 A'}]},
        {'id': 2, 'title': '[합성] 리치먼드 어린이집 총기 안전 사건',
         'summary': '합성 자료입니다. 리치먼드 어린이집에서 2세 아동과 장전된 총기 관련 사건이 보도됐습니다. 상세 경위는 미확인입니다.',
         'sources': [{'url': 'https://example.org/synthetic-safety', 'publisher': '합성 B'}]},
    ], 'script_prompt_version': 'v2', 'script_method': 'api_grounded_v2', 'news_usage': 'STANDARD'}


def interpretive(duration=30, quick=False, next_event=''):
    hook = '기준금리 동결이면 내 이자도 그대로일까요?'
    closing = '계약을 함께 보는 분에게 이 확인 방법을 공유해 주세요.'
    narrations = [
        hook + ' 합성 자료는 한국은행이 기준금리를 3.00%로 유지했다고 전합니다.',
        '기준금리 결정과 개인에게 적용되는 계약 금리는 같은 값이 아닙니다. 이번 소식을 내 이자 부담에 곧바로 대입하기보다 계약 조건과 연결해 이해할 필요가 있습니다.',
        '같은 결정을 보더라도 내가 이용하는 계약의 조건을 함께 보는 관점이 필요합니다. 뉴스의 결정과 자신의 계약을 구분해 이해해 보세요.',
        '지금은 이용 중인 계약의 금리 유형과 변경 조건을 확인해 보세요. ' + closing,
    ]
    roles, seconds = ['fact', 'meaning', 'meaning', 'action'], [6, 8, 8, 8]
    if quick:
        narrations = [narrations[0], narrations[1], narrations[-1]]
        roles, seconds = ['fact', 'meaning', 'action'], [6, 12, 12]
    elif next_event:
        narrations = [narrations[0], narrations[1], narrations[-1].replace(closing, ''), next_event + ' ' + closing]
        roles = ['fact', 'meaning', 'action', 'next']
    seconds = [value * duration // 30 for value in seconds]
    seconds[-1] += duration - sum(seconds)
    return {'analysis': {'misconception': '기준금리와 내 계약 금리가 같다는 오해',
                         'viewer_relevance': '자신의 이자 조건을 이해하는 관점',
                         'viewer_action': '이용 중인 계약의 금리 유형과 변경 조건 확인',
                         'next_event': next_event, 'ad_risk': 'low'},
            'title': '기준금리와 내 계약을 구분하는 방법', 'hook': hook,
            'summary': '합성 자료에 대한 시청자 관점 해석이며 계약의 조건을 확인하는 내용입니다.',
            'scenes': [{'seconds': sec, 'role': role, 'narration': narration,
                        'caption': '합성 예시 · ' + caption, 'material': '직접 제작한 계약 점검 아이콘'}
                       for sec, role, narration, caption in zip(seconds, roles, narrations,
                           ['기준금리 결정', '시청자 관점', '계약과 결정 구분', '확인할 일'][:len(roles)])],
            'closing': closing}


@pytest.mark.parametrize('version', ['v1', 'v2'])
def test_legacy_json_round_trip_remains_exact(version, monkeypatch):
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', version)
    old = OfflineProvider().complete(evidence(), 30, Options())
    assert 'analysis' not in old and all('role' not in s for s in old['scenes'])
    assert Script.model_validate(old).model_dump() == old
    value = {'overview': '합성 자료', 'comparisons': [{'article_ids': [1], 'reason': '검토', 'uncertainties': '미확인'}],
             'recommended_article_id': 1, 'selection_reason': '검토'}
    assert Analysis.model_validate(value).model_dump() == value


def test_optional_values_soft_normalize_and_safe_log(caplog):
    value = interpretive()
    value['analysis'].update(misconception='가'*151, viewer_relevance=None, viewer_action=['PRIVATE_INPUT'],
                             next_event='나'*200, ad_risk='PRIVATE_INPUT')
    value['scenes'][0]['role'] = 'intro-PRIVATE_INPUT'
    result = Script.model_validate(value).model_dump()
    assert result['analysis']['misconception'] == '가'*150
    assert result['analysis']['next_event'] == '나'*150
    assert result['analysis']['viewer_relevance'] == result['analysis']['viewer_action'] == ''
    assert result['analysis']['ad_risk'] is None and 'role' not in result['scenes'][0]
    assert 'PRIVATE_INPUT' not in caplog.text and 'normalized' in caplog.text
    value['analysis'] = ['PRIVATE_INPUT']
    assert 'analysis' not in Script.model_validate(value).model_dump()


def test_analysis_optional_bounds_and_risk_keep_legacy_core_strict():
    value = {'overview': '합성 비교', 'comparisons': [{'article_ids': [1], 'reason': '검토', 'uncertainties': '미확인',
              'viewer_relevance': ' HIGH ', 'ad_risk': 'bad', 'viewer_angle': '가'*301}],
             'recommended_angle': '나'*301}
    result = Analysis.model_validate(value).model_dump()
    assert result['comparisons'][0]['viewer_relevance'] == 'high'
    assert 'ad_risk' not in result['comparisons'][0]
    assert len(result['comparisons'][0]['viewer_angle']) == len(result['recommended_angle']) == 300
    value['comparisons'][0]['article_ids'] = ['1']
    with pytest.raises(ValueError):
        Analysis.model_validate(value)


@pytest.mark.parametrize('quick,next_event', [(True, ''), (False, ''), (False, '다음 결정의 쟁점은 제공된 후속 자료에서 확인합니다.')])
@pytest.mark.parametrize('duration', [30, 45, 60])
def test_roles_timing_grounding_and_no_added_narration(quick, next_event, duration):
    source = evidence()
    source['news_usage'] = 'QUICK' if quick else 'STANDARD'
    value = interpretive(duration, quick, next_event)
    validate_api_news_script(value, source)
    assert explainer_findings(value, source) == []
    contract = api_news_contract(source, source['news_usage'], duration)
    roles = [s['role'] for s in value['scenes']]
    assert roles in contract['role_orders'] and len(roles) == (3 if quick else 4)
    assert sum(s['seconds'] for s in value['scenes']) == duration
    # Planning fields and roles do not alter the existing spoken-unit estimate.
    without = deepcopy(value)
    without.pop('analysis')
    for scene in without['scenes']:
        scene.pop('role')
    assert speech_plan(value, duration) == speech_plan(without, duration)
    v1 = api_news_contract(source, source['news_usage'], duration, version='v1')
    assert contract['speech_estimate'] == v1['speech_estimate']
    assert contract['narration_spoken_units_target'] == v1['narration_spoken_units_target']
    assert source['articles'][0].get('published_at') is None


def test_composition_is_advisory_but_high_risk_needs_review():
    value, source = interpretive(), evidence()
    value['scenes'][0]['role'] = 'action'
    value['scenes'][1]['role'] = 'fact'
    value['scenes'][1]['seconds'] = 29
    value['closing'] = '원문을 확인해 주세요.'
    notes = explainer_findings(value, source)
    assert {n['code'] for n in notes} == {'explainer_roles', 'explainer_balance', 'explainer_closing',
                                       'explainer_spoken_closing', 'explainer_synthetic_context'}
    assert all(n['level'] == 'info' and n['kind'] == 'composition_warning'
               for n in notes if n['code'] in {'explainer_roles', 'explainer_balance', 'explainer_closing'})
    value['analysis']['ad_risk'] = 'high'
    assert explainer_findings(value, source)[-1]['level'] == 'warning'
    assert explainer_findings(value, {'script_method': 'api_grounded_v1'}) == []


@pytest.mark.parametrize('field', ['misconception', 'viewer_relevance', 'viewer_action', 'next_event'])
@pytest.mark.parametrize('claim', ['새 금리는 9.99%입니다.', '“자료에 없는 직접 발언입니다”'])
def test_unsubstantiated_planning_claim_cannot_hide_after_trim(field, claim):
    value = interpretive()
    value['analysis'][field] = '가'*150 + claim
    with pytest.raises(ValueError):
        validate_api_news_script(value, evidence())


def test_analysis_claim_checks_are_candidate_bound_and_exclude_rank_score():
    output = {'comparisons': [{'article_ids': [1], 'viewer_angle': '3.00%와 계약의 차이를 확인합니다.', 'score': 95},
                             {'article_ids': [2], 'viewer_angle': '가정의 안전 확인 관점'}],
              'recommended_article_id': 1, 'recommended_angle': '내 계약의 조건을 확인합니다.'}
    validate_explainer_analysis(output, evidence())
    output['comparisons'][1]['viewer_angle'] = '가'*300 + '3.00%'
    with pytest.raises(ValueError):
        validate_explainer_analysis(output, evidence())


@pytest.mark.parametrize('version', ['v1', 'v2'])
@pytest.mark.parametrize('kind', ['script', 'analysis'])
@pytest.mark.parametrize('provider', ['openai', 'claude_api'])
def test_actual_adapter_fake_wire_gets_matching_version_and_one_allowance(version, kind, provider, monkeypatch):
    source = evidence()
    source['script_prompt_version'] = version
    source['script_method'] = 'api_grounded_' + version
    calls = []
    options = Options(model='claude-sonnet-4-6' if provider == 'claude_api' else 'gpt-4.1-mini')
    if provider == 'claude_api':
        adapter = AnthropicProvider(lambda: 'synthetic-wire-key')
        response = {'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': '{}'}],
                    'usage': {'input_tokens': 100, 'output_tokens': 50}}
    else:
        adapter = OpenAIProvider(lambda: 'synthetic-wire-key', allow_retry=False)
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 50}}

    def send(request, *args):
        calls.append(json.loads(request.data))
        return json.dumps(response).encode()

    monkeypatch.setattr(adapter, '_open', send)
    if kind == 'script':
        adapter.complete(source, 30, options)
    else:
        adapter.analyze(source, options)
    assert len(calls) == 1 and not adapter.last_retried
    body = calls[0]
    system = body['system'] if provider == 'claude_api' else body['messages'][0]['content']
    assert system.startswith(prompt_instruction(kind, version=version))
    allowance = (600 if kind == 'script' else 400) if version == 'v2' else 0
    assert body['max_tokens'] == 1800 + allowance
    if provider == 'claude_api':
        schema = body['output_config']['format']['schema']
        assert ('analysis' in schema['properties']) == (kind == 'script' and version == 'v2')
        assert ('recommended_angle' in schema['properties']) == (kind == 'analysis' and version == 'v2')
        if kind == 'script' and version == 'v2':
            assert schema['$defs']['ScriptAnalysis']['additionalProperties'] is False
    else:
        assert body['response_format'] == {'type': 'json_object'}  # existing API compatibility
    assert adapter.last_usage['completion_tokens'] == 50


def test_version_default_rollback_and_existing_ceiling(monkeypatch):
    monkeypatch.delenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', raising=False)
    assert prompt_version() == 'v2'
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', 'v1')
    assert prompt_instruction('script') == SCRIPT_INSTRUCTION_V1
    assert prompt_instruction('analysis') == ANALYSIS_INSTRUCTION_V1
    assert prompt_version({'script_method': 'api_grounded_v2'}) == 'v2'
    assert prompt_options(Options(model='claude-sonnet-4-6', max_tokens=100_000), 'script', 'v2').max_tokens == 100_000
    assert prompt_options(Options(max_tokens=8990), 'analysis', 'v2').max_tokens == 9000
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', 'invalid')
    with pytest.raises(ValueError):
        prompt_version()


def test_v2_export_keeps_all_interpretation_scenes_once():
    value = interpretive()
    exported = script_json(value, 95)['script']
    combined = ' '.join(exported.values())
    assert combined.count(value['hook']) == combined.count(value['closing']) == 1
    assert all(scene['narration'] in combined for scene in value['scenes'][1:-1])
    assert 'misconception' not in combined and 'viewer_action' not in combined


def test_fake_ab_selection_saved_draft_edit_and_usage_version(state, monkeypatch):
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', 'v2')
    a, b = deepcopy(evidence()['articles'])
    with state['sessions'].begin() as session:
        article = session.get(NewsArticle, state['article_id'])
        article.title, article.summary = a['title'], a['summary']
        other = NewsArticle(source_id=article.source_id, title=b['title'], summary=b['summary'],
                            publisher='합성 B', url=b['sources'][0]['url'], canonical_url=b['sources'][0]['url'])
        session.add(other)
        session.flush()
        b_id = other.id
    state['payload'].update(comparisons=[
        {'article_ids': [state['article_id']], 'reason': '일상 계약을 해석할 수 있는 주제', 'uncertainties': '후속 일정 없음',
         'viewer_relevance': 'high', 'ad_risk': 'low', 'viewer_angle': '기준금리와 내 계약의 차이 확인'},
        {'article_ids': [b_id], 'reason': '안전 점검 관점', 'uncertainties': '상세 경위 미확인',
         'viewer_relevance': 'medium', 'ad_risk': 'high', 'viewer_angle': '비선정적 안전 점검 관점'}],
        recommended_angle='내 계약과 뉴스의 결정을 구분해 확인', recommended_article_id=state['article_id'])
    state['document']['content'][0]['text'] = json.dumps(state['payload'])
    limits = []
    reserve = state['budget'].reserve

    def capture_reserve(**kwargs):
        limits.append(kwargs['max_output_tokens'])
        return reserve(**kwargs)

    monkeypatch.setattr(state['budget'], 'reserve', capture_reserve)
    analysis_id = state['service'].analyze([state['article_id'], b_id], 'claude_api', True,
                                         Options(model='claude-sonnet-4-6'), news_usage='STANDARD')
    value = interpretive()
    state['document']['content'][0]['text'] = json.dumps(value)
    draft_id = state['service'].generate(analysis_id, 30, 'claude_api', True,
                                         Options(model='claude-sonnet-4-6'), article_ids=[state['article_id']])
    with state['sessions']() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.review_status == 'review_required'
        assert draft.content == value and draft.sources['script_method'] == 'api_grounded_v2'
        assert len(draft.sources['articles']) == 1
        analysis = session.get(IntelligenceRun, analysis_id)
        assert analysis.result['recommended_article_id'] == state['article_id']
        assert analysis.result['comparisons'][1]['ad_risk'] == 'high'
        assert analysis.options['max_tokens'] == 2200
        script_run = session.get(IntelligenceRun, draft.run_id)
        assert script_run.options['max_tokens'] == 2400
        assert script_run.options['output_token_allowance'] == 600
        assert all(run.options['script_prompt_version'] == 'v2' for run in [analysis, script_run])
        reservations = list(session.scalars(select(APIRequestReservation)))
        assert len(reservations) == 2 and all(r.status == 'success' and r.test_only for r in reservations)
        assert all(r.usage['completion_tokens'] == 721 for r in reservations)
        usages = list(session.scalars(select(AIUsage)))
        assert len(usages) == 2
        assert all(u.completion_tokens == 721 and u.prompt_tokens == 1098 for u in usages)
        assert {u.run_id for u in usages} == {analysis_id, script_run.id}
    assert limits == [2200, 2400]  # the budget and wire see the same allowance, only once
    # Legacy form omits additive metadata; saving must not discard it.
    edited = deepcopy(value)
    edited.pop('analysis')
    for scene in edited['scenes']:
        scene.pop('role')
    edited['scenes'][1]['caption'] = '계약을 구분해 확인'
    state['service'].edit(draft_id, 1, edited)
    with state['sessions']() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.content['analysis'] == value['analysis']
        assert [s['role'] for s in draft.content['scenes']] == ['fact', 'meaning', 'meaning', 'action']
        assert draft.review_status == 'review_required' and draft.revision == 2
    assert [c['max_tokens'] for c in state['calls']] == [2200, 2400]


def test_fake_high_risk_script_is_saved_with_non_graphic_visuals_and_review_warning(state):
    source = evidence()['articles'][1]
    with state['sessions'].begin() as session:
        article = session.get(NewsArticle, state['article_id'])
        article.title, article.summary = source['title'], source['summary']
    state['payload']['comparisons'][0].update(ad_risk='high', viewer_relevance='medium',
                                             viewer_angle='안전 점검을 해석하는 관점')
    state['document']['content'][0]['text'] = json.dumps(state['payload'])
    analysis_id = analyze(state)
    value = interpretive()
    value.update(title='어린이집 안전 점검 관점', hook='익숙한 공간이면 안전 확인은 충분할까요?',
                 summary='사건 경위는 미확인인 합성 자료이며 일상의 안전 점검 관점을 설명합니다.',
                 closing='함께 돌보는 분과 안전 확인 방법을 공유해 주세요.')
    value['analysis'].update(misconception='익숙한 공간이면 안전하다는 오해',
                             viewer_relevance='아이를 돌보는 환경의 안전 확인',
                             viewer_action='이용 중인 시설의 위험 물품 보관 안내 확인', ad_risk='high')
    narrations = [value['hook'] + ' 합성 자료는 리치먼드 어린이집의 총기 관련 사건을 전합니다.',
                  '상세 경위는 확인되지 않았습니다. 낯익은 공간의 안전을 당연하게 여기지 않는 관점이 필요합니다.',
                  '이 사건의 미확인 경위를 확대하기보다 아이를 돌보는 환경의 점검 관점으로 나누어 이해해 보세요.',
                  '이용 중인 시설의 위험 물품 보관 안내를 확인해 보세요. ' + value['closing']]
    for scene, text in zip(value['scenes'], narrations):
        scene.update(narration=text, caption='안전 점검 관점', material='비선정적 실루엣·안전 아이콘·텍스트')
    state['document']['content'][0]['text'] = json.dumps(value)
    identifier = state['service'].generate(analysis_id, 30, 'claude_api', True, Options(model='claude-sonnet-4-6'))
    with state['sessions']() as session:
        draft = session.get(ContentDraft, identifier)
        assert draft.review_status == 'review_required'
        assert any(n['code'] == 'explainer_ad_risk' and n['level'] == 'warning' for n in draft.review_notes)
        assert all('비선정적' in s['material'] for s in draft.content['scenes'])
    # Fake response proves storage/review behavior only, not real model risk classification.
    assert len(state['calls']) == 2


def test_truncated_claude_and_openai_responses_are_recorded_without_replay(state, monkeypatch):
    state['document']['stop_reason'] = 'max_tokens'
    with pytest.raises(IntelligenceError):
        analyze(state)
    run, reservation = latest(state)
    assert run.result['output_limit'] == {'stop_reason': 'max_tokens'}
    assert reservation.status == 'failed' and len(state['calls']) == 1
    adapter = OpenAIProvider(lambda: 'synthetic-wire-key', allow_retry=False)
    calls = []

    def send(*args):
        calls.append(1)
        return json.dumps({'usage': {'prompt_tokens': 10, 'completion_tokens': 20},
                           'choices': [{'finish_reason': 'length', 'message': {'content': 'PRIVATE_BODY'}}]}).encode()

    monkeypatch.setattr(adapter, '_open', send)
    with pytest.raises(ProviderOutputLimitError) as caught:
        adapter.complete(evidence(), 30, Options())
    assert 'PRIVATE_BODY' not in str(caught.value) and len(calls) == 1
    assert not adapter.last_retried and adapter.last_usage['completion_tokens'] == 20


def test_raw_planning_secret_is_blocked_before_optional_trim(state):
    analysis_id = analyze(state)
    value = OfflineProvider().complete(evidence(), 30, Options())
    value['analysis'] = {'misconception': '가'*150 + state['store'].key()}
    state['document']['content'][0]['text'] = json.dumps(value)
    state['calls'].clear()
    with pytest.raises(IntelligenceError):
        state['service'].generate(analysis_id, 30, 'claude_api', True, Options(model='claude-sonnet-4-6'))
    run, _ = latest(state)
    assert state['store'].key() not in json.dumps(run.result) + run.message
    assert len(state['calls']) == 1
    with state['sessions']() as session:
        assert list(session.scalars(select(ContentDraft))) == []


def test_both_wire_schemas_keep_optional_fields_additive():
    assert 'role' not in _script_output_schema('v1')['$defs']['Scene']['properties']
    assert 'role' in _script_output_schema('v2')['$defs']['Scene']['properties']
    assert 'recommended_angle' not in _analysis_output_schema('v1')['properties']
    assert 'recommended_angle' in _analysis_output_schema('v2')['properties']

