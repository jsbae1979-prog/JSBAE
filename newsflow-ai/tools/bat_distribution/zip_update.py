"""Authenticated ZIP contracts, reusing existing offline backup/rollback logic.

There is no default publisher verifier or live installer in this development
layer. Tests inject synthetic capabilities; no CLI can enable real updates.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import stat
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from newsflow.distribution.offline import relative, version
from newsflow.distribution.updates import publisher_matches

from .lifecycle import Blocked, ordinary_absolute, separated

MAX_ZIP = 256 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MAX_FILE = 512 * 1024 * 1024
MAX_FILES = 20000
_SEAL = object()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def payload_name(value: str) -> str:
    try:
        relative(value)  # Existing Windows reserved-name/UNC/ADS/parent contract.
    except (ValueError, TypeError):
        raise Blocked('unsafe-zip-path') from None
    if unicodedata.normalize('NFC', value) != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Blocked('noncanonical-zip-path')
    parts = value.split('/')
    lowered = [part.casefold() for part in parts]
    allowed = value in {'Start_NewsFlowAI.bat', 'Stop_NewsFlowAI.bat', 'Update_NewsFlowAI.bat', 'README.txt', 'app/layout.json'}
    allowed |= value.startswith(('app/runtime/', 'app/product/', 'app/frontend/', 'app/controller/',
                                 'app/site-packages/', 'tools/', 'licenses/'))
    if (not allowed or any(p in {'samples', '.git', '.env', 'user-data', 'update-backups'} for p in lowered)
            or Path(value).suffix.casefold() in {'.db', '.sqlite', '.sqlite3', '.dpapi', '.log'}
            or lowered[-1] in {'settings.json', 'ledger.json', 'oauth.json', 'tokens.json', 'publisher-trust.json'}):
        raise Blocked('nonprogram-or-unverified-sample-payload')
    return value


@dataclass(frozen=True)
class PublisherEvidence:
    certificate_sha256: str
    signed_content_sha256: str
    valid: bool
    timestamped: bool
    code_signing: bool


class UnavailableVerifier:
    def verify(self, content: bytes, signature: bytes) -> PublisherEvidence:
        raise Blocked('real-publisher-verifier-not-provisioned')


@dataclass(frozen=True)
class Trust:
    enabled: bool = False
    certificate_sha256: str = ''
    channel: str = 'private-bat'


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    digest: str


@dataclass(frozen=True)
class VerifiedZip:
    content: bytes = field(repr=False)
    version: str
    sequence: int
    previous_version: str
    previous_sequence: int
    files: tuple[FileRecord, ...]
    _seal: object = field(repr=False)


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise Blocked('duplicate-json-key')
        value[key] = item
    return value


def _zip_members(content: bytes, records: tuple[FileRecord, ...]) -> dict[str, bytes]:
    expected = {r.path: r for r in records}
    output, seen = {}, set()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if len(archive.infolist()) > MAX_FILES:
            raise Blocked('too-many-zip-members')
        total = 0
        for info in archive.infolist():
            if info.orig_filename != info.filename or info.flag_bits & 1:
                raise Blocked('encrypted-or-truncated-zip-name')
            # Files-only ZIP schema. No directory/link/alternate metadata entries.
            name = payload_name(info.filename)
            mode = (info.external_attr >> 16) & 0xFFFF
            if (info.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or info.external_attr & 0x400 or info.extra
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                raise Blocked('unsupported-zip-member-type')
            if name.casefold() in seen or name not in expected:
                raise Blocked('unexpected-or-duplicate-zip-member')
            seen.add(name.casefold())
            row = expected[name]
            total += info.file_size
            if (info.file_size != row.size or info.file_size > MAX_FILE or total > MAX_TOTAL
                    or info.file_size > 200 * max(1, info.compress_size)):
                raise Blocked('zip-size-or-ratio-limit')
            data = archive.read(info)
            if len(data) != row.size or sha(data) != row.digest:
                raise Blocked('zip-member-integrity')
            output[name] = data
    if set(output) != set(expected):
        raise Blocked('zip-members-missing')
    names = {n.casefold() for n in output}
    for name in names:
        if any('/'.join(name.split('/')[:i]) in names for i in range(1, len(name.split('/')))):
            raise Blocked('zip-file-directory-collision')
    return output


def validate(archive: Path, manifest: Path, signature: Path, trust: Trust, *,
             current_version: str, current_sequence: int, verifier=None) -> VerifiedZip:
    # Trust is independently supplied; never read it from the ZIP or an env flag.
    if (trust.enabled is not True or not re.fullmatch('[0-9a-f]{64}', trust.certificate_sha256)
            or trust.channel != 'private-bat'):
        raise Blocked('publisher-trust-missing-updates-disabled')
    verifier = verifier if verifier is not None else UnavailableVerifier()
    try:
        manifest, signature = ordinary_absolute(manifest), ordinary_absolute(signature)
        if not 0 < manifest.stat().st_size <= 4 * 1024 * 1024 or not 0 < signature.stat().st_size <= 65536:
            raise Blocked('signature-or-manifest-size')
        raw, signed = manifest.read_bytes(), signature.read_bytes()
        evidence = verifier.verify(raw, signed)
        publisher_matches('immutable-manifest-bytes', trust.certificate_sha256, lambda _: {
            'status': 'Valid' if evidence.valid is True else 'Invalid',
            'certificateSha256': evidence.certificate_sha256,
            'timestamped': evidence.timestamped, 'codeSigning': evidence.code_signing,
        })
        if evidence.signed_content_sha256 != sha(raw):
            raise Blocked('signature-not-bound-to-manifest')
        value = json.loads(raw, object_pairs_hook=_object)
        required = {'schemaVersion', 'appId', 'channel', 'version', 'sequence', 'supportedFrom',
                    'pythonVersion', 'architecture', 'migration', 'zipName', 'zipBytes', 'zipSha256', 'files'}
        if (not isinstance(value, dict) or set(value) != required or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
                or value['appId'] != 'NewsFlowAI' or value['channel'] != trust.channel
                or value['pythonVersion'] != '3.14.7' or value['architecture'] != 'AMD64'
                or value['migration'] != 'none'):
            raise Blocked('incompatible-product-or-migration')
        if (version(value['version']) <= version(current_version) or type(current_sequence) is not int
                or current_sequence < 0 or type(value['sequence']) is not int
                or value['sequence'] <= current_sequence or value['supportedFrom'] != [current_version]):
            raise Blocked('unsupported-version-or-rollback')
        if (not isinstance(value['files'], list) or not 0 < len(value['files']) <= MAX_FILES
                or type(value['zipBytes']) is not int or not 0 < value['zipBytes'] <= MAX_ZIP
                or not isinstance(value['zipSha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', value['zipSha256'])):
            raise Blocked('invalid-release-inventory')
        files = []
        for row in value['files']:
            if (not isinstance(row, dict) or set(row) != {'path', 'bytes', 'sha256'}
                    or type(row['bytes']) is not int or not 0 <= row['bytes'] <= MAX_FILE
                    or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
                raise Blocked('invalid-file-record')
            files.append(FileRecord(payload_name(row['path']), row['bytes'], row['sha256']))
        if len({r.path.casefold() for r in files}) != len(files):
            raise Blocked('duplicate-manifest-path')
        archive = ordinary_absolute(archive)
        if (not re.fullmatch(r'NewsFlowAI_Update_v[0-9]+\.[0-9]+\.[0-9]+\.zip', archive.name)
                or archive.name != value['zipName']
                or archive.name != f"NewsFlowAI_Update_v{value['version']}.zip"
                or archive.stat().st_size != value['zipBytes']):
            raise Blocked('zip-name-or-size-mismatch')
        content = archive.read_bytes()  # Fixed bounded immutable copy; no reopen at apply.
        if len(content) != value['zipBytes'] or sha(content) != value['zipSha256']:
            raise Blocked('zip-integrity')
        _zip_members(content, tuple(files))
        return VerifiedZip(content, value['version'], value['sequence'], current_version,
                           current_sequence, tuple(files), _SEAL)
    except (OSError, TypeError, KeyError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        if isinstance(error, Blocked):
            raise
        raise Blocked('update-verification-failed') from None


def apply_verified(release: VerifiedZip, installer, health):
    """Internal capability API, not wired to BAT; tests use only synthetic trees.

    Reuse OfflineInstall for its lock, SQLite backup, opaque-key backup, slots,
    journal and rollback. It rechecks version/supportedFrom under its own locks.
    health is mandatory; there is no success-by-default or app-start callback.
    """
    if not isinstance(release, VerifiedZip) or release._seal is not _SEAL or not callable(health):
        raise Blocked('verified-release-and-health-required')
    root, _ = separated(installer.root, installer.profile)
    # Reject stale approvals before making any staging changes.
    if installer.current() != {'version': release.previous_version, 'sequence': release.previous_sequence}:
        raise Blocked('installed-version-changed-reverify')
    files = _zip_members(release.content, release.files)
    with tempfile.TemporaryDirectory(prefix='.zip-input-', dir=root) as temp:
        source = ordinary_absolute(Path(temp))
        if source.parent != root:
            raise Blocked('staging-root-mismatch')
        for name, data in files.items():
            target = ordinary_absolute(source / name)
            target.parent.mkdir(parents=True, exist_ok=True)
            ordinary_absolute(target.parent)
            with target.open('xb') as stream:
                stream.write(data)
        manifest = {'appId': 'NewsFlowAI', 'channel': 'private-offline', 'version': release.version,
                    'sequence': release.sequence, 'supportedFrom': [release.previous_version],
                    'files': [{'path': r.path, 'bytes': r.size, 'sha256': r.digest} for r in release.files]}
        return installer.update_verified(source, manifest, health)


def recover_explicit(installer):
    """Existing explicit rollback only. Never apply/re-submit an unknown update."""
    separated(installer.root, installer.profile)
    return installer.recover()
