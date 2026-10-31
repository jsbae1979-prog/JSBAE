"""Five-field manual character registration; no AI/provider calls."""
import os
from pathlib import Path
import pytest
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image,profile
from newsflow.character.registry import CharacterRegistry
from newsflow.video_models.catalog import character_config

CAPTURE_DIR=Path(os.environ['NEWSFLOW_CHARACTER_CAPTURE_DIR']) if os.environ.get('NEWSFLOW_CHARACTER_CAPTURE_DIR') else None


def test_five_required_fields_allow_manual_save_with_optional_values_blank(app,browser,tmp_path):
    registry=CharacterRegistry(app.state.config.data_dir,app.state.image_studio)
    with local_server(app) as origin:
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();posts=[];page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters')
        page.get_by_label('캐릭터 참조 이미지 업로드',exact=True).set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':image()})
        page.get_by_role('button',name='새 캐릭터 등록',exact=True).click()
        dialog=page.get_by_role('dialog',name='새 캐릭터 등록',exact=True)
        expect(dialog.locator(':required')).to_have_count(5)
        assert not dialog.locator('.character-profile-optional').evaluate('(e)=>e.open')
        values={'캐릭터 이름':'합성 최소 캐릭터','외형 · 영어':'Original rabbit with round ears and a blue scarf.',
                '성격':'느긋하고 작은 실수를 재미있게 넘김','반복되는 상황':'바쁜 아침','캐릭터만의 반응':'천천히 해결'}
        for label,value in list(values.items())[:-1]:dialog.get_by_role('textbox',name=label,exact=True).fill(value)
        dialog.get_by_role('button',name='캐릭터 저장',exact=True).click()
        expect(dialog).to_be_visible()
        expect(dialog.get_by_role('textbox',name='캐릭터만의 반응',exact=True)).to_be_focused()
        assert not registry.list() and not any('/profiles/save' in url for url in posts)
        dialog.get_by_role('textbox',name='캐릭터만의 반응',exact=True).fill(values['캐릭터만의 반응'])
        for label in ['종류','이야기의 세계','고정 스타일 · 영어']:
            field=dialog.get_by_label(label,exact=True)
            assert field.evaluate('(e)=>e.required') is False
            expect(field).to_have_value('')
        out=CAPTURE_DIR or tmp_path/'captures';out.mkdir(parents=True,exist_ok=True)
        for width,height in [(1920,1080),(1366,768)]:
            page.set_viewport_size({'width':width,'height':height})
            expect(dialog.get_by_role('button',name='캐릭터 저장',exact=True)).to_be_in_viewport()
            page.screenshot(path=str(out/f'character-five-fields-{width}x{height}.png'))
        dialog.get_by_role('button',name='캐릭터 저장',exact=True).click()
        expect(dialog).to_have_count(0)
        saved=registry.list();assert len(saved)==1
        assert saved[0]['species']=='' and saved[0]['comedy_formula']['world']==''
        assert saved[0]['style_lock']==character_config()['style_lock']
        assert saved[0]['name_ko']==values['캐릭터 이름'] and saved[0]['personality']==values['성격']
        assert not any('/analyze' in url or '/auto-story' in url for url in posts)
        context.close()


def test_profile_edit_keeps_existing_optional_values_without_opening_them(app,browser,tmp_path):
    registry=CharacterRegistry(app.state.config.data_dir,app.state.image_studio)
    before=registry.save(profile('기존 합성 토끼','rabbit'),app.state.image_studio.asset_bytes(image()))
    with local_server(app) as origin:
        context=browser.new_context()
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page=context.new_page();page.goto(origin+'/studio/characters')
        page.get_by_role('button',name='내 캐릭터',exact=True).click()
        page.get_by_label('저장된 캐릭터',exact=True).select_option('profile:'+before['id'])
        page.get_by_role('button',name='특징 수정',exact=True).click()
        dialog=page.get_by_role('dialog',name='캐릭터 특징 수정',exact=True)
        assert not dialog.locator('.character-profile-optional').evaluate('(e)=>e.open')
        dialog.get_by_role('textbox',name='성격',exact=True).fill('조용하게 관찰하며 반응하는 성격')
        dialog.get_by_role('button',name='캐릭터 저장',exact=True).click()
        expect(dialog).to_have_count(0)
        after=registry.get(before['id'])
        assert after['revision']==before['revision']+1
        for key in ['species','style_lock','comedy_formula','supporting_cast','audience','asset']:
            assert after[key]==before[key]
        assert after['personality']=='조용하게 관찰하며 반응하는 성격'
        context.close()


@pytest.mark.parametrize('command', ['save','delete'])
def test_generic_profile_failure_is_action_specific_and_keeps_inputs(app,browser,tmp_path,command):
    registry=CharacterRegistry(app.state.config.data_dir,app.state.image_studio)
    saved=registry.save(profile('오류 보존 캐릭터','rabbit'),app.state.image_studio.asset_bytes(image()))
    with local_server(app) as origin:
        context=browser.new_context()
        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        endpoint='/api/studio/characters/profiles/save' if command=='save' else f'/api/studio/characters/profiles/{saved["id"]}/delete'
        attempts=[]
        def reject(route):
            attempts.append(route.request.method)
            route.fulfill(status=409,json={'detail':'입력·저장 상태·API 승인 한도를 확인하세요. 결과가 불명확하면 자동 재요청하지 않습니다.'})
        context.route('**'+endpoint,reject)
        page=context.new_page();page.goto(origin+'/studio/characters')
        page.get_by_role('button',name='내 캐릭터',exact=True).click()
        page.get_by_label('저장된 캐릭터',exact=True).select_option('profile:'+saved['id'])
        if command=='save':
            page.get_by_role('button',name='특징 수정',exact=True).click()
            dialog=page.get_by_role('dialog',name='캐릭터 특징 수정',exact=True)
            dialog.get_by_role('textbox',name='성격',exact=True).fill('저장 실패 후에도 남을 입력')
            dialog.get_by_role('button',name='캐릭터 저장',exact=True).click()
            expect(dialog.get_by_role('alert')).to_have_text('캐릭터 정보를 저장하지 못했습니다. 입력한 내용은 유지됩니다. 저장 상태를 확인하세요.')
            expect(dialog.get_by_role('textbox',name='성격',exact=True)).to_have_value('저장 실패 후에도 남을 입력')
        else:
            page.get_by_role('button',name='등록 삭제',exact=True).click()
            dialog=page.get_by_role('dialog',name='캐릭터 등록 삭제',exact=True)
            dialog.get_by_role('button',name='등록 삭제 확인',exact=True).click()
            expect(dialog.get_by_role('alert')).to_have_text('캐릭터 등록을 삭제하지 못했습니다.')
        expect(dialog).to_be_visible()
        assert attempts==['POST'] and registry.get(saved['id'])==saved
        context.close()
