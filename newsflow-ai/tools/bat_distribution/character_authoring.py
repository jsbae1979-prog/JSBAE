"""Authenticated, per-request character authoring in the local operating profile.

Only registered-character analysis, topics, and v1 episode scripts are connected.
The product authoring/budget ledger remains authoritative. No global credential
decryption, environment fallback, background work, or video authority is granted.
"""
from __future__ import annotations

from contextvars import ContextVar
import hashlib
from pathlib import Path
import re
from urllib.parse import parse_qs

from newsflow.character.authoring import (
    AuthoringAI, AnalysisResult, TopicResponse, CHARACTER_ANALYSIS_INSTRUCTION,
    TOPIC_INSTRUCTION, provider_for_model,
)
from newsflow.character.schema import CharacterError
from newsflow.intelligence.api_settings import APIBudgetService
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, CredentialError

ANALYZE = '/api/studio/characters/profiles/analyze'
AUTO_STORY = '/api/studio/characters/auto-story'
TOPICS = re.compile(r'/api/studio/characters/profiles/(char_[a-f0-9]{32})/topics/generate\Z')
WRITE = re.compile(r'/character/([a-f0-9]{32})/write\Z')
_ID = re.compile(r'[a-f0-9]{32}\Z')
_REQUEST_ID = re.compile(r'[A-Za-z0-9:._-]{1,64}\Z')
_REQUEST = ContextVar('newsflow_character_authoring_request', default=None)
_KEY_USE = ContextVar('newsflow_character_authoring_key_use', default=None)


def _deny():
    raise CharacterError('blocked')


def _unlinked(path):
    from newsflow.distribution.windows_profile import unlinked
    return unlinked(Path(path))


class _Store:
    """One current-profile DPAPI file; never consult the process environment."""
    def __init__(self, owner, provider, kind, native):
        self.owner, self.provider, self.kind, self.native = owner, provider, kind, native
        self.path = owner.profile / kind.FILE

    def _source(self):
        try:
            path = _unlinked(self.path)
            if (path != self.owner.profile / self.kind.FILE or not path.is_file()
                    or path.stat().st_nlink != 1 or not 0 < path.stat().st_size <= 8192):
                raise ValueError
            return path
        except Exception:
            raise CredentialError('현재 사용자 프로필에 저장된 API 키를 확인하세요.') from None

    def status(self):
        try:
            self._source()
            stored = True
        except CredentialError:
            stored = False
        return {'configured': stored, 'stored': stored, 'source': 'stored' if stored else None,
                'environment': False, 'storage_supported': True}

    def key(self):
        self.owner.active_key(self.provider)
        plain = payload = None
        try:
            payload = bytearray(self._source().read_bytes())
            if not 0 < len(payload) <= 8192:
                raise ValueError
            entropy = bytearray(hashlib.sha256(self.kind.ENTROPY).digest())
            plain = self.native.unprotect(payload, entropy)
            if not isinstance(plain, bytearray) or not 0 < len(plain) <= 1024:
                raise ValueError
            return self.kind.validate(bytes(plain).decode('utf8'))
        except Exception:
            raise CredentialError('Windows 보호 저장소의 API 키를 확인하세요.') from None
        finally:
            if isinstance(plain, bytearray): plain[:] = b'\0' * len(plain)
            if isinstance(payload, bytearray): payload[:] = b'\0' * len(payload)

    def save(self, *args, **kwargs):
        raise CredentialError('제작 요청에는 키 저장 권한이 없습니다.')

    def clear(self):
        raise CredentialError('제작 요청에는 키 삭제 권한이 없습니다.')


class _Authoring(AuthoringAI):
    def __init__(self, owner, keys, budget, providers=None):
        self.owner = owner
        super().__init__(keys, budget, providers)

    def generate(self, instruction, payload, schema, options, *, provider, request_id,
                 consent=False, image_bytes=None, kind='script', max_reserved_usd=None, story_review=None):
        # A local capability failure must not be recorded as an unknown paid call.
        self.last_usage = self.last_candidate = self.last_reservation = None
        self.last_reserved_usd = '0'
        self.response_received = False
        self.last_failure = {'stage': 'preflight', 'dispatched': False, 'response_received': False}
        context = self.owner.request()
        if consent is not True or provider_for_model(options.model) != provider:
            _deny()
        action = context['action']
        if action == 'analysis':
            valid = (instruction == CHARACTER_ANALYSIS_INSTRUCTION and schema is AnalysisResult
                     and kind == 'analysis' and isinstance(image_bytes, bytes))
        elif action == 'topics':
            valid = (instruction == TOPIC_INSTRUCTION and schema is TopicResponse
                     and kind == 'script' and image_bytes is None)
        else:
            from newsflow.character.episode_story import SCRIPT_INSTRUCTION, EpisodeScript
            job = self.owner.service.read(context['job_id'])
            valid = (instruction == SCRIPT_INSTRUCTION and schema is EpisodeScript and kind == 'script'
                     and image_bytes is None and max_reserved_usd is not None
                     and job.get('automation_version') == 1 and job.get('state') == 'writing'
                     and request_id == f"episode:{context['job_id']}:script:{job.get('script_request_sequence')}"
                     and options.model == job['studio_selection']['script_model']
                     and provider == job['script_provider'])
        if action in {'analysis', 'topics'}:
            valid = valid and request_id == context['request_id'] and options.model == context['model']
        if not valid:
            _deny()
        token = _KEY_USE.set((self.owner, context, provider))
        try:
            return super().generate(instruction, payload, schema, options, provider=provider,
                request_id=request_id, consent=consent, image_bytes=image_bytes, kind=kind,
                max_reserved_usd=max_reserved_usd, story_review=story_review)
        finally:
            _KEY_USE.reset(token)


class CharacterAuthoring:
    def __init__(self, service, profile, nativefactory, *, budget=None, providers=None):
        self.profile, self.service = _unlinked(profile), service
        if (not self.profile.is_absolute() or not self.profile.is_dir()
                or _unlinked(service.root) != self.profile / 'character'):
            _deny()
        native = nativefactory()
        keys = {provider: _Store(self, provider, kind, native) for provider, kind in
                (('claude_api', AnthropicKeyStore), ('openai', AIKeyStore))}
        self.authoring = _Authoring(self, keys, budget or APIBudgetService(service.sessions), providers)

    def request(self):
        context = _REQUEST.get()
        if not isinstance(context, dict) or context.get('owner') is not self:
            _deny()
        return context

    def active_key(self, provider):
        context = self.request()
        if _KEY_USE.get() != (self, context, provider):
            _deny()

    def wrap(self, normal_app, authenticated_app):
        return _Requests(self, normal_app, authenticated_app)


class _Requests:
    def __init__(self, owner, normal, authenticated):
        self.owner, self.normal, self.authenticated = owner, normal, authenticated

    async def __call__(self, scope, receive, send):
        path = scope.get('path', '')
        topic = TOPICS.fullmatch(path)
        write = WRITE.fullmatch(path)
        if (scope.get('type') != 'http' or scope.get('method') != 'POST'
                or not (path in {ANALYZE, AUTO_STORY} or topic or write)):
            return await self.normal(scope, receive, send)
        try:
            headers = {key.lower(): value for key, value in scope.get('headers', [])}
            if headers.get(b'content-type', b'').split(b';')[0] != b'application/x-www-form-urlencoded':
                _deny()
            body = b''
            while True:
                message = await receive()
                if message['type'] != 'http.request': _deny()
                body += message.get('body', b'')
                if len(body) > 65536: _deny()
                if not message.get('more_body'): break
            values = parse_qs(body.decode('utf8'), keep_blank_values=True)
            def one(name):
                items = values.get(name, [])
                if len(items) != 1: _deny()
                return items[0]
            if one('consent') != 'true': _deny()
            context = {'owner': self.owner}
            legacy = False
            if path == ANALYZE or topic:
                model, request_id = one('model'), one('request_id')
                provider_for_model(model)
                if not _REQUEST_ID.fullmatch(request_id): _deny()
                context.update(action='analysis' if path == ANALYZE else 'topics',
                               model=model, request_id=request_id)
                if topic: context['character_id'] = topic.group(1)
            else:
                identifier = write.group(1) if write else one('job_id')
                if not _ID.fullmatch(identifier): _deny()
                if write and 'job_id' in values and values['job_id'] != [identifier]: _deny()
                job = self.owner.service.read(identifier)
                legacy = job.get('automation_version') != 1
                context.update(action='script', job_id=identifier)
        except (CharacterError, CredentialError, UnicodeError, ValueError, OSError):
            await send({'type': 'http.response.start', 'status': 403, 'headers': []})
            return await send({'type': 'http.response.body', 'body': b'Character authoring scope denied.'})

        delivered = False
        async def replay():
            nonlocal delivered
            if delivered: return await receive()
            delivered = True
            return {'type': 'http.request', 'body': body, 'more_body': False}
        if legacy:
            return await self.normal(scope, replay, send)
        token = _REQUEST.set(context)
        try:
            # Original request and body still pass LocalAccess, Origin and CSRF.
            # No provider or credential is used until that authenticated route runs.
            return await self.authenticated(scope, replay, send)
        finally:
            _REQUEST.reset(token)


def install(app, profile, nativefactory):
    service = app.state.character
    if (getattr(service, '_character_authoring_connection', None) is not None
            or getattr(service, '_approved_character_trial', None) is not None
            or getattr(app.state, 'character_authoring', None) is not None
            or _unlinked(app.state.config.data_dir) != _unlinked(profile)):
        _deny()
    connection = CharacterAuthoring(service, profile, nativefactory)
    app.state.character_authoring = connection.authoring
    service._character_authoring_connection = connection
    return connection
