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
