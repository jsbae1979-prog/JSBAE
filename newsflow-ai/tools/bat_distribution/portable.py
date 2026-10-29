"""Fresh per-user ZIP bootstrap; never adopts the restored operating profile."""
import json
import secrets
from pathlib import Path
from .lifecycle import Blocked, ordinary_absolute, fixed_port


def portable_profile():
    return ordinary_absolute(Path.home() / 'AppData/Local/NewsFlowAI-BAT/portable-v1')


def load_portable(root, layout):
    from .windows_live import ValidationConfig
    if (layout.get('portableFirstRun') is not True or layout.get('validationOnly') is not False
            or layout.get('updatesEnabled') is not False):
        raise Blocked('portable-not-provisioned')
    # User-editable, non-secret connection data, deliberately outside immutable
    # program-file hashes. No profile/path/command/credential input is accepted.
    source = ordinary_absolute(root / 'connection.json')
    if source.stat().st_size > 1024:
        raise Blocked('portable-connection-size')
    raw = json.loads(source.read_bytes())
    if (set(raw) != {'schemaVersion','port','openBrowser'} or raw['schemaVersion'] != 1
            or type(raw['openBrowser']) is not bool):
        raise Blocked('portable-connection-fields')
    port = fixed_port(raw['port'])
    profile = portable_profile()
    marker = ordinary_absolute(profile / 'portable-install.private.json')
    identity = secrets.token_hex(16)
    if marker.is_file():
        if marker.stat().st_size > 4096:
            raise Blocked('portable-marker-size')
        value = json.loads(marker.read_bytes())
        import re
        if not re.fullmatch('[a-f0-9]{32}',value.get('installationId','')):
            raise Blocked('portable-marker-identity')
        identity = value['installationId']
    return ValidationConfig(root,profile,port,identity,raw['openBrowser'],'portable-local-operation')


def prepare_profile(config, create):
    from newsflow.distribution.windows_profile import current_sid, private_directory
    import win32security
    from .windows_live import _atomic
    profile = portable_profile()
    if config.profile != profile:
        raise Blocked('portable-fixed-user-profile-required')
    fresh = not profile.exists()
    if fresh and not create:
        raise Blocked('no-owned-session')
    if fresh:
        private_directory(profile.parent)
        private_directory(profile)
    else:
        private_directory(profile)
    sid = win32security.ConvertSidToStringSid(current_sid())
    expected = {'schemaVersion':1,'installationId':config.installation_id,
                'ownerSid':sid,'programRoot':str(config.program),'profileKind':'portable-local-operation'}
    marker = profile / 'portable-install.private.json'
    if fresh:
        _atomic(marker, expected)
    if not marker.is_file() or json.loads(marker.read_bytes()) != expected:
        raise Blocked('portable-existing-or-foreign-profile-refused')
    return sid
