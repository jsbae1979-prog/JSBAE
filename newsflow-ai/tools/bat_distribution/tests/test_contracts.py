import hashlib
import io
import json
import sqlite3
import stat
import sys
import zipfile
from contextlib import closing, nullcontext
from dataclasses import replace
from pathlib import Path

import pytest
from bat_distribution import contract_entry
from bat_distribution import lifecycle as life
from bat_distribution import zip_update as update

from newsflow.distribution import offline

SID = 'S-1-5-21-100-200-300-1001'  # Synthetic identity; never queried from Windows.
PIN = hashlib.sha256(b'unit-test-publisher-not-real').hexdigest()


@pytest.fixture
def plan(tmp_path):
    root, profile = tmp_path / 'Program Korean space', tmp_path / 'synthetic-profile'
    root.mkdir()
    files = {
        'app/runtime/python.exe': b'NON_EXECUTABLE_SYNTHETIC_RUNTIME',
        'app/runtime/python314.dll': b'NON_EXECUTABLE_SYNTHETIC_DLL',
        'app/frontend/index.html': b'<p>synthetic static bytes</p>',
        'tools/ffmpeg.exe': b'NON_EXECUTABLE_SYNTHETIC_FFMPEG',
        'tools/ffprobe.exe': b'NON_EXECUTABLE_SYNTHETIC_FFPROBE',
    }
    rows = []
    for name, data in files.items():
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        rows.append({'path': name, 'bytes': len(data), 'sha256': update.sha(data)})
    (root / 'app/layout.json').write_text(json.dumps({'schemaVersion': 1, 'pythonVersion': '3.14.7',
        'architecture': 'AMD64', 'files': rows}), encoding='utf8')
    return life.start_plan(root, profile, 49152, SID, 'a' * 32)


class FakePorts:
    def __init__(self, *, conflict=False, mismatch=False):
        self.calls, self.checked = [], []
        self.conflict, self.mismatch, self.closed = conflict, mismatch, False
    def check_private_profile(self, path, owner):
        self.checked.append((path, owner))  # ACL is simulated, not verified.
    def reserve_exclusive(self, host, port):
        self.calls.append((host, port))
        if self.conflict:
            raise OSError('synthetic collision')
        self.host, self.port = host, port + int(self.mismatch)
        return self
    def close(self):
        self.closed = True


def test_start_reserves_only_requested_loopback_and_retains_lease(plan):
    backend = FakePorts()
    held = life.prepare_start(plan, backend)
    assert backend.calls == [('127.0.0.1', 49152)] and not held.closed
    assert backend.checked == [(plan.profile, SID)]
    held.close()
    assert held.closed


def test_port_collision_has_no_fallback(plan):
    backend = FakePorts(conflict=True)
    with pytest.raises(life.Blocked, match='no-fallback'):
        life.prepare_start(plan, backend)
    assert backend.calls == [('127.0.0.1', 49152)]


def test_mismatched_port_lease_is_released(plan):
    backend = FakePorts(mismatch=True)
    with pytest.raises(life.Blocked, match='reservation-mismatch'):
        life.prepare_start(plan, backend)
    assert backend.closed


@pytest.mark.parametrize('port', [8765, 0, 1023, 65536, True, '49152'])
def test_invalid_operating_or_dynamic_port_rejected(port):
    with pytest.raises(life.Blocked):
        life.fixed_port(port)


@pytest.mark.parametrize('profile', ['same', 'child', 'parent'])
def test_program_profile_overlap_is_rejected(plan, profile):
    path = {'same': plan.program, 'child': plan.program / 'data', 'parent': plan.program.parent}[profile]
    with pytest.raises(life.Blocked, match='overlap'):
        life.start_plan(plan.program, path, plan.port, SID, 'a' * 32)


@pytest.mark.parametrize('path', [Path('relative'), Path('../outside'), Path('//server/share')])
def test_nonlocal_or_relative_roots_are_rejected(path):
    with pytest.raises(life.Blocked):
        life.ordinary_absolute(path)


def test_changed_runtime_is_rejected_before_port_operation(plan):
    (plan.program / 'app/runtime/python.exe').write_bytes(b'changed')
    backend = FakePorts()
    with pytest.raises(life.Blocked, match='runtime-file-mismatch'):
        life.prepare_start(plan, backend)
    assert not backend.calls and not backend.checked


def test_missing_runtime_file_is_not_success(plan):
    (plan.program / 'tools/ffprobe.exe').unlink()
    with pytest.raises(life.Blocked):
        life.inspect_layout(plan)


def identity(plan):
    return life.ProcessIdentity(700001, 'synthetic-create-1', SID,
        plan.program / 'app/runtime/python.exe', plan.installation_id, 'b' * 64)


class FakeProcess:
    def __init__(self, actual, *, stopped=True, timeout=False):
        self.identity, self.stopped, self.timeout = actual, stopped, timeout
        self.opens, self.requests, self.closed = 0, 0, False
    def open_owned_session(self, expected):
        self.opens += 1
        return self  # Represents one retained handle; no host PID is opened.
    def request_graceful_stop(self):
        self.requests += 1
    def wait_stopped(self, timeout):
        if self.timeout:
            raise TimeoutError('synthetic')
        return self.stopped
    def close(self):
        self.closed = True


def test_stop_matching_owner_creation_path_and_session(plan):
    expected = identity(plan)
    backend = FakeProcess(expected)
    assert life.stop_owned(plan, expected, backend) == 'STOPPED'
    assert backend.requests == 1 and backend.closed
    assert expected.session_nonce not in repr(expected)


@pytest.mark.parametrize('field,value', [('pid', 700002), ('creation_id', 'reused-PID'),
    ('owner_sid', 'S-1-5-21-999'), ('installation_id', 'c' * 32), ('session_nonce', 'd' * 64)])
def test_stop_refuses_changed_live_identity_without_stop_request(plan, field, value):
    expected = identity(plan)
    backend = FakeProcess(replace(expected, **{field: value}))
    with pytest.raises(life.Blocked, match='identity-changed'):
        life.stop_owned(plan, expected, backend)
    assert backend.requests == 0 and backend.closed


def test_foreign_expected_owner_rejected_before_open(plan):
    expected = replace(identity(plan), owner_sid='S-1-5-21-999')
    backend = FakeProcess(expected)
    with pytest.raises(life.Blocked, match='not-owned'):
        life.stop_owned(plan, expected, backend)
    assert backend.opens == 0


@pytest.mark.parametrize('timeout_exception', [False, True])
def test_stop_timeout_is_unknown_no_retry_or_force(plan, timeout_exception):
    backend = FakeProcess(identity(plan), stopped=False, timeout=timeout_exception)
    assert life.stop_owned(plan, identity(plan), backend) == 'UNKNOWN_NO_RETRY'
    assert backend.requests == 1 and backend.closed


class SyntheticVerifier:
    """Not cryptography: exact test-fixture bytes only; never a real signer."""
    def __init__(self, raw, *, overrides=None):
        self.raw, self.calls, self.overrides = raw, 0, overrides or {}
    def verify(self, raw, signature):
        self.calls += 1
        if raw != self.raw or signature != b'UNIT_TEST_SIGNATURE_ONLY':
            raise life.Blocked('synthetic-signature-mismatch')
        return replace(update.PublisherEvidence(PIN, update.sha(raw), True, True, True), **self.overrides)


@pytest.fixture
def package(tmp_path):
    def make(files=None, *, mutate=None, entries=None, inventory=None):
        files = files or {'app/product/version.txt': b'synthetic-v1.1'}
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as z:
            for name, data in files.items():
                z.writestr(name, data)
            for info, data in entries or []:
                z.writestr(info, data)
        data = stream.getvalue()
        archive = tmp_path / 'NewsFlowAI_Update_v1.1.0.zip'
        archive.write_bytes(data)
        value = {'schemaVersion': 1, 'appId': 'NewsFlowAI', 'channel': 'private-bat',
            'version': '1.1.0', 'sequence': 2, 'supportedFrom': ['1.0.0'], 'pythonVersion': '3.14.7',
            'architecture': 'AMD64', 'migration': 'none', 'zipName': archive.name,
            'zipBytes': len(data), 'zipSha256': update.sha(data), 'files': inventory or [
                {'path': n, 'bytes': len(b), 'sha256': update.sha(b)} for n, b in files.items()]}
        if mutate:
            mutate(value)
        raw = json.dumps(value, sort_keys=True).encode()
        manifest, signature = tmp_path / 'release.json', tmp_path / 'release.sig'
        manifest.write_bytes(raw)
        signature.write_bytes(b'UNIT_TEST_SIGNATURE_ONLY')
        return archive, manifest, signature, SyntheticVerifier(raw)
    return make


def verify(parts, *, trust=None):
    a, m, s, verifier = parts
    return update.validate(a, m, s, trust or update.Trust(True, PIN),
        current_version='1.0.0', current_sequence=1, verifier=verifier)


def test_missing_trust_refuses_even_nonexistent_files(tmp_path):
    with pytest.raises(life.Blocked, match='trust-missing'):
        update.validate(tmp_path / 'absent', tmp_path / 'absent-manifest', tmp_path / 'absent-sig',
            update.Trust(), current_version='1.0.0', current_sequence=1)
    assert list(tmp_path.iterdir()) == []


def test_default_verifier_cannot_enable_update(package):
    a, m, s, _ = package()
    with pytest.raises(life.Blocked, match='not-provisioned'):
        update.validate(a, m, s, update.Trust(True, PIN), current_version='1.0.0', current_sequence=1)


@pytest.mark.parametrize('changes', [{'valid': False}, {'timestamped': False}, {'code_signing': False},
    {'certificate_sha256': 'f' * 64}, {'signed_content_sha256': '0' * 64}])
def test_signer_claims_must_match_pinned_manifest(package, changes):
    a, m, s, verifier = package()
    verifier.overrides = changes
    with pytest.raises(life.Blocked):
        verify((a, m, s, verifier))


def test_hash_without_signature_is_not_publisher_authentication(package):
    parts = package()
    parts[2].write_bytes(b'NOT_A_SIGNATURE')
    with pytest.raises(life.Blocked, match='signature'):
        verify(parts)


def test_manifest_change_after_signature_fails(package):
    parts = package()
    parts[1].write_bytes(parts[1].read_bytes().replace(b'1.1.0', b'9.9.0'))
    with pytest.raises(life.Blocked, match='signature'):
        verify(parts)


@pytest.mark.parametrize('field,value', [('version', '1.0.0'), ('version', '0.9.0'), ('sequence', 1),
    ('sequence', True), ('supportedFrom', ['0.9.0']), ('pythonVersion', '3.12.0'),
    ('migration', 'required'), ('channel', 'stable'), ('architecture', 'ARM64'), ('schemaVersion', True)])
def test_rollback_unsupported_versions_and_migrations_blocked(package, field, value):
    with pytest.raises(life.Blocked):
        verify(package(mutate=lambda x: x.update({field: value})))


@pytest.mark.parametrize('name', ['../outside.txt', '/absolute.txt', '//server/share/x',
    'app/product/x:stream', 'app/product/CON.txt', 'app/product/trailing. ',
    'app/product/a\\b', 'app/product/a\n.py', 'samples/image.png',
    'app/product/assets/samples/example.png', 'app/product/newsflow.db',
    'app/product/key.dpapi', 'app/product/settings.json', 'app/controller/publisher-trust.json'])
def test_zip_path_and_user_data_boundaries(package, name):
    with pytest.raises(life.Blocked):
        verify(package({name: b'synthetic'}))


def test_archive_tamper_is_detected_without_extracting(package, tmp_path):
    parts = package()
    original = parts[0].read_bytes()
    parts[0].write_bytes(original[:-1] + bytes([original[-1] ^ 1]))
    with pytest.raises(life.Blocked, match='zip-integrity'):
        verify(parts)
    assert not (tmp_path / 'app').exists()


def test_member_digest_and_unexpected_extra_are_rejected(package):
    invalid = [{'path': 'app/product/version.txt', 'bytes': len(b'synthetic-v1.1'), 'sha256': '0' * 64}]
    with pytest.raises(life.Blocked, match='member-integrity'):
        verify(package(inventory=invalid))
    info = zipfile.ZipInfo('app/product/unregistered.txt')
    with pytest.raises(life.Blocked, match='unexpected'):
        verify(package(entries=[(info, b'unregistered')]))


def test_casefold_duplicates_rejected(package):
    with pytest.raises(life.Blocked, match='duplicate-manifest'):
        verify(package({'app/product/A.txt': b'a', 'app/product/a.txt': b'b'}))


@pytest.mark.parametrize('kind', ['symlink', 'extra', 'directory'])
def test_special_zip_entries_rejected(package, kind):
    info = zipfile.ZipInfo('app/product/ref' + ('/' if kind == 'directory' else '.txt'))
    if kind == 'symlink':
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
    if kind == 'extra':
        info.extra = b'\x0a\x00\x00\x00'
    with pytest.raises(life.Blocked):
        verify(package(entries=[(info, b'outside')]))


def test_zip_limits_and_file_directory_collision(package, monkeypatch):
    parts = package()
    monkeypatch.setattr(update, 'MAX_TOTAL', 1)
    with pytest.raises(life.Blocked, match='size-or-ratio'):
        verify(parts)
    monkeypatch.setattr(update, 'MAX_TOTAL', 1024)
    with pytest.raises(life.Blocked, match='directory-collision'):
        verify(package({'app/product/ref': b'a', 'app/product/ref/x.py': b'b'}))


@pytest.fixture
def installer(tmp_path, monkeypatch):
    def private_synthetic(path):
        path = life.ordinary_absolute(path)
        assert path.is_relative_to(tmp_path)
        path.mkdir(exist_ok=True)
        return path
    monkeypatch.setattr(offline, 'private_directory', private_synthetic)
    class SyntheticInstall(offline.OfflineInstall):
        def locks(self):
            return nullcontext()  # Native FileLock/ACL not part of this unit test.
    install = SyntheticInstall(tmp_path / 'program', tmp_path / 'profile')
    source = tmp_path / 'old-payload'
    (source / 'app/product').mkdir(parents=True)
    (source / 'app/product/version.txt').write_bytes(b'old-v1')
    old = {'appId': 'NewsFlowAI', 'channel': 'private-offline', 'version': '1.0.0', 'sequence': 1,
        'files': offline.tree(source)}
    install.initialize(source, old)
    with closing(sqlite3.connect(install.profile / 'newsflow.db')) as db:
        db.execute('CREATE TABLE synthetic(value TEXT)')
        db.execute("INSERT INTO synthetic VALUES ('preserved')")
        db.commit()
    (install.profile / 'settings.json').write_bytes(b'{"synthetic":true}')
    (install.profile / 'key.dpapi').write_bytes(b'SYNTHETIC_NOT_REAL_DPAPI')
    (install.profile / 'media.bin').write_bytes(b'synthetic-user-media')
    return install


def test_verified_zip_apply_preserves_data_and_old_slot(package, installer):
    release = verify(package())
    before = (installer.profile / 'key.dpapi').read_bytes()
    observations = []
    destination = update.apply_verified(release, installer, lambda path: observations.append(path.name))
    assert observations == ['1.1.0'] and destination.name == '1.1.0'
    assert installer.current() == {'version': '1.1.0', 'sequence': 2}
    assert (installer.slots / '1.0.0/app/product/version.txt').read_bytes() == b'old-v1'
    assert (installer.profile / 'key.dpapi').read_bytes() == before
    assert len(list(installer.backups.iterdir())) == 1 and installer.pending() is None
    assert not list(installer.root.glob('.zip-input-*'))


def test_source_zip_replaced_after_validation_cannot_change_applied_bytes(package, installer):
    parts = package()
    release = verify(parts)
    parts[0].write_bytes(b'changed after validation')
    destination = update.apply_verified(release, installer, lambda _: None)
    assert (destination / 'app/product/version.txt').read_bytes() == b'synthetic-v1.1'


def test_failed_health_restores_sqlite_settings_key_media_and_pointer(package, installer):
    release = verify(package())
    def fail_health(_):
        with closing(sqlite3.connect(installer.profile / 'newsflow.db')) as db:
            db.execute("UPDATE synthetic SET value='corrupt-in-test'")
            db.commit()
        for name in ('key.dpapi', 'settings.json', 'media.bin'):
            (installer.profile / name).write_bytes(b'changed-in-test')
        raise RuntimeError('synthetic health failure')
    with pytest.raises(RuntimeError, match='synthetic health'):
        update.apply_verified(release, installer, fail_health)
    with closing(sqlite3.connect(installer.profile / 'newsflow.db')) as db:
        assert db.execute('SELECT value FROM synthetic').fetchone() == ('preserved',)
    assert (installer.profile / 'key.dpapi').read_bytes() == b'SYNTHETIC_NOT_REAL_DPAPI'
    assert (installer.profile / 'settings.json').read_bytes() == b'{"synthetic":true}'
    assert (installer.profile / 'media.bin').read_bytes() == b'synthetic-user-media'
    assert installer.current() == {'version': '1.0.0', 'sequence': 1}
    assert installer.pending() is None and not list(installer.root.glob('.zip-input-*'))


def test_interruption_stays_pending_until_explicit_recovery(package, installer):
    class SyntheticPowerLoss(BaseException):
        pass
    calls = []
    def interrupted(_):
        calls.append('health')
        (installer.profile / 'settings.json').write_bytes(b'partially-written')
        raise SyntheticPowerLoss()
    release = verify(package())
    with pytest.raises(SyntheticPowerLoss):
        update.apply_verified(release, installer, interrupted)
    assert installer.pending()['phase'] == 'MIGRATING'
    with pytest.raises(offline.OfflineBlocked, match='unresolved'):
        update.apply_verified(release, installer, interrupted)
    assert calls == ['health']
    update.recover_explicit(installer)
    assert installer.pending() is None
    assert (installer.profile / 'settings.json').read_bytes() == b'{"synthetic":true}'
    assert installer.current() == {'version': '1.0.0', 'sequence': 1}


def test_health_required_and_stale_release_blocked_before_backup(package, installer):
    release = verify(package())
    with pytest.raises(life.Blocked, match='health-required'):
        update.apply_verified(release, installer, None)
    assert not list(installer.backups.iterdir())
    offline.atomic(installer.pointer, {'version': '1.1.0', 'sequence': 2})
    with pytest.raises(life.Blocked, match='version-changed'):
        update.apply_verified(release, installer, lambda _: None)
    assert not list(installer.backups.iterdir())


def test_corrupted_backup_requires_manual_inspection(package, installer):
    class SyntheticPowerLoss(BaseException):
        pass
    def interrupted(_):
        raise SyntheticPowerLoss()
    with pytest.raises(SyntheticPowerLoss):
        update.apply_verified(verify(package()), installer, interrupted)
    backup = next(installer.backups.iterdir())
    (backup / 'files/key.dpapi').write_bytes(b'damaged')
    with pytest.raises(offline.OfflineBlocked, match='backup-damaged'):
        update.recover_explicit(installer)
    assert installer.pending() is not None


@pytest.mark.parametrize('action,code', [('start', 2), ('stop', 2), ('update', 3)])
def test_bat_dispatcher_never_activates_live_backend(tmp_path, monkeypatch, capsys, action, code):
    monkeypatch.setenv('NEWSFLOW_BAT_LIVE', '1')  # Deliberately unsupported switch.
    assert contract_entry.main([action, str(tmp_path)]) == code
    assert 'BLOCKED' in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
    assert 'newsflow.main' not in sys.modules


def test_synthetic_reparse_marker_refused_without_native_link_creation(plan, monkeypatch):
    marker = plan.program
    original = type(marker).is_junction
    monkeypatch.setattr(type(marker), 'is_junction', lambda path: path == marker or original(path))
    with pytest.raises(life.Blocked, match='linked'):
        life.ordinary_absolute(plan.program / 'app')


def test_profile_access_denial_does_not_reserve_port(plan):
    class Denied(FakePorts):
        def check_private_profile(self, path, owner):
            raise life.Blocked('synthetic-private-profile-denial')
    backend = Denied()
    with pytest.raises(life.Blocked, match='profile-denial'):
        life.prepare_start(plan, backend)
    assert not backend.calls


def test_wrong_live_executable_never_receives_stop(plan):
    expected = identity(plan)
    backend = FakeProcess(replace(expected, executable=plan.program / 'different.exe'))
    with pytest.raises(life.Blocked, match='identity-changed'):
        life.stop_owned(plan, expected, backend)
    assert backend.requests == 0 and backend.closed
