"""Same-voice completed Fake WAV guidance; no user files, keys, calls or playback."""

import base64
import json
import os
import shutil
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_api_news_pipeline import api_pipeline as api_pipeline  # noqa: PLC0414
from test_api_news_pipeline import settled, start
from test_claude_analysis_response import analyze
from test_claude_analysis_response import no_external_calls as no_external_calls  # noqa: PLC0414
from test_claude_analysis_response import sessions as sessions  # noqa: PLC0414
from test_claude_analysis_response import state as state  # noqa: PLC0414
from test_claude_analysis_response import store as store  # noqa: PLC0414
from test_comparison_approval import comparison as comparison  # noqa: PLC0414
from test_explainer_prompts import evidence
from test_explainer_review_safety import compact_script
from test_voice_engines import Transport, config

from newsflow.db.models import AppSetting, ContentDraft, IntelligenceRun, NewsArticle
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.api_settings import APISettingsError
from newsflow.intelligence.korean import speech_plan, speech_seconds
from newsflow.intelligence.news_usage import api_news_contract
from newsflow.intelligence.provider import OpenAIProvider, Options
from newsflow.intelligence.service import IntelligenceError, IntelligenceService
from newsflow.shortform import Shortform
from newsflow.video.elevenlabs_tts import ElevenLabsKeys, ElevenLabsTTS, save_settings
from newsflow.video.engine import RenderError, fit_api_timings
from newsflow.video.narration_planning import load_profile, planning, selected_voice, validate_voice
from newsflow.video.production_policy import check_draft
from newsflow.video.tts import TTSError

SPEECH = {'rate': 0, 'pause_ms': 250}
VOICE = {'provider': 'elevenlabs', 'voice_id': 'syntheticVoice', 'model': 'eleven_multilingual_v2'}
TEXTS = ['합성 자료의 뜻을 살펴보는 참고 문장입니다.',
         '제공된 제목과 요약의 조건을 나누어 설명하는 예시 문장입니다.',
         '뉴스의 시점을 단정하지 않고 확인할 수 있는 자료의 범위를 구분합니다.',
         '자료에 없는 숫자와 발언을 덧붙이지 않고 제공된 맥락을 살펴보세요.']


@pytest.fixture
def recorded(tmp_path):
    class Keys:
        path = tmp_path / ElevenLabsKeys.FILE

        def key(self):
            return 'synthetic-not-an-account-key-12345'

    Keys.path.write_bytes(b'synthetic-encrypted-file-identity-only')
    calls = []
    provider = None

    def transport(method, path, payload=None):
        calls.append((method, path))
        if method == 'GET':
            return Transport().info
        text = payload['text']
        seconds = speech_seconds(text) * .85
        frames = round(seconds * 24000)
        provider.reported_credits = len(text)
        return {'audio_base64': base64.b64encode(b'\xe8\x03' * frames).decode(),
                'alignment': {'characters': list(text),
                              'character_start_times_seconds': [i * frames / 24000 / len(text) for i in range(len(text))],
                              'character_end_times_seconds': [(i+1) * frames / 24000 / len(text) for i in range(len(text))]}}

    provider = ElevenLabsTTS(tmp_path, config(), consent=True, keys=Keys(), transport=transport)
    for i, text in enumerate(TEXTS):
        try:
            provider.synthesize_timed(text, tmp_path/f'{i}.wav', 'elevenlabs', 30)
        except TTSError as exc:
            # This fixture contains synthetic data only; expose its local I/O cause, never live diagnostics.
            cause = exc.__context__
            raise AssertionError(f'Synthetic WAV fixture: {type(cause).__name__}: {cause}') from exc
    return {'root': tmp_path, 'provider': provider, 'calls': calls, 'keys': Keys(),
            'ledger': tmp_path/'tts-elevenlabs/ledger.json'}


def profile(value, **changes):
    return load_profile(value['root'], changes.get('voice', VOICE), changes.get('speech', SPEECH),
                        sample_checksums=changes.get('samples'))


def longer_script():
    value = compact_script()
    value['scenes'][0]['narration'] = value['scenes'][0]['narration'].replace('합성 자료는', '제공된 합성 예시 자료는')
    value['scenes'][1]['narration'] = value['scenes'][1]['narration'].replace(
        '내 계약의 조건을 따로', '내 계약의 구체적인 적용 조건을 각각 따로')
    value['scenes'][2]['narration'] = value['scenes'][2]['narration'].replace(
        '적용 조건을 나눠', '구체적인 금리 적용 조건을 서로 나눠')
    value['scenes'][3]['narration'] = value['scenes'][3]['narration'].replace(
        '은행 앱에서 금리 유형과 변경 조건을', '해당 은행 앱에서 금리 유형부터 적용·변경 조건을')
    return value


def test_read_only_guidance_uses_saved_matching_text_wav_usage_without_decrypt_or_new_call(recorded, monkeypatch):
    v = recorded
    before = v['ledger'].read_bytes()
    calls = len(v['calls'])
    monkeypatch.setattr(ElevenLabsKeys, 'key', lambda *_: pytest.fail('No real key access while planning'))
    result = profile(v)
    assert result['sample_count'] == 4 and result['ratio'] == pytest.approx(.85, abs=.00001)
    assert result['quality'] == 'NOT VERIFIED' and len(result['sample_checksums']) == 4
    assert v['ledger'].read_bytes() == before and len(v['calls']) == calls
    assert v['keys'].key() not in before.decode()


@pytest.mark.parametrize('fault', ['voice', 'model', 'rate', 'pause', 'key', 'missing_wav', 'changed_wav',
                                 'text', 'usage', 'legacy', 'unknown', 'checksum'])
def test_missing_changed_or_other_voice_evidence_never_reuses_frozen_profile(recorded, fault):
    v = recorded
    original = profile(v)
    voice, speech = deepcopy(VOICE), dict(SPEECH)
    ledger = json.loads(v['ledger'].read_text())
    name, row = next(iter(ledger.items()))
    if fault == 'voice':
        voice['voice_id'] = 'anotherSyntheticVoice'
    elif fault == 'model':
        voice['model'] = 'eleven_v3'
    elif fault in {'rate', 'pause'}:
        speech['rate' if fault == 'rate' else 'pause_ms'] += 1
    elif fault == 'key':
        v['keys'].path.write_bytes(b'new-encrypted-identity')
    elif fault == 'missing_wav':
        (v['root']/'tts-elevenlabs'/(name+'.wav')).unlink()
    elif fault == 'changed_wav':
        (v['root']/'tts-elevenlabs'/(name+'.wav')).write_bytes(b'changed')
    elif fault == 'text':
        row['narration_measurement']['text'] += ' 다른 내용'
    elif fault == 'usage':
        row['reported_credits'] = None
    elif fault == 'legacy':
        row.pop('narration_measurement')
    elif fault == 'unknown':
        row['state'] = 'reserved'
    else:
        row['narration_measurement']['checksum'] = '0'*64
    v['ledger'].write_text(json.dumps(ledger), encoding='utf-8')
    assert profile(v, voice=voice, speech=speech, samples=original['sample_checksums']) is None


def test_new_completed_samples_do_not_replace_frozen_earlier_guidance_or_replay_cache(recorded):
    v = recorded
    saved = profile(v)
    before, calls = v['ledger'].read_bytes(), len(v['calls'])
    v['provider'].synthesize_timed(TEXTS[0], v['root']/'reused.wav', 'elevenlabs', 30)
    assert len(v['calls']) == calls and v['ledger'].read_bytes() == before
    v['provider'].synthesize_timed('서로 다른 새 예시의 조건을 나누어 살펴보는 문장입니다.',
                                    v['root']/'new.wav', 'elevenlabs', 30)
    assert profile(v)['sample_count'] == 5
    assert profile(v, samples=saved['sample_checksums']) == saved


def test_legacy_records_or_too_few_distinct_samples_do_not_create_a_speed_guess(recorded):
    v = recorded
    ledger = json.loads(v['ledger'].read_text())
    for i, row in enumerate(ledger.values()):
        if i >= 2:
            row.pop('narration_measurement')
    v['ledger'].write_text(json.dumps(ledger), encoding='utf-8')
    assert profile(v) is None
    assert planning(v['root'], VOICE, SPEECH) == {'voice': VOICE, 'profile': None}


@pytest.mark.parametrize('duration', [30, 45, 60])
def test_measured_guidance_changes_writing_budget_not_selected_speed_or_real_audio_gate(recorded, duration):
    context = planning(recorded['root'], VOICE, SPEECH)
    source = evidence()
    before = deepcopy(context)
    original = api_news_contract(source, 'STANDARD', duration)
    updated = api_news_contract(source, 'STANDARD', duration, narration=context)
    assert updated['narration_voice'] == VOICE
    assert updated['narration_characters_maximum'] > original['narration_characters_maximum']
    assert updated['speech_estimate']['rate'] == 0 and updated['speech_estimate']['pause_ms'] == 250
    assert context == before
    with pytest.raises(RenderError, match='음성 분량'):
        fit_api_timings([6]*4, 30)  # A passing writing estimate cannot approve an actual short WAV.
    with pytest.raises(RenderError):
        fit_api_timings([8]*4, 30)
    fitted = fit_api_timings([6.875]*4, 30)
    assert sum(fitted) == 30 and all(t-6.875 <= 2 for t in fitted)


def test_voice_selection_drops_injected_ratio_or_proof_and_keeps_global_choice(recorded, sessions):
    assert validate_voice({**VOICE, 'ratio': .65, 'proof': 'invented'}) == VOICE
    assert selected_voice(sessions, 'elevenlabs', config()) == VOICE
    assert selected_voice(sessions, 'elevenlabs', {'voice_id': ''}) is None


def test_fake_api_draft_uses_frozen_voice_budget_and_edits_without_regeneration(state, recorded):
    v = state
    with v['sessions'].begin() as session:
        article = session.get(NewsArticle, v['article_id'])
        article.title, article.summary = evidence()['articles'][0]['title'], evidence()['articles'][0]['summary']
    service = v['service']
    service.narration_root, service.narration_voice = recorded['root'], VOICE
    parent = analyze(v)
    content = longer_script()
    assert speech_plan(content, 30)['estimated_total_seconds'] > 30
    v['document']['content'][0]['text'] = json.dumps(content)
    identifier = service.generate(parent, 30, 'claude_api', True, Options(model='claude-sonnet-4-6'))
    request = json.loads(v['calls'][-1]['messages'][0]['content'])
    contract = request['evidence']['news_usage_contract']
    assert 'narration_voice' not in contract
    assert contract['narration_characters_maximum'] > 197
    assert 'key_tag' not in json.dumps(contract) and 'synthetic-not-an-account-key' not in json.dumps(contract)
    with v['sessions']() as session:
        draft = session.get(ContentDraft, identifier)
        assert draft.review_status == 'review_required'
        assert not any(n['level'] != 'info' for n in draft.review_notes), draft.review_notes
        assert 27 <= service.review_speech_plan(content, draft.sources, 30)['estimated_total_seconds'] <= 30
        # Current default voice is irrelevant to a frozen draft's review.
        service.narration_voice = {**VOICE, 'voice_id': 'differentDefault'}
        assert not any(n['level'] != 'info' for n in service._review_notes(content, draft.sources, 30))
        check_draft(v['sessions'], draft, {'voice': 'elevenlabs', 'speech': SPEECH, 'elevenlabs': config()}, recorded['root'])
        with pytest.raises(IntelligenceError, match='음성·모델'):
            check_draft(v['sessions'], draft, {'voice': 'elevenlabs', 'speech': SPEECH,
                        'elevenlabs': {**config(), 'voice_id': 'other'}}, recorded['root'])
        original = deepcopy(session.get(IntelligenceRun, draft.run_id).result)
    service.edit(identifier, 1, content)
    assert len(v['calls']) == 2  # Fake analysis + Fake script; editing never calls a provider.
    # Changed frozen proof remains a warning even if generic text would otherwise fit.
    recorded['keys'].path.write_bytes(b'changed-identity')
    with v['sessions']() as session:
        draft = session.get(ContentDraft, identifier)
        assert session.get(IntelligenceRun, draft.run_id).result == original
        assert any(n['code'] == 'voice_planning_evidence_changed' for n in service._review_notes(content, draft.sources, 30))
        with pytest.raises(IntelligenceError):
            check_draft(v['sessions'], draft, {'voice': 'elevenlabs', 'speech': SPEECH,
                                             'elevenlabs': config()}, recorded['root'])


def test_uncalibrated_new_voice_and_old_contracts_never_receive_a_guessed_ratio(recorded):
    service = IntelligenceService(None, narration_root=recorded['root'])
    source = evidence()
    source['news_usage_contract'] = api_news_contract(source, 'STANDARD', 30, narration={'voice': VOICE, 'profile': None})
    assert service._timing_context(source)[0] == 1
    assert service._timing_context(source)[1][0]['code'] == 'voice_planning_unmeasured'
    source['news_usage_contract'] = api_news_contract(source, 'STANDARD', 30)
    assert service._timing_context(source) == (1, [])


def test_separate_cache_root_can_validate_with_original_key_identity_without_copy_or_decrypt(recorded, monkeypatch):
    v = recorded
    other = v['root']/'other'
    shutil.copytree(v['root']/'tts-elevenlabs', other/'tts-elevenlabs')
    monkeypatch.setattr(ElevenLabsKeys, 'key', lambda *_: pytest.fail('No decryption for planning'))
    assert load_profile(other, VOICE, SPEECH) is None
    assert load_profile(other, VOICE, SPEECH, keys=v['keys']) == profile(v)
    assert not (other/ElevenLabsKeys.FILE).exists()


def test_post_tts_speed_effect_does_not_reuse_unpaced_voice_calibration(recorded):
    from dataclasses import asdict

    source = evidence()
    source['shortform'] = asdict(Shortform(enabled=True, speed=1.1))
    contract = api_news_contract(source, 'STANDARD', 30, narration=planning(recorded['root'], VOICE, SPEECH))
    assert contract['narration_voice_profile'] is None
    assert contract['scene_narration_budgets'][0]['seconds'] <= 3


@pytest.mark.parametrize('provider', ['claude_api', 'openai'])
def test_wire_uses_selected_voice_budgets_without_sending_voice_ids_or_local_proof(recorded, monkeypatch, provider):
    source = evidence()
    source['news_usage_contract'] = api_news_contract(source, 'STANDARD', 30,
        narration=planning(recorded['root'], VOICE, SPEECH))
    original = deepcopy(source)
    calls = []
    content = longer_script()
    adapter = (AnthropicProvider(lambda: 'synthetic-wire-key') if provider == 'claude_api' else
               OpenAIProvider(lambda: 'synthetic-wire-key', allow_retry=False))
    response = ({'stop_reason': 'end_turn', 'content': [{'type': 'text', 'text': json.dumps(content)}],
                 'usage': {'input_tokens': 100, 'output_tokens': 50}} if provider == 'claude_api' else
                {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(content)}}],
                 'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})

    def send(request, *_):
        calls.append(json.loads(request.data))
        return json.dumps(response).encode()

    monkeypatch.setattr(adapter, '_open', send)
    adapter.complete(source, 30, Options(model='claude-sonnet-4-6' if provider == 'claude_api' else 'gpt-4.1-mini'))
    wire = calls[0]['messages'][0 if provider == 'claude_api' else -1]['content']
    assert 'narration_voice' not in wire and VOICE['voice_id'] not in wire and 'sample_checksums' not in wire
    assert json.loads(wire)['evidence']['news_usage_contract']['narration_characters_maximum'] > 197
    assert source == original and len(calls) == 1 and not adapter.last_retried


def test_failed_unknown_or_missing_usage_requests_never_become_planning_evidence(recorded):
    v = recorded
    calls = len(v['calls'])
    original = v['provider'].transport

    def broken(method, path, payload=None):
        if method == 'GET':
            return original(method, path, payload)
        v['calls'].append((method, path))
        raise TimeoutError()

    v['provider'].transport = broken
    with pytest.raises(TTSError):
        v['provider'].synthesize_timed('다른 실패 예시 문장입니다.', v['root']/'failed.wav', 'elevenlabs', 30)
    ledger = json.loads(v['ledger'].read_text())
    assert any(r['state'] == 'reserved' and 'narration_measurement' not in r for r in ledger.values())
    before = v['ledger'].read_bytes()
    with pytest.raises(TTSError):
        v['provider'].synthesize_timed('다른 실패 예시 문장입니다.', v['root']/'retry.wav', 'elevenlabs', 30)
    assert v['ledger'].read_bytes() == before and len(v['calls']) == calls + 2


def test_success_without_reported_usage_is_preserved_but_not_used_for_planning(recorded):
    v = recorded
    previous = profile(v)
    original = v['provider'].transport

    def no_usage(method, path, payload=None):
        result = original(method, path, payload)
        if method == 'POST':
            v['provider'].reported_credits = None
        return result

    v['provider'].transport = no_usage
    v['provider'].synthesize_timed('사용량이 확인되지 않은 다른 예시 문장입니다.', v['root']/'usage.wav', 'elevenlabs', 30)
    ledger = json.loads(v['ledger'].read_text())
    row = list(ledger.values())[-1]
    assert row['state'] == 'completed' and 'narration_measurement' not in row
    assert profile(v) == previous


def test_explicit_reuse_can_add_evidence_to_legacy_cache_without_rewriting_or_calling(recorded):
    v = recorded
    ledger = json.loads(v['ledger'].read_text())
    for row in ledger.values():
        row.pop('narration_measurement')
    v['ledger'].write_text(json.dumps(ledger), encoding='utf-8')
    original = v['ledger'].read_bytes()
    assert profile(v) is None
    calls = len(v['calls'])
    v['provider'].transport = lambda *_: pytest.fail('Local cache adoption cannot send a request')
    for text in TEXTS:
        v['provider'].remember_completed_cache(text)
    assert profile(v)['sample_count'] == 4 and len(v['calls']) == calls
    assert v['ledger'].read_bytes() == original
    receipts = v['root']/'tts-elevenlabs/narration-measurements.json'
    before = receipts.read_bytes()
    v['provider'].remember_completed_cache(TEXTS[0])
    assert receipts.read_bytes() == before
    with pytest.raises(TTSError):
        v['provider'].remember_completed_cache('캐시에 존재하지 않는 다른 문장입니다.')
    assert v['ledger'].read_bytes() == original and len(v['calls']) == calls


def test_saved_analysis_one_call_scope_freezes_voice_guidance(comparison, recorded):
    from test_comparison_recheck import completed_comparison

    from newsflow.intelligence.comparison_approval import approve_comparison, comparison_review

    v = comparison
    parent = completed_comparison(v)
    voice_args = {'analysis_id': parent, 'single_script': True,
                  'narration_root': recorded['root'], 'narration_voice': VOICE}
    review = comparison_review(v['sessions'], v['ids'], **voice_args)
    with pytest.raises(APISettingsError, match='다시 확인'):
        approve_comparison(v['sessions'], article_ids=v['ids'], review_token=review['token'], consent=True,
                           **{**voice_args, 'narration_voice': {**VOICE, 'voice_id': 'wrongVoice'}})
    grant = approve_comparison(v['sessions'], article_ids=v['ids'], review_token=review['token'], consent=True, **voice_args)
    v['service'].narration_root = recorded['root']
    v['document']['content'][0]['text'] = json.dumps(longer_script())
    result = v['service'].generate(parent, 30, 'claude_api', True, Options(model='claude-sonnet-4-6', timeout=300),
        article_ids=[v['ids'][0]], news_usage='STANDARD', script_prompt_version='v2',
        comparison_approval_id=grant, comparison_step='script-a-v2', narration_voice=VOICE)
    assert result and len(v['calls']) == 6
    with pytest.raises(IntelligenceError):
        v['service'].generate(parent, 30, 'claude_api', True, Options(model='claude-sonnet-4-6', timeout=300),
            article_ids=[v['ids'][0]], news_usage='STANDARD', script_prompt_version='v2',
            comparison_approval_id=grant, comparison_step='script-a-v2', narration_voice=VOICE)
    assert len(v['calls']) == 6


@pytest.mark.parametrize('permanent', [False, True])
def test_windows_local_rename_failure_never_resubmits_voice_or_resets_unknown(recorded, monkeypatch, permanent):
    v = recorded
    real = os.replace
    attempts = []
    text = '별도 저장 과정의 일시적 거부를 확인하는 합성 예시입니다.'

    def sharing_violation(source, destination):
        if str(destination).endswith('ledger.json'):
            value = json.loads(source.read_text(encoding='utf-8'))
            if len(value) == 5 and list(value.values())[-1]['state'] == 'completed':
                attempts.append(1)
                if permanent or len(attempts) < 3:
                    raise PermissionError('Synthetic sharing violation')
        return real(source, destination)

    monkeypatch.setattr('newsflow.video.elevenlabs_tts.os.replace', sharing_violation)
    monkeypatch.setattr('newsflow.video.elevenlabs_tts.time.sleep', lambda _: None)
    if permanent:
        with pytest.raises(TTSError):
            v['provider'].synthesize_timed(text, v['root']/'local-failure.wav', 'elevenlabs', 30)
        with pytest.raises(TTSError):
            v['provider'].synthesize_timed(text, v['root']/'blocked.wav', 'elevenlabs', 30)
        assert list(json.loads(v['ledger'].read_text()).values())[-1]['state'] == 'reserved'
        assert len(attempts) == 4
    else:
        v['provider'].synthesize_timed(text, v['root']/'local-save.wav', 'elevenlabs', 30)
        assert list(json.loads(v['ledger'].read_text()).values())[-1]['state'] == 'completed'
        assert len(attempts) == 3
    assert [method for method, _ in v['calls']].count('POST') == 5  # 4 fixture calls + exactly 1 new call.


def test_gui_service_uses_initial_choice_and_never_writes_defaults(recorded, sessions):
    from newsflow.gui.intelligence_routes import service

    save_settings(sessions, **config())
    with sessions.begin() as session:
        session.add(AppSetting(key='video_default_voice', value='elevenlabs'))
    with sessions() as session:
        before = {s.key: s.value for s in session.scalars(select(AppSetting))}
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(sessions=sessions,
                              video=SimpleNamespace(root=recorded['root']))))
    assert service(request).narration_voice == VOICE
    assert service(request, {'initial_voice': 'supertonic:F2'}).narration_voice == {
        'provider': 'supertonic', 'voice_id': 'supertonic:F2'}
    with sessions() as session:
        assert {s.key: s.value for s in session.scalars(select(AppSetting))} == before


def test_autopilot_freezes_v2_voice_guidance_from_job_and_keeps_it_after_default_changes(api_pipeline, app, recorded, monkeypatch):
    _, backend, provider, sessions, _, _ = api_pipeline
    root = app.state.config.data_dir
    shutil.copy2(recorded['keys'].path, root/ElevenLabsKeys.FILE)
    shutil.copytree(recorded['root']/'tts-elevenlabs', root/'tts-elevenlabs', dirs_exist_ok=True)
    save_settings(sessions, **config())
    monkeypatch.setenv('NEWSFLOW_SCRIPT_PROMPT_VERSION', 'v2')
    choices = {'version': 1, 'script_review': True, 'video_provider': 'off',
               'external_tts_consent': True, 'elevenlabs': config()}
    job = settled(api_pipeline, start(api_pipeline, voice='elevenlabs', production_options=choices))
    assert job['status'] == 'waiting_review' and provider.calls == ['search', 'analysis', 'script']
    with sessions() as session:
        draft = session.get(ContentDraft, job['content_draft_id'])
        contract = draft.sources['news_usage_contract']
        assert contract['narration_voice'] == VOICE and contract['narration_voice_profile']['sample_count'] == 4
        before = backend._draft_summary(draft, job['ai_mode'], job)
        save_settings(sessions, **{**config(), 'voice_id': 'newGlobalVoice', 'model': 'eleven_v3'})
        after = backend._draft_summary(draft, job['ai_mode'], job)
        assert before == after
        assert draft.sources['news_usage_contract'] == contract
    assert len(recorded['calls']) == 8  # Fixture measurements only; Autopilot made no voice request.
