"""Public fixture-only browser preview. Never imports or starts the product app."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json,mimetypes,threading,sys
from urllib.parse import urlsplit
from copy import deepcopy
import argparse
parser=argparse.ArgumentParser(description='Fixture-only model UI preview; no product app, providers or user DB.')
parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parents[2])
parser.add_argument('--before-dist',type=Path)
args=parser.parse_args()
PROJECT=args.project.resolve()
BEFORE=(args.before_dist or PROJECT/'frontend/dist').resolve()
sys.path.insert(0,str(PROJECT/'src'))
from newsflow.character.kling import catalog,snapshot,DEFAULTS
FIXTURES={p.stem:json.loads(p.read_text(encoding='utf8')) for p in (PROJECT/'tools/studio_v3/fixtures').glob('*.json')}
for row in FIXTURES['automation']['collections']['schedules']:
    if row.get('weekdays')=='':row['weekdays']=[]
# Clearly marked synthetic reference; no paid image, production data or original sample changes.
SVG=b'''<svg xmlns="http://www.w3.org/2000/svg" width="360" height="520" viewBox="0 0 360 520"><defs><linearGradient id="b" x2="1" y2="1"><stop stop-color="#21144c"/><stop offset="1" stop-color="#06364a"/></linearGradient></defs><rect width="360" height="520" fill="url(#b)"/><circle cx="180" cy="190" r="100" fill="#e5e3f5"/><path d="M96 130L95 52L151 108M210 106L267 54L265 137" fill="#c9c0ea" stroke="#eeeaff" stroke-width="12"/><ellipse cx="144" cy="184" rx="14" ry="21" fill="#14243e"/><ellipse cx="216" cy="184" rx="14" ry="21" fill="#14243e"/><path d="M165 220Q180 238 195 220" fill="none" stroke="#b45190" stroke-width="8"/><rect x="100" y="290" width="160" height="144" rx="45" fill="#3876d9"/><path d="M180 300V430" stroke="#70bff6" stroke-width="7"/><text x="180" y="480" fill="#b9dcff" font-size="18" text-anchor="middle">SYNTHETIC REFERENCE</text></svg>'''
chars=FIXTURES['characters']
chars['catalog']['characterStudio']=catalog()
identifier='a'*32
story={'title':'합성 검증 · 새로운 여행','scenes':[{'seconds':11,'role':'setup' if i==0 else 'punchline' if i==4 else 'build','caption':['새로운 세상','신비한 숲','작은 도전','따뜻한 우정','행복한 마무리'][i],'action':'The reference character explores an original forest.','narration':''} for i in range(5)]}
job={'id':identifier,'topic':'합성 검증 · 새로운 여행','state':'script_review','story':story,'studio_selection':snapshot(DEFAULTS),'referenceUrl':f'/api/studio/characters/{identifier}/reference','duration':55,'episode_limit':'10','day_limit':'20','quote':None,'scenes':[]}
chars['collections']['jobs']=[job]
chars['csrfToken']='synthetic-preview-only';chars['dataOrigin']='synthetic'
TRANSPORT='''"use strict";
const fixtures=DATA;
const templateJob=JSON.parse(JSON.stringify(fixtures.characters.collections.jobs[0]));
if(new URLSearchParams(location.search).has('catalog-test')){
 const caps=fixtures.characters.catalog.characterStudio,original=caps.modelsDetailed[0];
 const full={...original,id:'synthetic/full',label:'합성 Full',recommended:true,
   resolutions:['720p','1080p'],default_resolution:'1080p',duration_values:[4,5,6,7,8,9,10,11,12,13,14,15],
   pricing:{...original.pricing,per_second:{off:['0.10','0.10'],on:['0.20','0.20']},note:'합성 단가 · 실제 과금 없음'}};
 const mini={...full,id:'synthetic/mini',label:'합성 Mini',recommended:false,resolutions:['720p'],default_resolution:'720p',audio:{native:false,voice_select:false},pricing:{...full.pricing,per_second:{off:['0.05','0.05'],on:null}}};
 const fixed={...full,id:'synthetic/fixed',label:'합성 Fixed',recommended:false,resolutions:['720p'],default_resolution:'720p',duration_values:[4,6,8]};
 caps.modelsDetailed=[full,mini,fixed];caps.models=Object.fromEntries(caps.modelsDetailed.map(m=>[m.id,m.label]));
 caps.revision='synthetic-capability-test';caps.defaults={...caps.defaults,video_model:full.id,native_resolution:'1080p',clip_seconds:10,duration:50};
 fixtures.characters.collections.jobs=[];
}
window.fetch=async(input,options={})=>{
 const u=new URL(typeof input==='string'?input:input.url,location.origin);
 if(u.origin!==location.origin)return new Response('{}',{status:403});
 if((options.method||'GET')!=='GET'){
   const reply=(v,status=200)=>new Response(JSON.stringify(v),{status,headers:{'Content-Type':'application/json'}});
   const list=fixtures.characters.collections.jobs;
   if(u.pathname==='/character'){
     const form=options.body;
     const next={...templateJob,id:'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',topic:String(form.get('topic')),
       state:'needs_script',story:null,studio_selection:JSON.parse(form.get('studio_settings')),
       referenceUrl:'/api/studio/characters/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/reference',scenes:[]};
     list.unshift(next);return reply({id:next.id,created:true,state:next.state});
   }
   if(u.pathname==='/api/studio/characters/auto-story'){
     const row=list.find(x=>x.id===options.body.get('job_id'));
     row.story=JSON.parse(JSON.stringify(templateJob.story));row.story.title='합성 자동 스토리 · '+row.topic;
     row.story.scenes=row.story.scenes.slice(0,Math.min(5,Math.floor(60/row.studio_selection.clip_seconds))).map(s=>({...s,seconds:row.studio_selection.clip_seconds}));
     row.state='script_review';return reply({id:row.id,state:row.state});
   }
   if(u.pathname.endsWith('/settings')&&u.pathname.startsWith('/api/studio/characters/')){
     const row=list.find(x=>x.id===u.pathname.split('/')[4]);row.studio_selection=JSON.parse(options.body.get('settings'));
     return reply({id:row.id,saved:true});
   }
   return reply({error:'합성 화면 검증 · 외부 생성 요청 없음'},409);
 }
 let v;
 if(u.pathname==='/api/studio/workspace')v=fixtures.workspace;
 else if(u.pathname.startsWith('/api/studio/modules/'))v=fixtures[u.pathname.split('/').pop()];
 else if(u.pathname==='/api/samples')v={schemaVersion:1,assets:[]};
 else if(u.pathname==='/api/studio/production-context')v={schemaVersion:1,top3:[],selection:null};
 else if(u.pathname==='/api/feed-batches')v={schemaVersion:1,batches:[],defaults:{}};
 else if(u.pathname==='/api/studio/local-voices')v={schemaVersion:1,voices:[]};
 return new Response(JSON.stringify(v||{}),{status:v?200:404,headers:{'Content-Type':'application/json'}});
};
'''.replace('DATA',json.dumps(FIXTURES,ensure_ascii=False))
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):self.send_error(405)
 def do_GET(self):
  if self.headers.get('Host')!=f'127.0.0.1:{self.server.server_port}':self.send_error(403);return
  p=urlsplit(self.path).path
  root=BEFORE if self.server.server_port==18769 else PROJECT/'frontend/dist'
  if p=='/fixture-transport.js':data=TRANSPORT.encode();kind='text/javascript'
  elif p in [f'/api/studio/characters/{identifier}/reference','/api/studio/characters/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/reference']:data=SVG;kind='image/svg+xml'
  elif p.startswith('/studio/assets/'):
   name=p.removeprefix('/studio/assets/')
   if '/' in name or '\\' in name or name in ('','..'):self.send_error(404);return
   target=root/'assets'/name
   if not target.is_file():self.send_error(404);return
   data=target.read_bytes();kind=mimetypes.guess_type(name)[0] or 'application/octet-stream'
  elif p.startswith('/studio/'):
   data=(root/'index.html').read_text(encoding='utf8').replace('<head>','<head><script src="/fixture-transport.js"></script>').encode();kind='text/html; charset=utf-8'
  else:self.send_error(404);return
  self.send_response(200);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
  self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
  self.end_headers();self.wfile.write(data)
servers=[ThreadingHTTPServer(('127.0.0.1',p),Handler) for p in (18769,18770)]
threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
for t in threads:t.start()
print('FIXTURE_ONLY_BEFORE_18769_AFTER_18770_READY',flush=True)
try:threading.Event().wait()
except KeyboardInterrupt:pass
finally:
 for s in servers:s.shutdown();s.server_close()
 for t in threads:t.join()
 print('FIXTURE_PORTS_CLOSED',flush=True)
