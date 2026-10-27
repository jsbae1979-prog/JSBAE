"""Current-PC synthetic demo supervisor. No product policy or PowerShell changes."""
import argparse
import ctypes
import hashlib
import json
import msvcrt
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from ctypes import wintypes as W
from datetime import datetime
from pathlib import Path

assert sys.version_info[:3]==(3,14,7) and os.name=='nt'
K=ctypes.WinDLL('kernel32',use_last_error=True)
class IO(ctypes.Structure):_fields_=[(x,ctypes.c_ulonglong) for x in ('ReadOperationCount','WriteOperationCount','OtherOperationCount','ReadTransferCount','WriteTransferCount','OtherTransferCount')]
class BASIC(ctypes.Structure):_fields_=[('PerProcessUserTimeLimit',ctypes.c_longlong),('PerJobUserTimeLimit',ctypes.c_longlong),('LimitFlags',W.DWORD),('MinimumWorkingSetSize',ctypes.c_size_t),('MaximumWorkingSetSize',ctypes.c_size_t),('ActiveProcessLimit',W.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',W.DWORD),('SchedulingClass',W.DWORD)]
class LIMIT(ctypes.Structure):_fields_=[('BasicLimitInformation',BASIC),('IoInfo',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
K.CreateJobObjectW.argtypes=[ctypes.c_void_p,W.LPCWSTR];K.CreateJobObjectW.restype=W.HANDLE
K.SetInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD];K.SetInformationJobObject.restype=W.BOOL
K.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];K.AssignProcessToJobObject.restype=W.BOOL
K.CloseHandle.argtypes=[W.HANDLE];K.CloseHandle.restype=W.BOOL
class ACCOUNTING(ctypes.Structure):_fields_=[('TotalUserTime',ctypes.c_longlong),('TotalKernelTime',ctypes.c_longlong),('ThisPeriodTotalUserTime',ctypes.c_longlong),('ThisPeriodTotalKernelTime',ctypes.c_longlong),('TotalPageFaultCount',W.DWORD),('TotalProcesses',W.DWORD),('ActiveProcesses',W.DWORD),('TotalTerminatedProcesses',W.DWORD)]
K.QueryInformationJobObject.argtypes=[W.HANDLE,ctypes.c_int,ctypes.c_void_p,W.DWORD,ctypes.c_void_p];K.QueryInformationJobObject.restype=W.BOOL

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):h.update(block)
    return h.hexdigest()

def check_port(port):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        listener.bind(('127.0.0.1',port))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['start','stop','status']);parser.add_argument('--config',type=Path,required=True)
    args=parser.parse_args();config=args.config.resolve();root=config.parent
    c=json.loads(config.read_text(encoding='utf-8'));assert c['kind']=='NewsFlow-Step15B-DEMO'
    assert c['url']=='http://127.0.0.1:18765'
    profile=Path(c['profile']).resolve();exe=Path(c['exe']).resolve();bundle=exe.parent
    assert profile.is_relative_to(root) and profile!=root
    assert not profile.is_relative_to(bundle) and not bundle.is_relative_to(profile)
    assert json.loads((profile/'synthetic-only.json').read_text())=={'kind':'NewsFlow-Step15A-SYNTHETIC','port':18765}
    assert all(not p.is_symlink() and not p.is_junction() for p in [profile,exe,bundle])
    state=root/'launcher-state.json';request=root/'stop-request.txt'
    if args.action=='status':
        print(state.read_text(encoding='utf-8') if state.exists() else 'NOT STARTED');return
    if args.action=='stop':
        old=json.loads(state.read_text(encoding='utf-8'))
        if old['status']=='STOPPED':print('Already stopped');return
        assert old['status'] in ['STARTING','RUNNING'],'Not running; no force-stop or automatic retry'
        request.write_text(old['session'],encoding='ascii');print('Normal stop requested for this demo only.');return
    lock=(root/'launcher.lock').open('a+b');lock.seek(0);lock.write(b'1');lock.flush();lock.seek(0)
    msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    child=None;job=None;sid=uuid.uuid4().hex;code=1;normal=False
    def save(status,**values):
        value={'status':status,'at':datetime.now().astimezone().isoformat(),'session':sid,'mode':'DEMO-FAKE','url':c['url'],'operating_profile':False,'real_API':False,**values}
        pending=root/'launcher-state.pending';pending.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(pending,state)
    try:
        check_port(8765);check_port(18765)
        assert sha(exe)==c['sha256'],'EXE hash mismatch'
        manifest=json.loads(Path(c['bundle_manifest']).read_text(encoding='utf-8'))
        actual={p.relative_to(bundle).as_posix() for p in bundle.rglob('*') if p.is_file()}
        assert actual=={r['path'] for r in manifest},'Bundle file set mismatch'
        for row in manifest:
            p=(bundle/row['path']).resolve();assert p.is_relative_to(bundle)
            assert not p.is_symlink() and not p.is_junction() and p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],'Bundle integrity mismatch'
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS'}}
        env['PATH']=str(Path(env['SYSTEMROOT'])/'System32');env['PYTHONDONTWRITEBYTECODE']='1'
        job=K.CreateJobObjectW(None,None)
        if not job:raise ctypes.WinError(ctypes.get_last_error())
        limit=LIMIT();limit.BasicLimitInformation.LimitFlags=0x2000
        if not K.SetInformationJobObject(job,9,ctypes.byref(limit),ctypes.sizeof(limit)):raise ctypes.WinError(ctypes.get_last_error())
        request.unlink(missing_ok=True)
        save('STARTING',supervisor=os.getpid(),bundle_verified=len(manifest))
        with (root/('demo-'+sid+'.log')).open('wb') as log:
            child=subprocess.Popen([str(exe),'serve',str(profile)],cwd=profile,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        if not K.AssignProcessToJobObject(job,int(child._handle)):raise ctypes.WinError(ctypes.get_last_error())
        import urllib.request
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}));deadline=time.monotonic()+30;ready=False
        while time.monotonic()<deadline and child.poll() is None:
            try:
                with opener.open(c['url'],timeout=1) as response:ready=response.status==200
                if ready:break
            except (OSError,TimeoutError):pass
            time.sleep(.15)
        assert ready,'Synthetic server not ready; inspect demo log'
        save('RUNNING',supervisor=os.getpid(),child=child.pid,bundle_verified=len(manifest))
        print('DEMO / FAKE ONLY. Do not enter real keys or connect accounts.',flush=True)
        print(c['url'],flush=True);print('Use Stop Demo.cmd for normal shutdown. Keep this supervisor open.',flush=True)
        stop_sent=False;expired=False
        while child.poll() is None:
            if not stop_sent and request.exists() and request.read_text(encoding='ascii')==sid:
                child.send_signal(signal.CTRL_BREAK_EVENT);stop_sent=True;deadline=time.monotonic()+15
            if stop_sent and not expired and time.monotonic()>deadline and child.poll() is None:
                expired=True;save('BLOCKED_STOP_TIMEOUT',child=child.pid,normal_stop=False,automatic_retry=False)
            time.sleep(.1)
        check_port(18765)
        events=(profile/'AppData/Local/NewsFlowAI/logs/execution.log').read_text(encoding='utf-8')
        accounting=ACCOUNTING()
        assert K.QueryInformationJobObject(job,1,ctypes.byref(accounting),ctypes.sizeof(accounting),None)
        normal=stop_sent and not expired and child.returncode==0 and events.rstrip().endswith('server_stop') and accounting.ActiveProcesses==0
        assert normal,'Normal shutdown checks did not pass'
        save('STOPPED',normal_stop=True,exit_code=0,active_children=0,port_released=True,force_cleanup=False);code=0
    except BaseException as error:
        save('ERROR',error_type=type(error).__name__,message=str(error),normal_stop=False)
        raise
    finally:
        if job:
            accounting=ACCOUNTING()
            if K.QueryInformationJobObject(job,1,ctypes.byref(accounting),ctypes.sizeof(accounting),None) and accounting.ActiveProcesses:
                save('ABORTED_CLEANUP',normal_stop=False,force_cleanup=True,reason='Supervisor aborted; only its own demo Job is closed')
            K.CloseHandle(job)
            if child:child.wait(timeout=15)
        lock.seek(0);msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1);lock.close()
    return code
if __name__=='__main__':raise SystemExit(main())
