"""Deny/parse-only tests for the native bridge; these cases launch no process."""
from pathlib import Path
import json, os, subprocess, sys
import pytest
import native_boundary as native
import step13_guard as guard

@pytest.fixture
def cfg():
    return native.config()

@pytest.fixture
def env(tmp_path):
    values=dict(os.environ)
    values['NEWSFLOW_DATA_DIR']=str(tmp_path/'synthetic-profile')
    values['NEWSFLOW_PORT']='18765'
    return values

@pytest.fixture(autouse=True)
def no_registration_leak():
    native.clear_launch()
    before=set(native.IDENTITIES)
    yield
    native.clear_launch()
    native.IDENTITIES.clear();native.IDENTITIES.update(before)

def lock_args(tmp_path):
    return [sys.executable,'-c',native.CODES['lock'],str(tmp_path/'autopilot.lock')]

def test_runtime_and_bridge_hashes_match(cfg):
    native.runtime_check(cfg)
    assert Path(cfg['python']).resolve()==Path(sys.executable).resolve()
    assert guard.INSTALLED

@pytest.mark.parametrize('name',['python','bootstrap','boundary','guard'])
def test_mismatched_native_binary_or_bridge_hash_denies(cfg,name):
    changed=dict(cfg);changed[name+'_SHA256']='0'*64
    with pytest.raises(native.NativeBoundaryError,match='hash-mismatch'):
        native.runtime_check(changed)

@pytest.mark.parametrize('tail',[
    ['-c','print(123)'],['-m','pip'],['-m','newsflow.main','--unknown'],
    ['-E','-m','newsflow.main'],['-I','-m','newsflow.main'],
    ['-c','import os;os.system("whoami")'],['-'],
])
def test_unreviewed_python_entry_denies(cfg,tail):
    with pytest.raises(native.NativeBoundaryError):native.command_kind([sys.executable,*tail],cfg)

@pytest.mark.parametrize('extra',['--extra','--port=8765'])
def test_fixed_code_extra_argument_denies(cfg,tmp_path,extra):
    with pytest.raises(native.NativeBoundaryError):native.command_kind([*lock_args(tmp_path),extra],cfg)

@pytest.mark.parametrize('port',['8765','0','-1','65536','host:18765'])
def test_operating_and_invalid_ports_deny(port):
    with pytest.raises(native.NativeBoundaryError,match='native-port'):native.port(port)

@pytest.mark.parametrize('port',['18765','10453','65535'])
def test_only_numeric_nonoperating_synthetic_port_shape(port):
    assert native.port(port)==int(port)

@pytest.mark.parametrize('key',['OPENAI_API_KEY','ELEVENLABS_API_KEY','ACCESS_TOKEN','NEWSFLOW_SECRET_KEY'])
def test_unknown_credential_environment_denies(cfg,env,key):
    env[key]='synthetic-but-not-approved'
    with pytest.raises(native.NativeBoundaryError,match='credential-environment'):
        native.sanitized_env(env,'lock',cfg)

def test_only_exact_preview_sentinel_can_be_forwarded(cfg,env):
    env['NEWSFLOW_AI_API_KEY']='synthetic-only-must-be-removed'
    out=native.sanitized_env(env,'preview_boundary',cfg)
    assert out['NEWSFLOW_AI_API_KEY']=='synthetic-only-must-be-removed'
    assert 'PYTHONPATH' not in out and 'NODE_OPTIONS' not in out
    with pytest.raises(native.NativeBoundaryError):native.sanitized_env(env,'main',cfg)

def test_only_exact_main_invalid_secret_sentinel_is_allowed(cfg,env):
    env['NEWSFLOW_SECRET_KEY']='SECRET-SENTINEL'
    assert native.sanitized_env(env,'main',cfg)['NEWSFLOW_SECRET_KEY']=='SECRET-SENTINEL'
    env['NEWSFLOW_SECRET_KEY']='SECRET-SENTINEL-changed'
    with pytest.raises(native.NativeBoundaryError):native.sanitized_env(env,'main',cfg)

def test_operating_profile_and_project_output_denied(cfg,env):
    for target in (native.ROOT.parent/'forbidden-operating',guard.PROJECT,native.ROOT):
        env['NEWSFLOW_DATA_DIR']=str(target)
        with pytest.raises(native.NativeBoundaryError):native.sanitized_env(env,'lock',cfg)

def test_live_request_environment_denied(cfg,env):
    env['NEWSFLOW_AI_LIVE_TEST']='1'
    with pytest.raises(native.NativeBoundaryError,match='live-execution'):
        native.sanitized_env(env,'lock',cfg)

def test_python_ticket_requires_registered_context_and_unchanged_hash(tmp_path,env):
    argv,kw=native.prepare_spawn(lock_args(tmp_path),(),{'cwd':str(native.ROOT),'env':env})
    assert argv[1:4]==['-I','-S','-B']
    assert Path(argv[4]).name=='native_child_bootstrap.py'
    assert native.validate_process(None,argv,kw['cwd'],kw['env'])==argv
    ticket=Path(argv[5]);ticket.write_text('{}',encoding='utf-8')
    with pytest.raises(native.NativeBoundaryError,match='ticket-changed'):
        native.validate_process(None,argv,kw['cwd'],kw['env'])
    native.clear_launch()
    with pytest.raises(native.NativeBoundaryError,match='unregistered'):
        native.validate_process(None,argv,kw['cwd'],kw['env'])

@pytest.mark.parametrize('options',[
    {'shell':True},{'creationflags':0x01000000},{'creationflags':0x08000000},
])
def test_shell_breakaway_and_unapproved_process_options_deny(tmp_path,env,options):
    with pytest.raises(native.NativeBoundaryError):
        native.prepare_spawn(lock_args(tmp_path),(),{'cwd':str(native.ROOT),'env':env,**options})

def test_original_file_and_network_guard_still_denies():
    with pytest.raises(PermissionError):guard.check_file(native.ROOT.parent/'forbidden-operating/newsflow.db')
    with pytest.raises(PermissionError):guard.database_path(str(native.ROOT.parent/'forbidden-operating/newsflow.db'))
    with pytest.raises(PermissionError):guard.address_check(('127.0.0.1',8765))
    with pytest.raises(PermissionError):guard.address_check(('203.0.113.9',443))

def test_task_identity_payload_has_no_extra_fields(cfg):
    native.validate_payload({'operation':'identity'},cfg)
    with pytest.raises(native.NativeBoundaryError):native.validate_payload({'operation':'identity','xml':'x'},cfg)

@pytest.mark.parametrize('op',['read','create','delete','register','remove','Identity',''])
def test_task_mutation_and_unapproved_reads_deny(cfg,op):
    with pytest.raises(native.NativeBoundaryError,match='PowerShell-operation'):
        native.validate_payload({'operation':op},cfg)

def test_task_validate_accepts_only_exact_synthetic_schema(cfg,tmp_path):
    from newsflow.operations.startup import StartupPlan
    plan=StartupPlan(tmp_path/'install',tmp_path/'data',native.SYNTHETIC_SID)
    native.IDENTITIES.add(native.SYNTHETIC_SID)
    payload={'operation':'validate','sid':native.SYNTHETIC_SID,'name':plan.name,'xml':plan.xml()}
    native.validate_payload(payload,cfg)
    for altered in (plan.xml().replace('LeastPrivilege','HighestAvailable'),
                    plan.xml().replace('newsflow.operations.autorun','other.module'),
                    '<!DOCTYPE Task>'+plan.xml()):
        with pytest.raises(native.NativeBoundaryError):native.validate_payload({**payload,'xml':altered},cfg)
    native.IDENTITIES.clear()
    with pytest.raises(native.NativeBoundaryError,match='unverified-identity'):
        native.validate_payload(payload,cfg)

def test_task_exact_program_cannot_be_extended(cfg):
    from newsflow.operations.startup import SCRIPT
    argv=[cfg['powershell'],'-NoProfile','-NonInteractive','-Command',SCRIPT]
    native.powershell_argv(argv,cfg)
    executable=Path(cfg['powershell']).resolve()
    assert executable in guard.NATIVE_READ_FILES and executable not in guard.PINNED
    assert guard.check_file(executable)==executable
    with pytest.raises(PermissionError):guard.check_file(executable.parent)
    with pytest.raises(PermissionError):guard.check_file(executable.with_name('unapproved-neighbor.exe'))
    with pytest.raises(native.NativeBoundaryError,match='PowerShell-program'):
        native.powershell_argv([*argv[:-1],SCRIPT+'\nWrite-Output injected'],cfg)
    with pytest.raises(native.NativeBoundaryError):native.powershell_argv([*argv,'extra'],cfg)

def test_powershell_path_spelling_resolves_only_to_pinned_executable(cfg):
    from newsflow.operations.startup import SCRIPT
    suffix=['-NoProfile','-NonInteractive','-Command',SCRIPT]
    for spelling in (cfg['powershell'].swapcase(),cfg['powershell'].replace('\\','/')):
        native.powershell_argv([spelling,*suffix],cfg)
    for unapproved in ('powershell.exe',str(Path(cfg['powershell']).with_name('other.exe'))):
        with pytest.raises(native.NativeBoundaryError,match='PowerShell-executable-path'):
            native.powershell_argv([unapproved,*suffix],cfg)

def test_powershell_direct_popen_without_validated_stdin_denied(cfg):
    from newsflow.operations.startup import SCRIPT
    argv=[cfg['powershell'],'-NoProfile','-NonInteractive','-Command',SCRIPT]
    with pytest.raises(native.NativeBoundaryError,match='outside-validated-run'):
        native.prepare_powershell(argv,(),{'stdin':subprocess.PIPE,'stdout':subprocess.PIPE,'stderr':subprocess.PIPE},cfg)

def test_real_git_process_remains_unapproved():
    with pytest.raises(PermissionError):guard.validate_process(None,['git','status'],str(native.ROOT),dict(os.environ))


@pytest.mark.parametrize('key',['SYSTEMROOT','WINDIR','COMSPEC'])
def test_operating_system_environment_redirection_denied(cfg,env,tmp_path,key):
    env[key]=str(tmp_path/'untrusted-runtime')
    with pytest.raises(native.NativeBoundaryError,match='OS-environment-redirection'):
        native.sanitized_env(env,'lock',cfg)

def test_fixed_child_preloads_support_before_writable_harness():
    source=(native.ROOT/'native_child_bootstrap.py').read_text(encoding='utf-8')
    assert source.index('sys.path.insert(0,str(site))') < source.index('import click._winconsole, filelock, colorama.win32')
    assert source.index('import click._winconsole, filelock, colorama.win32') < source.index("sys.path.append(str(ROOT))")
    assert 'is_relative_to(site.resolve())' in source

    assert source.index('step13_guard.install()') < source.index("sys.path[:0]=[str(project/'src')")
