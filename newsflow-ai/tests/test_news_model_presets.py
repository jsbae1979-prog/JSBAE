"""Official public preset metadata; Fake request body parity; no paid calls."""
import json
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_news_model_selection import full,new_plan
from test_news_analysis_voice_features import context
from newsflow.video.ai.model_contracts import news_model_presets,check_model_contract
from newsflow.video.ai.settings import parse_durations,list_models
from newsflow.video.ai.higgsfield import HiggsfieldProvider
from newsflow.video.ai.contracts import ClipRequest


@pytest.mark.parametrize('preset',news_model_presets(),ids=lambda p:p['label'])
def test_presets_fit_existing_registration_contract(preset):
    assert parse_durations(','.join(map(str,preset['durations'])))==tuple(preset['durations'])
    for res in preset['resolutions']:
        assert check_model_contract(preset['path'],tuple(preset['durations']),res)[0]=='PASS'
    assert preset['docsUrl'].startswith('https://open.higgsfield.ai/models/')
    assert 'price' not in preset and preset['aspectRatio']=='9:16'


@pytest.mark.parametrize('preset',news_model_presets(),ids=lambda p:p['label'])
def test_quote_and_generation_use_identical_payload_with_fake_transport(preset):
    calls=[]
    def fake(host,method,path,body,headers,timeout):
        calls.append((path,json.loads(body)))
        return 200,json.dumps({'usd':'0.1'} if path.startswith('/estimate/') else {'request_id':'synthetic-request','status':'queued'}).encode()
    provider=HiggsfieldProvider(lambda:'synthetic-id:synthetic-secret',requester=fake)
    request=ClipRequest(preset['path'],'Synthetic blue scene',5,'720p')
    provider.estimate_usd(request);provider.submit(request)
    assert calls[0][1]==calls[1][1]
    if preset['label'] in {'Wan 3.0','PixVerse V6'}:assert calls[0][1]['generate_audio'] is False
    else:assert 'generate_audio' not in calls[0][1]


def test_gui_register_without_price_or_provider_call_then_select(full,browser):
    new_plan(full)
    with local_server(full.app) as origin:
        ctx=context(browser,origin);page=ctx.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/shorts?draft_id='+str(full.draft_id))
        page.get_by_role('combobox',name='영상 방식',exact=True).select_option('ai')
        page.get_by_role('button',name='영상 모델 등록',exact=True).click()
        dialog=page.get_by_role('dialog')
        dialog.get_by_role('combobox',name='추가할 영상 모델',exact=True).select_option('alibaba/wan-3.0/text-to-video')
        expect(dialog.get_by_role('combobox',name='해상도',exact=True)).to_have_value('720p')
        dialog.get_by_role('combobox',name='해상도',exact=True).select_option('1080p')
        expect(dialog.get_by_role('checkbox')).to_have_count(0)
        expect(dialog.get_by_role('textbox')).to_have_count(0)
        dialog.get_by_role('button',name='모델 추가',exact=True).click()
        expect(dialog).to_have_count(0)
        model=page.get_by_role('combobox',name='AI 영상 모델',exact=True)
        model.select_option('alibaba/wan-3.0/text-to-video')
        expect(page.get_by_text('비용 미확정 · 생성 전 견적 필요',exact=True)).to_be_visible()
        stored=next(m for m in list_models(full.app.state.sessions) if m.path=='alibaba/wan-3.0/text-to-video')
        assert stored.confirmed and stored.price_per_second is None and not stored.usable and stored.resolution=='1080p'
        assert len(posts)==1 and posts[0].endswith('/video-ai-settings/models') and not full.provider.calls
        page.get_by_role('button',name='AI 장면 계획 · 견적',exact=True).click()
        expect(page.get_by_role('dialog').get_by_role('combobox',name='등록된 영상 모델',exact=True)).to_have_value(stored.path)
        assert len(posts)==1
        ctx.close()
