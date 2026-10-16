from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest
from conftest import csrf

from newsflow.config import Settings
from newsflow.main import create_app
from newsflow.operations import evidence
from newsflow.operations.autorun import record
from newsflow.operations.startup import (
    SCRIPT,
    FakeTaskScheduler,
    StartupError,
    StartupPlan,
    StartupService,
    native,
    owned,
)

SID = 'S-1-5-21-100-200-300-1001'


@pytest.fixture
def startup(tmp_path):
    root = tmp_path/'설치 폴더 & space'
    data = tmp_path/'사용자 데이터'
    data.mkdir(); root.mkdir()
    plan = StartupPlan(root,data,SID)
    plan.python.parent.mkdir(parents=True); plan.python.write_bytes(b'synthetic')
    digest = hashlib.sha256(str(tuple(sys.version_info[:2])).encode())
    for name in ('pyproject.toml','requirements-dev.lock'):
        (root/name).write_bytes(b'fixture'); digest.update(b'fixture')
    (root/'.venv/.newsflow-installed').write_text(digest.hexdigest(),encoding='ascii')
    return StartupService(plan,FakeTaskScheduler())


def test_explicit_registration_and_removal_are_idempotent_without_overwrite(startup):
    state = startup.view()
    assert state['status'] == 'disabled' and state['prepared']
    assert startup.adapter.calls == []
    startup.change('register',state['revision'],True)
    assert startup.view()['status'] == 'enabled'
    with pytest.raises(StartupError):
        startup.change('register',state['revision'],True)
    startup.change('remove',startup.view()['revision'],True)
    assert startup.view()['status'] == 'disabled'
    assert startup.adapter.calls == ['create','delete']


@pytest.mark.parametrize('action',['register','remove','elevate',''])
def test_no_consent_never_mutates(startup,action):
    with pytest.raises(StartupError):
        startup.change(action,startup.view()['revision'],False)
    assert startup.adapter.calls == []


@pytest.mark.parametrize(('old','new'),[
    ('LeastPrivilege','HighestAvailable'),('InteractiveToken','Password'),
    ('IgnoreNew','Parallel'),('PT0S','PT1H'),('WakeToRun>false','WakeToRun>true'),
    ('StartWhenAvailable>false','StartWhenAvailable>true'),('Hidden>false','Hidden>true'),
    ('newsflow.operations.autorun','other.module'),('1001','9999'),
    ('</Settings>','<RestartOnFailure><Interval>PT1M</Interval><Count>3</Count></RestartOnFailure></Settings>'),
    ('</Actions>','<Exec><Command>evil.exe</Command></Exec></Actions>'),
])
def test_foreign_or_altered_tasks_cannot_be_adopted_or_deleted(startup,old,new):
    startup.adapter.xml = startup.plan.xml().replace(old,new)
    assert startup.view()['status'] == 'conflict'
    for action in ('register','remove'):
        with pytest.raises(StartupError):
            startup.change(action,startup.view()['revision'],True)
    assert startup.adapter.calls == []


def test_create_timeout_does_not_retry_and_next_read_reconciles(startup):
    def uncertain(plan):
        startup.adapter.xml = plan.xml()
        raise StartupError('결과 불명')
    startup.adapter.create = Mock(side_effect=uncertain)
    with pytest.raises(StartupError):
        startup.change('register',startup.view()['revision'],True)
    assert startup.view()['status'] == 'enabled'
    startup.adapter.create.assert_called_once()


def test_unprepared_update_requires_run_bat_and_preserves_existing(startup):
    (startup.plan.root/'pyproject.toml').write_text('updated')
    assert not startup.view()['prepared']
    with pytest.raises(StartupError):
        startup.change('register',startup.view()['revision'],True)
    assert startup.adapter.calls == []


def test_xml_escapes_paths_and_least_privilege_policy(startup):
    xml = startup.plan.xml()
    assert '&amp;' in xml and owned(startup.plan,xml)
    assert '<LogonTrigger>' in xml and '<BootTrigger>' not in xml
    assert '<UserId>'+SID+'</UserId>' in xml
    assert '-m newsflow.operations.autorun' in xml
    assert 'RegisterTask($p.name, $p.xml, 2,' in SCRIPT  # CREATE, never UPDATE
    assert 'ExecutionPolicy' not in SCRIPT and 'RunLevel=1' not in SCRIPT


@pytest.mark.parametrize('xml',['not xml','<!DOCTYPE x [<!ENTITY x SYSTEM "file:///secret">]><Task>&x;</Task>'])
def test_malformed_xml_closed(startup,xml):
    assert not owned(startup.plan,xml)


def test_registration_lock_prevents_concurrent_change(startup):
    from filelock import FileLock
    with FileLock(str(startup.plan.data_dir/'startup-settings.lock')), pytest.raises(StartupError):
        startup.change('register',startup.view()['revision'],True)
    assert startup.adapter.calls == []


def test_automatic_factory_never_wakes_paid_provider(tmp_path,monkeypatch,fake):
    from newsflow.video.ai.service import AIVideoCoordinator
    wake, start = Mock(), Mock()
    monkeypatch.setattr(AIVideoCoordinator,'wake',wake)
    monkeypatch.setattr(AIVideoCoordinator,'start',start)
    app = create_app(Settings(data_dir=tmp_path/'automatic'),fake,automatic_start=True)
    try:
        wake.assert_not_called(); start.assert_not_called()
        assert app.state.config.host == '127.0.0.1' and app.state.config.port == 8765
    finally:
        app.state.video_ai.close(); app.state.autopilot.close(); app.state.autopilot_backend.close()
        app.state.coordinator.close(); app.state.video.close(); app.state.engine.dispose()


def test_runtime_status_atomic_and_no_arbitrary_details(tmp_path):
    record(tmp_path,'starting'); record(tmp_path,'failed')
    assert json.loads((tmp_path/'startup-status.json').read_text())['status'] == 'failed'
    assert not list(tmp_path.glob('*.tmp'))
    with pytest.raises(ValueError):
        record(tmp_path,'secret-token')
    assert 'secret' not in (tmp_path/'startup-status.json').read_text()


def test_native_timeout_redacts_sensitive_output(monkeypatch):
    import newsflow.operations.startup as module
    monkeypatch.setattr(module.sys,'platform','win32')
    runner = Mock(side_effect=subprocess.TimeoutExpired(['secret'],20,output='secret-token'))
    monkeypatch.setattr(module.subprocess,'run',runner)
    with pytest.raises(StartupError) as exc:
        native({'operation':'identity'})
    assert 'secret' not in str(exc.value)
    assert runner.call_count == 1
    assert runner.call_args.kwargs.get('shell',False) is False
    assert runner.call_args.kwargs['timeout'] == 20


def post(client,path,data):
    return client.post(path,data={**data,'csrf_token':csrf(client)},headers={'Origin':'http://127.0.0.1'},follow_redirects=False)


def test_gui_registration_review_export_and_persistence(client,app,startup):
    app.state.startup_service = startup
    assert '사용 안 함' in client.get('/operations').text
    fields = {'command':'register','revision':startup.view()['revision']}
    assert post(client,'/operations/startup',fields).status_code == 422
    assert post(client,'/operations/startup',{**fields,'consent':'true'}).status_code == 303
    assert '등록됨' in client.get('/operations').text
    values = dict.fromkeys(evidence.ITEMS,'NOT VERIFIED')
    values['launch'] = 'PASS'
    assert post(client,'/operations/review',{**values,'revision':0,'consent':'true'}).status_code == 303
    assert 'KST' in client.get('/operations').text
    result = client.get('/operations/evidence.json')
    assert 'attachment' in result.headers['Content-Disposition']
    review = result.json()['human_review']
    assert review['items']['launch'] == 'PASS' and review['items']['video30'] == 'NOT VERIFIED'
    assert review['source'] == 'human_self_report'
    assert post(client,'/operations/review',{**values,'revision':0,'consent':'true'}).status_code == 422
    assert post(client,'/operations/startup',{'command':'remove','revision':startup.view()['revision'],'consent':'true'}).status_code == 303
    assert startup.adapter.calls == ['create','delete']


@pytest.mark.parametrize('path',['/operations/startup','/operations/review'])
@pytest.mark.parametrize('origin',['null','https://evil.example','http://localhost'])
def test_csrf_origin_protection(client,path,origin):
    token = csrf(client)
    assert client.post(path,data={'csrf_token':token},headers={'Origin':origin}).status_code == 403
    assert client.post(path,data={'consent':'true'}).status_code == 403


def test_review_never_passes_by_default_and_rejects_no_consent(client,app):
    assert set(evidence.read(app.state.sessions)['items'].values()) == {'NOT VERIFIED'}
    values = dict.fromkeys(evidence.ITEMS,'PASS')
    assert post(client,'/operations/review',{**values,'revision':0}).status_code == 422
    assert post(client,'/operations/review',{**values,'revision':0,'consent':'true','launch':'secret'}).status_code == 422
    export = client.get('/operations/evidence.json').text
    assert str(app.state.config.data_dir) not in export
    assert app.state.config.local_secret() not in export
    assert 'NOT VERIFIED' in export


@pytest.mark.skipif(sys.platform != 'win32',reason='Actual Windows Task Scheduler XML engine, read-only; no OS registration')
def test_native_windows_schema_roundtrip_without_registration(startup):
    from newsflow.operations.startup import local_service
    identity = native({'operation':'identity'})
    if identity['elevated'] or identity['sid'].endswith('-500'):
        with pytest.raises(StartupError):
            local_service(startup.plan.data_dir)
    # Schema-only COM object, never registered: synthetic principal, genuine caller identity.
    # The hosted runner is RID 500; production account restrictions must remain intact.
    plan = startup.plan
    response = native({'operation':'validate','sid':identity['sid'],'name':plan.name,'xml':plan.xml()})
    assert owned(plan,response['xml'])


@pytest.mark.parametrize('elevated',[True,None,'false'])
def test_elevated_or_unknown_identity_cannot_operate(monkeypatch,tmp_path,elevated):
    import newsflow.operations.startup as module
    adapter = Mock(return_value={'sid':SID,'elevated':elevated})
    monkeypatch.setattr(module,'native',adapter)
    with pytest.raises(StartupError):
        module.local_service(tmp_path)
    adapter.assert_called_once_with({'operation':'identity'})


def test_current_user_azure_ad_sid_is_supported(tmp_path):
    plan = StartupPlan(tmp_path,tmp_path,'S-1-12-1-100-200-300-400')
    assert owned(plan,plan.xml())


@pytest.mark.parametrize(('outcome','expected_code','expected_status'),[
    (KeyboardInterrupt,0,'stopped'),(RuntimeError,1,'failed'),(SystemExit,1,'failed')])
def test_automatic_entry_records_exit_without_secret_traceback(tmp_path,monkeypatch,capsys,outcome,expected_code,expected_status):
    import newsflow.main as main_module
    import newsflow.operations.autorun as module
    plan = Mock(python=Path(sys.executable))
    plan.prepared.return_value = True
    service = Mock(plan=plan)
    service.view.return_value = {'status':'enabled'}
    monkeypatch.setattr(module.sys,'platform','win32')
    monkeypatch.setattr(module.sys,'argv',['autorun','--data-dir',str(tmp_path)])
    monkeypatch.setattr(module,'local_service',lambda root:service)
    monkeypatch.setattr(main_module,'run',Mock(side_effect=outcome('secret-token')))
    assert module.main() == expected_code
    assert json.loads((tmp_path/'startup-status.json').read_text())['status'] == expected_status
    assert 'secret-token' not in capsys.readouterr().out



def test_builtin_administrator_cannot_bypass_least_privilege_with_filtered_token(tmp_path,monkeypatch):
    import newsflow.operations.startup as module
    monkeypatch.setattr(module,'native',Mock(return_value={'sid':'S-1-5-21-100-200-300-500','elevated':False}))
    with pytest.raises(StartupError,match='Administrator'):
        module.local_service(tmp_path)
