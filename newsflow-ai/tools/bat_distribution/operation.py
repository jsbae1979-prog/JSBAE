"""Explicit same-user local operation, with external execution still disabled.

This is independent of the old read-only and synthetic policies. It never adopts
an arbitrary profile, opens a key, starts a schedule, or grants paid execution.
"""
import hashlib
import json
import re
from pathlib import Path
from .lifecycle import Blocked, ordinary_absolute, fixed_port
from .restored_install import restored_paths
from .local_work import LocalWorkRequests


def load_operating(root, layout):
    from .windows_live import ValidationConfig
    if (layout.get('localOperationConnected') is not True
            or layout.get('validationOnly') is not False
            or layout.get('operatingProfile') != 'restored-local-operation'
            or layout.get('updatesEnabled') is not False):
        raise Blocked('local-operation-not-provisioned')
    base, profile = restored_paths()
    source = ordinary_absolute(base / 'launch.json')
    if source.stat().st_size > 4096:
        raise Blocked('operating-config-size')
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != layout.get('validationConfigSha256'):
        raise Blocked('operating-config-integrity')
    raw = json.loads(content)
    if (raw.get('schemaVersion') != 2
            or raw.get('profileKind') != 'restored-local-operation'
            or raw.get('readOnly') is not False
            or raw.get('decryptCredentials') is not False
            or raw.get('automaticJobsEnabled') is not False
            or raw.get('externalExecutionEnabled') is not False
            or type(raw.get('openBrowser')) is not bool
            or not re.fullmatch('[a-f0-9]{32}', raw.get('installationId', ''))):
        raise Blocked('local-operation-boundaries-required')
    if ordinary_absolute(Path(raw['programRoot'])) != root:
        raise Blocked('operating-program-identity')
    return ValidationConfig(root, profile, fixed_port(raw['port']), raw['installationId'],
                            raw['openBrowser'], 'restored-local-operation')


class OperatingRequests(LocalWorkRequests):
    """Local drafts/settings only; preserve inner authentication and CSRF.

    No fake transport is injected into real data. Collection, live providers,
    credential writes, OAuth, scheduler activation and SNS remain unavailable
    until separately authorized. Offline script edits retain revision checks.
    """
    POSTS = LocalWorkRequests.POSTS - {'/collection'} | {'/ai-settings/prices'}

    # Only cached capability data and local settings writes are enabled here.
    # Provider story/quote/submit routes remain outside the operation boundary.
    READS = (LocalWorkRequests.READS - {'/api/samples'}) | {'/api/studio/video-models'}
    CHARACTER_SETTINGS = re.compile(r'/api/studio/characters/[a-f0-9]{32}/settings\Z')
    CHARACTER_VISIBILITY = re.compile(r'/api/studio/characters/[a-f0-9]{32}/visibility\Z')
    COPIED_MEDIA = re.compile(r'/api/samples/[a-z0-9-]{1,48}/copy-file\Z')
    CHARACTER_CLIP = re.compile(r'/character/[a-f0-9]{32}/clips/[1-5]\Z')

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            method, path = scope['method'], scope['path']
            local_settings = method == 'POST' and (self.CHARACTER_SETTINGS.fullmatch(path)
                                                  or self.CHARACTER_VISIBILITY.fullmatch(path))
            copied_media = method in {'GET', 'HEAD'} and (self.COPIED_MEDIA.fullmatch(path) or self.CHARACTER_CLIP.fullmatch(path))
            if local_settings or copied_media:
                # self.app remains LocalAccess(original_app, session); inner
                # signed CSRF, Origin, ownership and file checks are unchanged.
                return await self.app(scope, receive, send)
        return await super().__call__(scope, receive, send)
