"""Actual Inno Setup lifecycle on disposable Windows CI only; never launches app.

Same-payload installer-version upgrade is not a product DB-migration/rollback test.
No binaries or synthetic user data are uploaded as public artifacts.
"""
import argparse,hashlib,json,os
from pathlib import Path
import sqlite3,subprocess,time,winreg

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bundle',type=Path,required=True);ap.add_argument('--workspace',type=Path,required=True);a=ap.parse_args()
    if os.environ.get('GITHUB_ACTIONS')!='true' or os.environ.get('RUNNER_OS')!='Windows':raise SystemExit('Disposable Windows CI only; never forge flags')
    root=a.workspace.resolve();runner=Path(os.environ['RUNNER_TEMP']).resolve()
    if root.exists() or not root.is_relative_to(runner) or root==runner:raise SystemExit('New owned Runner TEMP tree required')
    root.mkdir();results={'app_executed':False,'OS':'Windows CI, not Windows11 user installation','real_cross_user_test':False}
    compiler=next((p for base in [os.environ.get('ProgramFiles(x86)',''),os.environ.get('ProgramFiles','')] for version in ['6','7'] if (p:=Path(base)/('Inno Setup '+version)/'ISCC.exe').is_file()),None)
    if compiler is None:
        results['installer']='BLOCKED: no preinstalled compiler';(root/'installer-results.json').write_text(json.dumps(results,indent=2));print(json.dumps(results));return
    key=r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NewsFlowAI-PrivateCandidate_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,key):raise RuntimeError('Existing candidate registration; preserve and stop')
    except FileNotFoundError:pass
    setup=Path(__file__).with_name('newsflow-private.iss').resolve();target=root/'Installed'
    profile=root/'SyntheticUserData';profile.mkdir()
    db=sqlite3.connect(profile/'state.db');db.execute('create table state(k text,v text)');db.execute("insert into state values ('hidden','true')");db.commit();db.close()
    for n,body in [('settings.json',b'{"synthetic":true}'),('media.bin',b'SYNTHETIC-MEDIA'),('key-sentinel.dpapi',b'NOT-REAL-DPAPI')]:
        (profile/n).write_bytes(body)
    fingerprint=lambda:{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in profile.iterdir()}
    baseline=fingerprint();exe=a.bundle.resolve()/'NewsFlowAI-Candidate.exe';digest=hashlib.sha256(exe.read_bytes()).hexdigest()
    setups=[]
    for version in ['0.6.0','0.6.1']:
        out=root/('setup-'+version);out.mkdir()
        result=subprocess.run([str(compiler),'/Qp','/DCandidateVersion='+version,'/DAppBundle='+str(a.bundle.resolve()),'/DPrivateOutput='+str(out),str(setup)],capture_output=True,timeout=180)
        if result.returncode:raise RuntimeError('Compiler rejected definition; exit '+str(result.returncode))
        setups.append(out/'NewsFlowAI-Private-Setup.exe')
    def install(path):
        result=subprocess.run([str(path),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/DIR='+str(target)],capture_output=True,timeout=120)
        if result.returncode:raise RuntimeError('Private installation failed; exit '+str(result.returncode))
        if hashlib.sha256((target/exe.name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Installed executable differs')
        if fingerprint()!=baseline:raise RuntimeError('Synthetic data changed')
    def uninstall():
        result=subprocess.run([str(target/'unins000.exe'),'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART'],capture_output=True,timeout=120)
        if result.returncode:raise RuntimeError('Private uninstall failed')
        for _ in range(100):
            if not (target/exe.name).exists():break
            time.sleep(.1)
        if (target/exe.name).exists() or fingerprint()!=baseline:raise RuntimeError('Uninstall/data contract failed')
    install(setups[0]);results['actual_new_install']='PASS'
    install(setups[1]);results['actual_installer_version_update_same_payload']='PASS'
    uninstall();results['actual_uninstall_data_preserved']='PASS'
    install(setups[1]);results['actual_reinstall_data_preserved']='PASS'
    uninstall();results['final_owned_install_removed']='PASS'
    results.update(installer='PASS',setup_sha256=hashlib.sha256(setups[1].read_bytes()).hexdigest(),setup_bytes=setups[1].stat().st_size,
        first_run='NOT VERIFIED',product_database_migration='NOT VERIFIED',real_install_failure_rollback='NOT VERIFIED',publisher_signing='NOT VERIFIED')
    (root/'installer-results.json').write_text(json.dumps(results,indent=2),encoding='utf8');print(json.dumps(results))
if __name__=='__main__':main()
