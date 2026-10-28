"""Explicit Windows11 synthetic-profile installation, never operating data.

No signature bypass: the actual unsigned Update EXE must reject. Transaction
success/rollback uses the separate synthetic unit tests, not that executable.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import winreg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    args = parser.parse_args()
    if os.name != 'nt' or __import__('sys').getwindowsversion().build < 22000:
        raise SystemExit('Windows11 required')
    root = args.workspace.resolve()
    if root.exists():
        raise SystemExit('Fresh private verification workspace required')
    root.mkdir()
    results = {'checks': [], 'environment': 'Windows11 current SID, synthetic profile; not a new Windows account',
               'externalCalls': 0, 'publisherSigned': False, 'forcedCleanup': False,
               'signedEndToEndUpdate': 'BLOCKED: no real publisher certificate', 'DPI': 'NOT VERIFIED'}
    processes = []
    def check(name, ok):
        results['checks'].append({'name': name, 'status': 'PASS' if ok else 'FAIL'})
        if not ok:
            raise AssertionError(name)
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS'}}
    for name in ('Local', 'Roaming', 'Home', 'Temp'):
        (root / name).mkdir()
    env.update(PATH=str(Path(env['SYSTEMROOT']) / 'System32'), LOCALAPPDATA=str(root / 'Local'),
               APPDATA=str(root / 'Roaming'), USERPROFILE=str(root / 'Home'), HOME=str(root / 'Home'),
               TEMP=str(root / 'Temp'), TMP=str(root / 'Temp'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    installed = root / 'Local/Programs/NewsFlowAI-Private'
    profile = root / 'Local/NewsFlowAI-Desktop/v1'
    setup = args.build / 'candidates/NewsFlowAI_Setup_v1.0.0.exe'
    update = args.build / 'candidates/NewsFlowAI_Update_v1.1.0.exe'
    registration = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NewsFlowAI-PrivateOffline-v1_is1'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration):
            raise RuntimeError('Private registration already exists; preserve and stop')
    except FileNotFoundError:
        pass
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def http(port, path):
        try:
            with opener.open('http://127.0.0.1:' + str(port) + path, timeout=2) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            return exc.code
    def owned_port():
        executable = str(installed / 'slots/1.0.0/NewsFlowAI-Candidate.exe').replace("'", "''")
        query = "$ids=@(Get-CimInstance Win32_Process | Where-Object {$_.ExecutablePath -eq '" + executable + "'} | Select-Object -ExpandProperty ProcessId); Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.OwningProcess -in $ids -and $_.LocalAddress -eq '127.0.0.1'} | Select-Object -ExpandProperty LocalPort"
        output = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', query],
                                capture_output=True, text=True, timeout=20)
        return next((int(p) for p in output.stdout.split() if p.isdigit() and int(p) != 8765), None)
    def launch(label):
        with (root / (label + '.private.log')).open('wb') as log:
            proc = subprocess.Popen([str(installed / 'NewsFlowAI.exe'), '--no-browser'], cwd=installed,
                env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            processes.append(proc)
            port = None
            for _ in range(20):
                if proc.poll() is not None:
                    break
                port = owned_port()
                if port:
                    try:
                        if http(port, '/__local/connect') == 200:
                            break
                    except OSError:
                        pass
                time.sleep(.5)
            check(label + '_actual_product_http', port is not None and http(port, '/__local/connect') == 200)
            check(label + '_anonymous_api_blocked', http(port, '/api/samples') == 403)
            check(label + '_separate_nonoperating_port', port != 8765)
            proc.send_signal(signal.CTRL_BREAK_EVENT)
            proc.wait(timeout=20)
            check(label + '_normal_exit', proc.returncode == 0)
            with socket.socket() as probe:
                check(label + '_port_released', probe.connect_ex(('127.0.0.1', port)) != 0)
    def install():
        return subprocess.run([str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/NOICONS',
            '/DIR=' + str(installed), '/LOG=' + str(root / 'setup.private.log')], env=env, capture_output=True, timeout=240).returncode
    def uninstall():
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration) as key:
            value = winreg.QueryValueEx(key, 'UninstallString')[0]
        executable = Path(value.strip('"')).resolve()
        check('owned_uninstaller', executable.parent == installed and re.fullmatch(r'unins[0-9]{3}\.exe', executable.name) is not None)
        rc = subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                             env=env, capture_output=True, timeout=240).returncode
        check('uninstall_exit', rc == 0)
        for _ in range(100):
            if not (installed / 'NewsFlowAI.exe').exists():
                break
            time.sleep(.2)
        check('program_removed', not (installed / 'NewsFlowAI.exe').exists())
    try:
        check('private_initial_installer', install() == 0)
        check('initial_pointer', json.loads((installed / 'current.json').read_bytes())['version'] == '1.0.0')
        launch('first_launch')
        launch('relaunch')
        import win32crypt
        opaque = win32crypt.CryptProtectData(b'SYNTHETIC-NOT-A-REAL-KEY', 'private-offline', None, None, None, 0)
        (profile / 'synthetic.dpapi').write_bytes(opaque)
        (profile / 'synthetic-media.bin').write_bytes(b'SYNTHETIC-MEDIA-PRESERVE')
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                  (profile / 'synthetic.dpapi', profile / 'synthetic-media.bin', profile / 'session.key')}
        state = (installed / 'current.json').read_bytes()
        rejected = subprocess.run([str(update)], env=env, capture_output=True, timeout=60)
        check('actual_unsigned_update_rejected', rejected.returncode == 2)
        check('rejected_update_did_not_change_version', (installed / 'current.json').read_bytes() == state)
        check('rejected_update_no_transaction_or_migration', not (installed / 'update-journal.json').exists())
        check('no_secrets_in_update_output', b'SYNTHETIC-NOT' not in rejected.stdout + rejected.stderr)
        runtime = subprocess.run([str(installed / 'slots/1.0.0/NewsFlowAI-Candidate.exe'), '--offline-runtime-check'],
                                 env=env, capture_output=True, timeout=90)
        check('packaged_new_media_and_python_preflight', runtime.returncode == 0)
        catalog_root = installed / 'slots/1.0.0/_internal/newsflow/assets/samples'
        manifest = json.loads((catalog_root / 'manifest.json').read_bytes())
        check('new_sample_count_12', len(manifest['assets']) == 12)
        check('new_samples_not_rights_approved', all(r.get('rightsVerified') is False for r in manifest['assets']))
        check('all_new_sample_files_present', all((catalog_root / r['path']).is_file() for r in manifest['assets']))
        check('react_index_present', (installed / 'slots/1.0.0/_internal/frontend/dist/index.html').is_file())
        uninstall()
        check('data_retained_after_uninstall', before == {n: hashlib.sha256((profile / n).read_bytes()).hexdigest() for n in before})
        check('same_user_native_dpapi_retained', win32crypt.CryptUnprotectData((profile / 'synthetic.dpapi').read_bytes(), None, None, None, 0)[1] == b'SYNTHETIC-NOT-A-REAL-KEY')
        check('reinstall', install() == 0)
        check('data_retained_after_reinstall', before == {n: hashlib.sha256((profile / n).read_bytes()).hexdigest() for n in before})
        launch('reinstalled_launch')
        uninstall()
        check('no_owned_process_left', all(p.poll() is not None for p in processes))
        results['result'] = 'PASS'
    except BaseException as exc:
        results['result'] = 'FAIL'
        results['errorClass'] = type(exc).__name__
        results['failedCheck'] = next((r['name'] for r in reversed(results['checks']) if r['status'] == 'FAIL'), None)
        raise
    finally:
        # No generic taskkill; only owned processes get a normal break request.
        for process in processes:
            if process.poll() is None:
                try:
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                    process.wait(timeout=15)
                except Exception:
                    results['cleanup'] = 'BLOCKED: owned process needs inspection; no force cleanup used'
        (root / 'PRIVATE_INSTALL_TEST_RESULTS.json').write_text(json.dumps(results, indent=2))
        print(json.dumps(results))


if __name__ == '__main__':
    main()
