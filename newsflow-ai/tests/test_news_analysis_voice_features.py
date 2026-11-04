import hashlib,json,wave,os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs
import pytest
from playwright.sync_api import expect
from starlette.testclient import TestClient
from sqlalchemy import select
from conftest import csrf
from newsflow.db.models import AppSetting
from newsflow.distribution.local_access import LocalAccess,LaunchSession
from bat_distribution.operation import OperatingRequests
from newsflow.news.curator import Curator
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_voices_gui import korean
from test_elevenlabs_voices import catalog,payload,MP3
from test_google_news_trends import prepared,no_external_calls
from test_workspace_cleanup import articles

def context(browser,origin):
    c=browser.new_context(viewport={'width':1366,'height':768})
    c.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
    return c

def test_windows_preview_json_uses_only_fixed_installed_voice(client,korean):
    response=client.post('/voices/preview',data={'voice':'Fake Korean Voice','csrf_token':csrf(client),
        'text':'This arbitrary input must be ignored'},headers={'Accept':'application/json'})
    assert response.status_code==200
    assert response.json()['mediaUrl'].startswith('/voices/preview/preview-')
    assert len(korean.calls)==1 and korean.calls[0][0]=='Fake Korean Voice'

def test_official_sample_json_never_calls_paid_tts(client,catalog,monkeypatch):
    catalog.transport=lambda token:payload();catalog.load();calls=[]
    catalog.samples=SimpleNamespace(get=lambda url,timeout:(calls.append(url) or SimpleNamespace(status=200,body=MP3)))
    monkeypatch.setattr('newsflow.gui.video_routes._voice_catalog',lambda request:catalog)
    response=client.post('/video/tts/voices/preview',data={'voice_id':'voiceA','sample_consent':'true','csrf_token':csrf(client)},
        headers={'Accept':'application/json'})
    assert response.status_code==200 and response.json()['mediaUrl']=='/video/tts/voices/voiceA/sample'
    assert len(calls)==1 and calls[0].startswith('https://storage.googleapis.com/eleven-public-prod/')

@pytest.mark.parametrize('bad',['valid','csrf','origin','session'])
def test_operating_free_preview_keeps_authentication_and_csrf(app,korean,bad):
    launch=LaunchSession(18779);auth=LocalAccess(app,launch)
    client=TestClient(OperatingRequests(auth),base_url=launch.origin,client=('127.0.0.1',43210),follow_redirects=False)
    client.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]));client.get('/studio/shorts')
    data={'voice':'Fake Korean Voice','csrf_token':client.cookies.get('newsflow_csrf')}
    headers={'Origin':launch.origin,'Accept':'application/json'}
    if bad=='csrf':data['csrf_token']='bad'
    if bad=='origin':headers['Origin']='https://outside.invalid'
    if bad=='session':client.cookies.clear()
    response=client.post('/voices/preview',data=data,headers=headers)
    if bad=='valid':
        assert response.status_code==200 and response.json()['mediaUrl'].startswith('/voices/preview/preview-')
        assert len(korean.calls)==1
    else:
        assert response.status_code in {401,403}
        assert not korean.calls

def test_one_analysis_range_selector_and_api_information(app,browser):
    articles(app)
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+'/studio/news');box=p.get_by_role('region',name='뉴스 분석 설정',exact=True)
        expect(box).to_contain_text('분석 API');expect(box).to_contain_text('모델')
        expect(box.get_by_role('button',name='기사 분석 · 승인',exact=True)).to_be_visible()
        box.get_by_role('combobox',name='뉴스 분석 범위',exact=True).select_option('collection')
        expect(box.get_by_role('button',name='TOP 3 분석 · 승인',exact=True)).to_be_disabled()
        expect(box.get_by_role('button')).to_have_count(1)
        if os.environ.get('QUOTE_REVIEW_EVIDENCE'):
            folder=Path(os.environ['QUOTE_REVIEW_EVIDENCE']);folder.mkdir(parents=True,exist_ok=True)
            box.get_by_role('combobox',name='뉴스 분석 범위',exact=True).select_option('article')
            for w,h in [(1366,768),(1920,1080)]:
                p.set_viewport_size({'width':w,'height':h})
                assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
                p.screenshot(path=str(folder/f'news-analysis-{w}x{h}.png'),full_page=True)
        assert not posts;c.close()

def test_whole_collection_id_bound_automatically_without_numeric_input(app,prepared,browser):
    identifier=Curator(app.state.coordinator).context()['run_id']
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+'/studio/news');box=p.get_by_role('region',name='뉴스 분석 설정',exact=True)
        box.get_by_role('combobox',name='뉴스 분석 범위',exact=True).select_option('collection')
        box.get_by_role('button',name='TOP 3 분석 · 승인',exact=True).click()
        d=p.get_by_role('dialog',name='기사 분석',exact=True)
        expect(d.get_by_role('spinbutton')).to_have_count(0)
        expect(d).not_to_contain_text('collection context id')
        expect(d).to_contain_text('이번 수집 회차 전체')
        expect(d.get_by_role('checkbox')).to_have_count(1)
        expect(d.get_by_role('button',name='기사 분석',exact=True)).to_be_disabled()
        # Capture the browser form only with a synthetic local response; never invoke even the Fake paid adapter here.
        submitted=[]
        p.route(origin+'/news/curation/analyze',lambda r:(submitted.append(parse_qs(r.request.post_data)),
            r.fulfill(status=303,headers={'Location':'/news'},body='')))
        d.get_by_role('checkbox').check();d.get_by_role('button',name='기사 분석',exact=True).click()
        expect(d).not_to_be_visible()
        assert len(submitted)==1 and submitted[0]['collection_context_id']==[str(identifier)]
        assert submitted[0]['consent']==['true']
        assert prepared[1].calls==[];c.close()

def test_shorts_api_info_and_cached_voice_sample_without_generation(app,browser):
    root=app.state.config.data_dir;folder=root/'voice-preview';folder.mkdir(exist_ok=True)
    name='preview-'+'a'*32+'.wav';path=folder/name
    with wave.open(str(path),'wb') as out:
        out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*1600)
    path.with_suffix('.json').write_text(json.dumps({'provider':'windows','voice':'Fake Korean Voice','rate':0,'pause_ms':250,
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}),encoding='utf8')
    with app.state.sessions.begin() as db:db.add(AppSetting(key='video_default_voice',value='Fake Korean Voice'))
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();posts=[]
        p.on('request',lambda r:posts.append(r) if r.method=='POST' else None)
        p.goto(origin+'/studio/shorts');p.get_by_role('combobox',name='음성',exact=True).select_option('Fake Korean Voice')
        p.get_by_role('button',name='목소리 미리듣기',exact=True).click()
        expect(p.get_by_label('선택한 목소리 샘플',exact=True)).to_have_attribute('src','/voices/preview/'+name)
        expect(p.get_by_role('region',name='영상 API 정보',exact=True)).to_contain_text('FFmpeg')
        p.get_by_role('combobox',name='영상 방식',exact=True).select_option('ai')
        expect(p.get_by_role('region',name='영상 API 정보',exact=True)).to_contain_text('Higgsfield')
        if os.environ.get('QUOTE_REVIEW_EVIDENCE'):
            folder=Path(os.environ['QUOTE_REVIEW_EVIDENCE']);folder.mkdir(parents=True,exist_ok=True)
            for w,h in [(1366,768),(1920,1080)]:
                p.set_viewport_size({'width':w,'height':h})
                assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
                p.screenshot(path=str(folder/f'news-shorts-preview-{w}x{h}.png'),full_page=True)
        assert not posts;c.close()
