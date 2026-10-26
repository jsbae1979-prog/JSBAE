"""Local synthetic UI harness only. Never imports or starts the product engine."""
from pathlib import Path
import sys,json,os,re,urllib.parse,hashlib
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
R=Path(os.environ["NEWSFLOW_VISUAL_ROOT"]).resolve()
P=R/'repo/newsflow-ai';D=P/'frontend/dist';F=P/'tools/studio_v3/fixtures'
models={p.stem:json.loads(p.read_text(encoding='utf-8')) for p in F.glob('*.json')}
media=R/'preview-media/synthetic.mp4'
if media.is_file():
 models['workspace']['projects'][0]['mediaUrl']='/video/jobs/1/file'
 for name in models:
  if 'projects' in models[name]:models[name]['projects'][0]['mediaUrl']='/video/jobs/1/file'
records=R/'synthetic-form-events.jsonl'
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(D),**kwargs)
 def end_headers(self):
  self.send_header('Content-Security-Policy',"default-src 'self';script-src 'self';style-src 'self';img-src 'self';frame-ancestors 'none';base-uri 'none';form-action 'self'")
  self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');super().end_headers()
 def result(self,body,status=200):
  raw=json.dumps(body,ensure_ascii=False).encode();self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_GET(self):
  if self.headers.get('Host')!='127.0.0.1:18765' or self.path.startswith('http'):self.send_error(403);return
  path=urllib.parse.urlsplit(self.path).path
  if path=='/api/studio/workspace':return self.result(models['workspace'])
  if path.startswith('/api/studio/modules/'):
   name=path.rsplit('/',1)[-1]
   if name in models:return self.result(models[name])
   return self.result({'detail':'Unknown synthetic module'},404)
  if path=='/video/jobs/1/file':
   raw=media.read_bytes();total=len(raw);match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers.get('Range',''))
   start=int(match[1]) if match else 0;end=min(int(match[2]) if match and match[2] else total-1,total-1)
   if start>=total:self.send_error(416);return
   self.send_response(206 if match else 200);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes')
   if match:self.send_header('Content-Range',f'bytes {start}-{end}/{total}')
   self.send_header('Content-Length',str(end-start+1));self.end_headers();self.wfile.write(raw[start:end+1]);return
  if re.fullmatch(r'/studio/(?:dashboard|create|news|shorts|characters|images|automation|library|publishing|analytics|settings|onboarding)(?:/[a-zA-Z0-9_-]+)*',path):self.path='/index.html'
  elif re.fullmatch(r'/studio/assets/[a-zA-Z0-9._-]+',path):self.path=path[7:]
  else:self.send_error(404,'Synthetic harness has no engine/legacy pages');return
  super().do_GET()
 def do_POST(self):
  if self.headers.get('Host')!='127.0.0.1:18765' or self.headers.get('Origin')!='http://127.0.0.1:18765':return self.result({'detail':'Invalid origin'},403)
  if self.headers.get('Content-Type','').split(';')[0]!='application/x-www-form-urlencoded':return self.result({'detail':'Synthetic harness accepts reviewed local form tests only'},415)
  size=int(self.headers.get('Content-Length','0'))
  if not 0<size<=65536:return self.result({'detail':'Invalid size'},413)
  data=urllib.parse.parse_qs(self.rfile.read(size).decode('utf-8'),keep_blank_values=True)
  if data.get('csrf_token')!=['studio-synthetic-local-only']:return self.result({'detail':'CSRF rejected'},403)
  # These are UI simulation contracts, not a replacement for product validation.
  if self.path=='/ai/drafts/1':
   draft=models['shorts']['collections']['drafts'][0]
   if data.get('revision')!=[str(draft['revision'])]:return self.result({'detail':'다른 화면에서 변경됐습니다. 입력을 유지하고 새로고침하세요.'},409)
   try:content=json.loads(data['content'][0]);assert len(content['scenes'])==3 and content['title']
   except (KeyError,ValueError,AssertionError):return self.result({'detail':'Invalid synthetic script'},422)
   draft['content']=content;draft['revision']+=1;draft['review_status']='review_required'
  elif self.path=='/schedules':
   if not data.get('name'):return self.result({'detail':'이름이 필요합니다.'},422)
   models['automation']['collections']['schedules'].append({'id':99,'name':data['name'][0],'kind':data.get('kind',['daily'])[0],'local_time':data.get('local_time',['09:00'])[0],'status':'paused','revision':1})
  elif self.path=='/publishing/unified/local-draft':
   models['publishing']['collections']['drafts'].append({'id':99,'title':data.get('title',['합성 새 초안'])[0],'state':'draft','platform':data.get('target',['youtube'])[0],'revision':1})
  else:return self.result({'detail':'실제 엔진 실행은 연결하지 않았습니다. 합성 UI에서는 외부 호출·생성을 차단합니다.'},403)
  with records.open('a',encoding='utf-8') as f:f.write(json.dumps({'path':self.path,'keys':sorted(data),'synthetic':True,'external_calls':0})+'\n')
  return self.result({'saved':True,'synthetic':True})
 def do_CONNECT(self):self.send_error(403)
sys.path.insert(0,str(R))
import step13_guard
step13_guard.install()
server=ThreadingHTTPServer(('127.0.0.1',18765),Handler)
(R/'visual-server-safe.json').write_text(json.dumps({'pid':os.getpid(),'port':18765,'kind':'Synthetic React UI harness','product_engine_started':False,'Guard':True,'external_calls':0},indent=2))
try:server.serve_forever()
finally:server.server_close()
