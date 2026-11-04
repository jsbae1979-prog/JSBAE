"""Real operating request/credential boundary, entirely synthetic providers/data."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace as NS

import pytest
from starlette.testclient import TestClient
from bat_distribution import precision_access as m
from bat_distribution.operation import OperatingRequests
from newsflow.character.schema import CharacterError
from newsflow.character.precision_contract import INSTRUCTION, PrecisionScenario
from newsflow.distribution.local_access import LocalAccess, LaunchSession
from newsflow.intelligence.api_providers import AnthropicProvider, OpenAISearchProvider
from newsflow.intelligence.api_settings import FakeAPIBudgetService
from newsflow.intelligence.credentials import AIKeyStore, AnthropicKeyStore, FakeCipher, CredentialError
from newsflow.intelligence.provider import Options
from newsflow.publishing.image_generation import ImageGenerationError
from test_api_settings import configured
from test_character_precision import precision, Images

KEYS={'claude_api':'synthetic-precision-claude-0123456789','openai':'synthetic-precision-openai-0123456789'}

@pytest.fixture
def connected(precision,monkeypatch):
 p=precision;root=p.s.root.parent;app=p.app
 app.state.config=replace(app.state.config,data_dir=root)
 app.state.character=p.owner;app.state.image_studio=p.images
 state=NS(calls=[],decryptions=[],buffers=[],timeout=False)
 for provider,kind in [('claude_api',AnthropicKeyStore),('openai',AIKeyStore)]:
  kind(root,FakeCipher()).save(KEYS[provider]);configured(app.state.sessions,provider)
 class Native(FakeCipher):
  def unprotect(self,payload,entropy):
   state.decryptions.append(bytes(entropy));value=super().unprotect(payload,entropy)
   state.buffers.append(value);return value
 class Adapter(Images):
  def generate(self,prompt,key,**kw):
   assert key==KEYS['openai']
   return super().generate(prompt,'synthetic-key',**kw)
 def post(adapter,body,options):
  provider='claude_api' if isinstance(adapter,AnthropicProvider) else 'openai'
  assert adapter.key_provider()==KEYS[provider]
  state.calls.append((provider,deepcopy(body)))
  if state.timeout:raise TimeoutError('synthetic only')
  adapter.last_usage={'prompt_tokens':30,'completion_tokens':90}
  text=json.dumps(p.story,ensure_ascii=False)
  if provider=='claude_api':return {'stop_reason':'end_turn','content':[{'type':'text','text':text}]}
  return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}
 monkeypatch.setattr(AnthropicProvider,'_post',post)
 monkeypatch.setattr(OpenAISearchProvider,'_post',post)
 monkeypatch.setattr(m,'FeedReadiness',lambda state:p.readiness)
 monkeypatch.setattr('newsflow.gui.character_precision_routes.FeedReadiness',lambda state:p.readiness)
 adapter=Adapter()
 owner=m.PrecisionAccess(app,root,Native,adapter=adapter,budget=FakeAPIBudgetService(app.state.sessions))
 service=owner.service();launch=LaunchSession(18779)
 authenticated=LocalAccess(app,launch)
 client=TestClient(owner.wrap(OperatingRequests(authenticated),authenticated),base_url=launch.origin,client=('127.0.0.1',43210))
 token=launch.claim(launch.launch_url().split('#')[1]);client.cookies.set(launch.cookie_name,token)
 assert client.get(m.BASE).json()['paid_available'] is True
 def request(action,**values):
  return client.post(m.BASE+'/'+p.w['id']+'/'+action,
    data={**values,'csrf_token':client.cookies.get('newsflow_csrf')},headers={'Origin':launch.origin})
 def quote(numbers=[1,2,3,4,5]):
  w=service.read(p.w['id'])
  if not w['scenario']:w=service.edit(w['id'],w['revision'],p.story)
  return service.quote(w['id'],w['revision'],numbers)
 yield NS(p=p,owner=owner,s=service,state=state,adapter=adapter,client=client,request=request,quote=quote,launch=launch)
 client.close()

@pytest.mark.parametrize('provider,model',[('claude_api','claude-sonnet-4-6'),('openai','gpt-4.1-mini')])
def test_story_uses_selected_model_profile_without_images_and_never_replays(connected,provider,model):
 c=connected
 from newsflow.character.kling import snapshot,check
 w=c.s.read(c.p.w['id']);settings=check(w['video_settings']);settings['script_model']=model
 w['video_settings']=snapshot(settings,precise=True);c.s.save(w)
 response=c.request('story',revision=1,consent='true');assert response.status_code==200
 result=response.json();assert result['state']=='images',result
 assert result['story_attempts'][0]['state']=='success'
 assert len(c.state.calls)==1 and c.state.calls[0][0]==provider
 body=c.state.calls[0][1];assert body.get('system',body.get('instructions'))==INSTRUCTION
 encoded=json.dumps(body);assert all(cid in encoded for cid in c.p.ids)
 assert 'image_url' not in encoded and 'base64' not in encoded
 assert c.request('story',revision=result['revision'],consent='true').status_code==422
 assert len(c.state.calls)==1 and not c.adapter.calls
 assert all(not any(buf) for buf in c.state.buffers)

def test_ep01_scoped_five_images_confirm_handoff_and_selected_regeneration(connected):
 c=connected;w=c.quote();before=[c.p.images.asset(x['asset']).read_bytes() for x in c.p.chars]
 response=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true')
 assert response.status_code==200;result=response.json()
 assert [s['state'] for s in result['scenes']]==['review']*5,result
 assert [len(x['refs']) for x in c.adapter.calls]==[1,2,2,1,2]
 assert len(c.state.decryptions)==5 and not c.state.calls
 assert c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').status_code==422
 assert len(c.adapter.calls)==5
 for s in result['scenes']:result=c.s.confirm(result['id'],result['revision'],s['plan']['no'],1,True)
 others=deepcopy(result['scenes'][1:]);first=deepcopy(result['scenes'][0]['versions'][0])
 w=c.s.quote(result['id'],result['revision'],[1],True)
 result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
 saved=c.s.read(result['id'])
 assert len(c.adapter.calls)==6 and saved['scenes'][1:]==others
 assert saved['scenes'][0]['versions'][0]==first
 result=c.s.confirm(result['id'],result['revision'],1,2,True)
 result=c.s.handoff(result['id'],result['revision']);job=c.p.owner.read(result['video_job_id'])
 assert len(job['precision']['images'])==5 and job['duration']==26 and not c.p.video.sent
 assert before==[c.p.images.asset(x['asset']).read_bytes() for x in c.p.chars]

@pytest.mark.parametrize('fault',['cookie','csrf','origin','consent','reference','duplicate'])
def test_auth_consent_before_decryption(connected,fault):
 c=connected;w=c.quote([1]);values={'quote_hash':w['quote']['hash'],'consent':'true','reference_consent':'true',
  'csrf_token':c.client.cookies.get('newsflow_csrf')};headers={'Origin':c.launch.origin}
 if fault=='cookie':c.client.cookies.clear()
 if fault=='csrf':values['csrf_token']='wrong'
 if fault=='origin':headers['Origin']='https://outside.invalid'
 if fault=='consent':values['consent']='false'
 if fault=='reference':values['reference_consent']='false'
 if fault=='duplicate':values['consent']=['true','false']
 assert c.client.post(m.BASE+'/'+w['id']+'/generate',data=values,headers=headers).status_code==403
 assert not c.adapter.calls and not c.state.decryptions

@pytest.mark.parametrize('fault',['limit','scope','readiness','expired','changed_reference'])
def test_changed_budget_scope_reference_and_readiness_do_not_send(connected,monkeypatch,fault):
 c=connected;w=c.quote([1])
 if fault=='limit':c.p.readiness.limit='0.00001'
 if fault=='scope':c.p.readiness.scope='another-account'
 if fault=='readiness':monkeypatch.setattr(type(c.p.readiness),'__call__',lambda self,selection:{'generationEnabled':False})
 if fault=='expired':w['quote']['expires']=1;c.s.save(w)
 if fault=='changed_reference':c.p.images.asset(c.p.chars[0]['asset']).write_bytes(b'synthetic-tamper')
 response=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true')
 assert response.status_code in (200,422)
 assert not c.adapter.calls and not c.state.decryptions

@pytest.mark.parametrize('fault',['prompt','refs','draft','selection','quote'])
def test_exact_journal_binding_before_key(connected,monkeypatch,fault):
 c=connected;w=c.quote([1]);original=c.owner.images.execute
 def alter(identifier,**kw):
  if fault=='quote':
   saved=c.s.read(w['id']);saved['events'][-1]['quote']['reserve_usd']='0.00001';c.s.save(saved)
  else:
   from newsflow.db.models import IntelligenceRun
   with c.p.app.state.sessions.begin() as session:
    row=session.get(IntelligenceRun,identifier)
    if fault=='prompt':row.result={'prompt':'not-approved'}
    if fault=='refs':row.options={**row.options,'references':[c.p.chars[1]['asset']]}
    if fault=='selection':
     from newsflow.creation.catalog import snapshot
     row.options={**row.options,'selection':snapshot('image',{**w['selection'],'quality':'high'})}
   if fault=='draft':identifier=c.owner.images.create('not-approved',w['selection'],references=[c.p.images.asset(c.p.chars[0]['asset']).read_bytes()])
  return original(identifier,**kw)
 monkeypatch.setattr(c.owner.images,'execute',alter)
 result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
 assert result['scenes'][0]['state']=='unknown'
 assert not c.adapter.calls and not c.state.decryptions

def test_unknown_image_stops_batch_and_preserves_request_without_retry(connected):
 c=connected;w=c.quote();c.adapter.failure=ImageGenerationError('timeout')
 result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
 assert result['scenes'][0]['state']=='unknown' and len(c.adapter.calls)==1
 assert all(not s['versions'] for s in result['scenes'][1:])
 c.s.reconcile(result['id'],result['revision'])
 assert len(c.adapter.calls)==1
 assert c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').status_code==422
 assert len(c.adapter.calls)==1

def test_direct_key_and_generation_calls_remain_blocked(connected):
 c=connected
 for store in c.owner.keys.values():
  with pytest.raises(CredentialError):store.key()
 with pytest.raises(CharacterError):c.owner.authoring.generate(INSTRUCTION,{},PrecisionScenario,
  Options(model='claude-sonnet-4-6'),provider='claude_api',request_id='episode:'+'a'*32+':script:1',consent=True)
 with pytest.raises(CharacterError):c.owner.generation._generate(None,None,None,'studio',{},'not-approved')
 assert not c.state.decryptions and not c.adapter.calls and not c.state.calls

def test_unknown_story_does_not_replay_and_unrelated_routes_stay_blocked(connected):
 c=connected;c.state.timeout=True
 result=c.request('story',revision=1,consent='true').json()
 assert result['state']=='story_failed' and result['story_attempts'][0]['state']=='unknown'
 assert c.request('story',revision=1,consent='true').status_code==422
 assert len(c.state.calls)==1
 assert c.client.post('/api/other/generate',data={'consent':'true'}).status_code==403
 assert c.client.get(m.BASE,headers={'X-NewsFlow-Precision-Paid':'true'}).status_code==200
 c.client.cookies.clear();assert c.client.get(m.BASE).status_code==403

def test_usage_above_reserved_estimate_stops_remaining_batch(connected,monkeypatch):
 c=connected;w=c.quote();original=c.adapter.generate
 def expensive(*args,**kw):
  raw,_=original(*args,**kw)
  return raw,{'input_tokens':500,'output_tokens':1000000,'total_tokens':1000500}
 monkeypatch.setattr(c.adapter,'generate',expensive)
 result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
 assert len(c.adapter.calls)==1 and result['scenes'][0]['versions'][0]['over_reserve'] is True
 assert result['scenes'][0]['state']=='review'  # Preserve the paid result.
 assert all(not s['versions'] for s in result['scenes'][1:])
 q=c.s.quote(result['id'],result['revision'],[2])
 assert c.request('generate',quote_hash=q['quote']['hash'],consent='true',reference_consent='true').status_code==422
 assert len(c.adapter.calls)==1

@pytest.mark.parametrize('bad_path',[False,True])
def test_confirmed_precision_images_through_operating_quote_scope(connected,monkeypatch,bad_path):
 c=connected;w=c.quote()
 result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
 for s in result['scenes']:result=c.s.confirm(result['id'],result['revision'],s['plan']['no'],1,True)
 result=c.s.handoff(result['id'],result['revision']);identifier=result['video_job_id']
 from bat_distribution import character_quote_only as q
 from newsflow.character.kling import KlingClient
 from newsflow.video.ai.keys import VideoAIKeyStore
 from newsflow.character.precision_video import reference_path
 root=c.s.root.parent;calls=[]
 (root/VideoAIKeyStore.FILE).write_bytes(b'synthetic-protected-video-key')
 class Native:
  def unprotect(self,payload,entropy):return bytearray(b'synthetic-precision-video-key-0123456789')
 class Video(KlingClient):
  def upload_reference(self,path):
   self.credential();calls.append(('upload',path.name))
   return 'https://example.com/'+path.name
  def estimate(self,payload):
   self.credential();calls.append(('estimate',deepcopy(payload)));return '0.10'
  def submit_scene(self,*args,**kw):pytest.fail('Quotes must not create videos')
 monkeypatch.setattr(q,'KlingClient',Video)
 scope=q.QuoteOnly(c.p.owner,root,Native)
 token=q._REQUEST.set((scope,identifier))
 try:
  if bad_path:
   # Intercept only the caller's path, leaving the gate's exact-path validation intact.
   original=q._Client.upload_reference
   def wrong(client,path):return original(client,path.parent/'reference.png')
   monkeypatch.setattr(q._Client,'upload_reference',wrong)
   with pytest.raises(CharacterError):scope.prepare(identifier,consent=True,script_reviewed=True)
   assert not calls
  else:
   scope.prepare(identifier,consent=True,script_reviewed=True)
   job=c.p.owner.read(identifier)
   assert job['state']=='quoted' and job['quote_total_usd']=='0.50'
   assert [x[1] for x in calls if x[0]=='upload']==[f'precision-scene-{n}.png' for n in range(1,6)]
   assert len([x for x in calls if x[0]=='estimate'])==5
   assert all('No dialogue, no voices, no music.' in s['prompt'] for s in job['scenes'])
   from test_character_quote_expiry_review import expired
   previous=expired(c.p.owner,identifier)
   scope.prepare(identifier,consent=True,script_reviewed=True)
   job=c.p.owner.read(identifier)
   assert job['quote_hash']!=previous['quote_hash']
   assert job['precision']==previous['precision']
   assert job['quote_history'][-1]['quote_hash']==previous['quote_hash']
   assert len([x for x in calls if x[0]=='estimate'])==10
   assert not any(x[0]=='submit' for x in calls)
   from bat_distribution import character_manual_execution as execution
   class Submitted(Video):
    def submit_scene(self,payload,idempotency_key):
     self.credential();calls.append(('submit',idempotency_key))
     return {'request_id':idempotency_key,'status_url':'https://api.higgsfield.ai/requests/'+idempotency_key+'/status'}
    def upload_reference(self,*a):pytest.fail('An approved submit must not upload again')
    def estimate(self,*a):pytest.fail('An approved submit must not quote again')
   monkeypatch.setattr(execution,'KlingClient',Submitted)
   manual=execution.ManualExecution(c.p.owner,root,Native)
   active=execution._REQUEST.set((manual,identifier,'submit'))
   try:manual.execute('submit',identifier,consent=True,quote_hash=job['quote_hash'])
   finally:execution._REQUEST.reset(active)
   assert len([x for x in calls if x[0]=='submit'])==5
   assert all(s['state']=='submitted' for s in c.p.owner.read(identifier)['scenes'])
 finally:q._REQUEST.reset(token)


from test_character_precision_browser import dist,browser,local_server,browser_context
from playwright.sync_api import expect

def test_connected_precision_screen_has_enabled_story_without_automatic_requests(connected,browser):
 c=connected
 boundary=c.owner.wrap(OperatingRequests(c.p.app),c.p.app)
 with local_server(boundary) as origin:
  context=browser_context(browser,origin);page=context.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(origin+'/studio/characters?precision='+c.p.w['id'])
  expect(page.get_by_role('button',name='스토리 만들기',exact=True)).to_be_enabled()
  expect(page.get_by_text('정밀 제작의 AI 연결 준비 중 · 작품 편집과 검토는 사용할 수 있습니다.',exact=True)).to_have_count(0)
  assert not c.state.calls and not c.adapter.calls and not errors
  context.close()

def test_local_reconciliation_restores_observed_cost_without_another_request(connected):
 c=connected;w=c.quote()
 result=c.request('generate',quote_hash=w['quote']['hash'],consent='true',reference_consent='true').json()
 version=result['scenes'][0]['versions'][0];expected=version.pop('observed_usd')
 version.pop('over_reserve');version['state']='unknown';result['scenes'][0]['state']='unknown'
 c.s.save(result);before=len(c.adapter.calls)
 restored=c.s.reconcile(result['id'],result['revision'])
 assert restored['scenes'][0]['versions'][0]['observed_usd']==expected
 assert restored['scenes'][0]['state']=='review' and len(c.adapter.calls)==before
