"""Bounded Windows fixture inspector; no policy changes or execution fallback.

Default is read-only. --create-process-once explicitly requests ONE invocation
of the unchanged packaged --offline-runtime-check at the same installed path.
It never uses a shell, alternate executable, elevated token or retry loop.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def ordinary(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.exists() and (part.is_symlink() or part.is_junction() or
                              getattr(part.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('reparse-path-refused')
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--create-process-once', action='store_true')
    args = parser.parse_args()
    if os.name != 'nt' or sys.version_info[:3] != (3, 14, 7):
        raise SystemExit('Windows Python3.14.7 only')
    root, temp = ordinary(args.fixture), ordinary(os.environ['TEMP'])
    if root == temp or not root.is_relative_to(temp):
        raise SystemExit('synthetic-TEMP-fixture-required')
    old = json.loads(ordinary(root / 'cleanup-result.json').read_text())
    if old.get('syntheticProfilePreserved') is not True or old.get('exit') != 0:
        raise SystemExit('existing-owned-fixture-evidence-required')
    exe = ordinary(root / 'Local/Programs/NewsFlowAI-Private/slots/1.0.0/NewsFlowAI-Candidate.exe')
    if not re.fullmatch('[0-9a-f]{64}', args.expected_sha256):
        raise SystemExit('expected-image-digest-required')
    import win32api, win32con, win32file, win32security
    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32con.TOKEN_QUERY)
    try:
        elevated = win32security.GetTokenInformation(token, win32security.TokenElevation)
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
    finally:
        token.Close()
    if elevated:
        raise SystemExit('elevated-diagnostic-refused')
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    if digest != args.expected_sha256:
        raise SystemExit('image-changed-stop-without-execution')
    security = win32security.GetFileSecurity(str(exe), win32security.OWNER_SECURITY_INFORMATION | win32security.DACL_SECURITY_INFORMATION)
    owner = security.GetSecurityDescriptorOwner() == sid
    dacl = security.GetSecurityDescriptorDacl()
    own_execute = any((ace := dacl.GetAce(n))[0][0] == win32security.ACCESS_ALLOWED_ACE_TYPE
                      and ace[2] == sid and ace[1] & 0x20 for n in range(dacl.GetAceCount()))
    if not owner or not own_execute:
        raise SystemExit('owner-execute-boundary-failed')
    access = {}
    for name, desired in [('read', win32con.GENERIC_READ), ('execute', win32con.GENERIC_EXECUTE)]:
        try:
            handle = win32file.CreateFile(str(exe), desired, 7, None, win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
            handle.Close()
            access[name] = 'ALLOWED'
        except OSError as error:
            access[name] = {'winerror': error.winerror}
    result = {'callerPid': os.getpid(), 'elevated': False, 'imageSha256': digest,
              'ownerMatchesCaller': owner, 'ownerExecuteAce': bool(own_execute),
              'nativeFileAccess': access, 'childPid': None, 'processAttempted': False,
              'policyChanged': False, 'shellUsed': False, 'automaticRetry': False}
    if args.create_process_once:
        if any(value != 'ALLOWED' for value in access.values()):
            raise SystemExit('file-access-denied-stop-without-execution')
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'PROCESSOR_ARCHITECTURE', 'NUMBER_OF_PROCESSORS', 'OS'}}
        env.update(PATH=str(Path(env['SYSTEMROOT']) / 'System32'), LOCALAPPDATA=str(root / 'Local'),
                   APPDATA=str(root / 'Roaming'), USERPROFILE=str(root / 'Home'), HOME=str(root / 'Home'),
                   TEMP=str(root / 'Temp'), TMP=str(root / 'Temp'))
        result['processAttempted'] = True
        try:
            process = subprocess.Popen([str(exe), '--offline-runtime-check'], cwd=exe.parent, env=env,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            result['childPid'] = process.pid
            try:
                output = process.communicate(timeout=60)[0]
                result.update(exit=process.returncode, outputBytes=len(output))
            except subprocess.TimeoutExpired:
                result['state'] = 'UNKNOWN-stop-and-inspect-owned-child-no-auto-kill-or-retry'
        except OSError as error:
            result.update(state='PROCESS_CREATION_DENIED', exception=type(error).__name__, winerror=error.winerror)
    output = ordinary(args.output)
    if output.exists():
        raise SystemExit('preserve-existing-output')
    output.write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
