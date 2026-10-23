"""Five explicit Method B requests; append-only consent, never a global unknown reset."""

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AuditLog, IntelligenceRun, utcnow

from .api_settings import APISettingsError, _read, _unknown_fingerprint
from .news_usage import api_news_contract, assess_news_usage
from .presentation import presentation
from .provider import Options, prompt_instruction, prompt_options

PROVIDER, MODEL = 'claude_api', 'claude-sonnet-4-6'
APPROVAL, CONSUMED, FINISHED = 'api_comparison_approval', 'api_comparison_consumed', 'api_comparison_finished'
STEPS = (
    ('analysis-v1', 'analysis', 'v1', None), ('analysis-v2', 'analysis', 'v2', None),
    ('script-a-v1', 'script', 'v1', 0), ('script-a-v2', 'script', 'v2', 0),
    ('script-b-v2', 'script', 'v2', 1),
)
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


def _plan(source):
    result = []
    for name, kind, version, index in STEPS:
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


def _review(session, article_ids, sessions):
    from .service import IntelligenceService

    if (not isinstance(article_ids, list) or len(article_ids) != 2
            or any(type(i) is not int or i < 1 for i in article_ids) or len(set(article_ids)) != 2):
        raise APISettingsError('비교할 기사 A/B 두 건을 순서대로 확인하세요.')
    settings = _read(session, PROVIDER)
    if settings.model != MODEL or not settings.approved:
        raise APISettingsError('저장된 Claude 모델과 사용 승인을 먼저 확인하세요.')
    # Reuse the same source snapshot builder; it performs no external requests.
    source = IntelligenceService(sessions).evidence_for(article_ids)
    rows = list(session.scalars(select(APIRequestReservation).where(APIRequestReservation.provider == PROVIDER)))
    unknowns = _unknowns(rows)
    value = {'scope': 'method_b_five_requests', 'provider': PROVIDER, 'model': MODEL,
             'article_ids': article_ids, 'settings': _settings(settings), 'unknowns': unknowns,
             'plan': _plan(source)}
    return value, source


def comparison_review(sessions, article_ids):
    """Read-only preview. No credential load, acknowledgement or execution consent."""
    with sessions() as session:
        value, source = _review(session, article_ids, sessions)
        return {'token': _digest(value), 'articles': source['articles'],
                'steps': [step['step'] for step in value['plan']], 'unknown_count': len(value['unknowns'])}


def approve_comparison(sessions, *, article_ids, review_token, consent):
    if consent is not True or not isinstance(review_token, str) or not re.fullmatch(r'[a-f0-9]{64}', review_token):
        raise APISettingsError('기사·모델·기존 결과 불명 기록과 비교 5회 범위에 명시적으로 동의하세요.')
    with sessions.begin() as session:
        session.connection().exec_driver_sql('BEGIN IMMEDIATE')
        value, _ = _review(session, article_ids, sessions)
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
                or grant.get('scope') != 'method_b_five_requests'
                or grant['provider'] != settings.provider or grant['model'] != settings.model
                or grant['settings'] != _settings(settings)
                or datetime.fromisoformat(grant['expires_at']) <= utcnow()
                or grant['unknowns'] != _unknowns(rows)):
            raise ValueError
        used = [v for _, v in _entries(session, CONSUMED) if v.get('approval_id') == grant_id]
        if len(used) >= len(STEPS) or step_name != grant['plan'][len(used)]['step']:
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
            parent = previous['analysis-' + version]
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
