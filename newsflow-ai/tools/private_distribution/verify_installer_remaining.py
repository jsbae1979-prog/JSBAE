"""Complete installer-only checks after a Windows CreateProcess denial.

Never executes NewsFlowAI-Candidate.exe, never retries the blocked application
at another path. Only Setup and the registered owned uninstaller run.
"""
from contextlib import closing
import hashlib
import argparse
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import winreg

parser = argparse.ArgumentParser()
parser.add_argument('--workspace', type=Path, required=True)
parser.add_argument('--setup', type=Path, required=True)
args = parser.parse_args()
root = args.workspace.resolve()
if not root.is_relative_to(Path(os.environ['TEMP']).resolve()):
    raise SystemExit('Owned synthetic TEMP fixture required')
installed = root / 'Local/Programs/NewsFlowAI-Private'
profile = root / 'Local/NewsFlowAI-Desktop/v1'
setup = args.setup.resolve()
registration = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\NewsFlowAI-PrivateOffline-v1_is1'
result = {'checks': [], 'applicationExecution': 'BLOCKED / not attempted in this installer-only continuation',
          'forcedCleanup': False, 'externalCalls': 0}


def check(name, value):
    result['checks'].append({'name': name, 'status': 'PASS' if value else 'FAIL'})
    if not value:
        raise AssertionError(name)


def preserved():
    with closing(sqlite3.connect(profile / 'newsflow.db')) as db:
        rows = db.execute("SELECT key,value FROM app_settings WHERE key IN ('private-install-marker','sample_content:v1:hidden:synthetic-marker') ORDER BY key").fetchall()
    files = {name: hashlib.sha256((profile / name).read_bytes()).hexdigest()
             for name in ('synthetic.dpapi', 'synthetic-media.bin', 'session.key', 'synthetic-settings.json')}
    return {'rows': rows, 'files': files}


env = {k: v for k, v in os.environ.items() if k.upper() in {
    'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS'}}
env.update(PATH=str(Path(env['SYSTEMROOT']) / 'System32'), LOCALAPPDATA=str(root / 'Local'),
           APPDATA=str(root / 'Roaming'), USERPROFILE=str(root / 'Home'), HOME=str(root / 'Home'),
           TEMP=str(root / 'Temp'), TMP=str(root / 'Temp'))
try:
    previous = json.loads((root / 'PRIVATE_INSTALL_TEST_RESULTS.json').read_text())
    check('prior_fixture_owned_and_failed_at_reinstall', previous['failedCheck'] == 'reinstall' and
          next(r for r in previous['checks'] if r['name'] == 'private_initial_installer')['status'] == 'PASS')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration):
            raise RuntimeError('Existing registered installation; preserve and stop')
    except FileNotFoundError:
        pass
    # Only the verified empty directory left by the previous installer revision.
    if installed.exists():
        check('old_fixture_directory_empty_unlinked', not installed.is_symlink() and not installed.is_junction()
              and installed.resolve().is_relative_to(root.resolve()) and not list(installed.iterdir()))
        installed.rmdir()
    before = preserved()
    check('synthetic_db_and_hidden_markers_present', len(before['rows']) == 2)
    for turn in (1, 2):
        code = subprocess.run([str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/NOICONS',
            '/DIR=' + str(installed), '/LOG=' + str(root / ('remaining-setup-' + str(turn) + '.private.log'))],
            env=env, capture_output=True, timeout=180).returncode
        check('install_' + str(turn), code == 0)
        check('preserve_db_keys_media_settings_after_install_' + str(turn), preserved() == before)
        check('private_pointer_' + str(turn), json.loads((installed / 'current.json').read_text())['version'] == '1.0.0')
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration) as key:
            value = winreg.QueryValueEx(key, 'UninstallString')[0]
        uninstaller = Path(value.strip('"')).resolve()
        check('owned_uninstaller_' + str(turn), uninstaller.parent == installed and re.fullmatch(r'unins[0-9]{3}\.exe', uninstaller.name) is not None)
        code = subprocess.run([str(uninstaller), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'],
                              env=env, capture_output=True, timeout=180).returncode
        check('uninstall_' + str(turn), code == 0)
        for _ in range(100):
            if not installed.exists():
                break
            time.sleep(.2)
        check('owned_program_root_removed_' + str(turn), not installed.exists())
        check('preserve_db_keys_media_settings_after_uninstall_' + str(turn), preserved() == before)
    import win32crypt
    check('native_dpapi_still_decrypts', win32crypt.CryptUnprotectData((profile / 'synthetic.dpapi').read_bytes(), None, None, None, 0)[1] == b'SYNTHETIC-NOT-A-REAL-KEY')
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registration):
            absent = False
    except FileNotFoundError:
        absent = True
    check('private_registration_removed', absent)
    result['result'] = 'PASS'
except BaseException as error:
    result['result'] = 'FAIL'
    result['errorClass'] = type(error).__name__
    raise
finally:
    (root / 'REMAINING_INSTALLER_RESULTS.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))
