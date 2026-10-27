"""Authorized B-only bridge; original media/file/network guard remains installed."""
from pathlib import Path  # noqa: I001 -- audited Guard preload/order or bounded execution; keep runtime unchanged.
import os,json,hashlib,time,socket,contextlib,threading
from urllib.parse import urlsplit
R=Path(__file__).parent
C=json.loads((R/'guard-config-private.json').read_text());B=C['browser'];EVENTS=[];PLAYWRIGHT_LOOPS=[];OWNED_EXECUTORS=set();BROWSERS=[]
class BoundaryViolation(PermissionError):pass
def note(kind,**values):
 EVENTS.append({'kind':kind,**values});(R/'python-browser-events-safe.json').write_text(json.dumps(EVENTS,indent=2),encoding='utf-8')
def fail(kind):note('DENY',reason=kind);raise BoundaryViolation('B test boundary: '+kind)
def validate_node(executable,argv,cwd,env):
 if executable is not None and Path(executable).resolve()!=Path(B['node']):fail('Node executable mismatch')
 if argv!=[B['node'],B['cli'],'run-driver']:fail('Node argv')
 if Path(cwd or os.getcwd()).resolve()!=R.resolve():fail('Node cwd')
 for key,field in [('node','node_SHA256'),('cli','cli_SHA256'),('preload','preload_SHA256')]:
  if hashlib.sha256(Path(B[key]).read_bytes()).hexdigest()!=B[field]:fail('runtime hash')
 if env is None or env.get('NODE_OPTIONS')!='--require="'+Path(B['preload']).as_posix()+'"':fail('Node preload environment')
 if any(k.upper().endswith(('_KEY','_TOKEN','_SECRET','_PASSWORD')) for k in env):fail('credential environment')
 note('Node-approved',exact_entry=True,keys_inherited=False);return argv

def safe_url(url):
 u=urlsplit(url)
 return url=='about:blank' or u.scheme=='data' or (u.scheme=='http' and u.hostname=='127.0.0.1' and u.port==18765 and not u.username and not u.password)

def install_playwright():
 from playwright.sync_api import BrowserType,Browser,BrowserContext,Page,Route  # noqa: F401, I001 -- audited Guard preload/order or bounded execution; keep runtime unchanged.
 oldlaunch=BrowserType.launch;oldctx=Browser.new_context;oldgoto=Page.goto;oldcontinue=Route.continue_;oldfallback=Route.fallback
 def launch(self,*args,**kwargs):
  if self.name!='chromium' or args:fail('browser type')
  if kwargs.get('args'):fail('caller browser args')
  kwargs.pop('channel',None);kwargs['executable_path']=B['chrome'];kwargs['headless']=True;kwargs['chromium_sandbox']=True
  env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA','HOME','OS','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS'}}
  env['NODE_OPTIONS']='--require="'+Path(B['preload']).as_posix()+'"';kwargs['env']=env
  idx=sum(1 for x in EVENTS if x['kind']=='Chrome-launch')
  logdir=Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT'])/'netlogs';logdir.mkdir(parents=True,exist_ok=True)
  logfile=logdir/('netlog-'+str(idx)+'.json')
  kwargs['args']=['--proxy-server=http://127.0.0.1:18765','--proxy-bypass-list=127.0.0.1','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--disable-quic','--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--disable-component-update','--log-net-log='+str(logfile),'--net-log-capture-mode=Default']
  note('Chrome-launch',temporary_profile=True,operating_port=False,flags_fixed=True)
  browser=oldlaunch(self,**kwargs)
  PLAYWRIGHT_LOOPS.append(browser._impl_obj._loop);BROWSERS.append(browser)
  return browser
 def context(self,*args,**kwargs):
  kwargs['service_workers']='block';kwargs['accept_downloads']=False
  ctx=oldctx(self,*args,**kwargs)
  def gate(route):
   if safe_url(route.request.url):return route.continue_()
   note('blocked-browser-request',URL_SHA256=hashlib.sha256(route.request.url.encode()).hexdigest());route.abort();fail('external browser request')
  ctx.route('**/*',gate)
  return ctx
 def go(self,url,*args,**kwargs):
  u=urlsplit(url)
  virtual=(u.scheme=='http' and u.hostname=='127.0.0.1' and u.port is None and not u.username and not u.password)
  # Existing TestClient route.fulfill fixture uses a virtual origin, never a socket.
  # Network continue/fallback and the default route still require port18765.
  if not safe_url(url) and not virtual:fail('non-local navigation')
  if virtual:note('virtual-fulfill-origin',network_continue_allowed=False)
  return oldgoto(self,url,*args,**kwargs)
 def cont(self,*args,**kwargs):
  if not safe_url(kwargs.get('url') or self.request.url):fail('external continue')
  return oldcontinue(self,*args,**kwargs)
 def fallback(self,*args,**kwargs):
  if not safe_url(kwargs.get('url') or self.request.url):fail('external fallback')
  return oldfallback(self,*args,**kwargs)
 BrowserType.launch=launch;Browser.new_context=context;Page.goto=go;Route.continue_=cont;Route.fallback=fallback
 BrowserType.launch_persistent_context=lambda *a,**k:fail('persistent context forbidden')
 BrowserType.connect=lambda *a,**k:fail('existing browser connect forbidden')
 BrowserType.connect_over_cdp=lambda *a,**k:fail('existing browser CDP forbidden')
 note('Playwright-test-boundary-installed')

def install_local_fixture():
 import test_cloud_workspace_flow as module
 import uvicorn
 @contextlib.contextmanager
 def local_server(app):
  with socket.socket() as sock:
   sock.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1);sock.bind(('127.0.0.1',18765))
   server=uvicorn.Server(uvicorn.Config(app,log_level='error',access_log=False,lifespan='off',timeout_keep_alive=1,timeout_graceful_shutdown=3))
   thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
   try:
    deadline=time.monotonic()+15
    while not server.started:
     assert thread.is_alive() and time.monotonic()<deadline;time.sleep(.02)
    yield 'http://127.0.0.1:18765'
   finally:
    server.should_exit=True;thread.join(15)
    if thread.is_alive():fail('synthetic server not stopped')
 module.local_server=local_server
 note('fixture-server-fixed',port=18765)

def pytest_runtest_teardown(item,nextitem):
 log=R/'node-events-private.jsonl'
 if log.exists() and any(json.loads(x).get('type')=='DENY' for x in log.read_text().splitlines() if x):item.session.shouldstop='native Node test boundary denial; stop unsafe continuation'
 if any(x['kind']=='DENY' for x in EVENTS):item.session.shouldstop='Python/browser test boundary denial'

def browser_owned_threads():
 for loop in PLAYWRIGHT_LOOPS:
  executor=getattr(loop,'_default_executor',None)
  if executor is not None:OWNED_EXECUTORS.add(executor)
 return {thread for ex in OWNED_EXECUTORS for thread in getattr(ex,'_threads',())}

def pytest_sessionfinish(session,exitstatus):
 owned=browser_owned_threads()
 for ex in OWNED_EXECUTORS:ex.shutdown(wait=False,cancel_futures=True)
 deadline=time.monotonic()+10
 for thread in owned:thread.join(max(0,deadline-time.monotonic()))
 live=[t.name for t in owned if t.is_alive()]
 loops_open=sum(not loop.is_closed() for loop in PLAYWRIGHT_LOOPS)
 import asyncio
 loop_detail=[{'closed':loop.is_closed(),'running':loop.is_running(),'pending_tasks':sum(not t.done() for t in asyncio.all_tasks(loop)) if not loop.is_closed() else 0} for loop in PLAYWRIGHT_LOOPS]
 (R/'browser-runtime-cleanup-safe.json').write_text(json.dumps({'Playwright_loops':len(PLAYWRIGHT_LOOPS),'owned_executor_threads':len(owned),'owned_threads_remaining':live,'Playwright_loops_still_open':loops_open,'loop_detail':loop_detail,'connected_browsers':sum(browser.is_connected() for browser in BROWSERS),'proof':'Only actual registered Playwright loop executors deferred; all app/unknown threads retain per-test assertion.'}),encoding='utf-8')
 if live or loops_open:session.exitstatus=1
 note('pytest-finished',exit=int(exitstatus))


def pytest_runtest_logreport(report):
 row={'nodeid':report.nodeid,'when':report.when,'outcome':report.outcome,'duration':report.duration}
 if report.failed:row['failure_private']=str(report.longrepr)
 with (R/'test-progress-private.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
