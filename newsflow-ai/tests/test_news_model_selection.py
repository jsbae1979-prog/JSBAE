"""News model selection: synthetic local DB, no supplier generation."""
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs
import os
import pytest
from playwright.sync_api import expect
from sqlalchemy import select
from conftest import csrf
from test_final_production import full, no_external, new_plan, rows
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_analysis_voice_features import context
from newsflow.video.ai.settings import save_model
from newsflow.video.ai.production import DEFAULT_MODEL, read_contract
from newsflow.db.models import AIVideoPlan

SECOND = 'wan/v2.7/text-to-video'

def add_models(full):
    save_model(full.app.state.sessions, path=SECOND, label='Wan 2.7', price_per_second='0.02',
               durations='5,10,15', resolution='1080p', confirmed=True)
    save_model(full.app.state.sessions, path='unverified/model', label='Not supported', price_per_second='0.01',
               durations='5', resolution='720p', confirmed=True)

def test_read_catalog_excludes_unsupported_and_does_not_submit(full, client):
    add_models(full)
    data=client.get('/api/studio/modules/shorts').json()['catalog']
    assert {x['path'] for x in data['newsVideoModels']} == {DEFAULT_MODEL, SECOND}
    assert data['newsVideoDefault'] == DEFAULT_MODEL

@pytest.mark.parametrize('model',[DEFAULT_MODEL, SECOND])
def test_choice_reaches_every_scene_without_generation(full, client, model):
    add_models(full);new_plan(full)
    response=client.post('/video/ai/plans',data={'csrf_token':csrf(client),'draft_id':full.draft_id,
        'duration':30,'mode':'full','model_path':model},follow_redirects=False)
    assert response.status_code==303
    plan=int(response.headers['location'].rsplit('/',1)[1])
    assert all(s.model_path==model and s.status=='planned' for s in rows(full,plan))
    with full.app.state.sessions() as db:
        assert read_contract(db,plan)['model']['path']==model
        assert db.get(AIVideoPlan,plan).status=='draft'

@pytest.mark.parametrize('width',[1366,1920])
def test_visible_model_choice_reaches_review(full,browser,width):
    add_models(full);new_plan(full)
    with local_server(full.app) as origin:
        ctx=context(browser,origin);p=ctx.new_page();p.set_viewport_size({'width':width,'height':768 if width==1366 else 1080})
        posts=[]
        p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        p.goto(origin+'/studio/shorts?draft_id='+str(full.draft_id))
        p.get_by_role('combobox',name='영상 방식',exact=True).select_option('ai')
        model=p.get_by_role('combobox',name='AI 영상 모델',exact=True)
        expect(model).to_be_visible();model.select_option(SECOND)
        expect(model).to_have_value(SECOND)
        assert 'Not supported' not in model.inner_text()
        p.get_by_role('button',name='AI 장면 계획 · 견적',exact=True).click()
        dialog=p.get_by_role('dialog')
        expect(dialog.get_by_role('combobox',name='등록된 영상 모델',exact=True)).to_have_value(SECOND)
        expect(dialog.get_by_role('combobox',name='영상 제작 방식',exact=True)).to_have_value('full')
        assert not posts
        folder=os.environ.get('QUOTE_REVIEW_EVIDENCE')
        if folder:
            Path(folder).mkdir(parents=True,exist_ok=True)
            p.screenshot(path=str(Path(folder)/f'news-model-review-{width}.png'))
        ctx.close()


@pytest.mark.parametrize('auth',['valid','csrf','origin','session'])
def test_operating_local_model_registration_and_plan_keep_auth(full,auth):
    from starlette.testclient import TestClient
    from newsflow.distribution.local_access import LocalAccess, LaunchSession
    from bat_distribution.operation import OperatingRequests
    add_models(full);new_plan(full)
    launch=LaunchSession(18779)
    client=TestClient(OperatingRequests(LocalAccess(full.app,launch)),base_url=launch.origin,
        client=('127.0.0.1',40000),follow_redirects=False)
    client.cookies.set(launch.cookie_name,launch.claim(launch.launch_url().split('#')[1]))
    client.get('/studio/shorts')
    token=client.cookies.get('newsflow_csrf');headers={'Origin':launch.origin}
    if auth=='csrf':token='bad'
    if auth=='origin':headers['Origin']='https://outside.invalid'
    if auth=='session':client.cookies.clear()
    register={'csrf_token':token,'path':'alibaba/wan-3.0/text-to-video','label':'Wan 3.0','durations':'5,10,15',
        'resolution':'1080p','price_per_second':'0.02','confirmed':'true','pricing_mode':'manual'}
    response=client.post('/video-ai-settings/models',data=register,headers=headers)
    assert response.status_code==(303 if auth=='valid' else 403), response.text
    response=client.post('/video/ai/plans',data={'csrf_token':token,'draft_id':full.draft_id,
        'duration':30,'mode':'full','model_path':SECOND},headers=headers)
    assert response.status_code==(303 if auth=='valid' else 403), response.text
    if auth=='valid':
        assert client.post('/video-ai-settings/models',data={**register,'pricing_mode':'official'},headers=headers).status_code==403
        assert client.post('/video/ai/plans/1/confirm',data={'csrf_token':token,'confirmed':'true'},headers=headers).status_code==403
        assert client.post('/video/ai/plans/1/approve',data={'csrf_token':token},headers=headers).status_code==403
    assert not full.provider.calls
