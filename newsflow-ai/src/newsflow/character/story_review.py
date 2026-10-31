"""Read-only review and one-request consent for retained unknown episode costs.

The old journal is immutable. A review token is a concurrency fingerprint, not
an approval; only an authenticated POST can consume it inside budget.reserve.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import re

from sqlalchemy import select

from newsflow.db.models import APIRequestReservation, AuditLog, utcnow
from newsflow.intelligence.api_settings import (
    APISettingsError, _confirmed_rejections, _prices, _read, _reasons, _recent, _unknown_fingerprint,
)
from newsflow.intelligence.api_providers import MAX_REQUEST_BYTES

from .compose import digest
from .kling import check
from .schema import CharacterError

EVENT = 'api_episode_story_once_ack'
UNRESOLVED = '이전 AI 요청의 처리·과금이 미확정입니다. 기록을 보존하고 이번 새 스토리 1회 사용을 검토하세요.'
INVALID = '작업·설정 또는 이전 요청 상태가 변경됐습니다. 현재 작업의 사용 승인을 다시 확인하세요.'
MESSAGES = {
    'settings': INVALID,
    'same_job': '이미 실행했거나 결과 확인이 필요한 작업입니다. 같은 요청을 재전송하지 않습니다.',
    'reserved': '진행 중인 AI 요청이 있습니다. 완료 후 확인하세요.',
    'incomplete_unknown': '끝나지 않은 결과 불명 요청이 있습니다. 기존 요청 상태를 먼저 확인하세요.',
    'authentication': '선택한 AI의 인증·모델 확인이 필요합니다. 연결 설정을 확인하세요.',
    'approval': '선택한 AI의 사용 승인이 필요합니다. 연결 설정의 사용 한도를 확인하세요.',
    'key': '선택한 AI의 API 키 등록 상태를 확인하세요.',
    'limit': '스토리 요청 상한이 현재 사용 한도를 넘습니다. AI 1회 한도와 편당 한도를 확인하세요.',
}


class ReviewBlocked(APISettingsError):
    def __init__(self, code):
        self.code = code if code in MESSAGES else 'settings'
        super().__init__(MESSAGES[self.code])


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class StoryReviewRequest:
    service: object
    job_id: str
    token: str = ''
    consent: bool = False

    def context(self, *, writing=False):
        if not isinstance(self.job_id, str) or not re.fullmatch(r'[a-f0-9]{32}', self.job_id):
            raise APISettingsError(INVALID)
        job = self.service.read(self.job_id)
        expected_state, expected_attempt = ('writing', 1) if writing else ('needs_script', 0)
        if (job.get('automation_version') != 1 or job.get('state') != expected_state
                or job.get('script_attempts', 0) != expected_attempt or job.get('response_received', False)
                or job.get('script') or job.get('text_reservations') or job.get('scenes')):
            raise ReviewBlocked('same_job')
        chosen = check(job['studio_selection'])
        from .episode_service import script_provider
        sequence = job.get('script_request_sequence', 0) + (0 if writing else 1)
        if (type(sequence) is not int or sequence < 1
                or job.get('script_provider') != script_provider(chosen['script_model'])
                or job.get('duration') != chosen['duration']
                or not isinstance(job.get('character'), dict) or not job.get('topic')):
            raise APISettingsError(INVALID)
        reference = self.service.folder(self.job_id) / 'reference.png'
        if (not reference.is_file() or reference.is_symlink() or reference.is_junction()
                or digest(reference) != job.get('reference_sha256')):
            raise APISettingsError(INVALID)
        cap = Decimal(str(job['episode_limit']))
        if not cap.is_finite() or cap <= 0:
            raise APISettingsError(INVALID)
        return {
            'job_id': self.job_id, 'request_id': f'episode:{self.job_id}:script:{sequence}',
            'provider': job['script_provider'], 'model': chosen['script_model'],
            'duration': job['duration'], 'episode_limit': str(cap),
            'topic': fingerprint(job['topic']), 'profile': fingerprint(job['character']),
            'selection': fingerprint(job['studio_selection']),
            'reference_sha256': job['reference_sha256'],
        }


def document(session, settings, rows, context):
    """Called again inside the same BEGIN IMMEDIATE as the new reservation."""
    prefix = f"episode:{context['job_id']}:"
    if settings.provider != context['provider'] or settings.model != context['model']:
        raise ReviewBlocked('settings')
    if any(row.request_id.startswith(prefix) for row in rows):
        raise ReviewBlocked('same_job')
    if any(row.status == 'reserved' for row in rows):
        raise ReviewBlocked('reserved')
    rejected = _confirmed_rejections(session, rows)
    unknowns = [row for row in rows if row.status == 'unknown' and row.id not in rejected]
    if any(row.finished_at is None for row in unknowns):
        raise ReviewBlocked('incomplete_unknown')
    unknown = {row.id: _unknown_fingerprint(row) for row in unknowns}
    held = sum((max(Decimal(row.reserved_usd), Decimal(row.estimated_usd or '0'))
                for row in unknowns), Decimal(0))
    if not held.is_finite() or held < 0:
        raise APISettingsError(INVALID)
    value = {'scope': 'new_episode_story_once', 'context': context,
             'api': asdict(settings), 'unknowns': unknown}
    return {'token': fingerprint(value) if unknowns else '', 'ids': set(unknown),
            'unknowns': unknown, 'count': len(unknowns), 'held_usd': str(held),
            'context_fingerprint': fingerprint(context)}


def preview(service, authoring, job_id):
    """No key(), API call, approval save, reservation, or job mutation."""
    empty = {'token': '', 'count': 0, 'held_usd': '0'}
    try:
        review = StoryReviewRequest(service, job_id)
        context = review.context()
        budget = authoring.budget
        store = authoring.keys.get(context['provider'])
        with budget.sessions() as session:
            settings = _read(session, context['provider'])
            rows = list(session.scalars(select(APIRequestReservation).where(
                APIRequestReservation.provider == context['provider'])))
            key = store.status() if store else {}
            now = utcnow()
            reasons = _reasons(settings, key, 'script', now, fake=budget.test_only)
            if reasons:
                if not key.get('configured'):
                    raise ReviewBlocked('key')
                if not settings.approved:
                    raise ReviewBlocked('approval')
                if not budget.test_only and (settings.verified_model != settings.model
                        or not _recent(settings.authentication_verified_at, now)):
                    raise ReviewBlocked('authentication')
                if settings.request_limit_usd <= 0:
                    raise ReviewBlocked('limit')
                raise ReviewBlocked('settings')
            upper = budget._cost({'prompt_tokens': MAX_REQUEST_BYTES, 'completion_tokens': 4000,
                                  'search_calls': 0}, _prices(settings))
            if upper > min(settings.request_limit_usd, Decimal(context['episode_limit'])):
                raise ReviewBlocked('limit')
            state = document(session, settings, rows, context)
            # Do not repeat an already recorded exact-journal review for a
            # different new episode. Fresh or changed unknowns still require
            # the existing explicit review and are not silently acknowledged.
            from .request_scope import operation_for, unrelated_unknown_ids, previously_reviewed_ids
            operation = operation_for(kind='script',instruction='',payload={},model=context['model'],
                                      request_id=context['request_id'])
            reusable = unrelated_unknown_ids(rows, operation, previously_reviewed_ids(session,settings,rows))
            if state['ids'] and state['ids'] <= reusable:
                state = {**state,'token':'','count':0,'held_usd':'0'}
        return {'ready': True, 'review': {name: state[name] for name in empty},
                'message': UNRESOLVED if state['token'] else ''}
    except ReviewBlocked as error:
        return {'ready': False, 'review': empty, 'message': MESSAGES[error.code]}
    except (APISettingsError, CharacterError, KeyError, TypeError, ValueError, OSError, AttributeError, ArithmeticError):
        return {'ready': False, 'review': empty, 'message': INVALID}


def consume(session, settings, rows, review, *, request_id, kind, model, max_output_tokens):
    if (not isinstance(review, StoryReviewRequest) or review.consent is not True
            or not isinstance(review.token, str) or not re.fullmatch(r'[a-f0-9]{64}', review.token)
            or kind != 'script' or model != settings.model or max_output_tokens != 4000):
        raise APISettingsError(UNRESOLVED)
    context = review.context(writing=True)
    if context['request_id'] != request_id:
        raise APISettingsError(INVALID)
    state = document(session, settings, rows, context)
    if not state['token'] or state['token'] != review.token:
        raise APISettingsError(INVALID)
    # Audit and reservation are committed or rolled back together by the caller.
    session.add(AuditLog(level='info', event=EVENT, message=json.dumps({
        'scope': 'new_episode_story_once', 'request_id': request_id, 'provider': settings.provider,
        'model': model, 'review_fingerprint': state['token'],
        'context_fingerprint': state['context_fingerprint'], 'unknowns': state['unknowns'],
    }, separators=(',', ':'))))
    return state['ids']
