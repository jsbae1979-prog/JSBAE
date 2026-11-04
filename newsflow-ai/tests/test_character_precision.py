"""Synthetic EP01 fixtures only. No real character originals or provider traffic."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace as NS
from uuid import uuid4
import hashlib,json
import pytest
from PIL import Image
from newsflow.character.precision import PrecisionService
from newsflow.character.precision_contract import WorkSettings,PrecisionScenario,image_prompt,story_input
from newsflow.character.precision_video import reference_path
from newsflow.character.registry import CharacterRegistry
from newsflow.character.service import CharacterService
from newsflow.character.kling import DEFAULTS,O3,snapshot,check
from newsflow.character.schema import CharacterError
from newsflow.creation.catalog import DEFAULTS as IMAGE_DEFAULTS
from newsflow.creation.image_studio import ImageStudio
from newsflow.publishing.image_generation import ImageGenerationService,ImageGenerationError,OpenAIImageAdapter
from newsflow.publishing.image_reference import multipart_edit
from newsflow.video_models.catalog import CATALOG
from newsflow.video.engine import FFmpegAdapter
from test_character_episode_schema import image,profile
from test_character_episode_automation import FakeVideo

class Readiness:
    limit='10';scope='synthetic-account'
    def account_scope(self): return self.scope
    def standing_limit(self): return self.limit
    def __call__(self,selection): return {'generationEnabled':True}

class Images:
    def __init__(self): self.calls=[];self.failure=None
    def generate(self,prompt,key,*,selection=None,reference=None):
        assert key=='synthetic-key'
        self.calls.append({'prompt':prompt,'selection':deepcopy(selection),'refs':list(reference)})
        if self.failure: raise self.failure
        out=BytesIO();Image.new('RGB',tuple(map(int,selection['size'].split('x'))),
            (30*len(self.calls)%255,90,160)).save(out,'JPEG')
        return out.getvalue(),{'input_tokens':500,'output_tokens':800,'total_tokens':1300}

class Writer:
    response_received=True;last_reserved_usd='0.05';last_candidate=None
    def __init__(self,scenario):self.scenario=scenario;self.calls=[]
    def generate(self,instruction,payload,schema,options,**kw):
        assert kw['consent'] and 'image_bytes' not in kw
        self.calls.append(deepcopy(payload));return schema.model_validate(self.scenario)

def scenario(ids):
    descriptions=['사라진 쿠키 발견','친구를 의심','장난스러운 반격','뜻밖의 증거','반전 결말']
    return {'scenes':[{'no':i+1,'characters':[ids[0]] if i in (0,3) else ids,
        'description':descriptions[i],'location':'같은 주방 테이블','pose':'빈 접시 옆에 서 있음',
        'emotion':'호기심 어린 표정','camera':'눈높이 중간 구도','props':'접시는 테이블 왼쪽',
        'continuity':'같은 테이블, 같은 접시, 캐릭터의 위치 유지','caption':f'쿠키 사건 {i+1}',
        'seconds':seconds,'motion':'The character slowly points at the empty plate on the same table.',
        'motion_camera':'Static medium shot','sound':'Soft footsteps'} for i,seconds in enumerate([5,5,6,5,5])]}

@pytest.fixture
def precision(app,tmp_path,monkeypatch):
    def deny(*a,**kw):raise AssertionError('No external network in precision tests')
    monkeypatch.setattr('urllib.request.OpenerDirector.open',deny)
    adapter=Images();keys=NS(key=lambda:'synthetic-key')
    generation=ImageGenerationService(app.state.sessions,tmp_path,keys,adapter=adapter)
    images=ImageStudio(app.state.sessions,tmp_path,generation);registry=CharacterRegistry(tmp_path,images)
    chars=[registry.save(profile(n,s),images.asset_bytes(image(color))) for n,s,color in
           [('토토','rabbit','blue'),('루루','fox','orange')]]
    ids=[p['id'] for p in chars];story=scenario(ids)
    settings={**DEFAULTS,'video_model':O3,'native_resolution':'std','duration':30,'sound':'on'}
    ffmpeg=FFmpegAdapter.executable('ffmpeg',None);ffprobe=FFmpegAdapter.executable('ffprobe',None)
    video=FakeVideo(settings,tmp_path,ffmpeg)
    owner=CharacterService(tmp_path,app.state.sessions,keys,video=video,ffmpeg=ffmpeg,ffprobe=ffprobe)
    writer=Writer(story);readiness=Readiness()
    service=PrecisionService(tmp_path,registry,images,readiness,owner,writer,clock=lambda:1793750400)
    common=WorkSettings(title='EP01 사라진 쿠키 사건',topic='사라진 쿠키의 행방',relationships='장난을 즐기는 친구',
        style='Original soft 3D animation',world='집',background='주방',props='접시와 쿠키',scene_count=5,duration=26).model_dump()
    def create():return service.create(common,ids,{ids[0]:'Blue scarf',ids[1]:'Orange vest'},
        {**IMAGE_DEFAULTS['image'],'size':'864x1536'},settings,'5','5',uuid4().hex)
    w=create()
    return NS(s=service,w=w,create=create,story=story,ids=ids,chars=chars,adapter=adapter,writer=writer,
              owner=owner,video=video,images=images,readiness=readiness,app=app)

def scripted(p):
    return p.s.edit(p.w['id'],p.w['revision'],p.story)

def generated(p):
    w=scripted(p);w=p.s.quote(w['id'],w['revision'],[1,2,3,4,5])
    return p.s.generate(w['id'],w['quote']['hash'],True,True)

def confirmed(p):
    w=generated(p)
    for s in w['scenes']:
        w=p.s.confirm(w['id'],w['revision'],s['plan']['no'],1,True)
    return w

def test_ep01_five_requests_with_per_character_refs_and_no_caption(precision):
    p=precision;before=[hashlib.sha256(p.images.asset(c['asset']).read_bytes()).hexdigest() for c in p.chars]
    w=p.s.write_story(p.w['id'],1,True)
    assert len(p.writer.calls)==1 and len(p.writer.calls[0]['characters'])==2
    assert 'appearance' not in json.dumps(p.writer.calls[0])
    w=p.s.quote(w['id'],w['revision'],[1,2,3,4,5]);assert len(w['quote']['bounds'])==5
    assert w['quote']['provider_charge_cap'] is False
    w=p.s.generate(w['id'],w['quote']['hash'],True,True)
    assert [len(c['refs']) for c in p.adapter.calls]==[1,2,2,1,2]
    assert all(s['state']=='review' and s['confirmed'] is None for s in w['scenes'])
    for s,call in zip(w['scenes'],p.adapter.calls):
        assert s['plan']['caption'] not in call['prompt']
        assert 'No subtitles' in call['prompt']
        assert call['refs']==[p.images.asset(w['cast'][cid]['asset']).read_bytes() for cid in s['plan']['characters']]
        assert s['versions'][0]['sha256']==hashlib.sha256(p.images.asset(s['versions'][0]['asset']).read_bytes()).hexdigest()
    assert before==[hashlib.sha256(p.images.asset(c['asset']).read_bytes()).hexdigest() for c in p.chars]

def test_selected_regeneration_versions_rollback_and_other_approvals(precision):
    p=precision;w=confirmed(p);others=deepcopy(w['scenes'][1:]);first=w['scenes'][0]['versions'][0]
    with pytest.raises(ValueError):p.s.quote(w['id'],w['revision'],[1])
    w=p.s.quote(w['id'],w['revision'],[1],True)
    w=p.s.generate(w['id'],w['quote']['hash'],True,True)
    assert len(p.adapter.calls)==6 and w['scenes'][1:]==others
    assert w['scenes'][0]['versions'][0]==first and w['scenes'][0]['confirmed'] is None
    w=p.s.confirm(w['id'],w['revision'],1,1,True)
    assert w['scenes'][0]['selected']==1 and len(w['scenes'][0]['versions'])==2
    assert p.images.asset(first['asset']).exists()

@pytest.mark.parametrize('consent,refs',[(False,False),(True,False),(False,True)])
def test_no_approval_no_external_request(precision,consent,refs):
    p=precision;w=scripted(p);w=p.s.quote(w['id'],w['revision'],[1])
    with pytest.raises(ValueError):p.s.generate(w['id'],w['quote']['hash'],consent,refs)
    assert not p.adapter.calls

@pytest.mark.parametrize('failure',[ImageGenerationError('invalid_request',uncertain=False),ImageGenerationError('timeout')])
def test_failures_stop_batch_never_replay(precision,failure):
    p=precision;w=scripted(p);p.adapter.failure=failure
    w=p.s.quote(w['id'],w['revision'],[1,2,3,4,5]);q=w['quote']['hash']
    w=p.s.generate(w['id'],q,True,True)
    assert len(p.adapter.calls)==1 and not any(s['versions'] for s in w['scenes'][1:])
    with pytest.raises(ValueError):p.s.generate(w['id'],q,True,True)
    if failure.uncertain:
        with pytest.raises(ValueError):p.s.quote(w['id'],w['revision'],[1],True)
    assert len(p.adapter.calls)==1

def test_budget_scope_and_revision_reject_before_dispatch(precision):
    p=precision;w=scripted(p);w=p.s.quote(w['id'],w['revision'],[1])
    p.readiness.limit='0.00001'
    with pytest.raises(ValueError):p.s.generate(w['id'],w['quote']['hash'],True,True)
    p.readiness.limit='10';p.readiness.scope='changed'
    with pytest.raises(ValueError):p.s.generate(w['id'],w['quote']['hash'],True,True)
    assert not p.adapter.calls
    with pytest.raises(ValueError):p.s.edit(w['id'],1,p.story)

def test_invalid_cast_duration_no_silent_repair(precision):
    p=precision
    for mutate in (lambda s:s['scenes'][0].update(seconds=6),lambda s:s['scenes'][0].update(characters=['other'])):
        s=deepcopy(p.story);mutate(s)
        with pytest.raises(ValueError):p.s.edit(p.w['id'],1,s)
    assert p.s.read(p.w['id'])['state']=='needs_story' and not p.adapter.calls

def test_same_account_storage_isolation_and_original_registry_snapshot(precision,tmp_path):
    p=precision;w=scripted(p)
    other=PrecisionService(tmp_path/'other-user',p.s.registry,p.images,p.readiness,p.owner)
    with pytest.raises(OSError):other.read(w['id'])
    c=p.chars[0];updated=profile('別の名前','rabbit')
    p.s.registry.save(updated,c['asset'],c['id'],c['revision'])
    assert p.s.read(w['id'])['cast'][c['id']]['name_ko']=='토토'
    assert p.s.registry.get(c['id'])['name_ko']=='別の名前'

def test_edit_invalidates_only_changed_scene_and_preserves_history(precision):
    p=precision;w=confirmed(p);others=deepcopy(w['scenes'][1:]);old=deepcopy(w['scenes'][0]['versions'])
    plan=deepcopy(p.story);plan['scenes'][0]['emotion']='놀란 표정'
    w=p.s.edit(w['id'],w['revision'],plan)
    assert w['scenes'][1:]==others and w['scenes'][0]['versions']==old
    with pytest.raises(ValueError):p.s.confirm(w['id'],w['revision'],1,1,True)
    with pytest.raises(ValueError):p.s.handoff(w['id'],w['revision'])

def test_confirmed_images_existing_video_to_final_mp4(precision):
    p=precision
    from newsflow.character.editing import load_sfx_map
    p.story['scenes'][0]['sfx']=[{'at':'end','key':next(iter(load_sfx_map()))}]
    w=confirmed(p)
    w=p.s.handoff(w['id'],w['revision']);jid=w['video_job_id']
    assert p.s.handoff(w['id'],w['revision'])['video_job_id']==jid
    assert len(p.adapter.calls)==5 and not p.video.sent and not p.video.uploads
    job=p.owner.read(jid);assert job['duration']==26 and len(job['script']['scenes'])==5
    p.owner.prepare(jid,consent=True,script_reviewed=True)
    quoted=p.owner.read(jid)
    assert len(p.video.uploads)==5 and len(set(p.video.uploads))==5
    for i,s in enumerate(quoted['scenes'],1):
        assert s['payload']['image_urls'][0].endswith(f'precision-scene-{i}.png')
        assert 'No dialogue, no voices, no music.' in s['payload']['prompt']
        assert reference_path(p.owner,job,i).is_file()
    p.owner.submit(jid,consent=True,quote_hash=quoted['quote_hash'])
    p.owner.check(jid,consent=True)
    assert p.owner.read(jid)['state']=='clips_review'
    output=p.owner.render(jid,reviewed=True)
    final=p.owner.read(jid)
    assert output.is_file() and abs(final['output']['media']['duration']-26)<.12
    assert len(p.video.sent)==5 and len(p.adapter.calls)==5
    from newsflow.studio.read_models import character_rows
    shown=next(x for x in character_rows(NS(character=p.owner)) if x['id']==jid)
    assert shown['precisionWorkId']==w['id'] and shown['playback_seconds']==26
    old=deepcopy(final['scenes']);uploads=len(p.video.uploads)
    p.owner.prepare_regeneration(jid,2,consent=True)
    retry=p.owner.read(jid)
    assert retry['regeneration']['affected']==[2]
    assert retry['regeneration']['items'][0]['payload']['image_urls'][0].endswith('precision-scene-2.png')
    assert len(p.video.uploads)==uploads+1 and retry['scenes']==old
    assert len(p.video.sent)==5 and len(p.adapter.calls)==5

def test_multiple_reference_wire_and_capability():
    from newsflow.publishing.image_generation import MODEL
    from newsflow.publishing.image_reference import checked_references
    raw=image();body,ctype=multipart_edit({'model':MODEL,'prompt':'synthetic'},[raw,image('red')])
    assert body.count(b'name="image[]"')==2 and b'reference-1.png' in body and 'multipart' in ctype
    with pytest.raises(ImageGenerationError):checked_references([raw]*5,MODEL)
    with pytest.raises(ImageGenerationError):checked_references([raw],'unsupported-model')

def test_fast_duration_contract_stays_strict():
    with pytest.raises(CharacterError):snapshot({**DEFAULTS,'duration':26})
    assert check(snapshot({**DEFAULTS,'duration':26},precise=True))['duration']==26
    assert snapshot(DEFAULTS)['version']==2

def test_new_routes_require_csrf(client):
    response=client.post('/api/studio/character-precision/create',data={'payload':'{}','request_id':'a'*32})
    assert response.status_code==403


def test_interrupted_results_recovered_locally_without_provider_replay(precision):
    p=precision;w=generated(p)
    w['state']='generating';w['scenes'][0]['state']='generating'
    v=w['scenes'][0]['versions'][0];v['state']='requesting'
    for key in ('asset','sha256'):v.pop(key)
    p.s.save(w)
    recovered=p.s.reconcile(w['id'],w['revision'])
    assert recovered['scenes'][0]['state']=='review'
    assert recovered['scenes'][0]['versions'][0]['state']=='success'
    assert len(p.adapter.calls)==5

def test_interruption_without_saved_response_is_unknown_and_not_retried(precision):
    p=precision;w=scripted(p)
    w['state']='generating';w['scenes'][0]['versions']=[{'version':1,'state':'requesting','reserve_usd':'0.1'}]
    p.s.save(w);w=p.s.reconcile(w['id'],w['revision'])
    assert w['scenes'][0]['state']=='unknown'
    with pytest.raises(ValueError):p.s.quote(w['id'],w['revision'],[1],True)
    assert not p.adapter.calls


def test_wire_schema_keeps_local_patterns_out():
    from newsflow.intelligence.api_providers import _output_schema
    schema=_output_schema(PrecisionScenario)
    def walk(node):
        if isinstance(node,dict):
            assert not {'pattern','minLength','maxLength','minimum','maximum','maxItems'} & node.keys()
            assert node.get('minItems',0)<=1
            for value in node.values():walk(value)
        elif isinstance(node,list):
            for value in node:walk(value)
    walk(schema)


@pytest.mark.parametrize('provider,model',[('claude_api','claude-sonnet-4-6'),('openai','gpt-4.1-mini')])
def test_existing_authoring_transport_with_two_cast_profiles(precision,provider,model):
    from newsflow.character.authoring import AuthoringAI
    from newsflow.character.request_scope import validate_operation
    from test_character_authoring_v3 import Store,Adapter,Budget
    class ScopedBudget(Budget):
        def reserve_character(self,operation,**kwargs):
            assert validate_operation(operation,kwargs['kind'],kwargs['request_id'])['action']=='story'
            result=self.reserve(**kwargs);result.reserved_usd='0.05';return result
    p=precision;budget=ScopedBudget();adapter=Adapter(provider,p.story)
    p.s.authoring=AuthoringAI({provider:Store()},budget,{provider:adapter})
    w=p.s.read(p.w['id']);values=check(w['video_settings']);values['script_model']=model
    w['video_settings']=snapshot(values,precise=True);p.s.save(w)
    result=p.s.write_story(w['id'],w['revision'],True)
    assert result['state']=='images' and len(adapter.bodies)==1
    wire=json.dumps(adapter.bodies[0],ensure_ascii=False)
    assert '토토' in wire and '루루' in wire and 'base64' not in wire
    assert all(c['appearance'] not in wire for c in w['cast'].values()) and 'image_url' not in wire
    assert budget.finished[0][1]['status']=='success'
    with pytest.raises(ValueError):p.s.write_story(w['id'],result['revision'],True)
    assert len(adapter.bodies)==1


def test_precision_catalog_reuses_only_latest_choices_not_approval(precision,monkeypatch):
    from newsflow.gui.character_precision_routes import catalog
    p=precision;old=p.s.read(p.w['id']);new=p.create()
    # Explicit timestamps keep this test independent of the machine clock resolution.
    old['updated_at']='2026-01-01T00:00:00Z';new['updated_at']='2026-02-01T00:00:00Z'
    new['image_limit']='2.50';new['video_limit']='7'
    new['quote']={'consent':True,'account_scope':'fixture-only'}
    for w in (old,new):p.s.path(w['id']).write_text(json.dumps(w),encoding='utf8')
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:p.s)
    view=catalog(None)
    assert view['works'][0]['id']==new['id']
    reusable=view['recent_settings']
    assert set(reusable)=={'selection','video_settings','image_limit','video_limit'}
    assert reusable['image_limit']=='2.50' and reusable['video_limit']=='7'
    assert set(reusable['video_settings'])==set(DEFAULTS)
    created=p.s.create({**p.w['common'],'duration':20},p.ids,{cid:'Same reference outfit' for cid in p.ids},
        reusable['selection'],reusable['video_settings'],reusable['image_limit'],reusable['video_limit'],uuid4().hex)
    assert created['common']['duration']==20 and created['video_settings']['version']==3
    assert not created['story_attempts'] and not created.get('quote')
    assert p.s.read(old['id'])==old and p.s.read(new['id'])==new
    assert not p.adapter.calls and not p.writer.calls
