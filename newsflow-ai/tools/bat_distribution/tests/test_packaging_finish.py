"""New packaging/signature boundary cases only; accepted 78 tests not rerun."""
import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bat_distribution import dependency_inventory as inventory
from bat_distribution import publisher_verifier as publisher
from bat_distribution.lifecycle import Blocked
from bat_distribution.zip_update import Trust

CONTENT = b'{"synthetic":"manifest"}'
CERT = b'SYNTHETIC_PUBLIC_CERT_NOT_REAL_DER'
PIN = hashlib.sha256(CERT).hexdigest()


def signed_comment(content=CONTENT):
    # Syntactically representative only. NOT a real cryptographic signature.
    lines = [publisher.HEADER, '# ' + hashlib.sha256(content).hexdigest(), publisher.BEGIN,
             '# ' + base64.b64encode(b'NOT_REAL_PKCS7').decode(), publisher.END]
    return b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16le')


def anchor_fixture(tmp_path, **changes):
    profile = tmp_path / 'synthetic-profile'
    security = profile / 'security'
    security.mkdir(parents=True)
    (security / 'publisher.cer').write_bytes(CERT)
    value = {'schemaVersion': 1, 'channel': 'private-bat', 'updatesEnabled': True,
             'publisherCertificateSha256': PIN, 'certificateFile': 'publisher.cer',
             'verifierScriptSha256': 'a' * 64, 'offlineValidationAccepted': True}
    value.update(changes)
    (security / 'publisher-trust.json').write_text(json.dumps(value), encoding='utf8')
    return profile


def test_anchor_absence_rejects_without_creating_profile(tmp_path):
    profile = tmp_path / 'absent-profile'
    with pytest.raises(Blocked, match='anchor-missing'):
        publisher.load_anchor(profile)
    assert not profile.exists()


@pytest.mark.parametrize('changes', [{'updatesEnabled': False}, {'offlineValidationAccepted': False},
    {'publisherCertificateSha256': ''}, {'certificateFile': '../publisher.cer'},
    {'channel': 'stable'}, {'schemaVersion': True}])
def test_disabled_unqualified_or_malformed_anchor_rejected(tmp_path, changes):
    profile = anchor_fixture(tmp_path, **changes)
    with pytest.raises(Blocked):
        publisher.load_anchor(profile, attestor=lambda _: None)


def test_anchor_checks_owner_and_public_cert_pin(tmp_path):
    profile = anchor_fixture(tmp_path)
    checked = []
    anchor = publisher.load_anchor(profile, attestor=checked.append)
    assert anchor.trust == Trust(True, PIN)
    assert [path.name for path in checked] == ['synthetic-profile', 'security', 'publisher-trust.json', 'publisher.cer']
    (profile / 'security/publisher.cer').write_bytes(b'changed')
    with pytest.raises(Blocked, match='certificate-pin-mismatch'):
        publisher.load_anchor(profile, attestor=lambda _: None)


def test_foreign_anchor_ownership_rejected_before_content(tmp_path):
    profile = anchor_fixture(tmp_path)
    def reject(_):
        raise Blocked('synthetic-foreign-owner')
    with pytest.raises(Blocked, match='foreign-owner'):
        publisher.load_anchor(profile, attestor=reject)


def test_duplicate_anchor_keys_rejected(tmp_path):
    profile = anchor_fixture(tmp_path)
    file = profile / 'security/publisher-trust.json'
    file.write_text('{"updatesEnabled":false,"updatesEnabled":true}', encoding='utf8')
    with pytest.raises(Blocked, match='duplicate'):
        publisher.load_anchor(profile, attestor=lambda _: None)


@pytest.mark.parametrize('change', ['encoding', 'digest', 'executable-line', 'base64', 'trailing-line'])
def test_comment_container_rejects_nondata_or_unbound_input(change):
    data = signed_comment()
    text = data[2:].decode('utf-16le')
    if change == 'encoding':
        data = text.encode('utf8')
    elif change == 'digest':
        data = signed_comment(b'different manifest')
    elif change == 'executable-line':
        data = b'\xff\xfe' + text.replace(publisher.HEADER, 'Invoke-Expression anything').encode('utf-16le')
    elif change == 'base64':
        data = b'\xff\xfe' + text.replace('# Tk9UX1JFQUxfUEtDUzc=', '# !bad!').encode('utf-16le')
    else:
        data += 'Write-Output anything'.encode('utf-16le')
    with pytest.raises(Blocked):
        publisher.manifest_digest(CONTENT, data)


class FakeContentReader:
    def __init__(self, **changes):
        self.calls, self.changes = [], changes
    def read(self, container):
        self.calls.append(container)
        result = {'status': 'Valid', 'certificateSha256': PIN, 'timestamped': True,
                  'codeSigning': True, 'containerSha256': hashlib.sha256(container).hexdigest()}
        result.update(self.changes)
        return result


def test_prepared_adapter_binds_exact_manifest_container_and_signer():
    reader = FakeContentReader()
    verifier = publisher.WindowsCommentSignatureVerifier(publisher.PreparedAnchor(Trust(True, PIN), 'a'*64), reader=reader)
    data = signed_comment()
    result = verifier.verify(CONTENT, data)
    assert result.certificate_sha256 == PIN
    assert result.signed_content_sha256 == hashlib.sha256(CONTENT).hexdigest()
    assert reader.calls == [data]
    with pytest.raises(Blocked):
        verifier.verify(b'tampered', data)
    assert reader.calls == [data]


@pytest.mark.parametrize('change', [{'status': 'Rejected'}, {'certificateSha256': 'b'*64},
    {'timestamped': False}, {'codeSigning': False}, {'containerSha256': '0'*64}])
def test_prepared_adapter_rejects_native_claim_mismatch(change):
    verifier = publisher.WindowsCommentSignatureVerifier(publisher.PreparedAnchor(Trust(True, PIN), 'a'*64),
        reader=FakeContentReader(**change))
    with pytest.raises(Blocked, match='signature-mismatch'):
        verifier.verify(CONTENT, signed_comment())


def test_default_disabled_anchor_cannot_construct_verifier():
    with pytest.raises(Blocked, match='trust-missing'):
        publisher.WindowsCommentSignatureVerifier(publisher.PreparedAnchor(Trust(), ''))


def test_reader_script_pin_rejects_before_starting_any_process(monkeypatch):
    def never(*args, **kwargs):
        pytest.fail('native verifier must not start')
    monkeypatch.setattr(publisher.subprocess, 'run', never)
    with pytest.raises(Blocked, match='script-pin-mismatch'):
        publisher.WindowsContentReader('0'*64).read(signed_comment())


def test_fixed_signature_transport_passes_data_only_and_scrubs_environment(tmp_path, monkeypatch):
    # No actual PowerShell process: synthetic path and intercepted transport.
    system = tmp_path / 'synthetic-Windows'
    shell = system / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    shell.parent.mkdir(parents=True)
    shell.write_bytes(b'NOT_AN_EXECUTABLE')
    monkeypatch.setenv('SystemRoot', str(system))
    monkeypatch.setenv('NEWSFLOW_AI_KEY', 'SYNTHETIC_NEVER_TRANSMIT')
    script = Path(publisher.__file__).with_name('verify_manifest_content.ps1')
    pin = hashlib.sha256(script.read_bytes()).hexdigest()
    data, seen = signed_comment(), []
    def transport(command, **kwargs):
        seen.append(command)
        assert command == [str(shell), '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(script)]
        assert set(kwargs['env']) == {'SystemRoot', 'WINDIR', 'PATH'}
        assert kwargs['timeout'] == 30 and kwargs.get('shell', False) is False
        assert base64.b64decode(json.loads(kwargs['input'])['content']) == data
        return SimpleNamespace(returncode=0, stdout=b'{"status":"Rejected"}')
    monkeypatch.setattr(publisher.subprocess, 'run', transport)
    assert publisher.WindowsContentReader(pin).read(data) == {'status': 'Rejected'}
    assert len(seen) == 1


def test_dependency_closure_honors_markers_extras_cycles_and_all_constraints():
    data = {'a': ('1.0', ['b>=2', 'ignored; sys_platform == "linux"', 'c; extra == "feature"'], ['py3-none-any']),
            'b': ('2.1', ['a>=1'], ['cp314-cp314-win_amd64']), 'c': ('3.0', [], ['py3-none-any'])}
    result = inventory.resolve(['a[feature]>=1'], {'sys_platform': 'win32'}, lambda name: data[name])
    assert [(row['name'], row['version']) for row in result] == [('a','1.0'), ('b','2.1'), ('c','3.0')]
    assert len(result[0]['requirements']) == 2


def test_dependency_conflict_or_missing_is_not_invented():
    data = {'a': ('1.0', ['b>=3'], []), 'b': ('2.0', [], [])}
    with pytest.raises(ValueError, match='constraint:b'):
        inventory.resolve(['a'], {}, lambda name: data[name])
    with pytest.raises(KeyError):
        inventory.resolve(['absent'], {}, lambda name: data[name])


def test_unreviewed_direct_url_is_not_an_implicit_runtime_pin():
    with pytest.raises(ValueError, match='constraint'):
        inventory.resolve(['a @ https://invalid.example/a.whl'], {}, lambda _: ('1.0', [], []))


def test_single_reviewed_metadata_reader_does_not_import_packages(tmp_path):
    dist = tmp_path / 'demo-1.0.dist-info'
    dist.mkdir()
    (dist / 'METADATA').write_text('Metadata-Version: 2.1\nName: demo\nVersion: 1.0\nRequires-Dist: dep>=2\n', encoding='utf8')
    (dist / 'WHEEL').write_text('Wheel-Version: 1.0\nTag: cp314-cp314-win_amd64\n', encoding='utf8')
    read = inventory.metadata_reader([tmp_path])
    assert read('demo') == ('1.0', ['dep>=2'], ['cp314-cp314-win_amd64'])
    with pytest.raises(Exception) as error:
        read('not-installed')
    assert type(error.value).__name__ == 'PackageNotFoundError'


@pytest.mark.parametrize('use_dist', [True, False])
def test_frontend_mapping_matches_real_resource_resolver_without_app_import(tmp_path, use_dist):
    import importlib.util

    from bat_distribution import lifecycle
    project = Path(__file__).resolve().parents[3]
    source = project / 'src/newsflow/studio/resources.py'
    spec = importlib.util.spec_from_file_location('static_resource_mapping_test', source)
    resources = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(resources)
    program = tmp_path / 'Program'; program.mkdir()
    resources.__file__ = str(program / 'app/product/newsflow/studio/resources.py')
    assert resources.studio_dist_root() == program / 'app/frontend/dist'
    relative_index = 'app/frontend/dist/index.html' if use_dist else 'app/frontend/index.html'
    rows = []
    for name in ('app/runtime/python.exe', 'app/runtime/python314.dll', relative_index, 'tools/ffmpeg.exe', 'tools/ffprobe.exe'):
        target = program / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'NON_EXECUTABLE_FIXTURE')
        rows.append({'path': name, 'bytes': target.stat().st_size, 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()})
    (program / 'app/layout.json').write_text(json.dumps({'schemaVersion':1, 'pythonVersion':'3.14.7', 'architecture':'AMD64', 'files':rows}), encoding='utf8')
    plan = lifecycle.start_plan(program, tmp_path / 'Data', 49152, 'S-1-5-21-100-1001', 'a'*32)
    if use_dist:
        lifecycle.inspect_layout(plan)
    else:
        with pytest.raises(Blocked, match='required-runtime-file-missing'):
            lifecycle.inspect_layout(plan)


def test_prepared_verifier_connects_to_existing_zip_validator_without_install(tmp_path):
    import io
    import zipfile

    from bat_distribution import zip_update
    payload = b'SYNTHETIC_PROGRAM_TEXT'
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('app/product/version.txt', payload)
    data = stream.getvalue()
    archive_path = tmp_path / 'NewsFlowAI_Update_v1.1.0.zip'
    manifest_path, signature_path = tmp_path / 'release.json', tmp_path / 'release.sig'
    manifest = {'schemaVersion':1,'appId':'NewsFlowAI','channel':'private-bat','version':'1.1.0',
        'sequence':2,'supportedFrom':['1.0.0'],'pythonVersion':'3.14.7','architecture':'AMD64',
        'migration':'none','zipName':archive_path.name,'zipBytes':len(data),'zipSha256':hashlib.sha256(data).hexdigest(),
        'files':[{'path':'app/product/version.txt','bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}]}
    raw = json.dumps(manifest).encode()
    archive_path.write_bytes(data); manifest_path.write_bytes(raw); signature_path.write_bytes(signed_comment(raw))
    reader = FakeContentReader()
    verifier = publisher.WindowsCommentSignatureVerifier(publisher.PreparedAnchor(Trust(True,PIN),'a'*64), reader=reader)
    verified = zip_update.validate(archive_path, manifest_path, signature_path, Trust(True,PIN),
        current_version='1.0.0',current_sequence=1,verifier=verifier)
    assert verified.version == '1.1.0' and len(reader.calls)==1
    assert not (tmp_path / 'app').exists()
