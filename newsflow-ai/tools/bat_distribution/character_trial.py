"""One explicitly approved character trial; no global credential/provider unlock.

install(app, profile, policy, original_dpapi_factory) returns a controller whose
wrap(normal_app, authenticated_app) gates only the approved character workflow routes.
Both inner applications must retain the existing LocalAccess/Origin/CSRF layers.
This module never starts an app, opens a browser, or reads credentials on install.
"""
from __future__ import annotations

from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from urllib.parse import parse_qs

from filelock import FileLock
from starlette.requests import Request
from starlette.responses import JSONResponse

from newsflow.character.claude import CharacterWriter
from newsflow.character.schema import CharacterError
from newsflow.intelligence.credentials import AnthropicKeyStore, CredentialError
from newsflow.video.ai.keys import VideoAIKeyStore

K3 = 'kling-video/v3.0/std/image-to-video'
CLAUDE = 'claude-sonnet-4-6'
_CONTEXT = ContextVar('newsflow_character_trial', default=None)
_ID = re.compile(r'[a-f0-9]{32}\Z')
_ACTION = re.compile(r'/character/([a-f0-9]{32})/(prepare|submit|check|render)\Z')
_AUTHENTICATE = '/api/studio/characters/trial-authenticate'
_STATUS = '/api/studio/characters/trial-status'
_ARCHIVE = '/api/studio/characters/trial-archive'
_FIELDS = {'schemaVersion', 'id', 'expires_at', 'topic', 'reference_sha256',
           'script_model', 'video_model', 'duration', 'clip_seconds', 'scene_count',
           'sound', 'script_limit_usd', 'video_limit_usd', 'total_limit_usd'}


def _now():
    return datetime.now(UTC)


def _fail():
    raise CharacterError('blocked')


def _money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0:
            raise ValueError
        return result
    except (InvalidOperation, TypeError, ValueError):
        _fail()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode()).hexdigest()


def _private(path):
    from newsflow.distribution.windows_profile import private_directory
    return private_directory(path)


def _unlinked(path):
    from newsflow.distribution.windows_profile import unlinked
    return unlinked(path)


def _prices(sessions):
    from newsflow.intelligence.api_settings import read_api_settings, _prices as prices
    return prices(read_api_settings(sessions, 'claude_api'))


def _authentication(sessions):
    from newsflow.intelligence.api_settings import read_api_settings, _recent
    settings = read_api_settings(sessions, 'claude_api')
    verified = (settings.model == CLAUDE and settings.verified_model == CLAUDE
                and _recent(settings.authentication_verified_at, _now()))
    return settings.model, bool(verified)


def _unknown_review(value):
    if value is None:
        return {}
    if (not isinstance(value, dict) or len(value) != 7
            or any(not isinstance(key, str) or not _ID.fullmatch(key)
                   or not isinstance(item, str) or not re.fullmatch(r'[a-f0-9]{64}', item)
                   for key, item in value.items())):
        _fail()
    return dict(value)


def _archive_state(sessions, review):
    if not review:
        return False, 0, 0
    from sqlalchemy import select
    from newsflow.db.models import APIRequestReservation
    from newsflow.intelligence.request_archival import fingerprint
    with sessions() as session:
        rows = list(session.scalars(select(APIRequestReservation)
                    .where(APIRequestReservation.id.in_(sorted(review)))))
        unknown = sum(row.status == 'unknown' for row in rows)
        archived = sum(row.status == 'archived_unknown' for row in rows)
        matching = (len(rows) == 7 and unknown == 7 and all(
            row.finished_at is not None and fingerprint(row) == review[row.id] for row in rows))
    return matching, unknown, archived


def _reservation(sessions, identifier):
    from newsflow.db.models import APIRequestReservation
    with sessions() as session:
        row = session.get(APIRequestReservation, identifier)
        if row is None:
            _fail()
        return row.status, row.estimated_usd


def _policy(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        _fail()
    p = dict(value)
    try:
        expiry = datetime.fromisoformat(p['expires_at'])
        if (type(p['schemaVersion']) is not int or p['schemaVersion'] != 1 or not _ID.fullmatch(p['id'])
                or expiry.tzinfo is None or not _now() < expiry <= _now()+timedelta(hours=24)
                or not isinstance(p['topic'], str) or not 1 <= len(p['topic']) <= 150
                or not re.fullmatch(r'[a-f0-9]{64}', p['reference_sha256'])
                or p['script_model'] != CLAUDE or p['video_model'] != K3
                or any(type(p[k]) is not int for k in ('duration', 'clip_seconds', 'scene_count'))
                or (p['duration'], p['clip_seconds'], p['scene_count'], p['sound']) != (15, 3, 5, 'off')
                or (_money(p['script_limit_usd']), _money(p['video_limit_usd']),
                    _money(p['total_limit_usd'])) != (Decimal('.25'), Decimal('2.75'), Decimal('3'))):
            _fail()
    except (KeyError, TypeError, ValueError):
        _fail()
    return p


class _ReadOnlyCipher:
    def __init__(self, trial, native, provider, label):
        self._trial, self._native, self._provider = trial, native, provider
        self._entropy = hashlib.sha256(label).digest()

    def protect(self, payload, entropy):
        raise CredentialError('이번 제작 권한에는 키 저장이 포함되지 않습니다.')

    def unprotect(self, payload, entropy):
        self._trial.active(self._provider)
        if not isinstance(entropy, bytearray) or bytes(entropy) != self._entropy:
            raise CredentialError('이번 제작에 허용되지 않은 보호 자료입니다.')
        try:
            return self._native.unprotect(payload, entropy)
        except Exception:  # Native diagnostics must never escape a scoped API check.
            raise CredentialError('Windows 보호 저장소에서 승인된 API 키를 읽지 못했습니다.') from None


class _StoredOnly:
    def key(self):
        self._trial.active(self._provider)
        path = _unlinked(self.path)
        if not path.is_file() or not path.resolve().is_relative_to(self._trial.profile.resolve()):
            raise CredentialError('승인한 Windows 프로필의 저장 키가 필요합니다.')
        return super().key()

    def save(self, key):
        raise CredentialError('이번 제작 권한에는 키 저장이 포함되지 않습니다.')

    def clear(self):
        raise CredentialError('이번 제작 권한에는 키 삭제가 포함되지 않습니다.')


class _ClaudeStore(_StoredOnly, AnthropicKeyStore):
    pass


class _VideoStore(_StoredOnly, VideoAIKeyStore):
    pass


class _Budget:
    def __init__(self, trial, original):
        self.trial, self.original = trial, original

    def reserve(self, **kwargs):
        context = self.trial.active('claude')
        if (kwargs.get('provider') != 'claude_api' or kwargs.get('kind') != 'script'
                or kwargs.get('model') != CLAUDE or kwargs.get('max_output_tokens') != 3000
                or kwargs.get('request_id') != 'character:'+context.job_id
                or kwargs.get('max_search_calls', 0) != 0
                or kwargs.get('key_store') is not self.trial.service.keys):
            _fail()
        # Existing transport rejects requests above 64000 bytes; this deliberately
        # conservative input bound is recorded, never advertised as a vendor bill.
        from newsflow.intelligence.api_providers import MAX_REQUEST_BYTES
        prices = _prices(self.trial.service.sessions)
        upper = (_money(prices['input'])*MAX_REQUEST_BYTES
                 + _money(prices['output'])*3000)/1_000_000
        if upper > Decimal('.25'):
            _fail()
        with self.trial.journal() as row:
            if row['script']['state'] != 'unspent':
                _fail()
            row['script'].update(state='reserved', reserved_usd='0.25',
                                 conservative_bound_usd=str(upper), reservation_id=None)
        # The unchanged service still performs authentication, monthly limit,
        # request identity and existing reserved/unknown ledger checks.
        reservation = self.original.reserve(**kwargs)
        with self.trial.journal() as row:
            row['script']['reservation_id'] = reservation.id
        return reservation

    def finish(self, reservation_id, **kwargs):
        # Final accounting of an already dispatched request must remain possible
        # if its approval expires while the provider responds. This does not
        # expose a credential, send a request or enable another paid attempt.
        context = _CONTEXT.get()
        if context is None or context.trial is not self.trial or context.action != 'auto-story':
            _fail()
        with self.trial.journal() as row:
            if (row['job_id'] != context.job_id or row['script']['reservation_id'] != reservation_id
                    or row['script']['state'] != 'reserved'):
                _fail()
        self.original.finish(reservation_id, **kwargs)
        status, cost = _reservation(self.trial.service.sessions, reservation_id)
        with self.trial.journal() as row:
            okay = status == 'success' and cost is not None and _money(cost) <= Decimal('.25')
            row['script'].update(state='reported' if okay else 'unknown_or_over_limit',
                                 reported_usd=str(cost) if cost is not None else None)


class _Client:
    def __init__(self, trial, original, job_id):
        self.trial, self.original, self.job_id = trial, original, job_id

    def credential(self):
        self.trial.active('video', self.job_id)
        return self.original.credential()

    def _claim(self, name, maximum, action):
        context = self.trial.active('video', self.job_id)
        if context.action != action:
            _fail()
        with self.trial.journal() as row:
            if row['native_calls'].get(name, 0) >= maximum:
                _fail()
            row['native_calls'][name] = row['native_calls'].get(name, 0)+1

    def _payload(self, payload):
        if (not isinstance(payload, dict) or payload.get('duration') != 15
                or payload.get('sound') != 'off' or payload.get('multi_shots') is not False
                or set(payload) != {'prompt', 'duration', 'sound', 'multi_shots', 'image_url'}):
            _fail()

    def payload(self, *args, **kwargs):
        self.trial.active('video', self.job_id)
        payload = self.original.payload(*args, **kwargs)
        self._payload(payload)
        return payload

    def upload_reference(self, path):
        self._claim('upload', 1, 'prepare')
        return self.original.upload_reference(path)

    def estimate(self, payload):
        self._payload(payload)
        self._claim('estimate', 1, 'prepare')
        return self.original.estimate(payload)

    def submit_scene(self, payload, idempotency_key):
        self._payload(payload)
        self._claim('submit_scene', 1, 'submit')
        return self.original.submit_scene(payload, idempotency_key)

    def check(self, handle):
        self._claim('status', 300, 'check')
        return self.original.check(handle)

    def fetch(self, *args, **kwargs):
        self._claim('fetch', 1, 'check')
        return self.original.fetch(*args, **kwargs)


class _Journal:
    def __init__(self, trial, readonly=False):
        self.trial, self.readonly = trial, readonly

    def __enter__(self):
        self.lock = FileLock(str(self.trial.directory/'journal.lock'), timeout=0)
        self.lock.acquire()
        try:
            path = _unlinked(self.trial.path)
            if not path.is_file() or path.stat().st_size > 32768:
                _fail()
            self.row = json.loads(path.read_bytes())
            if (self.row.get('policy_sha256') != self.trial.policy_hash
                    or self.row.get('schemaVersion') != 1):
                _fail()
            return self.row
        except BaseException:
            self.lock.release()
            raise

    def __exit__(self, kind, value, traceback):
        try:
            if kind is None and not self.readonly:
                self.trial.save(self.row)
        finally:
            self.lock.release()


class Trial:
    def __init__(self, service, profile, policy, unknown_review=None):
        self.service, self.policy = service, _policy(policy)
        self.unknown_review = _unknown_review(unknown_review)
        self.unknown_review_hash = _hash(self.unknown_review)
        self.profile = _unlinked(Path(profile))
        if not self.profile.is_absolute() or not self.profile.is_dir():
            _fail()
        self.policy_hash = _hash(self.policy)
        self.directory = _private(_private(self.profile/'character-trials')/self.policy['id'])
        self.path = self.directory/'journal.json'
        if not self.path.exists():
            with FileLock(str(self.directory/'journal.lock'), timeout=0):
                if self.path.exists():
                    _fail()
                self.save({'schemaVersion': 1, 'policy_sha256': self.policy_hash,
                           'job_id': None, 'calls': {}, 'native_calls': {}, 'outcomes': {},
                           'script': {'state': 'unspent', 'reserved_usd': '0'},
                           'video': {'state': 'unspent', 'reserved_usd': '0'}})
        with self.journal() as row:
            if self.unknown_review:
                existing = row.get('unknown_review_sha256')
                if existing is not None and existing != self.unknown_review_hash:
                    _fail()
                if existing is None:
                    if row['calls'].get('archive', 0):
                        _fail()
                    row['unknown_review_sha256'] = self.unknown_review_hash

    def journal(self, *, readonly=False):
        return _Journal(self, readonly)

    def save(self, row):
        path = _unlinked(self.path)
        temporary = _unlinked(path.with_suffix('.new'))
        with temporary.open('xb') as stream:
            stream.write(json.dumps(row, sort_keys=True, ensure_ascii=False).encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _valid(self, identifier):
        if _now() >= datetime.fromisoformat(self.policy['expires_at']) or not _ID.fullmatch(identifier or ''):
            _fail()
        job = self.service.read(identifier)
        p, s = self.policy, job.get('studio_selection', {})
        if (job.get('topic') != p['topic'] or job.get('reference_sha256') != p['reference_sha256']
                or job.get('model') != p['video_model'] or job.get('claude_model') != p['script_model']
                or job.get('duration') != 15
                or any(s.get(k) != p[k] for k in ('video_model', 'script_model', 'duration', 'clip_seconds', 'sound'))
                or _money(job.get('episode_limit')) > Decimal('2.75')):
            _fail()
        reference = _unlinked(self.service.folder(identifier)/'reference.png')
        if hashlib.sha256(reference.read_bytes()).hexdigest() != p['reference_sha256']:
            _fail()
        if job.get('script'):
            scenes = job['script'].get('scenes', [])
            if len(scenes) != 5 or any(s.get('seconds') != 3 for s in scenes):
                _fail()
        return job

    def active(self, provider, identifier=None):
        context = _CONTEXT.get()
        if (context is not None and context.trial is self and provider == 'claude'
                and context.action == 'authenticate' and context.job_id is None and identifier is None):
            if _now() >= datetime.fromisoformat(self.policy['expires_at']):
                _fail()
            with self.journal() as row:
                if (row['calls'].get('authenticate') != 1
                        or row['outcomes'].get('authenticate') != 'started_or_unknown'):
                    _fail()
            return context
        if (context is None or context.trial is not self
                or (identifier is not None and context.job_id != identifier)
                or context.action not in ({'auto-story'} if provider == 'claude' else {'prepare', 'submit', 'check'})):
            _fail()
        self._valid(context.job_id)
        with self.journal() as row:
            if row['job_id'] != context.job_id:
                _fail()
        return context

    def authenticate(self, *, consent):
        """One explicit model-metadata GET through the existing scoped key store."""
        context = _CONTEXT.get()
        if (consent is not True or context is None or context.trial is not self
                or context.action != 'authenticate' or context.job_id is not None
                or _now() >= datetime.fromisoformat(self.policy['expires_at'])):
            _fail()
        with self.journal() as row:
            if row['calls'].get('authenticate', 0) != 0:
                _fail()
            row['calls']['authenticate'] = 1
            row['outcomes']['authenticate'] = 'started_or_unknown'
        try:
            model, _ = _authentication(self.service.sessions)
            if model != self.policy['script_model']:
                _fail()
            from newsflow.intelligence.api_connection import check_claude_connection
            result = check_claude_connection(self.service.sessions, self.service.keys, consent=True)
        except BaseException:
            with self.journal() as row:
                row['outcomes']['authenticate'] = 'failed_or_unknown'
            raise
        with self.journal() as row:
            row['outcomes']['authenticate'] = 'success' if result.ok else 'failed_or_unknown'
        return result

    def status(self):
        """Authenticated readiness metadata only; never decrypt or return a key."""
        context = _CONTEXT.get()
        if (context is None or context.trial is not self or context.action != 'status'
                or context.job_id is not None):
            _fail()
        model, verified = _authentication(self.service.sessions)
        with self.journal(readonly=True) as row:
            attempted = row['calls'].get('authenticate', 0) != 0
            archive_attempted = row['calls'].get('archive', 0) != 0
        matching, unknown, archived = _archive_state(self.service.sessions, self.unknown_review)
        key = _unlinked(self.service.keys.path)
        configured = key.is_file() and key.resolve().is_relative_to(self.profile.resolve())
        reasons = []
        if _now() >= datetime.fromisoformat(self.policy['expires_at']):
            reasons.append('이번 제작 승인 시간이 만료되었습니다.')
        if model != self.policy['script_model']:
            reasons.append('승인된 Claude 모델 설정이 필요합니다.')
        if not configured:
            reasons.append('이 Windows 프로필의 저장된 Claude API 키가 필요합니다.')
        if attempted:
            reasons.append('이번 승인에서 연결 확인을 이미 시도했습니다. 자동 재시도하지 않습니다.')
        return {'ready': not reasons, 'reasons': reasons, 'model': model,
                'keyConfigured': configured, 'authenticationVerified': verified, 'authAttempted': attempted,
                'archiveReady': matching and not archive_attempted
                    and _now() < datetime.fromisoformat(self.policy['expires_at']),
                'unknownCount': unknown, 'archivedCount': archived}

    def archive(self, *, consent):
        """Archive exactly the reviewed seven records; never delete or authorize replay."""
        context = _CONTEXT.get()
        if (consent is not True or context is None or context.trial is not self
                or context.action != 'archive' or context.job_id is not None
                or _now() >= datetime.fromisoformat(self.policy['expires_at'])
                or len(self.unknown_review) != 7 or _hash(self.unknown_review) != self.unknown_review_hash):
            _fail()
        with self.journal() as row:
            if (row['calls'].get('archive', 0) != 0
                    or row.get('unknown_review_sha256') != self.unknown_review_hash):
                _fail()
            row['calls']['archive'] = 1
            row['outcomes']['archive'] = 'started_or_unknown'
        try:
            from newsflow.intelligence.request_archival import archive_unknown
            result = archive_unknown(self.service.sessions, self.unknown_review, consent=True)
            if (result.get('count') != 7 or result.get('status') != 'archived_unknown'
                    or result.get('replay_authorized') is not False or result.get('deleted') != 0):
                _fail()
        except BaseException:
            with self.journal() as row:
                row['outcomes']['archive'] = 'failed_or_unknown'
            raise
        with self.journal() as row:
            row['outcomes']['archive'] = 'success'
        return {'count': 7, 'status': 'archived_unknown', 'replay_authorized': False}

    def invoke(self, action, identifier, method, *args, **kwargs):
        context = _CONTEXT.get()
        if context is None or context.trial is not self or context.action != action or context.job_id != identifier:
            _fail()
        job = self._valid(identifier)
        required = {'auto-story': 'needs_script', 'prepare': 'script_review', 'submit': 'quoted',
                    'check': 'generating', 'render': 'clips_review'}
        if job['state'] != required[action]:
            _fail()
        with self.journal() as row:
            if row['job_id'] is None and action == 'auto-story':
                row['job_id'] = identifier
            if row['job_id'] != identifier:
                _fail()
            maximum = 60 if action == 'check' else 1
            if row['calls'].get(action, 0) >= maximum:
                _fail()
            if action != 'auto-story' and row['outcomes'].get('auto-story') != 'success':
                _fail()
            if action in {'prepare', 'submit'} and row['script']['state'] != 'reported':
                _fail()
            if action == 'submit':
                scenes = job.get('scenes', [])
                total = sum((_money(scene['quote_usd']) for scene in scenes), Decimal(0))
                if (len(scenes) != 1 or any(scene.get('state') != 'not_submitted' for scene in scenes)
                        or total != _money(job['quote_total_usd']) or total > Decimal('2.75')
                        or total+Decimal('.25') > Decimal('3') or row['video']['state'] != 'unspent'
                        or row['outcomes'].get('prepare') != 'success'):
                    _fail()
                row['video'].update(state='reserved', reserved_usd=str(total))
            row['calls'][action] = row['calls'].get(action, 0)+1
            row['outcomes'][action] = 'started_or_unknown'
        try:
            result = method(*args, **kwargs)
            self._valid(identifier)
        except BaseException:
            # Keep claimed calls and quote exposure. No retries, refunds, or
            # modification of the product's own failed/unknown ledger entries.
            with self.journal() as row:
                row['outcomes'][action] = 'failed_or_unknown'
            raise
        with self.journal() as row:
            row['outcomes'][action] = 'success'
        return result

    def wrap(self, normal_app, authenticated_app):
        return _Requests(self, normal_app, authenticated_app)


class _Requests:
    def __init__(self, trial, normal_app, authenticated_app):
        self.trial, self.normal, self.authenticated = trial, normal_app, authenticated_app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.normal(scope, receive, send)
        path = scope['path']
        authentication = scope['method'] == 'POST' and path == _AUTHENTICATE
        archive = scope['method'] == 'POST' and path == _ARCHIVE
        status = scope['method'] == 'GET' and path == _STATUS
        matched = _ACTION.fullmatch(path)
        if not (authentication or archive or status) and (scope['method'] != 'POST'
                or (path != '/api/studio/characters/auto-story' and matched is None)):
            return await self.normal(scope, receive, send)
        try:
            if not status and _now() >= datetime.fromisoformat(self.trial.policy['expires_at']):
                _fail()
            if authentication or archive or status:
                identifier, action = None, 'authenticate' if authentication else 'archive' if archive else 'status'
            elif matched:
                identifier, action = matched.groups()
            else:
                headers = {k.lower(): v for k, v in scope.get('headers', [])}
                if headers.get(b'content-type', b'').split(b';')[0] != b'application/x-www-form-urlencoded':
                    _fail()
                body = b''
                while True:
                    message = await receive()
                    if message['type'] != 'http.request':
                        _fail()
                    body += message.get('body', b'')
                    if len(body) > 65536:
                        _fail()
                    if not message.get('more_body'):
                        break
                values = parse_qs(body.decode('utf8'), keep_blank_values=True)
                if len(values.get('job_id', [])) != 1:
                    _fail()
                identifier, action = values['job_id'][0], 'auto-story'
                delivered = False
                original_receive = receive
                async def receive():
                    nonlocal delivered
                    if delivered:
                        return await original_receive()
                    delivered = True
                    return {'type': 'http.request', 'body': body, 'more_body': False}
            if not (authentication or archive or status):
                self.trial._valid(identifier)
        except (CharacterError, ValueError, TypeError, OSError):
            await send({'type': 'http.response.start', 'status': 403,
                        'headers': [(b'content-type', b'text/plain; charset=utf-8')]})
            return await send({'type': 'http.response.body', 'body': b'Character trial scope denied; no retry.'})
        token = _CONTEXT.set(SimpleNamespace(trial=self.trial, action=action, job_id=identifier))
        try:
            # The existing authenticated application must run before any service
            # invocation/claim. No cookie, bootstrap token, CSRF or Origin bypass.
            return await self.authenticated(scope, receive, send)
        finally:
            _CONTEXT.reset(token)


def _register_routes(app, trial):
    # Small synthetic controller tests need no FastAPI router. The real app keeps
    # its original middleware, and these handlers are reached only after it.
    if not callable(getattr(app, 'add_api_route', None)):
        return

    async def authenticate(request: Request):
        try:
            form = await request.form()
            result = trial.authenticate(consent=form.getlist('consent') == ['true'])
        except (CharacterError, CredentialError, OSError):
            return JSONResponse({'ok': False, 'code': 'scope_denied',
                                 'message': '이번 연결 확인은 허용되지 않습니다. 자동 재시도하지 않습니다.'},
                                status_code=409)
        return JSONResponse({'ok': result.ok, 'code': result.code, 'message': result.message})

    async def status():
        try:
            return JSONResponse(trial.status())
        except (CharacterError, CredentialError, OSError, ValueError, TypeError):
            return JSONResponse({'ready': False, 'reasons': ['이번 연결 확인 상태를 읽지 못했습니다.'],
                                 'model': CLAUDE, 'keyConfigured': False,
                                 'authenticationVerified': False, 'authAttempted': True,
                                 'archiveReady': False, 'unknownCount': 0, 'archivedCount': 0}, status_code=403)

    async def archive(request: Request):
        try:
            form = await request.form()
            return JSONResponse(trial.archive(consent=form.getlist('consent') == ['true']))
        except Exception:
            return JSONResponse({'ok': False, 'code': 'archive_denied',
                                 'message': '검토한 기록을 정리하지 못했습니다. 자동 재시도하지 않습니다.'},
                                status_code=409)

    app.add_api_route(_AUTHENTICATE, authenticate, methods=['POST'], include_in_schema=False)
    app.add_api_route(_STATUS, status, methods=['GET'], include_in_schema=False)
    app.add_api_route(_ARCHIVE, archive, methods=['POST'], include_in_schema=False)


def install(app, profile, policy, nativefactory, unknown_review=None):
    """Configure one scope. nativefactory is the captured original DPAPI class.

    Global NoNativeCipher replacements remain unchanged. The returned native
    object stays behind two entropy- and request-context-limited read wrappers.
    """
    service = app.state.character
    if getattr(service, '_approved_character_trial', None) is not None:
        _fail()
    trial = Trial(service, profile, policy, unknown_review)
    native = nativefactory()  # Does not decrypt any value or change the global factory.
    claude_cipher = _ReadOnlyCipher(trial, native, 'claude', AnthropicKeyStore.ENTROPY)
    video_cipher = _ReadOnlyCipher(trial, native, 'video', VideoAIKeyStore.ENTROPY)
    keys = _ClaudeStore(trial.profile, claude_cipher)
    video_keys = _VideoStore(trial.profile, video_cipher)
    for store, provider in ((keys, 'claude'), (video_keys, 'video')):
        store._trial, store._provider = trial, provider
    service.keys, service.video_keys = keys, video_keys
    service.writer = CharacterWriter(keys.key)
    service.budget = _Budget(trial, service.budget)
    original_video = service.video_for
    def video_for(job):
        trial.active('video', job['id'])
        return _Client(trial, original_video(job), job['id'])
    service.video_for = video_for
    for name, action in (('write', 'auto-story'), ('prepare', 'prepare'), ('submit', 'submit'),
                         ('check', 'check'), ('render', 'render')):
        original = getattr(service, name)
        def bounded(identifier, *args, _method=original, _action=action, **kwargs):
            return trial.invoke(_action, identifier,
                                lambda: _method(identifier, *args, **kwargs))
        setattr(service, name, bounded)
    service._approved_character_trial = trial
    _register_routes(app, trial)
    return trial
