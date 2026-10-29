"""Manual, per-execution character video routes using existing product approvals.

Opt-in by a reviewed install layout; no story writer, scheduler, key mutation,
global provider access, new cumulative budget or implicit retry is introduced.
"""
from __future__ import annotations
from contextvars import ContextVar
import json
from pathlib import Path
import re

from newsflow.character.service import CharacterService, digest
from newsflow.character.kling import KlingClient, K3, O3, check as settings_for
from newsflow.character.schema import CharacterError
from .character_quote_only import _Store, _ReadOnlyCipher, _unlinked
from .lifecycle import Blocked

PATH = re.compile(r'/character/([a-f0-9]{32})/(submit|check)\Z')
_REQUEST = ContextVar('newsflow_manual_character_request', default=None)
_ACTIVE = ContextVar('newsflow_manual_character_active', default=None)


def _deny():
    raise CharacterError('blocked')


def enabled(config):
    """An absent flag leaves the previously approved quote-only mode intact."""
    if config.profile_kind not in {'restored-local-operation', 'portable-local-operation'}:
        return False
    value = json.loads((config.program/'app/layout.json').read_bytes()).get(
        'manualCharacterVideoExecutionEnabled', False)
    if type(value) is not bool:
        raise Blocked('manual-character-configuration')
    return value


class _Client:
    def __init__(self, scope, original):
        self.scope, self.original = scope, original

    def credential(self):
        self.scope.active()
        return self.original.credential()

    def submit_scene(self, payload, idempotency_key):
        context = self.scope.context('submit')
        job = self.scope.local.read(context['job_id'])
        matches = [scene for scene in job.get('scenes', [])
                   if scene.get('state') == 'submitting'
                   and scene.get('idempotency_key') == idempotency_key
                   and scene.get('payload') == payload]
        if job['state'] != 'generating' or len(matches) != 1 or idempotency_key in context['submitted']:
            _deny()
        # Product service has already persisted `submitting` before this call.
        context['submitted'].add(idempotency_key)
        return self.original.submit_scene(payload, idempotency_key)

    def check(self, handle):
        context = self.scope.context('check')
        job = self.scope.local.read(context['job_id'])
        matches = [scene for scene in job.get('scenes', [])
                   if scene.get('state') == 'submitted' and scene.get('handle') == handle]
        if job['state'] != 'generating' or len(matches) != 1:
            _deny()
        position = matches[0]['position']
        if position in context['statuses']:
            _deny()
        status = self.original.check(handle)
        context['statuses'][position] = status
        return status

    def fetch(self, status, target, cancel):
        context = self.scope.context('check')
        job = self.scope.local.read(context['job_id'])
        folder = self.scope.local.folder(context['job_id'])
        target = _unlinked(target)
        matches = [scene for scene in job.get('scenes', [])
                   if scene.get('state') == 'downloading'
                   and target == folder/f'scene-{scene["position"]}.mp4'
                   and context['statuses'].get(scene['position']) is status]
        if (job['state'] != 'generating' or len(matches) != 1 or target in context['fetched']
                or status.state != 'completed'):
            _deny()
        context['fetched'].add(target)
        return self.original.fetch(status, target, cancel)

    def upload_reference(self, *args, **kwargs):
        _deny()

    def estimate(self, *args, **kwargs):
        _deny()


class ManualExecution:
    def __init__(self, service, profile, nativefactory):
        self.profile = _unlinked(profile)
        if (not self.profile.is_absolute() or not self.profile.is_dir()
                or _unlinked(service.root) != self.profile/'character'):
            _deny()
        self.local = CharacterService.__new__(CharacterService)
        self.local.root = service.root
        self.local.ffmpeg = getattr(service, 'ffmpeg', None)
        self.local.ffprobe = getattr(service, 'ffprobe', None)
        self.local.video_for = self.video_for
        self.keys = _Store(self, _ReadOnlyCipher(self, nativefactory()))

    def context(self, action=None):
        requested, active = _REQUEST.get(), _ACTIVE.get()
        if (not isinstance(requested, tuple) or len(requested) != 3 or requested[0] is not self
                or not isinstance(active, dict) or active.get('request') != requested
                or (action is not None and requested[2] != action)):
            _deny()
        return active

    def active(self):
        return self.context()['job_id']

    def video_for(self, job):
        identifier = self.active()
        if job.get('id') != identifier:
            _deny()
        settings = settings_for(job['studio_selection'])
        if settings['video_model'] not in {K3, O3}:
            _deny()
        return _Client(self, KlingClient(self.keys.key, settings))

    def execute(self, action, identifier, *, consent=False, quote_hash=''):
        if action not in {'submit', 'check'} or _REQUEST.get() != (self, identifier, action):
            _deny()
        self.local.consent(consent)
        # Product methods own the lock, quote approval, per-execution cap,
        # pre-submit state journal, status/download transitions and no replay.
        job = self.local.read(identifier)
        settings = settings_for(job['studio_selection'])
        if (settings['video_model'] not in {K3, O3}
                or job.get('plan_hash') != self.local.plan_hash(job)
                or digest(_unlinked(self.local.folder(identifier)/'reference.png')) != job['reference_sha256']):
            _deny()
        token = _ACTIVE.set({'request': (self, identifier, action), 'job_id': identifier,
                             'submitted': set(), 'statuses': {}, 'fetched': set()})
        try:
            if action == 'submit':
                return CharacterService.submit(self.local, identifier, consent=True, quote_hash=quote_hash)
            return CharacterService.check(self.local, identifier, consent=True)
        finally:
            _ACTIVE.reset(token)

    def wrap(self, normal_app, authenticated_app):
        return _Requests(self, normal_app, authenticated_app)


class _Requests:
    def __init__(self, scope, normal, authenticated):
        self.scope, self.normal, self.authenticated = scope, normal, authenticated

    async def __call__(self, scope, receive, send):
        matched = PATH.fullmatch(scope.get('path', '')) if scope.get('type') == 'http' and scope.get('method') == 'POST' else None
        if not matched:
            return await self.normal(scope, receive, send)
        token = _REQUEST.set((self.scope, matched.group(1), matched.group(2)))
        try:
            return await self.authenticated(scope, receive, send)
        finally:
            _REQUEST.reset(token)


def install(app, profile, nativefactory):
    service = app.state.character
    if (getattr(service, '_manual_character_execution', None) is not None
            or getattr(service, '_approved_character_trial', None) is not None
            or _unlinked(app.state.config.data_dir) != _unlinked(profile)):
        _deny()
    manual = ManualExecution(service, Path(profile), nativefactory)
    for action in ('submit', 'check'):
        original = getattr(service, action)
        def wrapped(identifier, *args, _action=action, _original=original, **kwargs):
            if _REQUEST.get() == (manual, identifier, _action):
                if args:
                    _deny()
                return manual.execute(_action, identifier, **kwargs)
            return _original(identifier, *args, **kwargs)
        setattr(service, action, wrapped)
    service._manual_character_execution = manual
    service._manual_character_execution_enabled = True
    return manual
