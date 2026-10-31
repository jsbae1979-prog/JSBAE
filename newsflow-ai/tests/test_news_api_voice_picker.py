"""API voice metadata, public samples and local selection; all supplier calls Fake."""
import io,json,os,urllib.request
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from types import SimpleNamespace
import pytest
from conftest import csrf
from starlette.testclient import TestClient
from playwright.sync_api import expect
from sqlalchemy import select
from newsflow.db.models import AppSetting
from newsflow.distribution.local_access import LocalAccess,LaunchSession
from newsflow.video.elevenlabs_voices import ElevenLabsVoices
from newsflow.video.elevenlabs_tts import ElevenLabsKeys,settings
from newsflow.intelligence.credentials import FakeCipher
from newsflow.video.tts import TTSError
from bat_distribution.operation import OperatingRequests
from test_elevenlabs_voices import KEY,URL,MP3,payload,catalog,no_real_network
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_analysis_voice_features import context


def test_all_voice_metadata_omits_saved_filter_and_never_posts_synthesis(catalog,monkeypatch):
    calls=[]
    def fake_open(self,request,timeout):
        calls.append(request);return io.BytesIO(json.dumps(payload()).encode())
    monkeypatch.setattr(urllib.request.OpenerDirector,'open',fake_open)
    catalog.load(all_voices=True)
    assert len(calls)==1 and calls[0].get_method()=='GET' and calls[0].data is None
    assert parse_qs(urlsplit(calls[0].full_url).query)=={'page_size':['100']}
    assert KEY not in calls[0].full_url and catalog.cached()['voice_type']=='all'


def test_all_voice_pagination_is_manual_and_cannot_mix_saved_scope(catalog):
    calls=[];first=payload();first.update(has_more=True,next_page_token='page2')
    pages=[first,payload('Second','voiceB')]
    catalog.transport=lambda token:calls.append(token) or pages[len(calls)-1]
    catalog.load(all_voices=True);assert calls==[None]
    before=catalog.cached()
    with pytest.raises(TTSError):catalog.load(more=True)
    assert calls==[None] and catalog.cached()==before
    assert len(catalog.load(more=True,all_voices=True)['voices'])==2
    assert calls==[None,'page2']


@pytest.fixture
def all_voices(app,monkeypatch):
    keys=ElevenLabsKeys(app.state.config.data_dir,FakeCipher());keys.save(KEY)
    monkeypatch.setattr('newsflow.video.elevenlabs_tts.ElevenLabsKeys',lambda root:keys)
    entries=[payload()['voices'][0],payload('다른 목소리','voiceB',preview_url=URL.replace('voiceA','voiceB'))['voices'][0],
             payload('샘플 없는 목소리','voiceC',preview_url=None)['voices'][0]]
    cat=ElevenLabsVoices(app.state.config.data_dir,keys,transport=lambda token:{'voices':entries,'has_more':False,'next_page_token':None})
    cat.load(all_voices=True);downloads=[]
    cat.samples=SimpleNamespace(get=lambda url,timeout:downloads.append(url) or SimpleNamespace(status=200,body=MP3))
    monkeypatch.setattr('newsflow.gui.video_routes._voice_catalog',lambda request:cat)
    with app.state.sessions.begin() as db:
        db.add(AppSetting(key='tts_el_voice_id',value=json.dumps('voiceA')))
    return cat,downloads


@pytest.mark.parametrize('action',['load','select'])
@pytest.mark.parametrize('auth',['valid','csrf','origin','session'])
def test_operating_voice_metadata_and_selection_keep_auth_csrf(app,all_voices,action,auth):
    launch=LaunchSession(18779);client=TestClient(OperatingRequests(LocalAccess(app,launch)),base_url=launch.origin,
        client=('127.0.0.1',41234),follow_redirects=False)
    client.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]));client.get('/studio/shorts')
    before=settings(app.state.sessions);calls=[]
    all_voices[0].transport=lambda token:calls.append(token) or payload('Second','voiceB')
    fields={'consent':'true','scope':'all'} if action=='load' else {'voice_id':'voiceB'}
    fields['csrf_token']=client.cookies.get('newsflow_csrf');headers={'Origin':launch.origin,'Accept':'application/json'}
    if auth=='csrf':fields['csrf_token']='bad'
    if auth=='origin':headers['Origin']='https://outside.invalid'
    if auth=='session':client.cookies.clear()
    response=client.post('/video/tts/voices/'+action,data=fields,headers=headers)
    if auth=='valid':
        assert response.status_code==200
        if action=='load':assert response.json()=={'loaded':True} and calls==[None]
        else:
            assert response.json()=={'voiceId':'voiceB'} and not calls
            after=settings(app.state.sessions);assert after.pop('voice_id')=='voiceB'
            before.pop('voice_id');assert after==before
    else:
        assert response.status_code in {401,403} and not calls and settings(app.state.sessions)==before
    assert not all_voices[1]


def test_unlisted_voice_cannot_replace_current_selection(client,app,all_voices):
    before=settings(app.state.sessions)
    response=client.post('/video/tts/voices/select',data={'voice_id':'unlisted','csrf_token':csrf(client)},headers={'Accept':'application/json'})
    assert response.status_code==422 and settings(app.state.sessions)==before
    assert not all_voices[1]


def test_each_api_voice_can_be_previewed_and_selected_without_synthesis(app,browser,all_voices):
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda request:posts.append((urlsplit(request.url).path,parse_qs(request.post_data or ''))) if request.method=='POST' else None)
        p.goto(origin+'/studio/shorts');p.get_by_role('combobox',name='음성',exact=True).select_option('elevenlabs')
        box=p.get_by_role('region',name='ElevenLabs 목소리 선택',exact=True)
        picker=box.get_by_role('combobox',name='ElevenLabs 목소리',exact=True)
        expect(picker).to_have_value('voiceA');expect(picker.get_by_role('option')).to_have_count(4)
        picker.select_option('voiceB');box.get_by_role('button',name='목소리 미리듣기',exact=True).click()
        expect(box.get_by_label('선택한 목소리 샘플',exact=True)).to_have_attribute('src','/video/tts/voices/voiceB/sample')
        assert len(all_voices[1])==1 and '/voiceB/' in all_voices[1][0]
        assert settings(app.state.sessions)['voice_id']=='voiceA'
        box.get_by_role('button',name='이 목소리 사용',exact=True).click()
        expect(box.get_by_role('button',name='사용 중인 목소리',exact=True)).to_be_disabled()
        assert settings(app.state.sessions)['voice_id']=='voiceB'
        p.reload();expect(p.get_by_role('combobox',name='음성',exact=True)).to_have_value('elevenlabs')
        p.get_by_role('combobox',name='음성',exact=True).select_option('elevenlabs')
        expect(picker).to_have_value('voiceB')
        if os.environ.get('QUOTE_REVIEW_EVIDENCE'):
            folder=Path(os.environ['QUOTE_REVIEW_EVIDENCE']);folder.mkdir(parents=True,exist_ok=True)
            for w,h in [(1366,768),(1920,1080)]:
                p.set_viewport_size({'width':w,'height':h});assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
                box.screenshot(path=str(folder/f'api-voice-picker-{w}x{h}.png'))
        picker.select_option('voiceC');expect(box.get_by_role('button',name='목소리 미리듣기',exact=True)).to_be_disabled()
        expect(box).to_contain_text('공급사 미리듣기 샘플이 없습니다')
        assert [path for path,_ in posts]==['/video/tts/voices/preview','/video/tts/voices/select']
        assert posts[0][1]['voice_id']==['voiceB'] and len(all_voices[1])==1
        assert posts[1][1]['use_for_news']==['true']
        c.close()


def test_using_voice_changes_only_voice_id_and_news_preference(client,app,all_voices):
    with app.state.sessions() as db:before={row.key:row.value for row in db.scalars(select(AppSetting))}
    response=client.post('/video/tts/voices/select',data={'voice_id':'voiceB','use_for_news':'true','csrf_token':csrf(client)},headers={'Accept':'application/json'})
    assert response.status_code==200
    with app.state.sessions() as db:after={row.key:row.value for row in db.scalars(select(AppSetting))}
    assert after.pop('video_default_voice')=='elevenlabs'
    assert json.loads(after.pop('tts_el_voice_id'))=='voiceB'
    before.pop('video_default_voice',None);before.pop('tts_el_voice_id',None)
    assert after==before and not all_voices[1]


@pytest.mark.parametrize('path',['/video/tts/check','/video/tts','/video/tts/key'])
def test_voice_picker_authority_never_enables_paid_or_key_routes(app,all_voices,path):
    launch=LaunchSession(18779);client=TestClient(OperatingRequests(LocalAccess(app,launch)),base_url=launch.origin,
        client=('127.0.0.1',41234),follow_redirects=False)
    client.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]));client.get('/studio/shorts')
    before=settings(app.state.sessions)
    response=client.post(path,data={'csrf_token':client.cookies.get('newsflow_csrf')},headers={'Origin':launch.origin})
    assert response.status_code==403 and settings(app.state.sessions)==before and not all_voices[1]
