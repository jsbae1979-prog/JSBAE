"""Fail-closed publisher-pinned offline update validation, never installation.

No publisher certificate is provisioned by this project. No synthetic signature
can enable real updates. Tests explicitly inject an untrusted stub verifier.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


class UpdateBlocked(ValueError):
    pass


def authenticode(path: Path):
    if os.name != 'nt':
        raise UpdateBlocked('Windows signature verifier required')
    script = Path(__file__).with_name('verify_authenticode.ps1')
    powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-File',str(script),
                             '-Artifact',str(path)],capture_output=True,timeout=30,check=False)
    if result.returncode:
        raise UpdateBlocked('signature verification failed')
    try:
        return json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError,UnicodeError):
        raise UpdateBlocked('invalid signature result') from None


def publisher_matches(path, expected, verifier):
    if not re.fullmatch(r'[0-9a-f]{64}',expected):
        raise UpdateBlocked('publisher certificate not provisioned')
    observed = verifier(path)
    if (observed.get('status') != 'Valid' or observed.get('certificateSha256') != expected
            or observed.get('timestamped') is not True or observed.get('codeSigning') is not True):
        raise UpdateBlocked('publisher/signature/timestamp mismatch')


def validate_update(manifest_path: Path, artifact: Path, trust: dict, highest_sequence: int,
                    *, verifier=authenticode):
    """Read-only validation. Does not fetch, execute, install or advance state.

    Caller must hold the per-user lock and persist a protected high-water mark
    atomically ONLY after the installation succeeds. Actual updater is not shipped.
    """
    for path in (manifest_path,artifact):
        if not path.is_file() or path.is_symlink() or path.is_junction():
            raise UpdateBlocked('ordinary update file required')
    if trust.get('updatesEnabled') is not True or type(highest_sequence) is not int or highest_sequence < 0:
        raise UpdateBlocked('updates disabled or invalid high-water mark')
    if manifest_path.stat().st_size > 65536:
        raise UpdateBlocked('manifest too large')
    publisher = trust.get('publisherCertificateSha256','')
    publisher_matches(manifest_path,publisher,verifier)
    # Signed PowerShell container is DATA ONLY. Never Invoke/Import/Dot-source it.
    raw = manifest_path.read_bytes()
    try:
        lines = raw.decode('ascii').splitlines()
        if lines[0] != '# NewsFlow-Update-Manifest-v1' or not lines[1].startswith('# '):
            raise ValueError()
        if not lines[2:] or lines[2] != '# SIG # Begin signature block' or any(not s.startswith('#') for s in lines[2:]):
            raise ValueError()
        manifest = json.loads(base64.b64decode(lines[1][2:],validate=True))
    except (ValueError,IndexError,UnicodeError):
        raise UpdateBlocked('invalid signed manifest container') from None
    if (not isinstance(manifest,dict) or set(manifest) != {'appId','channel','sequence','version','file','sha256','bytes'}
            or manifest['appId'] != 'NewsFlowAI' or manifest['channel'] != trust.get('channel')
            or type(manifest['sequence']) is not int or manifest['sequence'] <= highest_sequence
            or not isinstance(manifest['version'],str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+',manifest['version'])
            or manifest['file'] != artifact.name or not re.fullmatch(r'NewsFlowAI-[A-Za-z0-9._-]+\.exe',artifact.name)
            or type(manifest['bytes']) is not int or manifest['bytes'] <= 0
            or not isinstance(manifest['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',manifest['sha256'])):
        raise UpdateBlocked('manifest policy or rollback rejected')
    if artifact.stat().st_size != manifest['bytes'] or hashlib.sha256(artifact.read_bytes()).hexdigest()!=manifest['sha256']:
        raise UpdateBlocked('update bytes mismatch')
    publisher_matches(artifact,publisher,verifier)
    return {k:manifest[k] for k in ('version','sequence','sha256','bytes')}
