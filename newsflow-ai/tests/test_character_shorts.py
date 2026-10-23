"""Synthetic character storyboards and Fake supplier receipts. No account access."""
import io
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import select
from test_api_settings import configured
from test_api_settings import sessions as sessions  # noqa: PLC0414
from test_api_settings import store as store  # noqa: PLC0414

from newsflow.character.claude import CharacterWriter
from newsflow.character.higgsfield_client import MODEL, HiggsfieldVideoClient, reference_bytes
from newsflow.character.schema import CharacterError, Storyboard, load_character, prompts
from newsflow.character.service import CharacterService, now
from newsflow.db.models import APIRequestReservation
from newsflow.intelligence.api_settings import APISettingsError, FakeAPIBudgetService
from newsflow.intelligence.provider import Options
from newsflow.video.ai.contracts import ClipStatus, ProviderAmbiguousSubmit


def story():
    return {'plan':{'situation':'합성 직장인 예시','contrast':'모두 바쁠 때 혼자 여유','punchline':'귤 하나의 평온'},
            'title':'느긋한 월요일','hook_caption':'월요일 출근 1분 지각',
            'scenes':[
                {'seconds':10,'role':'setup','action':'Workers hurry through an office corridor.',
                 'caption':'모두 분주한 아침','sfx':''},
                {'seconds':10,'role':'contrast','action':'The capybara slowly settles into a chair.',
                 'caption':'혼자만 여유로운 대리','sfx':'한숨'},
                {'seconds':10,'role':'punchline','action':'The capybara calmly peels a tangerine.',
                 'caption':'일단 귤부터','sfx':''}], 'end_caption':'내일도 느긋하게 만나요'}


def png():
    buf=io.BytesIO()
    Image.new('RGB',(144,256),'brown').save(buf,format='PNG')
    return buf.getvalue()


class Writer:
    calls=0

    def __init__(self):
        self.last_usage={'prompt_tokens':100,'completion_tokens':300}

    def write(self,payload,options):
        self.calls+=1
        assert payload['duration']==30 and options.model=='claude-sonnet-4-6'
        result=story()
        result['plan']['situation']=payload['topic']
        result['title']=payload['topic'][:80]
        result['scenes'][0]['caption']=payload['topic'][:40]
        return Storyboard.model_validate(result)


class Video:
    credential=staticmethod(lambda:'synthetic-higgsfield-key')
    calls=0
    uploads=0
    states=None

    def upload_reference(self,path):
        self.uploads+=1
        reference_bytes(path)
        return 'https://example.com/character.png'

    payload=staticmethod(HiggsfieldVideoClient.payload)

    def estimate(self,payload):
        return '0.50'

    def submit_scene(self,payload,key):
        self.calls+=1
        return {'request_id':'synthetic-'+key,'status_url':'https://api.higgsfield.ai/requests/synthetic-'+key+'/status'}

    def check(self,handle):
        return ClipStatus(self.states or 'queued')


@pytest.fixture
def setup(tmp_path,sessions,store):
    configured(sessions)
    video,writer=Video(),Writer()
    s=CharacterService(tmp_path/'private',sessions,store,writer=writer,video=video,
                       budget=FakeAPIBudgetService(sessions))
    return SimpleNamespace(service=s,video=video,writer=writer,sessions=sessions,store=store)


def create(setup,**kwargs):
    return setup.service.create(kwargs.get('topic','합성 월요일 지각'),kwargs.get('episode','5'),kwargs.get('daily','20'),
                                reference=png())


def prepared(setup,**kwargs):
    identifier=create(setup,**kwargs)
    setup.service.write(identifier,consent=True)
    setup.service.prepare(identifier,consent=True,script_reviewed=True)
    return identifier


@pytest.mark.parametrize('change', ['sum','last','first','middle','count','seconds','extra','korean','length','bool'])
def test_story_rejects_wrong_shape(change):
    s=story()
    if change=='sum':s['scenes'][0]['seconds']=9
    elif change=='last':s['scenes'][-1]['role']='contrast'
    elif change=='first':s['scenes'][0]['role']='contrast'
    elif change=='middle':s['scenes'][1]['role']='punchline'
    elif change=='count':s['scenes']=s['scenes'][:2]
    elif change=='seconds':s['scenes'][0]['seconds']=3
    elif change=='extra':s['voice']='real'
    elif change=='korean':s['scenes'][0]['action']='한국어 동작'
    elif change=='length':s['hook_caption']='가'*31
    else:s['scenes'][0]['seconds']=True
    with pytest.raises(ValueError):Storyboard.model_validate(s)


def test_character_config_and_locked_prompts(tmp_path):
    c=load_character()
    assert c.made_for_kids is False and c.species=='capybara'
    for p in prompts(Storyboard.model_validate(story()),c):
        assert c.appearance in p['prompt'] and c.style_lock in p['prompt']
    bad=tmp_path/'bad.json';bad.write_text('{}')
    with pytest.raises(CharacterError):load_character(bad)


def test_real_claude_envelope_uses_existing_transport_without_news_schema(monkeypatch):
    writer=CharacterWriter(lambda:'synthetic-key-only')
    bodies=[]
    def opened(req,timeout,limit):
        bodies.append(json.loads(req.data))
        return json.dumps({'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(story())}],
                           'usage':{'input_tokens':100,'output_tokens':300}}).encode()
    monkeypatch.setattr(writer,'_open',opened)
    result=writer.write({'duration':30,'topic':'합성','character':load_character().model_dump()},
                         Options(model='claude-sonnet-4-6',timeout=300,max_tokens=3000))
    assert result.scenes[-1].role=='punchline' and len(bodies)==1
    assert bodies[0]['output_config']['format']['schema']['required']==list(story())
    assert 'tools' not in bodies[0] and writer.last_usage['completion_tokens']==300


def test_claude_invalid_json_stops_without_second_request(setup,monkeypatch):
    i=create(setup)
    def invalid(*args):
        setup.writer.calls+=1
        raise ValueError('SYNTHETIC SECRET MUST NOT LEAK')
    monkeypatch.setattr(setup.writer,'write',invalid)
    with pytest.raises(CharacterError,match='공급사') as e:setup.service.write(i,consent=True)
    assert 'SECRET' not in str(e.value)
    with pytest.raises(CharacterError):setup.service.write(i,consent=True)
    assert setup.writer.calls==1 and setup.video.calls==0
    with setup.sessions() as session:
        record=session.scalar(select(APIRequestReservation))
        assert record.status=='failed'  # A received response with usage is not a transport timeout.


def test_explicit_consents_and_original_reservations_preserved(setup):
    i=create(setup)
    with pytest.raises(CharacterError):setup.service.write(i)
    assert setup.writer.calls==0
    setup.service.write(i,consent=True)
    with setup.sessions() as session:
        original=session.scalar(select(APIRequestReservation))
        assert original.request_id=='character:'+i and original.status=='success'
    with pytest.raises(CharacterError):setup.service.prepare(i,consent=True)
    assert setup.video.uploads==0
    with pytest.raises(CharacterError):setup.service.write(i,consent=True)


def test_successful_plan_reuses_reference_and_freezes_model(setup):
    i=prepared(setup)
    j=prepared(setup)
    assert setup.video.uploads==1 and setup.writer.calls==2
    first=setup.service.read(i)
    assert first['model']==MODEL and first['quote_total_usd']=='1.50'
    assert first['reference_sha256']==setup.service.read(j)['reference_sha256']
    assert all('image_urls' in s['payload'] and s['payload']['generate_audio'] is False for s in first['scenes'])
    setup.service.submit(i,consent=True,quote_hash=first['quote_hash'])
    with pytest.raises(CharacterError):setup.service.submit(i,consent=True,quote_hash=first['quote_hash'])
    assert setup.video.calls==3


def test_budget_and_daily_limits_before_generation(setup):
    i=create(setup,episode='1')
    setup.service.write(i,consent=True)
    with pytest.raises(CharacterError):setup.service.prepare(i,consent=True,script_reviewed=True)
    assert setup.video.calls==0
    first=prepared(setup,episode='2',daily='2')
    quote=setup.service.read(first)['quote_hash']
    setup.service.submit(first,consent=True,quote_hash=quote)
    second=prepared(setup,episode='2',daily='2')
    with pytest.raises(CharacterError):
        setup.service.submit(second,consent=True,quote_hash=setup.service.read(second)['quote_hash'])
    assert setup.video.calls==3


def test_unknown_submit_preserved_and_never_replayed(setup,monkeypatch):
    i=prepared(setup)
    def ambiguous(*args):
        setup.video.calls+=1
        raise ProviderAmbiguousSubmit()
    monkeypatch.setattr(setup.video,'submit_scene',ambiguous)
    with pytest.raises(CharacterError):setup.service.submit(i,consent=True,quote_hash=setup.service.read(i)['quote_hash'])
    job=setup.service.read(i)
    assert job['state']=='submission_unknown' and job['scenes'][0]['state']=='unknown'
    assert len(job['scenes'][0]['idempotency_key'])==32
    for action in [lambda:setup.service.submit(i,consent=True,quote_hash=job['quote_hash']),
                   lambda:setup.service.check(i,consent=True)]:
        with pytest.raises(CharacterError):action()
    assert setup.video.calls==1


@pytest.mark.parametrize('state',['queued','in_progress','failed','nsfw','canceled'])
def test_statuses_never_generate_additional_scenes(setup,state):
    i=prepared(setup)
    setup.service.submit(i,consent=True,quote_hash=setup.service.read(i)['quote_hash'])
    setup.video.states=state
    if state in {'failed','nsfw','canceled'}:
        with pytest.raises(CharacterError):setup.service.check(i,consent=True)
        assert setup.service.read(i)['state']=='scene_review'
    else:
        setup.service.check(i,consent=True)
        assert setup.service.read(i)['state']=='generating'
    assert setup.video.calls==3


@pytest.mark.parametrize('change',['expired','key','quote','script'])
def test_changed_or_expired_plan_blocked_before_submit(setup,change,monkeypatch):
    i=prepared(setup);job=setup.service.read(i);quote=job['quote_hash']
    if change=='expired':job['quoted_at']=(now()-timedelta(minutes=20)).isoformat()
    elif change=='key':monkeypatch.setattr(setup.video,'credential',lambda:'another-synthetic-key')
    elif change=='quote':job['scenes'][0]['quote_usd']='0.01'
    else:job['script']['scenes'][0]['caption']='수정'
    setup.service.save(job)
    with pytest.raises(CharacterError):setup.service.submit(i,consent=True,quote_hash=quote)
    assert setup.video.calls==0


def test_api_existing_unknown_not_bypassed(setup):
    budget=setup.service.budget
    old=budget.reserve(provider='claude_api',request_id='old-unknown',kind='analysis',
                       model='claude-sonnet-4-6',max_output_tokens=2000,key_store=setup.store)
    budget.finish(old.id,status='unknown')
    i=create(setup)
    with pytest.raises(APISettingsError):setup.service.write(i,consent=True)
    assert setup.writer.calls==0
    with setup.sessions() as session:
        original=session.get(APIRequestReservation,old.id)
        assert original.status=='unknown'


def test_upload_headers_and_exact_reference_schema(tmp_path):
    path=tmp_path/'ref.png';path.write_bytes(png())
    calls=[]
    def requester(host,method,path,body,headers,timeout):
        calls.append((host,method,path,body,headers))
        if method=='PUT':return 200,b''
        if path=='/files/generate-upload-url':
            return 200,json.dumps({'upload_url':'https://storage.example.com/u?sign=synthetic',
              'public_url':'https://example.com/ref.png','upload_headers':{'Content-Type':'image/png',
              'x-amz-tagging':'retention=temporary'}}).encode()
        if path.startswith('/estimate/'):
            return 200,b'{"usd":"0.50"}'
        return 200,json.dumps({'status':'queued','request_id':'synthetic123',
             'status_url':'https://api.higgsfield.ai/requests/synthetic123/status'}).encode()
    video=HiggsfieldVideoClient(lambda:'synthetic-id:synthetic-secret',requester=requester)
    url=video.upload_reference(path)
    assert 'Authorization' not in calls[1][4] and calls[1][4]['x-amz-tagging']=='retention=temporary'
    p=video.payload('A calm capybara.',10,url)
    assert set(p)=={'prompt','duration','image_urls','aspect_ratio','resolution','generate_audio'}
    assert video.estimate(p)=='0.50'
    handle=video.submit_scene(p,'f'*32)
    assert handle['request_id']=='synthetic123'
    assert calls[-1][4]['Idempotency-Key']=='f'*32


@pytest.mark.parametrize('state',['queued','in_progress','completed','failed','nsfw','canceled'])
def test_official_six_statuses_and_video_url(state):
    calls=[]
    def requester(*args):
        calls.append(args)
        return 200,json.dumps({'status':state,'video':{'url':'https://example.com/safe.mp4'}}).encode()
    v=HiggsfieldVideoClient(lambda:'synthetic-key',requester=requester)
    result=v.check({'request_id':'synthetic123','status_url':'https://api.higgsfield.ai/requests/synthetic123/status'})
    assert result.state==state and len(calls)==1 and calls[0][1]=='GET'
    assert bool(result.video_url)==(state=='completed')


@pytest.mark.parametrize('url',['http://example.com/s','https://127.0.0.1/s','https://api.higgsfield.ai.evil.test/s'])
def test_status_url_cannot_redirect_credentials(url):
    calls=[]
    def requester(*a):
        calls.append(a)
        return 200,json.dumps({'status':'queued','request_id':'synthetic123','status_url':url}).encode()
    v=HiggsfieldVideoClient(lambda:'synthetic-key',requester=requester)
    with pytest.raises(ProviderAmbiguousSubmit):v.submit_scene(v.payload('Calm.',10,'https://example.com/r.png'),'f'*32)
    assert len(calls)==1


def test_fake_gui_stages_csrf_and_no_new_startup_dispatch(client,app,setup):
    from conftest import csrf
    app.state.character=setup.service
    token=csrf(client)
    assert '캐릭터 쇼츠' in client.get('/video').text
    assert client.get('/character').status_code==200
    assert setup.video.calls==setup.writer.calls==0
    data={'topic':'합성 코미디','episode_limit':'5','day_limit':'20'}
    files={'reference':('reference.png',png(),'image/png')}
    assert client.post('/character',data=data,files=files).status_code==403
    response=client.post('/character',data={**data,'csrf_token':token},files=files)
    assert response.status_code==200
    i=setup.service.listing()[0]['id']
    response=client.post('/character/'+i+'/write',data={'csrf_token':token,'consent':'true'})
    assert response.status_code==200 and '대본' in response.text
    assert setup.writer.calls==1 and setup.video.calls==0
    assert client.get('/character/'+i+'/file').status_code==404
    assert client.get('/character/'+i+'/clips').status_code==200


def test_reference_validation_path_and_text_injection(setup,tmp_path):
    for identifier in ['../outside','0'*31,'../'+'0'*32]:
        with pytest.raises(CharacterError):setup.service.read(identifier)
    with pytest.raises(CharacterError):setup.service.create('HF_KEY=synthetic-secret','5','20')
    bad=tmp_path/'not-image.png';bad.write_text('synthetic')
    with pytest.raises(CharacterError):reference_bytes(bad)


def test_character_upload_preserves_other_forms_limits_and_origin(client,app,setup):
    from conftest import csrf
    app.state.character=setup.service
    token=csrf(client)
    data={'topic':'합성','episode_limit':'5','day_limit':'20','csrf_token':token}
    f={'reference':('ref.png',png(),'image/png')}
    assert client.post('/character',data=data,files=f,headers={'Origin':'https://evil.example'}).status_code==403
    assert client.post('/sources',data=data,files=f).status_code==415
    two=[('reference',('one.png',png(),'image/png')),('second',('two.png',png(),'image/png'))]
    assert client.post('/character',data=data,files=two).status_code==400
    assert client.post('/character',data={**data,'pad':'x'*(11*1024*1024)},files=f).status_code==413
    assert setup.service.listing()==[] and setup.writer.calls==setup.video.calls==0
