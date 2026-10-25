import sys,os,json,pathlib,time
R=pathlib.Path(__file__).parent
assert sys.version_info[:3]==(3,14,7)
deadline=time.monotonic()+10
while not (R/'job-ready.signal').exists():
 if time.monotonic()>deadline:raise SystemExit('owned process Job not assigned')
 time.sleep(.01)
import step13_guard
import click._winconsole,filelock,colorama.win32
step13_guard.install()
import browser_boundary
browser_boundary.install_playwright()
if sys.argv[1]=='minimal':
 from http.server import HTTPServer,BaseHTTPRequestHandler
 import threading
 class Handler(BaseHTTPRequestHandler):
  def log_message(self,*args):pass
  def do_GET(self):
   if self.path.startswith('http') or self.headers.get('Host')!='127.0.0.1:18765':raise RuntimeError('not synthetic origin')
   content=b'{"fake":true}' if self.path=='/fake' else b'<html><title>NewsFlow B Synthetic</title><h1>LOCAL FAKE ONLY</h1><script>fetch("/fake").then(r=>r.json()).then(x=>document.body.dataset.fake=x.fake)</script></html>'
   self.send_response(200);self.send_header('Content-Type','application/json' if self.path=='/fake' else 'text/html');self.end_headers();self.wfile.write(content)
 server=HTTPServer(('127.0.0.1',18765),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
 try:
  from playwright.sync_api import sync_playwright
  with sync_playwright() as pw:
   browser=pw.chromium.launch(headless=True);ctx=browser.new_context();page=ctx.new_page()
   assert page.goto('http://127.0.0.1:18765').status==200
   page.wait_for_function('document.body.dataset.fake === "true"');assert page.title()=='NewsFlow B Synthetic'
   page.screenshot(path=str(R/'artifacts/minimal-local.png'));ctx.close();browser.close()
  (R/'minimal-safe.json').write_text(json.dumps({'Chrome':'PASS','Playwright':'PASS','localhost18765':'PASS','fake_response':'PASS','operating_input_used':False}),encoding='utf-8')
 finally:server.shutdown();server.server_close();thread.join(5)
else:
 browser_boundary.install_local_fixture()
 import pytest
 targets=json.loads((R/'original91-IDs-safe.json').read_text())
 if sys.argv[1]=='gui':targets=[x for x in targets if 'test_pc_cloud_windows_browser.py::' in x]
 elif sys.argv[1]=='remaining':targets=[x for x in targets if 'test_pc_cloud_windows_browser.py::' not in x]
 elif sys.argv[1]=='full':targets=['tests']
 out=R/sys.argv[1];out.mkdir(exist_ok=False)
 os.environ['NEWSFLOW_VALIDATION_OUTPUT']=str(out/'evidence')
 options=['-q','-rs','-p','no:cacheprovider','-p','step13_guard','-p','step13_fixtures','-p','browser_boundary','-p','conftest','-c',str(pathlib.Path(step13_guard.CONFIG['project'])/'pyproject.toml'),'--rootdir',step13_guard.CONFIG['project'],'--basetemp',str(out/'temp'),'--junitxml',str(out/'pytest.xml'),*targets]
 raise SystemExit(pytest.main(options))
