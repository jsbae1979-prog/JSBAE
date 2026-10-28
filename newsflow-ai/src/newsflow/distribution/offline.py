"""Per-user offline side-by-side installation and crash-recoverable updates.

No network/download API. The frozen updater authenticates itself BEFORE calling
this transaction layer. Tests inject synthetic payloads/callbacks, never a public
signature bypass. Existing operating entry/profile are not migrated or adopted.
"""
from __future__ import annotations

from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
from uuid import uuid4

from .windows_profile import private_directory, unlinked


class OfflineBlocked(ValueError):
    pass


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def atomic(path, value):
    path = unlinked(path)
    temp = path.with_name(path.name + '.pending-' + uuid4().hex)
    with temp.open('xb') as stream:
        stream.write(json.dumps(value, sort_keys=True).encode())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', value):
        raise OfflineBlocked('invalid-version')
    return tuple(map(int, value.split('.')))


def relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or any(c in value for c in '\x00<>"|?*')):
        raise OfflineBlocked('unsafe-payload-name')
    parts = value.split('/')
    if any(p in ('', '.', '..') or p.endswith((' ', '.'))
           or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?', p) for p in parts):
        raise OfflineBlocked('unsafe-payload-name')
    return PurePosixPath(value)


def tree(root, *, profile=False):
    unlinked(root)
    result = []
    for path in sorted(Path(root).rglob('*')):
        unlinked(path)
        if path.is_file():
            rel = path.relative_to(root).as_posix()
            if profile and path.relative_to(root).parts[0] == 'update-backups':
                continue
            if profile and (rel == 'desktop.lock' or rel.endswith(('-wal', '-shm'))):
                continue
            relative(rel)
            result.append({'path': rel, 'bytes': path.stat().st_size, 'sha256': digest(path)})
    return sorted(result, key=lambda row: row['path'])


def payload_check(root, manifest):
    if manifest.get('appId') != 'NewsFlowAI' or manifest.get('channel') != 'private-offline':
        raise OfflineBlocked('wrong-product-channel')
    version(manifest.get('version'))
    rows = manifest.get('files')
    if not isinstance(rows, list) or not rows or len(rows) > 20000:
        raise OfflineBlocked('invalid-file-list')
    names = [str(relative(r['path'])) for r in rows]
    if len(set(n.casefold() for n in names)) != len(names):
        raise OfflineBlocked('duplicate-payload')
    for row in rows:
        if (type(row.get('bytes')) is not int or row['bytes'] < 0 or
                not re.fullmatch('[0-9a-f]{64}', row.get('sha256', ''))):
            raise OfflineBlocked('invalid-file-digest')
    if tree(root) != sorted(rows, key=lambda r: r['path']):
        raise OfflineBlocked('payload-integrity')


def _copy(source, target):
    unlinked(source)
    unlinked(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    with target.open('r+b') as stream:
        os.fsync(stream.fileno())
    if digest(source) != digest(target):
        raise OfflineBlocked('copy-integrity')


def snapshot(profile, backup):
    """Stopped profile only. Copy secrets as opaque bytes, no decrypt/logging."""
    private_directory(backup)
    files = private_directory(backup / 'files')
    rows = []
    for row in tree(profile, profile=True):
        rel = row['path']
        source = profile / rel
        # SQLite WAL/SHM belong to a DB snapshot, not independent file copies.
        if rel == 'desktop.lock' or rel.endswith(('-wal', '-shm')):
            continue
        target = files / rel
        if source.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
            target.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
                with closing(sqlite3.connect(target)) as dst:
                    src.backup(dst)
                    if dst.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                        raise OfflineBlocked('backup-integrity')
        else:
            _copy(source, target)
        rows.append({'path': rel, 'bytes': target.stat().st_size, 'sha256': digest(target)})
    atomic(backup / 'snapshot-index.json', {'files': rows,
           'absentDatabases': [] if (profile / 'newsflow.db').exists() else ['newsflow.db']})
    return rows


def restore(profile, backup):
    """Restore known backed-up files only. Never delete arbitrary user media."""
    index = json.loads((backup / 'snapshot-index.json').read_bytes())
    rows = index['files']
    for row in rows:
        source = unlinked(backup / 'files' / str(relative(row['path'])))
        if source.stat().st_size != row['bytes'] or digest(source) != row['sha256']:
            raise OfflineBlocked('backup-damaged-manual-recovery-required')
    for row in rows:
        source, dest = backup / 'files' / row['path'], unlinked(profile / row['path'])
        if dest.suffix.lower() in ('.db', '.sqlite', '.sqlite3'):
            for suffix in ('-wal', '-shm'):
                sidecar = unlinked(Path(str(dest) + suffix))
                if sidecar.exists():
                    sidecar.unlink()
        temporary = dest.with_name(dest.name + '.restore-' + uuid4().hex)
        _copy(source, temporary)
        os.replace(temporary, dest)
    for name in index.get('absentDatabases', []):
        if name != 'newsflow.db':
            raise OfflineBlocked('invalid-absent-database')
        for suffix in ('-wal', '-shm', ''):
            path = unlinked(profile / (name + suffix))
            if path.exists():
                path.unlink()
    return rows


class OfflineInstall:
    """All paths are current-user-private; full-profile and update locks required."""
    def __init__(self, root, profile):
        self.root = private_directory(Path(root))
        self.profile = private_directory(Path(profile))
        if self.root == self.profile or self.root.is_relative_to(self.profile) or self.profile.is_relative_to(self.root):
            raise OfflineBlocked('program-data-overlap')
        self.slots = private_directory(self.root / 'slots')
        self.backups = private_directory(self.profile / 'update-backups')
        self.pointer = self.root / 'current.json'
        self.journal = self.root / 'update-journal.json'

    def locks(self):
        from filelock import FileLock, Timeout
        stack = ExitStack()
        try:
            stack.enter_context(FileLock(str(self.root / 'install.lock')).acquire(timeout=0))
            stack.enter_context(FileLock(str(self.profile / 'desktop.lock')).acquire(timeout=0))
        except Timeout:
            stack.close()
            raise OfflineBlocked('close-NewsFlow-AI-normally-before-updating') from None
        return stack

    def current(self):
        unlinked(self.pointer)
        return json.loads(self.pointer.read_bytes()) if self.pointer.exists() else None

    def pending(self):
        unlinked(self.journal)
        if not self.journal.exists():
            return None
        row = json.loads(self.journal.read_bytes())
        return row if row.get('phase') not in ('COMMITTED', 'ROLLED_BACK') else None

    def _stage(self, source, manifest):
        payload_check(source, manifest)
        stage = self.slots / ('.staging-' + uuid4().hex)
        private_directory(stage)
        for row in manifest['files']:
            _copy(source / row['path'], stage / row['path'])
        payload_check(stage, manifest)
        destination = unlinked(self.slots / manifest['version'])
        if destination.exists():
            raise OfflineBlocked('version-slot-exists-manual-review-required')
        stage.rename(destination)
        atomic(self.root / ('release-' + manifest['version'] + '.json'), manifest)
        return destination

    def initialize(self, source, manifest):
        with self.locks():
            if self.current() or self.pending():
                raise OfflineBlocked('existing-install-use-signed-update')
            destination = self._stage(source, manifest)
            atomic(self.pointer, {'version': manifest['version'], 'sequence': manifest['sequence']})
            return destination

    def finalize_preinstalled(self, manifest):
        with self.locks():
            if self.current() or self.pending():
                raise OfflineBlocked('existing-install-use-signed-update')
            payload_check(self.slots / manifest['version'], manifest)
            atomic(self.root / ('release-' + manifest['version'] + '.json'), manifest)
            atomic(self.pointer, {'version': manifest['version'], 'sequence': manifest['sequence']})

    def update_verified(self, source, manifest, health):
        """Private transaction API. Frozen public entry always verifies signer first."""
        with self.locks():
            old = self.current()
            if not old or self.pending():
                raise OfflineBlocked('not-installed-or-unresolved-update')
            if (version(manifest.get('version')) <= version(old['version']) or
                    type(manifest.get('sequence')) is not int or manifest['sequence'] <= old['sequence'] or
                    old['version'] not in manifest.get('supportedFrom', [])):
                raise OfflineBlocked('unsupported-update-or-downgrade')
            # Quiescence and full integrity are established before backup/migration.
            payload_check(source, manifest)
            needed = sum(r['bytes'] for r in manifest['files']) + sum(r['bytes'] for r in tree(self.profile, profile=True)) * 2
            if shutil.disk_usage(self.root).free < needed + 64 * 1024 * 1024:
                raise OfflineBlocked('insufficient-space')
            tx = uuid4().hex
            backup = self.backups / tx
            snapshot(self.profile, backup)
            journal = {'transaction': tx, 'phase': 'PREPARED', 'old': old,
                       'candidate': manifest['version'], 'backup': tx}
            atomic(self.journal, journal)
            try:
                destination = self._stage(source, manifest)
                journal['phase'] = 'MIGRATING'
                atomic(self.journal, journal)
                health(destination)  # fixed packaged operation, never shell/user args
                payload_check(destination, manifest)
                journal['phase'] = 'VERIFIED'
                atomic(self.journal, journal)
                atomic(self.pointer, {'version': manifest['version'], 'sequence': manifest['sequence']})
                journal['phase'] = 'COMMITTED'
                atomic(self.journal, journal)
                return destination
            except Exception:
                # Backup is retained for explicit inspection/recovery; no paid work
                # is retried. BaseException/power loss leaves the journal unresolved.
                restore(self.profile, backup)
                atomic(self.pointer, old)
                journal['phase'] = 'ROLLED_BACK'
                atomic(self.journal, journal)
                raise

    def recover(self):
        """Explicit recovery only, never re-submit or resume an unknown update."""
        with self.locks():
            pending = self.pending()
            if not pending:
                raise OfflineBlocked('no-pending-update')
            tx = pending.get('backup', '')
            if not re.fullmatch('[0-9a-f]{32}', tx):
                raise OfflineBlocked('invalid-backup-id')
            restore(self.profile, unlinked(self.backups / tx))
            atomic(self.pointer, pending['old'])
            pending['phase'] = 'ROLLED_BACK'
            atomic(self.journal, pending)

    def active_executable(self):
        if self.pending():
            raise OfflineBlocked('incomplete-update-explicit-recovery-required')
        current = self.current()
        if not current:
            raise OfflineBlocked('not-installed')
        version(current['version'])
        manifest = json.loads(unlinked(self.root / ('release-' + current['version'] + '.json')).read_bytes())
        slot = unlinked(self.slots / current['version'])
        payload_check(slot, manifest)
        return slot / 'NewsFlowAI-Candidate.exe'

    def remove_installed_programs(self):
        """Remove inventoried immutable program bytes only; all data/backups stay."""
        with self.locks():
            if self.pending():
                raise OfflineBlocked('recover-incomplete-update-before-uninstall')
            releases = []
            for path in self.root.glob('release-*.json'):
                unlinked(path)
                manifest = json.loads(path.read_bytes())
                version(manifest['version'])
                slot = unlinked(self.slots / manifest['version'])
                payload_check(slot, manifest)
                releases.append((path, slot, manifest))
            for path, slot, manifest in releases:
                for row in manifest['files']:
                    unlinked(slot / row['path']).unlink()
                # Only verified-owned empty directories are removed. Unknown
                # files/races fail and remain for manual inspection.
                for directory in sorted(slot.rglob('*'), key=lambda p: len(p.parts), reverse=True):
                    if directory.is_dir():
                        unlinked(directory).rmdir()
                slot.rmdir()
                path.unlink()
            self.pointer.unlink(missing_ok=True)
            self.journal.unlink(missing_ok=True)
