"""Step13J-final test-only native bridge. No product import installs this policy.

Only pinned Python re-exec through the guarded child bootstrap, and the existing
PowerShell startup program with identity/validate stdin, can cross this boundary.
All other interpreters, raw Python entry points, shell and task mutations deny.
"""
from pathlib import Path  # noqa: I001 -- audited Guard preload/order or bounded execution; keep runtime unchanged.
import hashlib, json, os, re, subprocess, sys, threading, uuid
from contextvars import ContextVar

ROOT = Path(__file__).resolve().parent
EVENTS = []
LAUNCHES = {}
PS_CONTEXT = ContextVar('native_schema_only', default=None)
IDENTITIES = set()
INSTALLED = False
# Fixed script constants are inserted from the reviewed test AST by the authoring helper.
CODES = {'lock': "from filelock import FileLock; import sys; lock=FileLock(sys.argv[1]); lock.acquire(); print('ready', flush=True); sys.stdin.readline(); lock.release()", 'oauth_bind': "import json,socket,sys\ns=socket.socket(socket.AF_INET,socket.SOCK_STREAM)\ntry:\n s.bind(('127.0.0.1',int(sys.argv[1])))\nexcept OSError:\n print(json.dumps({'bind_denied':True}))\nelse:\n print(json.dumps({'bind_denied':False}))\nfinally:\n s.close()\n", 'preview_boundary': "\nimport os, runpy, socket, subprocess\nmodule = runpy.run_path('tools/ui_preview.py')\nmodule['install_boundary']()\nassert 'NEWSFLOW_AI_API_KEY' not in os.environ\nfor operation in [lambda: socket.getaddrinfo('never-resolve.example.com',443),\n                  lambda: subprocess.Popen(['powershell.exe','-Command','blocked'])]:\n    try:\n        operation()\n    except OSError:\n        pass\n    else:\n        raise AssertionError('Preview boundary did not block a side effect')\n", 'entrypoint': "\nimport faulthandler,json,os,sys,threading,time\nfaulthandler.dump_traceback_later(20)\nfrom pathlib import Path\nfrom pc_cloud_guard import audit,attempts\nsys.addaudithook(audit)\nfrom newsflow import main\nfrom newsflow.news.rss_adapter import FakeRSSAdapter\nfrom newsflow.scheduler.service import Scheduler\nfrom newsflow.publishing.calendar import PublishingCalendar\nfrom newsflow.video.ai.service import AIVideoCoordinator\nScheduler.start=lambda self:None\nPublishingCalendar.start=lambda self:None\nAIVideoCoordinator.start=lambda self:None\ncreate=main.create_app\nmain.create_app=lambda settings,**kwargs:create(settings,FakeRSSAdapter({}),**kwargs)\nimport uvicorn\nserver=uvicorn.Server\nclass BoundedServer(server):\n    def __init__(self,config):\n        config.timeout_graceful_shutdown=3\n        super().__init__(config)\n    async def startup(self,sockets=None):\n        await super().startup(sockets)\n        def wait_stop():\n            deadline=time.monotonic()+60\n            while not Path(os.environ['NF_STOP_FILE']).exists() and time.monotonic()<deadline:\n                time.sleep(.05)\n            self.should_exit=True\n        threading.Thread(target=wait_stop,daemon=True).start()\nuvicorn.Server=BoundedServer\nmain.run()\nfaulthandler.cancel_dump_traceback_later()\nPath(os.environ['NF_GUARD_RESULT']).write_text(json.dumps({'attempts':attempts,'shutdown':'normal'}))\n"}
STARTUP_SCRIPT_SHA256 = '7df022615758d2200e61615299ff4861f6eab4ec4aed9ec767bbe8a794956b28'
SYNTHETIC_SID = 'S-1-5-21-100-200-300-1001'

class NativeBoundaryError(PermissionError):
    pass

def deny(reason):
    EVENTS.append({'kind':'DENY','reason':reason})
    raise NativeBoundaryError('Step13J native boundary: '+reason)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def config():
    p=ROOT/'native-config-private.json'
    if not p.is_file():deny('native-config-missing')
    c=json.loads(p.read_text(encoding='utf-8-sig'))
    if c.get('Python')!='3.14.7':deny('Python-version-policy')
    return c

def guard():
    import step13_guard
    return step13_guard

def safe_path(value, *, output=False):
    g=guard();p=g.path(value)
    if p==ROOT or not g.inside(p,ROOT) or g.inside(p,g.PROJECT):deny('non-synthetic-native-path')
    g.check_file(p,write=output)
    return p

def runtime_check(c):
    if tuple(sys.version_info[:3])!=(3,14,7):deny('runtime-version')
    for key in ('python','bootstrap','boundary','guard'):
        p=Path(c[key]).resolve()
        if key!='python' and p.parent!=ROOT:deny('bridge-location')
        if sha(p)!=c[key+'_SHA256']:deny('native-hash-mismatch-'+key)
    if Path(c['python']).resolve()!=Path(sys.executable).resolve():deny('Python-executable')
    if Path(c['bootstrap']).name!='native_child_bootstrap.py':deny('bootstrap-name')
    vendor=Path(c['fixture_vendor']).resolve()
    found={str(p.relative_to(vendor)).replace('\\','/'):sha(p) for p in vendor.rglob('*.py')}
    if found!=c['vendor_python_hashes']:deny('vendor-code-hash')

def source_check(c, relative):
    g=guard();p=(g.PROJECT/relative).resolve()
    if not g.inside(p,g.PROJECT):deny('source-path')
    if sha(p)!=c['source_hashes'].get(relative):deny('native-source-hash')
    return p

def recognizes_binary(value):
    try:
        p=guard().path(value)
        if p==Path(sys.executable).resolve():return True
        c=config()
        return p==Path(c['powershell']).resolve()
    except NativeBoundaryError:
        return False

def port(value):
    try:p=int(value)
    except (ValueError,TypeError):deny('native-port')
    if p==8765 or not 1024<=p<=65535:deny('native-port')
    return p

def command_kind(argv,c):
    """Accept only reviewed code bytes/entry points; never arbitrary -c or -m."""
    if not all(type(v) is str for v in argv):deny('native-argument-types')
    tail=argv[1:]
    if tail[:1]==['-B']:tail=tail[1:]
    if len(tail)>=2 and tail[0]=='-c':
        for name,code in CODES.items():
            if tail[1]!=code:continue
            if name=='lock' and len(tail)==3:
                p=safe_path(tail[2],output=True)
                if p.name!='autopilot.lock':deny('lock-filename')
            elif name=='oauth_bind' and len(tail)==3:port(tail[2])
            elif name in ('preview_boundary','entrypoint') and len(tail)==2:pass
            else:deny('fixed-script-arguments')
            return name,{'kind':'code','code_name':name,'args':tail[2:]}
        deny('unapproved-Python-code')
    g=guard()
    if tail[:2]==['-m','newsflow.main'] and len(tail)==2:
        source_check(c,'src/newsflow/main.py')
        return 'main',{'kind':'module','module':'newsflow.main','args':[]}
    if tail[:2]==['-m','newsflow.diagnostics'] and tail[2:]==['--url','https://example.com/rss?api_key=DO-NOT-EXPOSE-API-KEY']:
        source_check(c,'src/newsflow/diagnostics.py')
        return 'diagnostics',{'kind':'module','module':'newsflow.diagnostics','args':tail[2:]}
    if len(tail)==3 and Path(tail[0]).resolve()==g.PROJECT/'tools/ui_preview.py' and tail[1]=='--data-dir':
        source_check(c,'tools/ui_preview.py');p=safe_path(tail[2])
        if not p.is_dir():deny('preview-must-test-existing-directory')
        return 'preview_existing',{'kind':'script','relative':'tools/ui_preview.py','args':tail[1:]}
    if len(tail)==11 and Path(tail[0]).resolve()==g.PROJECT/'tools/ci_feed_review.py':
        if tail[1:4]!=['--mode','cloud','--output'] or tail[5:]!=['--max-seconds','5','--preflight-host','localhost','--only','google-news-kr-top,github-blog']:deny('feed-review-arguments')
        source_check(c,'tools/ci_feed_review.py');safe_path(tail[4],output=True)
        return 'feed_review',{'kind':'script','relative':'tools/ci_feed_review.py','args':tail[1:]}
    deny('unapproved-Python-entry')

BASE_ENV={'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS'}
PATH_ENV={'TEMP','TMP','USERPROFILE','HOME','LOCALAPPDATA','APPDATA','NEWSFLOW_DATA_DIR','NEWSFLOW_VALIDATION_OUTPUT','NF_STOP_FILE','NF_GUARD_RESULT'}

def sanitized_env(original,mode,c):
    """Reject real credentials before copying only the required synthetic values."""
    original=dict(os.environ if original is None else original)
    if not all(type(k) is str and type(v) is str for k,v in original.items()):deny('native-environment-types')
    trusted=c['os_environment']
    upper={k.upper():v for k,v in original.items()}
    for k in BASE_ENV:
        if upper.get(k)!=trusted.get(k):deny('OS-environment-redirection')
    allowed_sentinels={'preview_boundary':{'NEWSFLOW_AI_API_KEY':'synthetic-only-must-be-removed'},'main':{'NEWSFLOW_SECRET_KEY':'SECRET-SENTINEL'}}.get(mode,{})
    for k,v in original.items():
        if k.upper().endswith(('_KEY','_TOKEN','_PASSWORD','_SECRET')):  # noqa: SIM102 -- audited Guard preload/order or bounded execution; keep runtime unchanged.
            if allowed_sentinels.get(k)!=v:deny('credential-environment')
    out=dict(trusted)
    for k in PATH_ENV:
        if k in original:
            safe_path(original[k],output=True);out[k]=original[k]
    for k in ('TEMP','TMP','USERPROFILE','HOME','LOCALAPPDATA','APPDATA','NEWSFLOW_DATA_DIR'):
        if k not in out:deny('missing-synthetic-environment-'+k)
    if 'NEWSFLOW_PORT' in original:out['NEWSFLOW_PORT']=str(port(original['NEWSFLOW_PORT']))
    else:out['NEWSFLOW_PORT']='18765'
    if original.get('NEWSFLOW_HOST','127.0.0.1')!='127.0.0.1':deny('non-loopback-native-host')
    out['NEWSFLOW_HOST']='127.0.0.1'
    if mode=='entrypoint':
        for k in ('NF_STOP_FILE','NF_GUARD_RESULT'):
            if k not in out:deny('missing-entrypoint-signal')
    for k in ('NEWSFLOW_LIVE_TEST','NEWSFLOW_AI_LIVE_TEST'):
        if original.get(k,'0')!='0':deny('live-execution-environment')
        out[k]='0'
    for k,v in allowed_sentinels.items():
        if original.get(k)==v:out[k]=v
    out.update(PYTHONUTF8='1',PYTHONDONTWRITEBYTECODE='1',STEP13_ROOT=str(ROOT),STEP13_PROJECT=str(guard().PROJECT),STEP13_NATIVE_CHILD='1')
    bins=guard().PINNED
    for key,stem in (('NEWSFLOW_FFMPEG','ffmpeg'),('NEWSFLOW_FFPROBE','ffprobe')):
        selected=[p for p in bins if p.stem.lower()==stem]
        if len(selected)!=1:deny('media-binary-ambiguity')
        out[key]=str(selected[0])
    out['PATH']=os.pathsep.join([str(Path(c['python']).parent),str(Path(out['SYSTEMROOT'])/'System32'),out['SYSTEMROOT']])
    # -I/-S ignores Python environment search paths; bootstrap supplies exact roots.
    return out

def prepare_spawn(args,pos,kwargs):
    """Called only by the existing guarded Popen wrapper, before native creation."""
    g=guard();argv=g.split_windows(args);binary=g.path(argv[0],kwargs.get('cwd'))
    if binary!=Path(sys.executable).resolve():
        c=config()
        if binary!=Path(c['powershell']).resolve():return args,kwargs
        return prepare_powershell(argv,pos,kwargs,c)
    if pos:deny('native-positional-Popen-options')
    c=config();runtime_check(c)
    if kwargs.get('executable') is not None and Path(kwargs['executable']).resolve()!=binary:deny('native-executable-mismatch')
    if kwargs.get('creationflags',0) not in (0,subprocess.CREATE_NEW_PROCESS_GROUP):deny('native-creation-flags')
    if kwargs.get('shell',False):deny('native-shell')
    cwd=g.path(kwargs.get('cwd') or os.getcwd())
    if not g.inside(cwd,ROOT):deny('native-cwd')
    mode,payload=command_kind(argv,c)
    if mode=='preview_boundary':source_check(c,'tools/ui_preview.py')
    if mode=='entrypoint':
        source_check(c,'src/newsflow/main.py');source_check(c,'tools/pc_cloud_guard.py')
    env=sanitized_env(kwargs.get('env'),mode,c)
    ticket_dir=ROOT/'native-tickets';ticket_dir.mkdir(exist_ok=True)
    ticket=ticket_dir/(uuid.uuid4().hex+'.json')
    body={'schema':1,'mode':mode,'payload':payload,'cwd':str(cwd),'environment_sha256':hashlib.sha256(json.dumps(env,sort_keys=True).encode()).hexdigest()}
    ticket.write_text(json.dumps(body,ensure_ascii=False),encoding='utf-8')
    digest=sha(ticket)
    secured=[str(binary),'-I','-S','-B',str(Path(c['bootstrap']).resolve()),str(ticket),digest]
    new=dict(kwargs);new['env']=env;new['cwd']=str(cwd)
    LAUNCHES[threading.get_ident()]={'argv':secured,'env':env,'cwd':str(cwd),'ticket_sha256':digest}
    EVENTS.append({'kind':'Python-approved','mode':mode,'Guard_child_required':True})
    return secured,new

def validate_process(executable,argv,cwd,env):
    c=config();g=guard();binary=g.path(argv[0],cwd)
    if binary==Path(c['powershell']).resolve():return validate_powershell(executable,argv,cwd,env,c)
    runtime_check(c)
    launch=LAUNCHES.get(threading.get_ident())
    if launch is None or argv!=launch['argv'] or dict(env or {})!=launch['env'] or str(g.path(cwd))!=launch['cwd']:deny('unregistered-native-child')
    if executable is not None and g.path(executable,cwd)!=Path(c['python']).resolve():deny('native-executable-mismatch')
    if sha(argv[5])!=launch['ticket_sha256']:deny('native-ticket-changed')
    return argv

def clear_launch():
    LAUNCHES.pop(threading.get_ident(),None)

def validate_payload(payload,c):
    if not isinstance(payload,dict):deny('PowerShell-JSON-shape')
    operation=payload.get('operation')
    if operation=='identity' and set(payload)=={'operation'}:return
    if operation!='validate' or set(payload)!={'operation','sid','name','xml'}:deny('PowerShell-operation')
    if payload['sid'] not in IDENTITIES:deny('PowerShell-unverified-identity')
    xml=payload['xml']
    if not isinstance(xml,str) or len(xml)>32768 or '<!' in xml:deny('PowerShell-XML-shape')
    import xml.etree.ElementTree as ET
    try:
        tree=ET.fromstring(xml)
        ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        work=tree.findtext('t:Actions/t:Exec/t:WorkingDirectory',namespaces=ns)
        args=tree.findtext('t:Actions/t:Exec/t:Arguments',namespaces=ns)
        values=guard().split_windows(args)
        if values[:3]!=['-m','newsflow.operations.autorun','--data-dir'] or len(values)!=4:deny('PowerShell-task-arguments')
        root=safe_path(work);data=safe_path(values[3])
        from newsflow.operations.startup import StartupPlan
        plan=StartupPlan(root,data,SYNTHETIC_SID)
        if xml!=plan.xml() or payload['name']!=plan.name:deny('PowerShell-synthetic-schema')
    except NativeBoundaryError:raise
    except (ValueError,TypeError,ET.ParseError):deny('PowerShell-XML-parse')

def powershell_argv(argv,c):
    if not all(type(v) is str for v in argv):deny('PowerShell-argument-types')
    if len(argv)!=5 or argv[1:4]!=['-NoProfile','-NonInteractive','-Command']:deny('PowerShell-arguments')
    executable=Path(argv[0])
    if not executable.is_absolute() or executable.resolve()!=Path(c['powershell']).resolve():deny('PowerShell-executable-path')
    if hashlib.sha256(argv[4].encode()).hexdigest()!=STARTUP_SCRIPT_SHA256:deny('PowerShell-program')
    if sha(c['powershell'])!=c['powershell_SHA256']:deny('PowerShell-hash')
    source_check(c,'src/newsflow/operations/startup.py')

def prepare_powershell(argv,pos,kwargs,c):
    if pos or kwargs.get('creationflags',0)!=0 or kwargs.get('shell',False):deny('PowerShell-process-options')
    ctx=PS_CONTEXT.get()
    if ctx is None:deny('PowerShell-outside-validated-run')
    powershell_argv(argv,c)
    if argv!=ctx['argv']:deny('PowerShell-context-arguments')
    if any(kwargs.get(k)!=subprocess.PIPE for k in ('stdin','stdout','stderr')):deny('PowerShell-stdio')
    env=sanitized_env(kwargs.get('env'),'schema',c)
    # The fixed program needs Windows built-ins only; never load user modules/profile.
    env={k:v for k,v in env.items() if k.upper() in BASE_ENV|{'PATH','TEMP','TMP','USERPROFILE','HOME','LOCALAPPDATA','APPDATA'}}
    env['PSModulePath']=str(Path(env['SYSTEMROOT'])/'System32/WindowsPowerShell/v1.0/Modules')
    cwd=str(ROOT)
    new=dict(kwargs);new.update(env=env,cwd=cwd)
    LAUNCHES[threading.get_ident()]={'argv':argv,'env':env,'cwd':cwd,'operation':ctx['payload']['operation']}
    EVENTS.append({'kind':'PowerShell-approved','operation':ctx['payload']['operation'],'task_registration_allowed':False})
    return argv,new

def validate_powershell(executable,argv,cwd,env,c):
    powershell_argv(argv,c);ctx=PS_CONTEXT.get();launch=LAUNCHES.get(threading.get_ident())
    if ctx is None or launch is None or argv!=launch['argv'] or dict(env or {})!=launch['env'] or str(Path(cwd).resolve())!=launch['cwd']:deny('PowerShell-unregistered-context')
    if executable is not None and Path(executable).resolve()!=Path(c['powershell']).resolve():deny('PowerShell-executable-mismatch')
    validate_payload(ctx['payload'],c)
    return argv

def install_run_boundary():
    global INSTALLED
    if INSTALLED:return
    original_run=subprocess.run
    def limited_run(*popenargs,**kwargs):
        args=popenargs[0] if popenargs else kwargs.get('args')
        if args is None:return original_run(*popenargs,**kwargs)
        argv=guard().split_windows(args)
        try:c=config()
        except NativeBoundaryError:
            if Path(str(argv[0])).name.lower()=='powershell.exe':raise
            return original_run(*popenargs,**kwargs)
        if guard().path(argv[0],kwargs.get('cwd'))!=Path(c['powershell']).resolve():return original_run(*popenargs,**kwargs)
        powershell_argv(argv,c)
        current=os.environ.get('PYTEST_CURRENT_TEST','').rsplit(' ',1)[0].replace('\\','/')
        if not current.endswith('test_operational_startup.py::test_native_windows_schema_roundtrip_without_registration'):deny('PowerShell-test-scope')
        value=kwargs.get('input')
        if type(value) is not str or len(value)>65536:deny('PowerShell-input')
        def unique_object(pairs):
            result={}
            for k,v in pairs:
                if k in result:deny('PowerShell-duplicate-JSON-key')
                result[k]=v
            return result
        try:payload=json.loads(value,object_pairs_hook=unique_object)
        except (ValueError,TypeError):deny('PowerShell-JSON')
        validate_payload(payload,c)
        if kwargs.get('encoding')!='utf-8' or kwargs.get('timeout')!=20 or kwargs.get('capture_output') is not True or kwargs.get('check',False) is not False:deny('PowerShell-run-options')
        token=PS_CONTEXT.set({'argv':argv,'payload':payload,'input':value})
        try:
            result=original_run(*popenargs,**kwargs)
            EVENTS.append({'kind':'PowerShell-complete','operation':payload['operation'],'exit':result.returncode})
            if payload['operation']=='identity' and result.returncode==0:
                try:
                    identity=json.loads(result.stdout.lstrip('\ufeff'))
                    sid=identity['sid']
                    if not re.fullmatch(r'S-1-(?:5-21|12-1)-(?:[0-9]+-){3}[0-9]+',sid) or not isinstance(identity.get('elevated'),bool):deny('PowerShell-identity-response')
                    IDENTITIES.add(sid)
                except (ValueError,TypeError,KeyError):deny('PowerShell-identity-response')
            return result
        except (subprocess.TimeoutExpired, OSError) as exc:
            # Diagnostic type only: never record argv, SID, stdout, stderr or environment.
            EVENTS.append({'kind':'PowerShell-exception','operation':payload['operation'],
                           'error_type':type(exc).__name__})
            raise
        finally:PS_CONTEXT.reset(token)
    subprocess.run=limited_run;INSTALLED=True


def write_evidence(output):
    target=Path(output)/'native-boundary-safe.json'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'events':EVENTS,'guard_disabled':False,'real_credentials_allowed':False,'task_mutation_permitted':False,'arbitrary_Python_or_Git_permitted':False,'note':'Approval events count validated dispatches; they do not claim all OS traffic was observed.'},indent=2),encoding='utf-8')
