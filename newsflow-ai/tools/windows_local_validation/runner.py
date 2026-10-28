"""Owned, loopback HTTP -> unchanged ASGI app. Windows11 synthetic validation only.

No CI variable, operating main(), ASGI lifespan, scheduler, provider or shell.
The source-pinned verification Guard and existing native facades remain unchanged.
Any new Guard rejection stops this run; it is not dynamically permitted.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import traceback

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent;TOOLS=HERE.parent;PROJECT=HERE.parents[1]
args=argparse.ArgumentParser();args.add_argument('--workspace',required=True);args.add_argument('--diagnostic',action='store_true');options=args.parse_args()
workspace=Path(options.workspace).resolve()
if os.name!='nt' or sys.version_info[:3]!=(3,14,7) or sys.getwindowsversion().build<22000 or sys.getwindowsversion().product_type!=1:raise SystemExit('Windows11 workstation / Python3.14.7 required')
if 'GITHUB_ACTIONS' in os.environ:raise SystemExit('Local runner does not accept CI environment')
if not workspace.is_dir() or not (workspace/'owned-test-profile.json').is_file():raise SystemExit('Fresh owned profile required')
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((HERE/'SOURCE_HASHES.json').read_text(encoding='utf8'))
if any(digest(HERE/n)!=h for n,h in manifest.items()):raise SystemExit('Runner source mismatch')
borrowed=json.loads((HERE/'BORROWED_SOURCES.json').read_text(encoding='utf8'))
if any(digest(TOOLS/n)!=h for n,h in borrowed.items()):raise SystemExit('Borrowed source mismatch')
import shutil
for source,target in [('native_guard_copy/guard_verification.py','step13_guard.py'),('native_guard_copy/native_boundary_original.py','native_boundary.py'),('native_app_policy/verification_gate_app.py','verification_gate.py')]:
    (workspace/target).write_bytes((TOOLS/source).read_bytes())
reads=[workspace,PROJECT/'src',PROJECT/'frontend/dist',HERE,TOOLS/'native_capability',TOOLS/'native_rtl_filelock',TOOLS/'native_guard_copy',TOOLS/'native_app_policy',Path(sys.prefix),Path(sys.base_prefix)]
(workspace/'guard-config-private.json').write_text(json.dumps({'project':str(workspace/'protected-project'),'read_roots':[str(p) for p in reads],'binaries':{},'browser':{'node':str(workspace/'no-node.exe')},'verification_capability_sha256':manifest['guard_capability.py']}),encoding='utf8')
vendor=importlib.metadata.distribution('filelock')
if vendor.version!='3.32.7':raise SystemExit('Reviewed filelock version required')
package=Path(vendor.locate_file('filelock')).resolve()
sources={('filelock' if n=='__init__.py' else 'filelock.'+n[:-3]):str(package/n) for n in ('__init__.py','_api.py','_descriptor.py','_windows.py','_identity.py','_marker.py','_lease.py','_util.py')}
sys.path[:0]=[str(workspace),str(HERE),str(TOOLS/'native_rtl_filelock'),str(TOOLS/'native_capability'),str(PROJECT/'src')]
from runtime_fixes import bounded_import_paths
before_paths=list(sys.path)
sys.path[:]=bounded_import_paths(sys.path,reads)
pruned_count=len(before_paths)-len(sys.path)
evidence={'python':sys.version.split()[0],'Windows':str(sys.getwindowsversion()),'diagnostic_only':options.diagnostic,'CI_environment_used':False,'paid_API_SNS_calls':0,'OS_DPI':'NOT VERIFIED / unchanged','requests':[],'cleanup_errors':[],'final':'BLOCKED'}
evidence['http_scope_rejections']=[];evidence['feed_batches_reads']=[]
evidence['unneeded_import_search_entries_removed']=pruned_count
policy=bridge=native=app=server=loop=None
phase='Guard-first-bootstrap'
try:
    assert 'filelock' not in sys.modules and 'newsflow.main' not in sys.modules
    import step13_guard as guard
    guard.install()
    from verification_gate import VerificationGate, Denied
    gate=VerificationGate(workspace,PROJECT/'src',read_roots=reads);gate.install()
    from guard_capability import NativeRegistration
    registration=NativeRegistration(gate,sources);guard.register_verification_capability(registration)
    old_native=set(guard._NATIVE);old_dll=set(guard._SYSTEM_DLLS)
    import adapter
    native=adapter._Native(gate)
    from rtl_boundary import RtlBoundary
    bridge=RtlBoundary(native,registration);bridge.install_crt_wrappers()
    from local_policy import WindowsLocalPolicy,LOCK_NAMES
    policy=WindowsLocalPolicy(workspace,reads)
    registration.attach_app_policy(policy,manifest['local_policy.py'])
    data=Path(bridge.scope.root)
    for name in LOCK_NAMES:bridge.register_path(name)
    policy.install_sqlite([data/'newsflow.db']);policy.install_threads()
    from runtime_fixes import install_optional_probe
    optional_probe=install_optional_probe(policy,package)
    evidence['Guard_first']=guard.INSTALLED and gate.installed and 'filelock' not in sys.modules
    phase=policy.phase='create-app'
    from newsflow.config import Settings
    from newsflow.main import create_app
    from newsflow.news.rss_adapter import FakeRSSAdapter
    import secrets
    app=create_app(Settings(data_dir=data,port=18765,secret_key=secrets.token_hex(32)),FakeRSSAdapter({}),automatic_start=True)
    policy.checkpoint(guard.ATTEMPTS,gate.denials)
    if options.diagnostic:raise RuntimeError('Diagnostic-only run ends before seeding or HTTP')
    assert app.state.scheduler.thread is None and app.state.video_ai.thread is None
    evidence['lifespan_entered']=False;evidence['scheduler_started']=False
    evidence['data_path']=str(data);evidence['real_create_app']='PASS'
    phase=policy.phase='synthetic-seed'
    from seed import populate
    evidence['seed']=populate(app)
    policy.checkpoint(guard.ATTEMPTS,gate.denials)
    # No operational task/identity probe is part of a synthetic local profile.
    import newsflow.gui.operations_routes as operations
    operations.status=lambda *a,**k:{'registered':False,'synthetic':True,'reason':'Windows task registration not tested'}
    phase=policy.phase='owned-HTTP-server'
    policy.checkpoint(guard.ATTEMPTS,gate.denials)
    import asyncio
    import socketserver
    from http.server import HTTPServer,BaseHTTPRequestHandler
    from urllib.parse import urlsplit
    loop=asyncio.new_event_loop();asyncio.set_event_loop(loop)
    # Writes are local-only and still traverse unchanged product Origin/CSRF.
    from http_surface import request_allowed as allowed
    async def dispatch(method,url,headers,body):
        p=urlsplit(url);messages=[];received=False;size=0
        scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1','scheme':'http','method':method,'path':p.path,'raw_path':p.path.encode('ascii'),'query_string':p.query.encode('ascii'),'root_path':'','headers':[(k.lower().encode('latin1'),v.encode('latin1')) for k,v in headers.items()],'server':('127.0.0.1',18765),'client':('127.0.0.1',18766),'extensions':{}}
        async def receive():
            nonlocal received
            if not received:received=True;return {'type':'http.request','body':body,'more_body':False}
            await asyncio.Event().wait()
        async def send(m):
            nonlocal size
            if m['type'] not in {'http.response.start','http.response.body'}:raise RuntimeError('Unrequested ASGI extension')
            size+=len(m.get('body',b''))
            if size>20*1024*1024:raise RuntimeError('Bounded response exceeded')
            messages.append(m)
        with policy.request_io():
            async with asyncio.timeout(20):await app(scope,receive,send)
        return messages
    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*a):pass
        def do_GET(self):self.serve()
        def do_HEAD(self):self.serve()
        def do_POST(self):self.serve()
        def serve(self):
            path=urlsplit(self.path).path
            if self.client_address[0]!='127.0.0.1' or self.headers.get('Host')!='127.0.0.1:18765':self.send_error(403);return
            if not allowed(self.command,path):
                evidence['http_scope_rejections'].append({'method':self.command,'path':path})
                self.send_error(403,'Not in local validation scope');return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if length<0 or length>1024*1024:self.send_error(413);return
                body=self.rfile.read(length)
                result=loop.run_until_complete(dispatch(self.command,self.path,self.headers,body))
                start=next(m for m in result if m['type']=='http.response.start');content=b''.join(m.get('body',b'') for m in result if m['type']=='http.response.body')
                self.send_response(start['status'])
                for k,v in start['headers']:
                    if k.lower() not in {b'content-length',b'transfer-encoding',b'connection'}:self.send_header(k.decode('latin1'),v.decode('latin1'))
                original_length=next((v.decode() for k,v in start['headers'] if k.lower()==b'content-length'),str(len(content)))
                self.send_header('Content-Length',original_length if self.command=='HEAD' else str(len(content)))
                self.send_header('Connection','close');self.end_headers();self.close_connection=True
                if self.command!='HEAD':self.wfile.write(content)
                evidence['requests'].append({'method':self.command,'path':path,'status':start['status'],'bytes':len(content)})
                if self.command=='GET' and path=='/api/feed-batches' and start['status']==200:
                    data=json.loads(content)
                    evidence['feed_batches_reads'].append({'status':200,'batches':[{'id':b['id'],'status':b['status'],'revision':b['revision'],'ranks':[i['rank'] for i in b['items']]} for b in data['batches']]})
                if guard.ATTEMPTS or gate.denials:policy.halt=True
            except (BrokenPipeError,ConnectionResetError):self.close_connection=True
            except BaseException as exc:
                evidence['blocked']={'phase':policy.phase,'type':type(exc).__name__,'reason':str(exc)};policy.halt=True
                try:self.send_error(503,'Validation stopped; inspect evidence')
                except OSError:pass
    class OwnedHTTP(HTTPServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self);self.server_name='127.0.0.1';self.server_port=18765
    server=OwnedHTTP(('127.0.0.1',18765),Handler,bind_and_activate=False)
    policy.register_listener(server.socket);server.server_bind();server.server_activate();server.timeout=.5
    (workspace/'ready.json').write_text(json.dumps({'url':'http://127.0.0.1:18765/studio/dashboard','pid':os.getpid(),'synthetic':True}),encoding='utf8')
    print('LOCAL_VALIDATION_READY http://127.0.0.1:18765/studio/dashboard',flush=True)
    while not policy.halt and not (workspace/'STOP').exists():server.handle_request()
    evidence['final']='CONDITIONAL' if not policy.halt else 'BLOCKED'
except BaseException as exc:
    evidence['blocked']={'phase':phase,'type':type(exc).__name__,'reason':str(exc),'traceback':traceback.format_exc()}
    print('LOCAL_VALIDATION_BLOCKED '+type(exc).__name__+': '+str(exc),flush=True)
finally:
    if server is not None:server.server_close()
    if policy is not None:policy.phase='explicit-cleanup'
    if loop is not None:
        try:loop.run_until_complete(loop.shutdown_asyncgens());loop.run_until_complete(loop.shutdown_default_executor(timeout=2));loop.close()
        except BaseException as exc:evidence['cleanup_errors'].append({'resource':'eventloop','type':type(exc).__name__,'reason':str(exc)})
    if app is not None:
        if evidence.get('seed',{}).get('feed_batch_id'):
            try:
                b=app.state.top_three_feeds.view(evidence['seed']['feed_batch_id'])
                after={'id':b['id'],'status':b['status'],'revision':b['revision'],'items':[(i['rank'],i['status']) for i in b['items']]}
                evidence['feed_batch_after_reads']=after
                evidence['feed_batch_logically_unchanged']=after==evidence['seed']['feed_batch_snapshot']
            except BaseException as exc:evidence['cleanup_errors'].append({'resource':'feed-read-check','reason':str(exc)})
        for name in ('youtube','tiktok','instagram','publishing_calendar','scheduler','video_ai','autopilot','autopilot_backend','coordinator','video'):
            item=getattr(app.state,name,None)
            if item is not None:
                try:item.close()
                except BaseException as exc:evidence['cleanup_errors'].append({'resource':name,'type':type(exc).__name__,'reason':str(exc)})
        try:app.state.engine.dispose()
        except BaseException as exc:evidence['cleanup_errors'].append({'resource':'engine','reason':str(exc)})
    if policy is not None:
        for connection in list(policy.sqlite_connections):
            try:connection.close()
            except BaseException as exc:evidence['cleanup_errors'].append({'resource':'SQLite','reason':str(exc)})
        for thread in policy.threads:thread.join(timeout=2)
    if bridge is not None:
        try:bridge.close()
        except BaseException as exc:evidence['cleanup_errors'].append({'resource':'FileLock','reason':str(exc)})
        evidence['lock_resources']=bridge.status()
    if native is not None:evidence['remaining_native_handles']=len(native._owned_handles)
    if policy is not None:evidence['policy']=policy.status()
    if 'optional_probe' in globals():evidence['optional_link_probes_suppressed']=optional_probe.suppressed
    if 'guard' in globals():
        evidence['guard_denials']=guard.ATTEMPTS
        evidence['native_tables_unchanged']='old_native' in globals() and old_native==set(guard._NATIVE) and old_dll==set(guard._SYSTEM_DLLS)
    if 'gate' in globals():evidence['gate_denials']=gate.denials
    evidence['borrowed_sources_unchanged']=all(digest(TOOLS/n)==h for n,h in borrowed.items())
    (workspace/'result.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    print('LOCAL_VALIDATION_RESULT '+evidence['final'],flush=True)
