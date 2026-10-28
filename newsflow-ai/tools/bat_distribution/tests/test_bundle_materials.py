"""New wheel/ZIP material tests only. No app, BAT, native loader or network."""
import base64
import csv
import hashlib
import io
import json
import zipfile

import pytest
from bat_distribution import bundle_assembly as bundle
from bat_distribution import wheel_materials as wheels
from bat_distribution.lifecycle import Blocked
from bat_distribution.zip_update import payload_name


def make_wheel(tmp_path, *, additions=None, bad_hash=False, unrecorded=False, tag='py3-none-any', python='>=3.8'):
    contents = {'demo/__init__.py': b"raise RuntimeError('must not import fixture')\n",
        'demo-1.0.dist-info/METADATA': f'Metadata-Version: 2.1\nName: demo\nVersion: 1.0\nRequires-Python: {python}\n'.encode(),
        'demo-1.0.dist-info/WHEEL': f'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: {tag}\n'.encode()}
    contents.update(additions or {})
    lines = []
    for name, data in contents.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        lines.append([name, 'sha256=' + digest, str(len(data))])
    if bad_hash:
        lines[0][1] = 'sha256=' + '0' * 43
    record = 'demo-1.0.dist-info/RECORD'
    lines.append([record, '', ''])
    stream = io.StringIO(newline='')
    csv.writer(stream, lineterminator='\n').writerows(lines)
    contents[record] = stream.getvalue().encode()
    if unrecorded:
        contents['demo/extra.py'] = b'unrecorded'
    path = tmp_path / 'demo-1.0-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    expected = {'name': 'demo', 'version': '1.0', 'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return path, expected


def test_record_verified_and_spread_without_import_postinstall_or_pth(tmp_path):
    path, expected = make_wheel(tmp_path, additions={
        'demo.pth': b"import definitely_must_not_execute\n",
        'demo-1.0.data/scripts/postinstall.py': b"raise RuntimeError('must not execute')\n"})
    checked = wheels.read_wheel(path, expected)
    root = tmp_path / 'program'; root.mkdir()
    result = wheels.spread_wheel(root, checked)
    assert checked['recordHashesChecked'] == 5
    assert not result['postinstallExecuted'] and not result['pthExecuted']
    assert (root / 'app/runtime/Scripts/postinstall.py').exists()
    installed = (root / 'app/site-packages/demo-1.0.dist-info/RECORD').read_text()
    assert '../runtime/Scripts/postinstall.py' in installed


def test_outer_wheel_hash_mismatch(tmp_path):
    path, expected = make_wheel(tmp_path)
    expected['sha256'] = '0' * 64
    with pytest.raises(Blocked, match='outer-hash'):
        wheels.read_wheel(path, expected)


@pytest.mark.parametrize('changes,reason', [({'bad_hash': True}, 'record-hash'),
    ({'unrecorded': True}, 'unrecorded-member'), ({'tag': 'cp314-cp314-win_arm64'}, 'tag-mismatch'),
    ({'python': '>=3.15'}, 'python-requirement')])
def test_internal_wheel_contract_rejections(tmp_path, changes, reason):
    path, expected = make_wheel(tmp_path, **changes)
    with pytest.raises(Blocked, match=reason):
        wheels.read_wheel(path, expected)


@pytest.mark.parametrize('name', ['../outside.py', '/root.py', '//server/share/file', 'demo/x:ads',
                                 'demo/CON.txt', 'demo/a\\b', 'demo/a\n.py'])
def test_wheel_path_rejections_before_spread(tmp_path, name):
    path, expected = make_wheel(tmp_path, additions={name: b'unsafe'})
    with pytest.raises(Blocked):
        wheels.read_wheel(path, expected)
    assert not (tmp_path / 'app').exists()


def test_wheel_casefold_duplicate_rejected(tmp_path):
    path, expected = make_wheel(tmp_path, additions={'demo/CASE.txt': b'a', 'demo/case.txt': b'b'})
    with pytest.raises(Blocked, match='duplicate-path'):
        wheels.read_wheel(path, expected)


@pytest.mark.parametrize('scheme,destination', [('purelib', 'app/site-packages/pkg/a.py'),
    ('platlib', 'app/site-packages/pkg/a.py'), ('scripts', 'app/runtime/Scripts/pkg/a.py')])
def test_wheel_spread_schemes_are_fixed(scheme, destination):
    assert wheels.spread_target('demo-1.0.data/' + scheme + '/pkg/a.py') == destination


@pytest.mark.parametrize('scheme', ['data', 'headers', 'unknown'])
def test_unreviewed_spread_destinations_blocked(scheme):
    with pytest.raises(Blocked, match='unsupported-data-scheme'):
        wheels.spread_target('demo-1.0.data/' + scheme + '/a')


def test_existing_different_file_is_not_overwritten(tmp_path):
    root = tmp_path / 'program'; root.mkdir()
    wheels.write_member(root, 'app/site-packages/a.py', b'old')
    with pytest.raises(Blocked, match='collision'):
        wheels.write_member(root, 'app/site-packages/a.py', b'new')
    assert (root / 'app/site-packages/a.py').read_bytes() == b'old'


def test_initial_and_update_zip_layout_and_no_execution(tmp_path):
    root = tmp_path / 'program'; root.mkdir()
    wheels.write_member(root, 'app/product/info.txt', b'synthetic')
    initial, update = tmp_path / 'initial.zip', tmp_path / 'update.zip'
    bundle.create_zip(root, initial, prefix='NewsFlowAI/')
    bundle.create_zip(root, update)
    with zipfile.ZipFile(initial) as archive:
        assert archive.namelist() == ['NewsFlowAI/app/product/info.txt']
    with zipfile.ZipFile(update) as archive:
        assert archive.namelist() == ['app/product/info.txt']
        assert archive.testzip() is None
    assert not (tmp_path / 'NewsFlowAI').exists()


def test_zip_does_not_replace_old_output_or_write_inside_program(tmp_path):
    root = tmp_path / 'program'; root.mkdir()
    wheels.write_member(root, 'README.txt', b'synthetic')
    existing = tmp_path / 'existing.zip'; existing.write_bytes(b'preserve')
    for target in (existing, root / 'inside.zip'):
        with pytest.raises(Blocked, match='outside-program'):
            bundle.create_zip(root, target)
    assert existing.read_bytes() == b'preserve'


def test_generated_version_metadata_retains_source_and_disabled_state(tmp_path):
    root = tmp_path / 'program'; root.mkdir()
    wheels.write_member(root, 'app/product/info.txt', b'synthetic')
    bundle._set_release(root, '1.0.0', 'a' * 40)
    bundle._set_release(root, '1.1.0', 'a' * 40)
    data = json.loads((root / 'app/layout.json').read_bytes())
    assert data['releaseVersion'] == '1.1.0' and data['sourceSha'] == 'a' * 40
    assert data['liveStartStopConnected'] is False and data['updatesEnabled'] is False
    assert (root / 'app/product/info.txt').read_bytes() == b'synthetic'


def test_only_sample_catalog_python_source_is_allowed():
    assert payload_name('app/product/newsflow/samples/catalog.py').endswith('catalog.py')
    for name in ('app/product/newsflow/assets/samples/manifest.json',
                 'app/product/newsflow/samples/image.png', 'samples/image.png',
                 'app/product/newsflow/distribution/publisher-trust.json'):
        with pytest.raises(Blocked):
            payload_name(name)


def test_package_pth_is_search_data_without_import_site_or_activation():
    assert 'import site\n' not in bundle.PTH
    assert '../product\n' in bundle.PTH and '../site-packages\n' in bundle.PTH
    assert not any(line.startswith('import ') for line in bundle.PTH.splitlines())
