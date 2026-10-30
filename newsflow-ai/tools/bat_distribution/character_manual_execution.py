"""Manual, per-execution character video routes using existing product approvals.

Opt-in by a reviewed install layout; no story writer, scheduler, key mutation,
global provider access, new cumulative budget or implicit retry is introduced.
"""
from __future__ import annotations
from contextvars import ContextVar
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from threading import Lock
import re

from newsflow.character.service import CharacterService, digest, fingerprint
from newsflow.character.kling import KlingClient, check as settings_for
from newsflow.character.higgsfield_client import amount
from newsflow.video.ai.download import safe_url
from newsflow.video_models.catalog import CATALOG
from newsflow.character.schema import CharacterError
from .character_quote_only import _Store, _ReadOnlyCipher, _unlinked
from .lifecycle import Blocked

PATH = re.compile(r'/character/([a-f0-9]{32})/(submit|check|diagnose)\Z')
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
        context = self.scope.context()
        action = context['request'][2]
        if action not in {'submit', 'check'}:
            _deny()
        job = self.scope.local.read(context['job_id'])
        matches = [scene for scene in job.get('scenes', [])
                   if scene.get('state') == 'submitting'
                   and scene.get('idempotency_key') == idempotency_key
                   and scene.get('payload') == payload]
        if len(matches) != 1:
            _deny()
        scene = matches[0]
        if action == 'check':
            self.scope.approved_episode(job)
            receipt = context['continuations'].get(scene['position'])
            if (job['state'] not in {'generating', 'scene_review', 'status_or_download_failed'}
                    or context['initial_states'].get(scene['position']) != 'waiting_dependency'
                    or any(value in {'unknown', 'submitting'} for value in context['initial_states'].values())
                    or not receipt or receipt.get('quote') is None
                    or payload != receipt['payload']
                    or scene.get('dependency') != receipt['dependency']
                    or scene.get('execution_quote_usd') != str(receipt['quote'])
                    or amount(receipt['quote']) > amount(scene['quote_usd'])
                    or idempotency_key != f'{job["id"]}-s{scene["position"]}-t{scene["attempt"]}'):
                _deny()
            self.scope.parent_frame(job, scene, receipt['frame'])
        elif job['state'] != 'generating':
            _deny()
        elif job.get('automation_version') == 1:
            self.scope.approved_episode(job)
            if (scene.get('continuity') != 'cut'
                    or context['initial_states'].get(scene['position']) != 'not_submitted'
                    or idempotency_key != f'{job["id"]}-s{scene["position"]}-t{scene["attempt"]}'):
                _deny()
        # A shared request-local lock also protects concurrent cut dispatch.
        with context['claims_lock']:
            if idempotency_key in context['submitted']:
                _deny()
            context['submitted'].add(idempotency_key)
        return self.original.submit_scene(payload, idempotency_key)

    def check(self, handle):
        context = self.scope.context('check')
        job = self.scope.local.read(context['job_id'])
        episode = job.get('automation_version') == 1
        states = {'submitted', 'downloading'} if episode else {'submitted'}
        job_states = {'generating', 'scene_review', 'submission_unknown', 'status_or_download_failed'} if episode else {'generating', 'scene_review'}
        matches = [scene for scene in job.get('scenes', [])
                   if scene.get('state') in states and scene.get('handle') == handle]
        if job['state'] not in job_states or len(matches) != 1:
            _deny()
        position = matches[0]['position']
        if position in context['statuses']:
            _deny()
        context['statuses'][position] = None  # Claim before a possibly failing read.
        status = self.original.check(handle)
        context['statuses'][position] = status
        return status

    def diagnose(self, handle, *, protected=()):
        context = self.scope.context('diagnose')
        job = self.scope.local.read(context['job_id'])
        from newsflow.character.status_diagnostics import TERMINAL
        matches = [scene for scene in job.get('scenes', [])
                   if scene.get('state') in TERMINAL and scene.get('handle') == handle]
        if job['state'] != 'scene_review' or len(matches) != 1:
            _deny()
        position = matches[0]['position']
        if position in context['statuses']:
            _deny()
        context['statuses'][position] = 'observing'
        return self.original.diagnose(handle, protected=protected)

    def fetch(self, status, target, cancel):
        context = self.scope.context('check')
        job = self.scope.local.read(context['job_id'])
        folder = self.scope.local.folder(context['job_id'])
        target = _unlinked(target)
        episode = job.get('automation_version') == 1
        def filename(scene):
            suffix = f'-t{scene["attempt"]}' if episode and scene['attempt'] > 1 else ''
            return f'scene-{scene["position"]}{suffix}.mp4'
        matches = [scene for scene in job.get('scenes', [])
                   if scene.get('state') == 'downloading'
                   and target == folder / filename(scene)
                   and context['statuses'].get(scene['position']) is status]
        job_states = {'generating', 'scene_review', 'submission_unknown', 'status_or_download_failed'} if episode else {'generating', 'scene_review'}
        if (job['state'] not in job_states or len(matches) != 1 or target in context['fetched']
                or target.exists() or status.state != 'completed'):
            _deny()
        context['fetched'].add(target)
        return self.original.fetch(status, target, cancel)

    def upload_reference(self, path):
        context = self.scope.context('check')
        job = self.scope.local.read(context['job_id'])
        self.scope.approved_episode(job)
        matches = [scene for scene in job['scenes'] if scene['state'] == 'preparing_dependency'
                   and context['initial_states'].get(scene['position']) == 'waiting_dependency']
        if len(matches) != 1:
            _deny()
        scene = matches[0]
        if (scene['position'] in context['continuations']
                or fingerprint(scene['payload']) != scene['approved_template_hash']
                or any(value in {'unknown', 'submitting'} for value in context['initial_states'].values())):
            _deny()
        dependency = self.scope.parent_frame(job, scene, path)
        receipt = {'frame': _unlinked(path), 'dependency': dependency, 'quote': None}
        context['continuations'][scene['position']] = receipt  # Never retry this upload within a check.
        public = safe_url(self.original.upload_reference(path))
        field = CATALOG.model(job['model']).get('continuation_param')
        if not field:
            _deny()
        receipt['payload'] = {**scene['payload'], field: public}
        return public

    def estimate(self, payload):
        context = self.scope.context('check')
        job = self.scope.local.read(context['job_id'])
        self.scope.approved_episode(job)
        matches = [scene for scene in job['scenes'] if scene['state'] == 'preparing_dependency'
                   and context['continuations'].get(scene['position'], {}).get('payload') == payload]
        if len(matches) != 1:
            _deny()
        scene = matches[0]
        receipt = context['continuations'][scene['position']]
        if receipt.get('estimate_attempted'):
            _deny()
        self.scope.parent_frame(job, scene, receipt['frame'])
        receipt['estimate_attempted'] = True
        price = amount(self.original.estimate(payload))
        receipt['quote'] = str(price)
        # Product EpisodeFlow compares the new price to the approved scene quote.
        # A higher quote is returned, not clamped or silently approved.
        return str(price)


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

    def approved_episode(self, job):
        from newsflow.character.episode_service import EpisodeFlow
        if (job.get('automation_version') != 1 or job.get('id') != self.active()
                or job.get('approved_plan_hash') != job.get('plan_hash')
                or job.get('plan_hash') != self.local.plan_hash(job)
                or job.get('script_approval', {}).get('sha256') != fingerprint(job.get('script'))
                or not job.get('quote_approvals')
                or hashlib.sha256(self.keys.key().encode()).hexdigest() != job.get('quote_key_id')):
            _deny()
        exposure = sum((amount(row['usd']) for row in job['quote_approvals']), Decimal(0))
        exposure += EpisodeFlow.text_exposure(job)
        if exposure > amount(job['episode_limit']):
            _deny()

    def parent_frame(self, job, scene, path):
        """Only this approved continuation's owned, completed parent's frame."""
        if (scene.get('continuity') != 'continue' or type(scene.get('from')) is not int
                or not 1 <= scene['from'] < scene['position']):
            _deny()
        parent = job['scenes'][scene['from'] - 1]
        folder = self.local.folder(job['id'])
        expected = folder / 'frames' / f'scene-{parent["position"]}-t{parent["attempt"]}-last.png'
        suffix = f'-t{parent["attempt"]}' if parent['attempt'] > 1 else ''
        clip = folder / f'scene-{parent["position"]}{suffix}.mp4'
        if (parent['position'] != scene['from'] or parent['state'] != 'downloaded'
                or parent.get('file') != clip.name or _unlinked(path) != expected
                or not _unlinked(clip).is_file() or digest(clip) != parent.get('sha256')
                or not expected.is_file() or digest(expected) != parent.get('last_frame_sha256')):
            _deny()
        return {'position': parent['position'], 'attempt': parent['attempt'],
                'clip_sha256': parent['sha256'], 'frame_sha256': parent['last_frame_sha256']}

    def video_for(self, job):
        identifier = self.active()
        if job.get('id') != identifier:
            _deny()
        settings = settings_for(job['studio_selection'])
        return _Client(self, KlingClient(self.keys.key, settings))

    def execute(self, action, identifier, *, consent=False, quote_hash=''):
        if action not in {'submit', 'check', 'diagnose'} or _REQUEST.get() != (self, identifier, action):
            _deny()
        self.local.consent(consent)
        # Product methods own the lock, quote approval, per-execution cap,
        # pre-submit state journal, status/download transitions and no replay.
        job = self.local.read(identifier)
        settings = settings_for(job['studio_selection'])
        if (job.get('plan_hash') != self.local.plan_hash(job)
                or digest(_unlinked(self.local.folder(identifier)/'reference.png')) != job['reference_sha256']):
            _deny()
        token = _ACTIVE.set({'request': (self, identifier, action), 'job_id': identifier,
                             'submitted': set(), 'statuses': {}, 'fetched': set(),
                             'initial_states': {row['position']: row['state'] for row in job.get('scenes', [])},
                             'continuations': {}, 'claims_lock': Lock()})
        try:
            if action == 'submit':
                return CharacterService.submit(self.local, identifier, consent=True, quote_hash=quote_hash)
            if action == 'diagnose':
                return CharacterService.diagnose(self.local, identifier, consent=True)
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
    for action in ('submit', 'check', 'diagnose'):
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
