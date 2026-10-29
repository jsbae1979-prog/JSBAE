import json
import hashlib
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient
from bat_distribution import contract_entry
from bat_distribution.lifecycle import Blocked, ProcessIdentity
from bat_distribution import windows_live as live


def test_old_unprovisioned_dispatcher_stays_inert(tmp_path):
    assert contract_entry.main(['start', str(tmp_path)]) == 2


def config(tmp_path, port=18767):
    root = tmp_path / 'Program'
    (root / 'app').mkdir(parents=True)
    external = root.parent / 'validation-launch.json'
    external.write_text(json.dumps({
        'schemaVersion': 1, 'syntheticOnly': True, 'profileName': 'SyntheticProfile',
        'installationId': 'b' * 32, 'port': port, 'openBrowser': False}))
    (root / 'app/layout.json').write_text(json.dumps({
        'liveStartStopConnected': True, 'validationOnly': True,
        'validationConfigSha256': hashlib.sha256(external.read_bytes()).hexdigest()}))
    return root


@pytest.mark.parametrize('port', [8765, 0])
def test_validation_cannot_use_operating_or_dynamic_port(tmp_path, port):
    with pytest.raises(Blocked):
        live.load_config(config(tmp_path, port))


def test_profile_cannot_adopt_operating_data(tmp_path):
    root = config(tmp_path)
    p = root.parent / 'validation-launch.json'
    data = json.loads(p.read_text())
    data['profileName'] = 'NewsFlowAI'
    p.write_text(json.dumps(data))
    layout = root / 'app/layout.json'
    metadata = json.loads(layout.read_text())
    metadata['validationConfigSha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
    layout.write_text(json.dumps(metadata))
    with pytest.raises(Blocked, match='synthetic-validation'):
        live.load_config(root)


async def inner(scope, receive, send):
    await send({'type': 'http.response.start', 'status': 200, 'headers': []})
    await send({'type': 'http.response.body', 'body': b'INNER'})


def control(peer='127.0.0.1'):
    calls = []
    identity = ProcessIdentity(101, 'synthetic-creation', 'S-1-5-21-1-1001',
                               Path('C:/synthetic/python.exe'), 'b' * 32, 'a' * 64)
    app = live.Control(inner, identity, 'http://127.0.0.1:18767', lambda: calls.append('stop'))
    return TestClient(app, base_url='http://127.0.0.1:18767', client=(peer, 52000)), calls


def headers(token='a' * 64, origin='http://127.0.0.1:18767'):
    return {'Origin': origin, 'X-NewsFlow-Stop': token}


def test_control_accepts_one_owned_stop_only():
    client, calls = control()
    assert client.post('/__bat/stop', headers=headers()).status_code == 202
    assert client.post('/__bat/stop', headers=headers()).status_code == 409
    assert calls == ['stop']


@pytest.mark.parametrize('kind', ['wrong-token', 'foreign-origin', 'body', 'get', 'foreign-peer'])
def test_control_refuses_unowned_or_nonempty_request(kind):
    client, calls = control('192.0.2.2' if kind == 'foreign-peer' else '127.0.0.1')
    h = headers(token='c' * 64 if kind == 'wrong-token' else 'a' * 64,
                origin='http://example.invalid' if kind == 'foreign-origin' else 'http://127.0.0.1:18767')
    response = client.get('/__bat/stop', headers=h) if kind == 'get' else client.post(
        '/__bat/stop', headers=h, content=b'not-empty' if kind == 'body' else b'')
    assert response.status_code == 403
    assert calls == []


def test_foreign_process_identity_is_closed_without_stop(monkeypatch, tmp_path):
    expected = ProcessIdentity(101, 'created', 'S-1-5-21-1-1001',
                               tmp_path / 'python.exe', 'b' * 32, 'a' * 64)
    calls = []
    class Handle:
        def Close(self):
            calls.append('closed')
    def open_process(rights, inherit, pid):
        assert rights == 0x101000 and inherit is False and pid == 101
        return Handle()
    import sys
    monkeypatch.setitem(sys.modules, 'win32api', SimpleNamespace(OpenProcess=open_process))
    monkeypatch.setattr(live, '_read_session', lambda _: expected)
    monkeypatch.setattr(live, '_identity', lambda *args: replace(expected, creation_id='different'))
    with pytest.raises(Blocked, match='identity-changed'):
        live.WindowsStop(SimpleNamespace(profile=tmp_path)).open_owned_session(expected)
    assert calls == ['closed']


@pytest.mark.parametrize('path', ['/api/feed-batches/1/step', '/image-studio/1/generate', '/publishing/submit'])
def test_synthetic_policy_blocks_execution(path):
    client = TestClient(live.SyntheticRequests(inner))
    assert client.post(path).status_code == 403


def test_synthetic_policy_retains_defaults_save_and_reads():
    client = TestClient(live.SyntheticRequests(inner))
    assert client.post('/api/feed-batches/defaults').status_code == 200
    assert client.get('/api/feed-batches').status_code == 200


def test_external_validation_metadata_is_bound_and_not_a_payload(tmp_path):
    from bat_distribution.zip_update import payload_name
    root = config(tmp_path)
    actual = live.load_config(root)
    assert actual.profile == root.parent / 'SyntheticProfile'
    assert not (root / 'app/validation-launch.json').exists()
    for name in ('app/validation-launch.json', 'README-VALIDATION.txt'):
        with pytest.raises(Blocked, match='nonprogram-or-unverified-sample-payload'):
            payload_name(name)  # Distribution allowlist is deliberately unchanged.


def test_changed_external_validation_metadata_is_refused(tmp_path):
    root = config(tmp_path)
    external = root.parent / 'validation-launch.json'
    external.write_bytes(external.read_bytes() + b' ')
    with pytest.raises(Blocked, match='validation-configuration-integrity'):
        live.load_config(root)


def test_distributable_without_external_harness_remains_inert(tmp_path):
    root = config(tmp_path)
    external = root.parent / 'validation-launch.json'
    external.rename(root / 'app/validation-launch.json')
    assert contract_entry.main(['start', str(root)]) == 2
