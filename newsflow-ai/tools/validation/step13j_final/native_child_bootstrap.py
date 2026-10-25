"""Guard-first, exact-ticket entry for approved synthetic Python subprocesses."""
import sys, os, json, hashlib, ctypes, ipaddress, re, sqlite3, threading, subprocess, uuid, contextvars
from urllib.parse import urlsplit, unquote, parse_qsl
from pathlib import Path

ROOT=Path(__file__).resolve().parent
if sys.version_info[:3]!=(3,14,7):raise SystemExit('Python version mismatch')
if len(sys.argv)!=3:raise SystemExit('Invalid synthetic child entry')
ticket=Path(sys.argv[1]).resolve();expected=sys.argv[2]
if ticket.parent!=ROOT/'native-tickets' or ticket.suffix!='.json':raise SystemExit('Invalid synthetic ticket path')
raw=ticket.read_bytes()
if hashlib.sha256(raw).hexdigest()!=expected:raise SystemExit('Synthetic ticket changed')
value=json.loads(raw);config=json.loads((ROOT/'native-config-private.json').read_text(encoding='utf-8-sig'))
if value.get('schema')!=1:raise SystemExit('Unknown synthetic ticket')
if hashlib.sha256(json.dumps(dict(os.environ),sort_keys=True).encode()).hexdigest()!=value['environment_sha256']:raise SystemExit('Synthetic environment changed')
for key in ('bootstrap','boundary','guard'):
    p=Path(config[key]).resolve()
    if p.parent!=ROOT or hashlib.sha256(p.read_bytes()).hexdigest()!=config[key+'_SHA256']:raise SystemExit('Synthetic bridge changed')
project=Path(json.loads((ROOT/'guard-config-private.json').read_text(encoding='utf-8-sig'))['project']).resolve()
# -I/-S omits environment/PTH search paths. These exact reviewed roots are added.
site=Path(sys.prefix)/'Lib/site-packages'
if not site.is_dir():raise SystemExit('Expected isolated runtime unavailable')
# Do not put writable ROOT/project ahead of these pre-Guard support imports.
sys.path.insert(0,str(site))
import click._winconsole, filelock, colorama.win32
for module in (click,click._winconsole,filelock,colorama,colorama.win32):
    if not Path(module.__file__).resolve().is_relative_to(site.resolve()):raise SystemExit('Untrusted Windows support import')
# Fixed stdlib/support imports are loaded before adding the reviewed harness roots.
sys.path.append(str(ROOT))
kernel=ctypes.WinDLL('kernel32',use_last_error=True)
kernel.GetCurrentProcess.argtypes=[];kernel.GetCurrentProcess.restype=ctypes.c_void_p
kernel.IsProcessInJob.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int)];kernel.IsProcessInJob.restype=ctypes.c_int
inside_job=ctypes.c_int()
if not kernel.IsProcessInJob(kernel.GetCurrentProcess(),None,ctypes.byref(inside_job)) or not inside_job.value:raise SystemExit('Synthetic child is not owned by a process Job')
import step13_guard
step13_guard.install()
# Product and vendor imports enter only after the file/DB/network audit is active.
sys.path[:0]=[str(project/'src'),str(project/'tools'),config['fixture_vendor']]
import native_boundary
native_boundary.runtime_check(config)
mode=value['mode'];payload=value['payload']
expected_environment=native_boundary.sanitized_env(os.environ,mode,config)
if expected_environment!=dict(os.environ):raise SystemExit('Synthetic environment is not canonical')
if Path.cwd().resolve()!=Path(value['cwd']).resolve():raise SystemExit('Synthetic cwd changed')
sys.stdout.reconfigure(encoding='utf-8',errors='backslashreplace')
sys.stderr.reconfigure(encoding='utf-8',errors='backslashreplace')
import runpy
report={'mode':mode,'guard_installed_before_product':True,'owned_Job':True,'operating_profile_used':False,'external_provider_requests_authorized':False,'network_policy':'Guard denies external DNS/socket requests; see recorded denials'}
try:
    if mode in ('main','entrypoint'):
        # Test-only automatic execution suppression. Collection API remains available.
        from newsflow.scheduler.service import Scheduler
        from newsflow.publishing.calendar import PublishingCalendar
        from newsflow.video.ai.service import AIVideoCoordinator
        Scheduler.start=lambda self:None
        PublishingCalendar.start=lambda self:None
        AIVideoCoordinator.start=lambda self:None
        report['automatic_workers_suppressed']=True
    if payload['kind']=='code':
        code=native_boundary.CODES.get(payload['code_name'])
        if code is None or mode!=payload['code_name']:raise SystemExit('Unknown fixed synthetic script')
        sys.argv=['-c',*payload['args']]
        exec(compile(code,'<fixed-synthetic-'+mode+'>','exec'),{'__name__':'__main__','__builtins__':__builtins__})
    elif payload['kind']=='module':
        if payload['module'] not in ('newsflow.main','newsflow.diagnostics'):raise SystemExit('Unknown synthetic module')
        sys.argv=[payload['module'],*payload['args']]
        runpy.run_module(payload['module'],run_name='__main__',alter_sys=True)
    elif payload['kind']=='script':
        if payload['relative'] not in ('tools/ui_preview.py','tools/ci_feed_review.py'):raise SystemExit('Unknown synthetic script')
        script=native_boundary.source_check(config,payload['relative'])
        sys.argv=[str(script),*payload['args']]
        runpy.run_path(str(script),run_name='__main__')
    else:raise SystemExit('Unknown child payload')
finally:
    report['Guard_denials']=list(step13_guard.ATTEMPTS)
    report['native_denials']=[e['reason'] for e in native_boundary.EVENTS if e['kind']=='DENY']
    out=ROOT/'native-child-evidence';out.mkdir(exist_ok=True)
    (out/(ticket.stem+'-safe.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
