"""Same-user private restored-profile validation; never an operating data adoption.

Only fixed per-user destination paths, authenticated local reads and opaque
credential copies are enabled. Production Guard/DPAPI implementations are untouched.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from .lifecycle import Blocked, ordinary_absolute, fixed_port


def restored_paths():
    # The host desktop can virtualize LOCALAPPDATA. This private installation
    # intentionally uses the real current Windows user home, not that variable.
    base = ordinary_absolute(Path.home() / 'AppData/Local/NewsFlowAI-BAT')
    return base, ordinary_absolute(base / 'v1')


def load_restored(root, layout):
    from .windows_live import ValidationConfig
    base, profile = restored_paths()
    source = ordinary_absolute(base / 'launch.json')
    if source.stat().st_size > 4096:
        raise Blocked('restored-launch-config-size')
    content = source.read_bytes()
    if hashlib.sha256(content).hexdigest() != layout.get('validationConfigSha256'):
        raise Blocked('restored-launch-integrity')
    raw = json.loads(content)
    if (raw.get('schemaVersion') != 2 or raw.get('profileKind') != 'restored-private-validation'
            or raw.get('readOnly') is not True or raw.get('decryptCredentials') is not False
            or type(raw.get('openBrowser')) is not bool
            or not re.fullmatch('[a-f0-9]{32}', raw.get('installationId', ''))):
        raise Blocked('restored-readonly-config-required')
    if ordinary_absolute(Path(raw['programRoot'])) != root:
        raise Blocked('restored-program-identity')
    return ValidationConfig(root, profile, fixed_port(raw['port']), raw['installationId'],
                            raw['openBrowser'], 'restored-private-validation')


def check_restored_profile(config, owner_sid):
    marker = ordinary_absolute(config.profile / 'restored-install.private.json')
    if marker.stat().st_size > 4096:
        raise Blocked('restored-profile-marker-size')
    value = json.loads(marker.read_bytes())
    if (value.get('installationId') != config.installation_id
            or value.get('ownerSid') != owner_sid or value.get('opaqueCredentialsOnly') is not True
            or not re.fullmatch('[a-f0-9]{64}', value.get('sourceDbSha256', ''))):
        raise Blocked('restored-profile-owner-or-identity')
    if not ordinary_absolute(config.profile / 'newsflow.db').is_file():
        raise Blocked('restored-database-missing')


class RestoredRequests:
    """Read-only validation; no collection, provider/OAuth, scheduler or posting UI writes."""
    READS = {'/__local/connect', '/__local/connect.js', '/api/studio/workspace',
             '/api/studio/production-context', '/api/feed-batches', '/api/samples',
             '/api/studio/local-voices', '/api/studio/system-startup'}
    MODULES = {'news','shorts','characters','images','automation','library','publishing',
               'analytics','settings','onboarding'}
    MEDIA = re.compile(r'/(?:video/jobs/[0-9]+/(?:file|thumbnail)|image-posts/[0-9]+/file|'
                       r'image-studio/[0-9]+/file|api/studio/characters/[a-f0-9]{32}/reference|'
                       r'character/[a-f0-9]{32}/(?:reference|file)|'
                       r'video/tts/voices/[A-Za-z0-9_-]+/sample|voices/preview/preview-[A-Za-z0-9_.-]+)\Z')
    def __init__(self, app):
        self.app = app
        self.refused = 0
    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        method, path = scope['method'], scope['path']
        read = (path in self.READS or path.startswith(('/studio/', '/static/'))
                or path.removeprefix('/api/studio/modules/') in self.MODULES
                   and path.startswith('/api/studio/modules/') or self.MEDIA.fullmatch(path))
        allowed = method in {'GET','HEAD'} and read or method == 'POST' and path == '/__local/claim'
        if not allowed:
            self.refused += 1
            await send({'type':'http.response.start','status':403,
                        'headers':[(b'content-type',b'text/plain'),(b'cache-control',b'no-store')]})
            return await send({'type':'http.response.body','body':b'Restored profile: read-only validation.'})
        return await self.app(scope, receive, send)


def disable_credential_decryption():
    # Validation-process-only deny capability: status()/ciphertext hashing still
    # work. No real native cipher is constructed and no stored key is decrypted.
    from newsflow.oauth import vault, production_dpapi
    state = {'nativeCipherRequests': 0}
    class NoNativeCipher:
        def __init__(self, *args, **kwargs):
            state['nativeCipherRequests'] += 1
            raise vault.VaultError()
    vault._DPAPI = NoNativeCipher
    production_dpapi._DPAPI = NoNativeCipher
    return state
