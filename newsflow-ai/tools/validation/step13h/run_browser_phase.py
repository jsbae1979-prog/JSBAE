"""Own only this Python->Node->Chrome tree with a kill-on-close Windows Job."""
import sys,os,json,subprocess,time,ctypes,hashlib,datetime
from pathlib import Path
from ctypes import wintypes as W
assert sys.version_info[:3]==(3,14,7)
R=Path(__file__).parent
D=json.loads((R/'runtime-config-private.json').read_text());P=Path(D['project']);runtime=Path(D['runtime']);vendor=Path(D['fixture_vendor'])
sys.path.insert(0,str(R))
if sys.argv[1]=="minimal":
 import observer
 observer.start(R)
phase=sys.argv[1];assert phase in ('minimal','gui','remaining','full','security','envfix','cwdcheck','h','h2')
for name in ('temp','home','local','roaming','artifacts'):(R/name).mkdir(exist_ok=True)
c=json.loads((R/'guard-config-private.json').read_text());c['browser']['preload_SHA256']=hashlib.sha256((R/'node_boundary.cjs').read_bytes()).hexdigest();(R/'guard-config-private.json').write_text(json.dumps(c,indent=2),encoding='utf-8')
env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS'}}
binary=Path(next(iter(c['binaries']))).parent
env.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',PYTHONPATH=os.pathsep.join([str(R),str(vendor),str(P),str(P/'tests'),str(P/'tools'),str(P/'src')]),STEP13_ROOT=str(R),STEP13_PROJECT=str(P),NEWSFLOW_DATA_DIR=str(R/'synthetic-profile'),NEWSFLOW_VALIDATION_OUTPUT=str(R/'artifacts'),NEWSFLOW_PORT='18765',NEWSFLOW_LIVE_TEST='0',NEWSFLOW_AI_LIVE_TEST='0',LOCALAPPDATA=str(R/'home/AppData/Local'),APPDATA=str(R/'home/AppData/Roaming'),TEMP=str(R/'temp'),TMP=str(R/'temp'),USERPROFILE=str(R/'home'),HOME=str(R/'home'),NEWSFLOW_FFMPEG=str(binary/'ffmpeg.exe'),NEWSFLOW_FFPROBE=str(binary/'ffprobe.exe'),NEWSFLOW_FONT_PATH=r'C:\Windows\Fonts\malgun.ttf',STEP13_WORKER_MODE='suppressed',NEWSFLOW_TEST_BROWSER_EXECUTABLE=c['browser']['chrome'],NODE_OPTIONS='--require="'+Path(c['browser']['preload']).as_posix()+'"')
env['PATH']=os.pathsep.join([str(binary),str(runtime/'Scripts'),r'C:\Windows\System32',r'C:\Windows'])
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
job_counts=None
job=K.CreateJobObjectW(None,None)
if not job:raise ctypes.WinError(ctypes.get_last_error())
limit=LIMIT();limit.BasicLimitInformation.LimitFlags=0x2000
if not K.SetInformationJobObject(job,9,ctypes.byref(limit),ctypes.sizeof(limit)):raise ctypes.WinError(ctypes.get_last_error())
gate=R/'job-ready.signal';gate.unlink(missing_ok=True)
started=datetime.datetime.now().astimezone().isoformat();process=None;assigned=False;timedout=False
try:
 with (R/(phase+'-process.log')).open('wb') as log:
  process=subprocess.Popen([str(runtime/'Scripts/python.exe'),'-B',str(R/'browser_bootstrap.py'),phase],cwd=R,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
  if not K.AssignProcessToJobObject(job,int(process._handle)):raise ctypes.WinError(ctypes.get_last_error())
  assigned=True;gate.write_text('owned test Job assigned',encoding='ascii')
  try:code=process.wait(timeout=180 if phase=='minimal' else (5400 if phase=='full' else 1500))
  except subprocess.TimeoutExpired:timedout=True;code=124
finally:
 accounting=ACCOUNTING()
 if K.QueryInformationJobObject(job,1,ctypes.byref(accounting),ctypes.sizeof(accounting),None):job_counts={'active_before_close':accounting.ActiveProcesses,'total_processes':accounting.TotalProcesses}
 K.CloseHandle(job)
 if process is not None:
  try:process.wait(timeout=15)
  except subprocess.TimeoutExpired:raise RuntimeError('owned child did not exit after Job close')
 gate.unlink(missing_ok=True)
if sys.argv[1]=="minimal":observer.finish()
result={'phase':phase,'started':started,'finished':datetime.datetime.now().astimezone().isoformat(),'exit':code,'child_PID':process.pid if process else None,'Job_assigned':assigned,'Job_kill_on_close':True,'Job_process_counts':job_counts,'child_exited':process.poll() is not None if process else True,'timeout':timedout,'provider_env_inherited':False,'operating_risk':'current Windows user still has operating OS file rights; no complete OS isolation claim','original_Guard_preserved':True}
(R/(phase+'-supervisor-safe.json')).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)
raise SystemExit(code)
