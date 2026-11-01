"""Focused synthetic regression for the 2026-11-01 whole-program findings."""
from datetime import UTC,datetime,timedelta
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from uuid import uuid4
import base64,json
import pytest
from PIL import Image
from sqlalchemy import select
from newsflow.db.models import APIRequestReservation,AIUsage,IntelligenceRun
from newsflow.studio.read_models import rows,SPECS,module_view
from newsflow.studio.usage_projection import combined_usage
from newsflow.publishing.image_generation import OpenAIImageAdapter,ImageGenerationError
from newsflow.publishing.image_reference import multipart_edit
from newsflow.publishing.posting_copy import PostingCopy,digest
from newsflow.publishing.service import PublishingError
from newsflow.creation.catalog import DEFAULTS
from conftest import csrf

def reservation(n,at,request_id=None,usage=None):
    return APIRequestReservation(id=f'{1000-n:032x}',request_id=request_id or f'character:{n}',
        provider='claude_api',kind='script',model='fixture-model',status='success',reserved_usd='1',
        bounds={},prices={},usage=usage if usage is not None else {'prompt_tokens':100,'completion_tokens':50},created_at=at)

def test_all_analytics_records_and_latest_order(app):
    start=datetime(2026,1,1,tzinfo=UTC)
    with app.state.sessions.begin() as s:
        s.add_all(reservation(n,start+timedelta(days=n)) for n in range(105))
    request=SimpleNamespace(app=app,state=SimpleNamespace(csrf_token='synthetic'))
    # Direct row projection and the actual API projection both must preserve old periods.
    with app.state.sessions() as s:
        columns=dict((key,cols) for key,_,cols in SPECS['analytics'])['requests']
        data=rows(s,'APIRequestReservation',columns,limit=None)
        assert len(data)==105 and data[0]['created_at'].startswith('2026-04-15')
        assert data[-1]['created_at'].startswith('2026-01-01')
        usage=combined_usage(s,[])
        assert len(usage)==105 and sum(x['total_tokens'] for x in usage)==15750
        assert len([x for x in usage if x['created_at'].startswith('2026-01')])==31

def test_exact_dedup_and_missing_usage_preserved(app):
    now=datetime.now(UTC)
    with app.state.sessions.begin() as s:
        run=IntelligenceRun(kind='analysis',provider='claude_api',status='success',options={},result={},evidence={},message='fixture')
        s.add(run);s.flush();identifier=run.id
        s.add(reservation(1,now,f'intelligence:{identifier}'))
        s.add(reservation(2,now,usage={}))
        s.add(reservation(3,now,usage={'prompt_tokens':True,'completion_tokens':2}))
        s.add(AIUsage(run_id=identifier,provider='claude_api',model='fixture-model',kind='analysis',status='success',prompt_tokens=100,completion_tokens=50,total_tokens=150))
        s.add(AIUsage(run_id=identifier,provider='claude_api',model='another-model',kind='analysis',status='success',prompt_tokens=3,completion_tokens=4,total_tokens=7))
    with app.state.sessions() as s:
        legacy=rows(s,'AIUsage','id provider model kind status prompt_tokens completion_tokens total_tokens created_at',limit=None)
        result=combined_usage(s,legacy)
        assert len(result)==2 and sum(x['total_tokens'] for x in result)==157
        assert len(list(s.scalars(select(APIRequestReservation))))==3
        assert len(list(s.scalars(select(AIUsage))))==2

def png():
    stream=BytesIO();Image.new('RGB',(128,128),'red').save(stream,'PNG');return stream.getvalue()

def test_reference_edits_wire_and_response_without_network():
    result=BytesIO();Image.new('RGB',(1024,1280)).save(result,'JPEG')
    encoded=json.dumps({'data':[{'b64_json':base64.b64encode(result.getvalue()).decode()}],
        'usage':{'input_tokens':10,'output_tokens':20,'total_tokens':30}}).encode()
    class Response(BytesIO):
        def __enter__(self):return self
        def __exit__(self,*args):self.close()
    class Opener:
        calls=[]
        def open(self,request,timeout):
            self.calls.append(request)
            assert request.full_url=='https://api.openai.com/v1/images/edits'
            assert request.get_header('Content-type').startswith('multipart/form-data; boundary=')
            assert b'name="image[]"; filename="reference.png"' in request.data
            assert png() in request.data and b'fixture prompt' in request.data
            assert b'private-path' not in request.data
            return Response(encoded)
    opener=Opener();raw,usage=OpenAIImageAdapter(opener).generate('fixture prompt','fixture-key',selection=DEFAULTS['image'],reference=png())
    assert raw==result.getvalue() and usage['total_tokens']==30 and len(opener.calls)==1

@pytest.mark.parametrize('reference',[b'',b'bad','https://example.com/private.png',b'x'*(20*1024*1024+1)],ids=['empty','invalid','url','oversize'])
def test_invalid_reference_never_sent(reference):
    with pytest.raises(ImageGenerationError) as error:multipart_edit({'prompt':'fixture'},reference)
    assert error.value.uncertain is False

def test_reference_draft_flow_no_replay(app):
    generation=app.state.image_generation
    generation.keys=SimpleNamespace(key=lambda:'fixture-key')
    class Adapter:
        calls=[]
        def generate(self,prompt,key,**options):
            self.calls.append(options);assert options['reference']==png()
            out=BytesIO();Image.new('RGB',(1024,1280)).save(out,'JPEG')
            return out.getvalue(),{'input_tokens':1,'output_tokens':2,'total_tokens':3}
    adapter=Adapter();generation.adapter=adapter
    studio=app.state.image_studio
    identifier=studio.create('Fixture drawing',DEFAULTS['image'],reference=png())
    with pytest.raises(PublishingError):studio.execute(identifier)
    first=studio.execute(identifier,consent=True,reviewed=True)
    assert studio.execute(identifier,consent=True,reviewed=True)==first
    assert len(adapter.calls)==1 and generation.get(first).status=='success'
    assert studio.get(identifier).options['reference']

@pytest.fixture
def preparation(app):
    source={'id':'character:'+'a'*32,'kind':'character','title':'Fixture','content':{'output_sha256':'1'*64}}
    svc=PostingCopy(app.state,source=lambda key:{**deepcopy(source),'id':key})
    app.state.posting_copy=svc
    return svc,source

COPY={'title':'Fixture','description':'Description','hashtags':['#fixture']}
PREP={'platforms':['youtube','instagram'],'content_reviewed':True,'rights_reviewed':True,'sources_reviewed':True}

def test_character_preparation_cas_invalidation_and_no_publish(preparation):
    svc,source=preparation;key=source['id'];h=digest(source)
    record=svc.save(key,h,0,COPY,preparation=PREP)
    assert record['preparation']['published'] is False
    assert record['preparation']['transmission_approved'] is False
    assert svc.view(key)['preparationCurrent']
    with pytest.raises(PublishingError):svc.save(key,h,0,COPY,preparation=PREP)
    source['content']['output_sha256']='2'*64
    assert not svc.view(key)['preparationCurrent']
    with pytest.raises(PublishingError):svc.save(key,h,1,COPY,preparation=PREP)
    updated=svc.save(key,digest(source),1,{**COPY,'title':'Changed'})
    assert 'preparation' not in updated and updated['approval'] is False

@pytest.mark.parametrize('patch',[{'platforms':[]},{'platforms':['youtube','youtube']},
    {'platforms':['email']},{'content_reviewed':False},{'rights_reviewed':'true'},{'sources_reviewed':1}])
def test_preparation_validation(preparation,patch):
    svc,source=preparation
    with pytest.raises(PublishingError):svc.save(source['id'],digest(source),0,COPY,preparation={**PREP,**patch})
    assert svc.view(source['id'])['revision']==0

def test_image_only_instagram(preparation):
    svc,source=preparation;source['kind']='image';source['id']='image:1'
    with pytest.raises(PublishingError):svc.save(source['id'],digest(source),0,COPY,preparation=PREP)
    row=svc.save(source['id'],digest(source),0,COPY,preparation={**PREP,'platforms':['instagram']})
    assert row['preparation']['platforms']==['instagram']

def test_preparation_route_csrf_and_local_boundary(preparation,client):
    svc,source=preparation
    data={'csrf_token':csrf(client),'project_id':source['id'],'source_hash':digest(source),
        'revision':'0','copy':json.dumps(COPY),'preparation':json.dumps(PREP)}
    path='/api/studio/publishing/copy/prepare'
    assert client.post(path,data={**data,'csrf_token':'wrong'}).status_code==403
    result=client.post(path,data=data)
    assert result.status_code==200,result.text
    assert result.json()['preparation']['status']=='prepared'
    assert result.json()['approval'] is False


def test_timing_review_explains_without_changing_story(tmp_path):
    from test_character_episode_automation import setup_episode,script
    from newsflow.character.episode_recovery import timing_review
    from newsflow.character.episode_policy import total_playback_seconds
    service,video,key,_,_=setup_episode(tmp_path)
    job=service.read(key);candidate=script();before=deepcopy(candidate)
    result=timing_review(job,candidate)
    assert result['targetSeconds']==job['duration']
    assert abs(result['playbackSeconds']-total_playback_seconds(candidate))<.001
    assert result['allowedClipSeconds'] and result['sceneRange']
    assert candidate==before and not video.sent and not service.authoring.calls

def test_timing_review_invalid_numbers_are_not_repaired(tmp_path):
    from test_character_episode_automation import setup_episode,script
    from newsflow.character.episode_recovery import timing_review
    service,video,key,_,_=setup_episode(tmp_path)
    candidate=script();candidate['scenes'][0]['seconds']='invalid'
    result=timing_review(service.read(key),candidate)
    assert result['playbackSeconds'] is None and not result['withinTimingRange']
    assert candidate['scenes'][0]['seconds']=='invalid' and not video.sent
