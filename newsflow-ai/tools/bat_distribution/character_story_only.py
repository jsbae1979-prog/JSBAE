"""One explicitly approved text-only Claude story; no global provider unlock.

The existing character service, budget ledger, writer and JSON validation remain
in charge. A hash-pinned private approval binds its first matching new job once.
Old trial policies/journals are read only. Quotes use the separate QuoteOnly scope.
"""
from __future__ import annotations

from contextvars import ContextVar
from copy import copy, deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qs

from filelock import FileLock

from newsflow.character.claude import CharacterWriter
from newsflow.character.kling import O3, check
from newsflow.character.schema import CharacterError
from newsflow.character.service import fingerprint
from newsflow.intelligence.credentials import AnthropicKeyStore, CredentialError

PATH = '/api/studio/characters/auto-story'
CLAUDE = 'claude-sonnet-4-6'
_ID = re.compile(r'[a-f0-9]{32}\Z')
_SHA = re.compile(r'[a-f0-9]{64}\Z')
_REQUEST = ContextVar('newsflow_story_request', default=None)
_ACTIVE = ContextVar('newsflow_story_active', default=None)
_ENTROPY = hashlib.sha256(AnthropicKeyStore.ENTROPY).digest()
_FIELDS = {'schemaVersion', 'id', 'created_after', 'expires_at', 'topic_sha256',
           'reference_sha256', 'selection_sha256', 'script_model', 'script_limit_usd',
           'prior_exposure_usd', 'total_limit_usd', 'prior_journals'}


def _deny():
    raise CharacterError('blocked')


def _now():
    return datetime.now(UTC)


def _unlinked(path):
    from newsflow.distribution.windows_profile import unlinked
    return unlinked(Path(path))


def _private(path):
    from newsflow.distribution.windows_profile import private_directory
    return private_directory(path)


def _money(value):
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount < 0:
            raise ValueError
        return amount
    except (InvalidOperation, TypeError, ValueError):
        _deny()


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed
    except (TypeError, ValueError):
        _deny()


def _validate_policy_v1(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        _deny()
    p = dict(value)
    if (type(p['schemaVersion']) is not int or p['schemaVersion'] != 1
            or not isinstance(p['id'], str) or not _ID.fullmatch(p['id'])
            or any(not isinstance(p[k], str) or not _SHA.fullmatch(p[k])
                   for k in ('topic_sha256', 'reference_sha256', 'selection_sha256'))
            or p['script_model'] != CLAUDE
            or _money(p['script_limit_usd']) != Decimal('.25')
            or _money(p['prior_exposure_usd']) != Decimal('3.65')
            or _money(p['total_limit_usd']) != Decimal('4.50')):
        _deny()
    start, end = _time(p['created_after']), _time(p['expires_at'])
    if not start <= _now() < end <= start + timedelta(hours=24):
        _deny()
    prior = p['prior_journals']
    if (not isinstance(prior, dict) or not 1 <= len(prior) <= 1000
            or any(not isinstance(k, str) or not _ID.fullmatch(k)
                   or not isinstance(v, str) or not _SHA.fullmatch(v) for k, v in prior.items())):
        _deny()
    return p


_FIELDS_V2 = {'schemaVersion', 'id', 'approved_at', 'expires_at', 'job_id', 'topic_sha256',
              'reference_sha256', 'selection_sha256', 'script_model', 'script_limit_usd',
              'story_total_limit_usd', 'prior_story_exposure_usd', 'prior_video_exposure_usd',
              'prior_trial_journals', 'prior_story_journals'}


def validate_policy(value):
    if not isinstance(value, dict) or value.get('schemaVersion') != 2:
        return _validate_policy_v1(value)
    p = deepcopy(value)
    if (set(p) != _FIELDS_V2 or type(p['schemaVersion']) is not int
            or any(not isinstance(p[k], str) or not _ID.fullmatch(p[k]) for k in ('id', 'job_id'))
            or any(not isinstance(p[k], str) or not _SHA.fullmatch(p[k])
                   for k in ('topic_sha256', 'reference_sha256', 'selection_sha256'))
            or p['script_model'] != CLAUDE or not Decimal(0) < _money(p['script_limit_usd']) <= Decimal('.25')
            or _money(p['story_total_limit_usd']) < Decimal(0)):
        _deny()
    start, end = _time(p['approved_at']), _time(p['expires_at'])
    if not start <= _now() < end <= start + timedelta(hours=24):
        _deny()
    for name in ('prior_trial_journals', 'prior_story_journals'):
        prior = p[name]
        if (not isinstance(prior, dict) or len(prior) > 1000 or p['id'] in prior
                or any(not isinstance(k, str) or not _ID.fullmatch(k)
                       or not isinstance(v, str) or not _SHA.fullmatch(v) for k, v in prior.items())):
            _deny()
    _money(p['prior_video_exposure_usd'])
    _money(p['prior_story_exposure_usd'])  # Historical reporting only, never a cumulative gate.
    return p


def _prices(sessions):
    from newsflow.intelligence.api_settings import read_api_settings, _prices as prices
    return prices(read_api_settings(sessions, 'claude_api'))


def _reservation(sessions, identifier):
    from newsflow.db.models import APIRequestReservation
    with sessions() as session:
        row = session.get(APIRequestReservation, identifier)
        if row is None:
            _deny()
        return row.status, row.estimated_usd


class _ReadOnlyCipher:
    def __init__(self, scope, native):
        self.scope, self.native = scope, native

    def protect(self, *args):
        raise CredentialError('스토리 실행에는 키 저장 권한이 없습니다.')

    def unprotect(self, payload, entropy):
        self.scope.active()
        if (not isinstance(entropy, bytearray) or bytes(entropy) != _ENTROPY
                or not isinstance(payload, bytearray) or not 0 < len(payload) <= 8192):
            raise CredentialError('승인된 Claude 키만 사용할 수 있습니다.')
        try:
            return self.native.unprotect(payload, entropy)
        except Exception:
            raise CredentialError('Windows 보호 저장소의 Claude 키를 확인하세요.') from None


class _Store(AnthropicKeyStore):
    def __init__(self, scope, cipher):
        super().__init__(scope.profile, cipher)
        self.scope = scope

    def key(self):
        self.scope.active()
        path = _unlinked(self.path)
        if (path != self.scope.profile / AnthropicKeyStore.FILE or not path.is_file()
                or path.stat().st_nlink != 1 or not 0 < path.stat().st_size <= 8192):
            raise CredentialError('현재 프로필에 저장된 Claude 키가 필요합니다.')
        return super().key()  # Exact stored file only; no environment fallback.

    def save(self, *args):
        raise CredentialError('스토리 실행에는 키 저장 권한이 없습니다.')

    def clear(self):
        raise CredentialError('스토리 실행에는 키 삭제 권한이 없습니다.')


class _Budget:
    def __init__(self, scope, original):
        self.scope, self.original = scope, original

    def reserve(self, **kwargs):
        identifier = self.scope.active()
        if (kwargs.get('provider') != 'claude_api' or kwargs.get('kind') != 'script'
                or kwargs.get('request_id') != self.scope.request_id(identifier)
                or kwargs.get('model') != CLAUDE or kwargs.get('max_output_tokens') != 3000
                or kwargs.get('max_search_calls', 0) != 0
                or kwargs.get('key_store') is not self.scope.local.keys):
            _deny()
        from newsflow.intelligence.api_providers import MAX_REQUEST_BYTES
        prices = _prices(self.scope.local.sessions)
        bound = (_money(prices['input']) * MAX_REQUEST_BYTES + _money(prices['output']) * 3000) / 1_000_000
        if bound > self.scope.request_limit():
            _deny()
        # Claim is already durable. Existing authentication/monthly/unknown gates
        # still run, and no failed gate is converted into an execution grant.
        row = self.scope.read_receipt()
        if row['reservation_id'] is not None:
            _deny()
        from newsflow.intelligence.api_settings import APISettingsError
        try:
            reservation = self.original.reserve(**kwargs)
        except APISettingsError:
            # Character routes expose fixed CharacterError messages only; keep
            # the existing budget/auth block without leaking settings diagnostics.
            raise CharacterError('blocked') from None
        row.update(reservation_id=reservation.id, conservative_bound_usd=str(bound))
        self.scope.save_receipt(row)
        return reservation

    def finish(self, identifier, **kwargs):
        self.scope.active(check_expiry=False)
        if self.scope.read_receipt()['reservation_id'] != identifier:
            _deny()
        self.original.finish(identifier, **kwargs)


class StoryOnly:
    def __init__(self, service, profile, policy, nativefactory):
        self.profile = _unlinked(profile)
        if not self.profile.is_absolute() or not self.profile.is_dir():
            _deny()
        self.policy = validate_policy(policy)
        self.policy_hash = fingerprint(self.policy)
        if _unlinked(service.root) != self.profile / 'character':
            _deny()
        self.directory = _unlinked(self.profile / 'character-story-approvals' / self.policy['id'])
        self.path = _unlinked(self.directory / 'journal.json')
        # Copy the service object only. Do not run constructors/startup/recovery or
        # mutate the original service's budget, keys, writer or video capability.
        self.local = copy(service)
        self.local.keys = _Store(self, _ReadOnlyCipher(self, nativefactory()))
        self.local.writer = CharacterWriter(self.local.keys.key)
        self.local.budget = _Budget(self, service.budget)
        self.prior_exposure()

    def request_id(self, identifier):
        return 'character:' + identifier

    def request_limit(self):
        return Decimal('.25')

    def prior_exposure(self):
        parent = _unlinked(self.profile / 'character-trials')
        if not parent.is_dir():
            _deny()
        found, total = set(), Decimal(0)
        for entry in parent.iterdir():
            entry = _unlinked(entry)
            if not entry.is_dir():
                continue
            if not _ID.fullmatch(entry.name):
                _deny()
            path = _unlinked(entry / 'journal.json')
            if not path.is_file() or not 0 < path.stat().st_size <= 32768:
                _deny()
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != self.policy['prior_journals'].get(entry.name):
                _deny()
            row = json.loads(raw)
            if row.get('schemaVersion') != 1:
                _deny()
            for section in ('script', 'video'):
                total += _money(row[section]['reserved_usd'])
            found.add(entry.name)
        if found != set(self.policy['prior_journals']) or total != _money(self.policy['prior_exposure_usd']):
            _deny()
        if total + Decimal('.25') > _money(self.policy['total_limit_usd']):
            _deny()
        return total

    def valid_job(self, identifier):
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            _deny()
        p = self.policy
        if not _time(p['created_after']) <= _now() < _time(p['expires_at']):
            _deny()
        job = self.local.read(identifier)
        selected = check(job.get('studio_selection'))
        if (not _time(p['created_after']) <= _time(job['created_at']) <= _now()
                or hashlib.sha256(job['topic'].encode('utf8')).hexdigest() != p['topic_sha256']
                or job.get('reference_sha256') != p['reference_sha256']
                or fingerprint(job['studio_selection']) != p['selection_sha256']
                or job.get('claude_model') != p['script_model']
                or job.get('duration') != 30 or job.get('model') != O3
                or selected.get('script_model') != CLAUDE or selected.get('video_model') != O3
                or selected.get('duration') != 30 or selected.get('clip_seconds') != 6
                or selected.get('native_resolution') != 'std' or selected.get('sound') != 'on'):
            _deny()
        reference = _unlinked(self.local.folder(identifier) / 'reference.png')
        if (not reference.is_file() or not 0 < reference.stat().st_size <= 10*1024*1024
                or hashlib.sha256(reference.read_bytes()).hexdigest() != p['reference_sha256']):
            _deny()
        return job

    def active(self, *, check_expiry=True):
        requested, active = _REQUEST.get(), _ACTIVE.get()
        if not isinstance(active, tuple) or requested != active or active[0] is not self:
            _deny()
        if check_expiry:
            self.valid_job(active[1])
        row = self.read_receipt()
        if row['job_id'] != active[1] or row['state'] != 'started_or_unknown':
            _deny()
        return active[1]

    def read_receipt(self):
        path = _unlinked(self.path)
        if not path.is_file() or not 0 < path.stat().st_size <= 4096:
            _deny()
        row = json.loads(path.read_bytes())
        if (row.get('schemaVersion') != 1 or row.get('policy_sha256') != self.policy_hash
                or row.get('reserved_usd') != '0.25' or row.get('generation_requests') != 0
                or row.get('state') not in {'started_or_unknown', 'success', 'failed_or_unknown'}):
            _deny()
        return row

    def save_receipt(self, row):
        path, temporary = _unlinked(self.path), _unlinked(self.path.with_suffix('.new'))
        with temporary.open('x', encoding='utf8') as stream:
            json.dump(row, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def write(self, identifier, *, consent=False):
        if _REQUEST.get() != (self, identifier):
            _deny()
        self.local.consent(consent)
        job = self.valid_job(identifier)
        if job.get('state') != 'needs_script' or job.get('script') or job.get('scenes') or job.get('script_attempts'):
            _deny()
        self.prior_exposure()
        parent = _private(self.profile / 'character-story-approvals')
        _private(self.directory)
        with FileLock(str(parent / 'story.lock'), timeout=0):
            # Any earlier story-only claim remains an exposure, even after expiry,
            # errors or a new approval ID. New scopes need an explicit review.
            if any(parent.glob('*/journal.json')):
                _deny()
            row = {'schemaVersion': 1, 'policy_sha256': self.policy_hash, 'job_id': identifier,
                   'state': 'started_or_unknown', 'reserved_usd': '0.25', 'reservation_id': None,
                   'prior_exposure_usd': self.policy['prior_exposure_usd'], 'generation_requests': 0,
                   'claimed_at': _now().isoformat()}
            self.save_receipt(row)  # Durable claim before key access/provider I/O.
        token = _ACTIVE.set((self, identifier))
        try:
            self.local.write(identifier, consent=True)
            if self.local.read(identifier).get('state') != 'script_review':
                _deny()
            row = self.read_receipt()
            status, cost = _reservation(self.local.sessions, row['reservation_id'])
            if status != 'success' or cost is None or _money(cost) > Decimal('.25'):
                _deny()
            row.update(state='success', estimated_usage_usd=str(cost))
            self.save_receipt(row)
        except BaseException:
            row = self.read_receipt()
            row['state'] = 'failed_or_unknown'
            self.save_receipt(row)
            raise
        finally:
            _ACTIVE.reset(token)

    def wrap(self, normal_app, authenticated_app):
        return _Requests(self, normal_app, authenticated_app)


def _attempt_exposure(row):
    """Never release a conservative reservation, including a known failure."""
    if not isinstance(row, dict) or 'reserved_usd' not in row:
        _deny()
    held = _money(row['reserved_usd'])
    for name in ('estimated_usage_usd', 'reported_usd'):
        if row.get(name) is not None:
            held = max(held, _money(row[name]))
    return held


class StoryOnlyV2(StoryOnly):
    """A fresh explicit approval of one existing job, with bounded known retries.

    Historical totals remain auditable; only the explicitly approved request limit gates execution.
    Each explicit request retains its own <= USD .25 conservative reservation.
    """

    def request_limit(self):
        return _money(self.policy['script_limit_usd'])

    def request_id(self, identifier):
        row = self.read_receipt()
        return 'character:' + identifier + (':' + str(row['attempt']) if row['attempt'] > 1 else '')

    def _snapshot_rows(self, folder, expected, *, exclude=None):
        parent = _unlinked(self.profile / folder)
        if not parent.exists():
            if expected:
                _deny()
            return []
        if not parent.is_dir():
            _deny()
        found, rows = set(), []
        for entry in parent.iterdir():
            entry = _unlinked(entry)
            if not entry.is_dir():
                continue
            if not _ID.fullmatch(entry.name):
                _deny()
            if entry.name == exclude:
                continue
            path = _unlinked(entry / 'journal.json')
            if not path.is_file() or not 0 < path.stat().st_size <= 32768:
                _deny()
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected.get(entry.name):
                _deny()
            value = json.loads(raw)
            if not isinstance(value, dict):
                _deny()
            rows.append(value)
            found.add(entry.name)
        if found != set(expected):
            _deny()
        return rows

    def prior_exposure(self):
        story, video = Decimal(0), Decimal(0)
        for row in self._snapshot_rows('character-trials', self.policy['prior_trial_journals']):
            if row.get('schemaVersion') != 1:
                _deny()
            story += _attempt_exposure(row.get('script'))
            video += _attempt_exposure(row.get('video'))
        for row in self._snapshot_rows('character-story-approvals', self.policy['prior_story_journals'],
                                       exclude=self.policy['id']):
            if row.get('schemaVersion') == 1:
                story += _attempt_exposure(row)
            elif row.get('schemaVersion') == 2:
                attempts = row.get('attempts')
                if not isinstance(attempts, list) or not 1 <= len(attempts) <= 3:
                    _deny()
                story += sum((_attempt_exposure(attempt) for attempt in attempts), Decimal(0))
            else:
                _deny()
        if (story != _money(self.policy['prior_story_exposure_usd'])
                or video != _money(self.policy['prior_video_exposure_usd'])):
            _deny()
        return story

    def valid_job(self, identifier):
        p = self.policy
        if identifier != p['job_id'] or not _time(p['approved_at']) <= _now() < _time(p['expires_at']):
            _deny()
        job = self.local.read(identifier)
        selected = check(job.get('studio_selection'))
        if (not _time(job['created_at']) <= _time(p['approved_at'])
                or hashlib.sha256(job['topic'].encode('utf8')).hexdigest() != p['topic_sha256']
                or job.get('reference_sha256') != p['reference_sha256']
                or fingerprint(job['studio_selection']) != p['selection_sha256']
                or job.get('claude_model') != p['script_model']
                or job.get('duration') != 30 or job.get('model') != O3
                or selected.get('script_model') != CLAUDE or selected.get('video_model') != O3
                or selected.get('duration') != 30 or selected.get('clip_seconds') != 6
                or selected.get('native_resolution') != 'std' or selected.get('sound') != 'on'):
            _deny()
        reference = _unlinked(self.local.folder(identifier) / 'reference.png')
        if (not reference.is_file() or not 0 < reference.stat().st_size <= 10*1024*1024
                or hashlib.sha256(reference.read_bytes()).hexdigest() != p['reference_sha256']):
            _deny()
        return job

    def _document(self):
        path = _unlinked(self.path)
        if not path.is_file() or not 0 < path.stat().st_size <= 16384:
            _deny()
        row = json.loads(path.read_bytes())
        if (row.get('schemaVersion') != 2 or row.get('policy_sha256') != self.policy_hash
                or row.get('job_id') != self.policy['job_id'] or row.get('generation_requests') != 0
                or not isinstance(row.get('attempts'), list) or not 1 <= len(row['attempts']) <= 3):
            _deny()
        sequence = []
        for attempt in row['attempts']:
            if (attempt.get('job_id') != row['job_id'] or type(attempt.get('attempt')) is not int
                    or not 1 <= attempt['attempt'] <= 3
                    or _money(attempt.get('reserved_usd')) != self.request_limit()
                    or attempt.get('state') not in {'started_or_unknown', 'success', 'known_failed', 'failed_or_unknown'}):
                _deny()
            sequence.append(attempt['attempt'])
        if sequence != list(range(sequence[0], sequence[0] + len(sequence))):
            _deny()
        if _money(row.get('reserved_usd')) != self.request_limit() * len(sequence):
            _deny()
        return row

    def read_receipt(self):
        return self._document()['attempts'][-1]

    def save_receipt(self, row):
        document = self._document()
        previous = document['attempts'][-1]
        if (row.get('attempt') != previous['attempt'] or row.get('job_id') != previous['job_id']
                or row.get('reserved_usd') != previous['reserved_usd']):
            _deny()
        document['attempts'][-1] = row
        super().save_receipt(document)

    def _known_previous(self, job, last_attempt):
        if job.get('response_received') is not True:
            _deny()
        from sqlalchemy import select
        from newsflow.db.models import APIRequestReservation
        request = 'character:' + job['id'] + (':' + str(last_attempt) if last_attempt > 1 else '')
        with self.local.sessions() as session:
            row = session.scalar(select(APIRequestReservation).where(APIRequestReservation.request_id == request))
            if (row is None or row.provider != 'claude_api' or row.kind != 'script' or row.model != CLAUDE
                    or row.status != 'failed' or row.finished_at is None or row.estimated_usd is None
                    or not isinstance(row.usage, dict)
                    or any(type(row.usage.get(key)) is not int or row.usage[key] < 0
                           for key in ('prompt_tokens', 'completion_tokens'))):
                _deny()

    def write(self, identifier, *, consent=False):
        if _REQUEST.get() != (self, identifier):
            _deny()
        self.local.consent(consent)
        job = self.valid_job(identifier)
        previous = job.get('script_attempts', 0)
        if type(previous) is not int or not 0 <= previous < 3 or job.get('script') or job.get('scenes'):
            _deny()
        if job.get('state') == 'needs_script':
            if previous != 0:
                _deny()
        elif job.get('state') == 'script_failed' and previous > 0:
            self._known_previous(job, previous)
        else:
            _deny()
        parent = _private(self.profile / 'character-story-approvals')
        _private(self.directory)
        with FileLock(str(parent / 'story.lock'), timeout=0):
            prior = self.prior_exposure()
            if self.path.exists():
                document = self._document()
                last = document['attempts'][-1]
                if last['state'] != 'known_failed' or last['attempt'] != previous:
                    _deny()
            else:
                document = {'schemaVersion': 2, 'policy_sha256': self.policy_hash, 'job_id': identifier,
                            'generation_requests': 0, 'attempts': [], 'reserved_usd': '0'}
            own = sum((_attempt_exposure(attempt) for attempt in document['attempts']), Decimal(0))
            # User-approved per-execution policy: historical totals do not block a new explicit request.
            document['attempts'].append({'job_id': identifier, 'attempt': previous + 1,
                'state': 'started_or_unknown', 'reserved_usd': str(self.request_limit()), 'reservation_id': None,
                'claimed_at': _now().isoformat()})
            document['reserved_usd'] = str(self.request_limit() * len(document['attempts']))
            super().save_receipt(document)  # Durable separate claim before each explicitly requested call.
        token = _ACTIVE.set((self, identifier))
        try:
            self.local.write(identifier, consent=True)
            if self.local.read(identifier).get('state') != 'script_review':
                _deny()
            row = self.read_receipt()
            status, cost = _reservation(self.local.sessions, row['reservation_id'])
            if cost is not None:
                row['estimated_usage_usd'] = str(cost)
                self.save_receipt(row)
            if status != 'success' or cost is None or _money(cost) > self.request_limit():
                _deny()
            row['state'] = 'success'
            self.save_receipt(row)
        except BaseException:
            row = self.read_receipt()
            row['state'] = 'failed_or_unknown'
            if row['reservation_id'] is not None:
                status, cost = _reservation(self.local.sessions, row['reservation_id'])
                current = self.local.read(identifier)
                if cost is not None:
                    row['estimated_usage_usd'] = str(cost)
                if (status == 'failed' and cost is not None and _money(cost) <= self.request_limit()
                        and current.get('state') == 'script_failed' and current.get('response_received') is True):
                    row['state'] = 'known_failed'
            self.save_receipt(row)
            raise
        finally:
            _ACTIVE.reset(token)


class _Requests:
    def __init__(self, story, normal, authenticated):
        self.story, self.normal, self.authenticated = story, normal, authenticated

    async def __call__(self, scope, receive, send):
        path = scope.get('path')
        scoped_write = (self.story.policy['schemaVersion'] == 2
                        and path == '/character/' + self.story.policy['job_id'] + '/write')
        if (scope.get('type') != 'http' or scope.get('method') != 'POST' or not (path == PATH or scoped_write)):
            return await self.normal(scope, receive, send)
        try:
            headers = {key.lower(): value for key, value in scope.get('headers', [])}
            if headers.get(b'content-type', b'').split(b';')[0] != b'application/x-www-form-urlencoded':
                _deny()
            body = b''
            while True:
                message = await receive()
                if message['type'] != 'http.request':
                    _deny()
                body += message.get('body', b'')
                if len(body) > 65536:
                    _deny()
                if not message.get('more_body'):
                    break
            values = parse_qs(body.decode('utf8'), keep_blank_values=True)
            identifier = self.story.policy['job_id'] if scoped_write else None
            if identifier is not None:
                if 'job_id' in values and values['job_id'] != [identifier]:
                    _deny()
            elif len(values.get('job_id', [])) == 1:
                identifier = values['job_id'][0]
            if (values.get('consent') != ['true'] or not isinstance(identifier, str)
                    or not _ID.fullmatch(identifier)):
                _deny()
        except (CharacterError, UnicodeError, ValueError):
            await send({'type': 'http.response.start', 'status': 403, 'headers': []})
            return await send({'type': 'http.response.body', 'body': b'Story approval scope denied; no retry.'})
        delivered, original_receive = False, receive

        async def replay():
            nonlocal delivered
            if delivered:
                return await original_receive()
            delivered = True
            return {'type': 'http.request', 'body': body, 'more_body': False}

        token = _REQUEST.set((self.story, identifier))
        try:
            # Exact original body reaches LocalAccess and the original CSRF/Origin
            # middleware before a claim, key access or service invocation.
            return await self.authenticated(scope, replay, send)
        finally:
            _REQUEST.reset(token)


def install(app, profile, policy, nativefactory):
    service = app.state.character
    if (getattr(service, '_approved_character_trial', None) is not None
            or getattr(service, '_character_story_only', None) is not None
            or _unlinked(app.state.config.data_dir) != _unlinked(profile)):
        _deny()
    controller = StoryOnlyV2 if isinstance(policy, dict) and policy.get('schemaVersion') == 2 else StoryOnly
    story = controller(service, profile, policy, nativefactory)
    original = service.write

    def write(identifier, *args, **kwargs):
        if _REQUEST.get() == (story, identifier):
            return story.write(identifier, *args, **kwargs)
        return original(identifier, *args, **kwargs)

    service.write = write
    service._character_story_only = story
    return story
