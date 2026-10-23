"""Scoped Method B requests; append-only consent, never a global unknown reset."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AuditLog, ContentDraft, IntelligenceRun, utcnow

from .api_settings import APISettingsError, _read, _unknown_fingerprint
from .korean import assess_script, speech_plan
from .news_usage import api_news_contract, assess_news_usage, explainer_findings
from .presentation import presentation
from .provider import Options, prompt_instruction, prompt_options

PROVIDER, MODEL = 'claude_api', 'claude-sonnet-4-6'
APPROVAL, CONSUMED, FINISHED = 'api_comparison_approval', 'api_comparison_consumed', 'api_comparison_finished'
STEPS = (
    ('analysis-v1', 'analysis', 'v1', None), ('analysis-v2', 'analysis', 'v2', None),
    ('script-a-v1', 'script', 'v1', 0), ('script-a-v2', 'script', 'v2', 0),
    ('script-b-v2', 'script', 'v2', 1),
)
RECHECK_STEPS = STEPS[3:]  # A/B V2 scripts only, reusing a successful saved V2 analysis.
SINGLE_RECHECK_STEPS = RECHECK_STEPS[:1]  # A only; never inherit the unused B permission.
RUNTIME_FIELDS = {'script_prompt_version', 'script_method', 'news_usage', 'news_usage_result',
                  'news_usage_contract', 'analysis_result', 'presentation'}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str,
                                     separators=(',', ':')).encode()).hexdigest()


def _settings(settings):
    # A separately approved authentication refresh may update proof timestamps.
    ignored = {'authentication_verified_at', 'verified_model', 'search_verified_at', 'request_succeeded_at',
               'billing_confirmed_at', 'account_remaining_usd'}
    return _digest({k: v for k, v in asdict(settings).items() if k not in ignored})


def _entries(session, event):
    result = []
    for row in session.scalars(select(AuditLog).where(AuditLog.event == event).order_by(AuditLog.id)):
        try:
            value = json.loads(row.message)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            result.append((row, value))
    return result


def _unknowns(rows):
    if any(r.status == 'reserved' or r.status == 'unknown' and r.finished_at is None for r in rows):
        raise APISettingsError('진행 중 요청은 비교 승인으로 우회할 수 없습니다.')
    return {r.id: _unknown_fingerprint(r) for r in rows if r.status == 'unknown'}


def _plan(source, steps=STEPS):
    result = []
    for name, kind, version, index in steps:
        base = deepcopy(source)
        if index is not None:
            chosen = source['articles'][index]['id']
            base['articles'] = [a for a in source['articles'] if a['id'] == chosen]
            base['groups'] = [[i for i in group if i == chosen] for group in source['groups'] if chosen in group]
        contract = api_news_contract(base, 'STANDARD', 30 if kind == 'script' else None, version=version)
        options = prompt_options(Options(model=MODEL, timeout=300), kind, version)
        result.append({'step': name, 'kind': kind, 'version': version, 'source': _digest(base),
                       'contract': _digest(contract), 'assessment': _digest(assess_news_usage(base, 'STANDARD')),
                       'instruction': _digest(prompt_instruction(kind, version=version)),
                       'max_tokens': options.max_tokens})
    return result


def _saved_analysis(session, identifier):
    parent = session.get(IntelligenceRun, identifier) if type(identifier) is int and identifier > 0 else None
    reservation = session.scalar(select(APIRequestReservation).where(
        APIRequestReservation.request_id == f'intelligence:{identifier}')) if parent else None
    proof = next((v for _, v in _entries(session, FINISHED)
                  if v.get('request_id') == f'intelligence:{identifier}'
                  and parent and v.get('approval_id') == parent.options.get('comparison_approval_id')), None)
    if (not parent or parent.kind != 'analysis' or parent.status != 'success' or parent.provider != PROVIDER
            or parent.options.get('model') != MODEL or parent.options.get('script_prompt_version') != 'v2'
            or parent.options.get('comparison_step') != 'analysis-v2'
            or not reservation or reservation.status != 'success' or reservation.provider != PROVIDER
            or reservation.kind != 'analysis' or reservation.model != MODEL
            or not isinstance(reservation.usage, dict)
            or not reservation.usage.get('prompt_tokens') or not reservation.usage.get('completion_tokens')
            or not proof or proof.get('status') != 'success'
            or proof.get('run_fingerprint') != _unknown_fingerprint(parent)):
        raise APISettingsError('사용량과 완료 기록이 확인된 기존 V2 비교 분석이 필요합니다.')
    return parent, reservation


def _review(session, article_ids, sessions, analysis_id=None, single_script=False):
    from .service import IntelligenceService

    if (not isinstance(article_ids, list) or len(article_ids) != 2
            or any(type(i) is not int or i < 1 for i in article_ids) or len(set(article_ids)) != 2):
        raise APISettingsError('비교할 기사 A/B 두 건을 순서대로 확인하세요.')
    if type(single_script) is not bool or single_script and analysis_id is None:
        raise APISettingsError('단일 대본 재검증에는 저장된 V2 분석이 필요합니다.')
    settings = _read(session, PROVIDER)
    if settings.model != MODEL or not settings.approved:
        raise APISettingsError('저장된 Claude 모델과 사용 승인을 먼저 확인하세요.')
    # Reuse the same source snapshot builder; it performs no external requests.
    source = IntelligenceService(sessions).evidence_for(article_ids)
    rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == PROVIDER)))
    unknowns = _unknowns(rows)
    parent, parent_reservation = _saved_analysis(session, analysis_id) if analysis_id is not None else (None, None)
    if parent and _digest({k: v for k, v in parent.evidence.items() if k not in RUNTIME_FIELDS}) != _digest(source):
        raise APISettingsError('저장된 분석의 기사 자료가 현재 비교 자료와 다릅니다.')
    scope = ('method_b_saved_analysis_one_script' if single_script else
             'method_b_saved_analysis_two_scripts' if parent else 'method_b_five_requests')
    steps = SINGLE_RECHECK_STEPS if single_script else RECHECK_STEPS if parent else STEPS
    value = {'scope': scope,
             'provider': PROVIDER, 'model': MODEL,
             'article_ids': article_ids, 'settings': _settings(settings), 'unknowns': unknowns,
             'plan': _plan(source, steps)}
    if parent:
        value['saved_analysis'] = {'id': parent.id, 'fingerprint': _unknown_fingerprint(parent),
                                   'reservation_fingerprint': _unknown_fingerprint(parent_reservation)}
    return value, source


def comparison_review(sessions, article_ids, *, analysis_id=None, single_script=False):
    """Read-only preview. No credential load, acknowledgement or execution consent."""
    with sessions() as session:
        value, source = _review(session, article_ids, sessions, analysis_id, single_script)
        return {'token': _digest(value), 'articles': source['articles'],
                'steps': [step['step'] for step in value['plan']], 'unknown_count': len(value['unknowns'])}


def approve_comparison(sessions, *, article_ids, review_token, consent, analysis_id=None, single_script=False):
    if consent is not True or not isinstance(review_token, str) or not re.fullmatch(r'[a-f0-9]{64}', review_token):
        raise APISettingsError('기사·모델·기존 결과 불명 기록과 검토한 비교 호출 범위에 명시적으로 동의하세요.')
    with sessions.begin() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        value, _ = _review(session, article_ids, sessions, analysis_id, single_script)
        if _digest(value) != review_token:
            raise APISettingsError('자료·설정·결과 불명 기록이 바뀌었습니다. 비교 범위를 다시 확인하세요.')
        for entry, previous in _entries(session, APPROVAL):
            if previous.get('review_token') == review_token:
                return entry.id  # no renewal, extra grant or reset on a duplicate action
        value.update(review_token=review_token, expires_at=(utcnow() + timedelta(hours=1)).isoformat())
        entry = AuditLog(level='info', event=APPROVAL, message=json.dumps(value, separators=(',', ':')))
        session.add(entry)
        session.flush()
        return entry.id


def authorize_step(session, settings, request_id, kind, rows, max_output_tokens):
    """Called under the existing reservation transaction, after normal auth/limit gates."""
    match = re.fullmatch(r'intelligence:([1-9][0-9]*)', request_id)
    run = session.get(IntelligenceRun, int(match[1])) if match else None
    grant_id = run.options.get('comparison_approval_id') if run else None
    step_name = run.options.get('comparison_step') if run else None
    if grant_id is None and step_name is None:
        return None
    if type(grant_id) is not int or grant_id < 1 or not isinstance(step_name, str):
        raise APISettingsError('비교 승인 식별자를 확인하세요.')
    entry = session.get(AuditLog, grant_id)
    try:
        grant = json.loads(entry.message) if entry and entry.event == APPROVAL else {}
        if (_digest({k: v for k, v in grant.items() if k not in {'review_token', 'expires_at'}}) != grant['review_token']
                or grant.get('scope') not in {'method_b_five_requests', 'method_b_saved_analysis_two_scripts',
                                             'method_b_saved_analysis_one_script'}
                or grant['provider'] != settings.provider or grant['model'] != settings.model
                or grant['settings'] != _settings(settings)
                or datetime.fromisoformat(grant['expires_at']) <= utcnow()
                or grant['unknowns'] != _unknowns(rows)):
            raise ValueError
        reuse = grant['scope'] != 'method_b_five_requests'
        definitions = (SINGLE_RECHECK_STEPS if grant['scope'] == 'method_b_saved_analysis_one_script' else
                       RECHECK_STEPS if reuse else STEPS)
        if [p['step'] for p in grant['plan']] != [p[0] for p in definitions]:
            raise ValueError
        saved_parent, saved_reservation = (_saved_analysis(session, grant['saved_analysis']['id'])
                                           if reuse else (None, None))
        if reuse and (_unknown_fingerprint(saved_parent) != grant['saved_analysis']['fingerprint']
                      or _unknown_fingerprint(saved_reservation) != grant['saved_analysis']['reservation_fingerprint']):
            raise ValueError
        used = [v for _, v in _entries(session, CONSUMED) if v.get('approval_id') == grant_id]
        if len(used) >= len(definitions) or step_name != grant['plan'][len(used)]['step']:
            raise ValueError
        previous = {}
        finished = [v for _, v in _entries(session, FINISHED) if v.get('approval_id') == grant_id]
        for position, item in enumerate(used):
            old = session.get(IntelligenceRun, item['run_id'])
            reservation = session.scalar(select(APIRequestReservation).where(
                APIRequestReservation.request_id == item['request_id']))
            proof = next((p for p in finished if p.get('request_id') == item['request_id']), None)
            if (item['step'] != grant['plan'][position]['step'] or not old or old.status != 'success'
                    or not reservation or reservation.status != 'success' or not proof
                    or proof.get('run_fingerprint') != _unknown_fingerprint(old)):
                raise ValueError
            if reuse:
                draft = session.scalar(select(ContentDraft).where(ContentDraft.run_id == old.id))
                if (not draft or draft.duration != 30 or draft.revision != 1 or draft.content != old.result
                        or draft.review_status != 'review_required'
                        or any(note.get('level') != 'info' for note in
                               assess_script(old.result, old.evidence, 30) + explainer_findings(old.result, old.evidence))
                        or speech_plan(old.result, 30)['estimated_total_seconds'] < 27):
                    raise ValueError
            previous[item['step']] = old
        expected = grant['plan'][len(used)]
        version = expected['version']
        base = {k: v for k, v in run.evidence.items() if k not in RUNTIME_FIELDS}
        if (run.provider != PROVIDER or run.kind != kind or kind != expected['kind'] or run.status != 'running'
                or run.evidence.get('news_usage') != 'STANDARD'
                or run.evidence.get('script_method') != 'api_grounded_' + version
                or run.evidence.get('script_prompt_version') != version
                or _digest(base) != expected['source']
                or _digest(run.evidence.get('news_usage_contract')) != expected['contract']
                or _digest(run.evidence.get('news_usage_result')) != expected['assessment']
                or _digest(prompt_instruction(kind, version=version)) != expected['instruction']
                or run.options.get('model') != MODEL or max_output_tokens != expected['max_tokens']
                or run.options.get('max_tokens') != expected['max_tokens']
                or run.options.get('base_max_tokens') != 1800 or run.options.get('temperature') != .2
                or run.options.get('timeout') != 300 or run.options.get('script_prompt_version') != version):
            raise ValueError
        if kind == 'script':
            parent = saved_parent if reuse else previous['analysis-' + version]
            if (run.options.get('duration') != 30 or run.options.get('analysis_run_id') != parent.id
                    or run.evidence.get('analysis_result') != parent.result
                    or run.evidence.get('presentation') != presentation()):
                raise ValueError
        return {'approval_id': grant_id, 'step': step_name, 'run_id': run.id,
                'request_id': request_id, 'unknown_ids': sorted(grant['unknowns'])}
    except (ValueError, KeyError, TypeError, AttributeError):
        raise APISettingsError('비교 승인 범위·순서·기록이 일치하지 않습니다. 자동 재호출하지 않습니다.') from None


def record_finished(session, reservation):
    match = re.fullmatch(r'intelligence:([1-9][0-9]*)', reservation.request_id)
    run = session.get(IntelligenceRun, int(match[1])) if match else None
    if not run or type(run.options.get('comparison_approval_id')) is not int:
        return
    item = next((v for _, v in _entries(session, CONSUMED)
                 if v.get('request_id') == reservation.request_id and v.get('run_id') == run.id
                 and v.get('approval_id') == run.options['comparison_approval_id']), None)
    if item is not None:
        session.add(AuditLog(level='info', event=FINISHED, message=json.dumps({
            'approval_id': item['approval_id'], 'step': item['step'], 'request_id': reservation.request_id,
            'status': reservation.status, 'run_fingerprint': _unknown_fingerprint(run)}, separators=(',', ':'))))
