"""Two real frozen product revisions, private CI only; not a public updater.

Failures tested before starting the new product/migrations. No claim of post-DB-
migration rollback. Only nonsecret evidence JSON may leave this disposable job.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import winreg


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    for name in ('old', 'new', 'workspace'):
        ap.add_argument('--'+name, type=Path, required=True)
    ap.add_argument('--old-sha', required=True)
    ap.add_argument('--new-sha', required=True)
    a = ap.parse_args()
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or
            os.environ.get('RUNNER_OS') != 'Windows'):
        raise SystemExit('Disposable Windows CI only; never forge CI flags')
    root = a.workspace.resolve()
    temp = Path(os.environ['RUNNER_TEMP']).resolve()
    if root.exists() or root == temp or not root.is_relative_to(temp):
        raise SystemExit('Fresh owned Runner TEMP directory required')
    root.mkdir()
    results = dict(scope='Windows Server CI, not Windows11 installation', checks=[],
                   public_updater=False, publisher_signed=False,
                   post_migration_rollback='NOT VERIFIED',
                   default_profile_migration='NOT VERIFIED', old_source=a.old_sha,
                   new_source=a.new_sha, forced_cleanup=False)
    def check(name, ok):
        results['checks'].append(dict(name=name, status='PASS' if ok else 'FAIL'))
        if not ok:
            raise AssertionError(name)
    compiler = next((p for base in [os.environ.get('ProgramFiles(x86)', ''), os.environ.get('ProgramFiles', '')]
                     for ver in ('6','7') if (p := Path(base)/('Inno Setup '+ver)/'ISCC.exe').is_file()), None)
    if compiler is None:
        raise RuntimeError('Preinstalled Inno compiler unavailable')
    key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NewsFlowAI-RecoveryEvidence_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key):
            raise RuntimeError('Existing private registration; preserve and stop')
    except FileNotFoundError:
        pass
    installed = root/'Installed'
    state = root/'active.json'
    local = root/'SyntheticLocalAppData'
    local.mkdir()
    from newsflow.distribution.windows_profile import distribution_profile
    profile = distribution_profile(local)
    env = {k:v for k,v in os.environ.items() if k.upper() in {
        'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS'}}
    for d in ('Home','Roaming','Temp'):
        (root/d).mkdir()
    env.update(PATH=str(Path(env['SYSTEMROOT'])/'System32'), USERPROFILE=str(root/'Home'),
               HOME=str(root/'Home'), LOCALAPPDATA=str(local), APPDATA=str(root/'Roaming'),
               TEMP=str(root/'Temp'), TMP=str(root/'Temp'), NEWSFLOW_DATA_DIR=str(profile),
               NEWSFLOW_PORT='18765', NEWSFLOW_HOST='127.0.0.1',
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    processes=[]
    evidence = root/'recovery-results.json'

    def slot(name):
        if name not in ('previous','candidate'):
            raise ValueError('Unknown owned slot')
        return installed/'slots'/name

    def activate(name, fail=False):
        # Candidate-only atomic selection. Real public update signature gate is
        # untouched/disabled; this is not a signature bypass exposed to users.
        old = state.read_bytes() if state.exists() else None
        pending=state.with_suffix('.pending')
        pending.write_text(json.dumps({'slot':name}),encoding='utf8')
        os.replace(pending,state)
        try:
            if fail:
                raise RuntimeError('SYNTHETIC_ACTIVATION_FAILURE')
        except BaseException:
            if old is not None:
                pending.write_bytes(old)
                os.replace(pending,state)
            else:
                state.unlink(missing_ok=True)
            raise

    def compile_setup(bundle, name, version, failure=False):
        out=root/name
        out.mkdir()
        args=[str(compiler),'/Qp','/DCandidateVersion='+version,
              '/DAppBundle='+str(bundle.resolve()),'/DPrivateOutput='+str(out),
              '/DSlot='+('previous' if name=='old-setup' else 'candidate')]
        if failure:
            args.append('/DInjectFailure=1')
        args.append(str(Path(__file__).with_name('recovery-slot.iss')))
        with (out/'compiler.log').open('wb') as log:
            rc=subprocess.run(args,stdout=log,stderr=subprocess.STDOUT,timeout=180).returncode
        check('compile_'+name,rc==0)
        exe=out/'Recovery-Setup.exe'
        results.setdefault('setups',{})[name]={'sha256':digest(exe),'bytes':exe.stat().st_size}
        return exe

    def install(exe):
        return subprocess.run([str(exe),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',
                               '/DIR='+str(installed)],capture_output=True,timeout=120).returncode

    def http(port,path):
        try:
            with opener.open('http://127.0.0.1:'+str(port)+path,timeout=1) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def owned_port():
        # Only the exact installed candidate's process and descendants may count.
        exe=str(slot('candidate')/'NewsFlowAI-Candidate.exe').replace("'","''")
        command=("$ids=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq '"+exe+
                 "'} | Select-Object -ExpandProperty ProcessId); Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
                 "Where-Object {$_.OwningProcess -in $ids -and $_.LocalAddress -eq '127.0.0.1'} | Select-Object -ExpandProperty LocalPort")
        r=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,timeout=15)
        ports=[int(x) for x in r.stdout.split() if x.isdigit()]
        return next((p for p in ports if p!=8765),None)

    def start_stop(name,label):
        execution_log=profile/'logs/execution.log'
        before_stops=execution_log.read_text(encoding='utf8',errors='replace').count('server_stop') if execution_log.exists() else 0
        executable=slot(name)/'NewsFlowAI-Candidate.exe'
        args=[str(executable)]+(['--no-browser'] if name=='candidate' else [])
        with (root/(label+'.private.log')).open('wb') as log:
            process=subprocess.Popen(args,cwd=slot(name),env=env,stdout=log,stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            processes.append(process)
            port=18765 if name=='previous' else None
            ready=False
            try:
                for _ in range(45):
                    if process.poll() is not None:
                        break
                    if port is None:
                        port=owned_port()
                    if port is not None:
                        try:
                            ready=http(port,'/__local/connect' if name=='candidate' else '/studio/dashboard')==200
                        except (OSError,urllib.error.URLError):
                            pass
                    if ready:
                        break
                    time.sleep(1)
                if not ready:
                    log.flush()
                    diagnostic=(root/(label+'.private.log')).read_text(encoding='utf8',errors='replace')
                    # The child has a fresh empty synthetic profile and no provider
                    # secrets; expose only exception classes and missing module names.
                    results['startup_diagnostic']={'exit':process.poll(),
                        'exception_classes':re.findall(r'(?m)^([A-Za-z]+(?:Error|Exception)):',diagnostic),
                        'missing_modules':re.findall(r'No module named ([^\r\n]+)',diagnostic),
                        'startup_error_marker':'server_startup_or_runtime_error' in diagnostic}
                check(label+'_actual_product_http_ready',ready and port!=8765)
                if name=='candidate':
                    check(label+'_anonymous_api_denied',http(port,'/api/samples')==403)
                else:
                    check(label+'_react_asset',http(port,'/studio/dashboard')==200)
                process.send_signal(signal.CTRL_BREAK_EVENT)
                process.wait(timeout=15)
                log.flush()
                shutdown_log=(root/(label+'.private.log')).read_text(encoding='utf8',errors='replace')
                stop_marker=(execution_log.read_text(encoding='utf8',errors='replace').count('server_stop')>before_stops
                             if execution_log.exists() else False)
                expected_old_interrupt=(name=='previous' and process.returncode==1 and stop_marker
                    and re.search(r'(?m)^KeyboardInterrupt\s*$',shutdown_log) is not None
                    and re.search(r'(?m)^[A-Za-z]+(?:Error|Exception):',shutdown_log) is None)
                results.setdefault('shutdown',{})[label]={'exit':process.returncode,
                    'server_stop_marker':stop_marker,'historical_pyinstaller_keyboardinterrupt':bool(expected_old_interrupt)}
                check(label+'_normal_shutdown',process.returncode==0 or expected_old_interrupt)
                released=False
                import socket
                for _ in range(30):
                    with socket.socket() as probe:
                        released=probe.connect_ex(('127.0.0.1',port))!=0
                    if released:
                        break
                    time.sleep(.1)
                check(label+'_port_released',released)
            finally:
                if process.poll() is None:
                    results['forced_cleanup']=True
                    subprocess.run(['taskkill.exe','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)

    def persisted():
        with sqlite3.connect(profile/'newsflow.db') as db:
            rows=db.execute("SELECT key,value FROM app_settings WHERE key IN ('release-recovery-marker','sample_content:v1:recovery') ORDER BY key").fetchall()
        return {'rows':rows, 'files':{n:digest(profile/n) for n in
                ('session.key','synthetic-settings.json','synthetic-secret.dpapi','synthetic-media.bin')}}

    try:
        check('different_product_source_commits',a.old_sha!=a.new_sha)
        old_hash=digest(a.old/'NewsFlowAI-Candidate.exe')
        new_hash=digest(a.new/'NewsFlowAI-Candidate.exe')
        results['product_exe_sha256']={'previous':old_hash,'candidate':new_hash}
        check('different_product_executables',old_hash!=new_hash)
        old_setup=compile_setup(a.old,'old-setup','0.6.0')
        bad_setup=compile_setup(a.new,'failing-setup','0.7.0',True)
        new_setup=compile_setup(a.new,'new-setup','0.7.0')
        check('previous_actual_install',install(old_setup)==0)
        activate('previous')
        start_stop('previous','initial_previous')
        import win32crypt
        plaintext=b'SYNTHETIC-ONLY-NOT-A-PROVIDER-KEY'
        (profile/'synthetic-secret.dpapi').write_bytes(win32crypt.CryptProtectData(plaintext,'synthetic-recovery',None,None,None,0))
        (profile/'synthetic-settings.json').write_text('{"synthetic":true}',encoding='utf8')
        (profile/'synthetic-media.bin').write_bytes(b'SYNTHETIC-MEDIA-KEEP')
        with sqlite3.connect(profile/'newsflow.db') as db:
            db.executemany('INSERT INTO app_settings(key,value) VALUES (?,?)',
                           [('release-recovery-marker','retain'),('sample_content:v1:recovery','hidden')])
        before=persisted()
        rc=install(bad_setup)
        results['injected_installer_exit']=rc
        check('injected_installer_failure_observed',rc!=0)
        check('previous_exe_intact_after_failed_copy',digest(slot('previous')/'NewsFlowAI-Candidate.exe')==old_hash)
        check('active_previous_after_failed_install',json.loads(state.read_text())['slot']=='previous')
        check('data_preserved_after_failed_install',persisted()==before)
        start_stop('previous','failed_install_recovery_previous')
        check('different_product_update_install',install(new_setup)==0)
        check('candidate_installed_exact_bytes',digest(slot('candidate')/'NewsFlowAI-Candidate.exe')==new_hash)
        try:
            activate('candidate',fail=True)
        except RuntimeError:
            pass
        check('failed_activation_restored_previous_pointer',json.loads(state.read_text())['slot']=='previous')
        start_stop('previous','failed_activation_recovery_previous')
        check('data_preserved_after_activation_recovery',persisted()==before)
        activate('candidate')
        start_stop('candidate','successful_candidate')
        start_stop('candidate','restarted_candidate')
        check('data_preserved_after_real_product_update',persisted()==before)
        check('native_dpapi_still_decrypts',win32crypt.CryptUnprotectData((profile/'synthetic-secret.dpapi').read_bytes(),None,None,None,0)[1]==plaintext)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key) as entry:
            value=winreg.QueryValueEx(entry,'UninstallString')[0]
        uninstaller=Path(value.strip('"')).resolve()
        check('owned_uninstaller',uninstaller.parent==installed.resolve() and re.fullmatch(r'unins[0-9]{3}\.exe',uninstaller.name) is not None)
        rc=subprocess.run([str(uninstaller),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],capture_output=True,timeout=120).returncode
        check('actual_uninstall',rc==0)
        for _ in range(100):
            if not (slot('candidate')/'NewsFlowAI-Candidate.exe').exists() and not list(installed.glob('unins*')):
                break
            time.sleep(.1)
        check('installed_slots_removed',not any(installed.glob('slots/*/NewsFlowAI-Candidate.exe')))
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key):
                registration_removed=False
        except FileNotFoundError:
            registration_removed=True
        check('owned_registration_removed',registration_removed)
        check('data_preserved_after_uninstall',persisted()==before)
        check('no_owned_process_remains',all(p.poll() is not None for p in processes))
        results['result']='PASS'
    except BaseException as exc:
        results['result']='FAIL'
        results['failure']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        evidence.write_text(json.dumps(results,indent=2),encoding='utf8')
        print(json.dumps(results))


if __name__=='__main__':
    main()
