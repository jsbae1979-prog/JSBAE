"""Actual React review of a bounded Fake analysis draft; no paid requests."""
import pytest
from playwright.sync_api import expect

from newsflow.character.registry import CharacterRegistry
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_authoring_v3 import Store, build, candidate, png
from test_character_species_review import LONG_SPECIES


@pytest.mark.parametrize('short_species', ['', 'rabbit'])
def test_partial_analysis_requires_manual_candidate_and_save(app, browser, short_species):
    answer = candidate()
    answer['species'] = LONG_SPECIES
    service, adapter, budget = build('claude_api', answer)
    app.state.character_authoring = service
    app.state.api_keys = {'claude_api': Store()}
    registry = CharacterRegistry(app.state.config.data_dir, app.state.image_studio)
    with local_server(app) as origin:
        context = browser.new_context(viewport={'width':1366, 'height':768})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
        page = context.new_page()
        posts, errors = [], []
        page.on('request', lambda request: posts.append(request.url) if request.method=='POST' else None)
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin+'/studio/characters')
        page.get_by_label('캐릭터 참조 이미지 업로드', exact=True).set_input_files(
            {'name':'synthetic.png', 'mimeType':'image/png', 'buffer':png()})
        page.get_by_role('button', name='새 캐릭터 등록', exact=True).click()
        dialog = page.get_by_role('dialog', name='새 캐릭터 등록', exact=True)
        dialog.get_by_text('AI로 특징 초안 만들기 · 선택 사항', exact=True).click()
        dialog.get_by_label('선택한 AI에 참조 이미지를 전송하는 유료 분석에 동의합니다.', exact=True).check()
        dialog.get_by_role('button', name='이미지로 특징 초안 만들기', exact=True).click()
        notice = dialog.get_by_text('초안을 받았습니다. 종류는 짧게 수정하거나 비워두세요.', exact=True)
        expect(notice).to_be_visible()
        review = dialog.get_by_role('region', name='종류 초안 검토', exact=True)
        assert not review.locator('details').evaluate('(e)=>e.open')
        expect(review.get_by_text(LONG_SPECIES, exact=True)).not_to_be_visible()
        species = dialog.get_by_label('종류', exact=True)
        expect(species).to_have_value('')
        expect(species).to_have_attribute('maxlength', '40')
        assert not species.evaluate('(e)=>e.required')
        expect(dialog.get_by_label('캐릭터 이름', exact=True)).to_have_value('')
        expect(dialog.get_by_label('성격', exact=True)).to_have_value('')
        expect(dialog.get_by_role('textbox', name='외형 · 영어', exact=True)).to_have_value(answer['appearance'])
        for row in answer['candidates']:
            expect(dialog.get_by_role('button', name=row['name_ko']+' 선택', exact=True)).to_be_visible()
        assert not registry.list()
        assert not any(url.endswith('/profiles/save') for url in posts)
        assert len(adapter.bodies)==1 and len(budget.finished)==1
        expect(dialog.get_by_role('button', name='이미지로 특징 초안 만들기', exact=True)).to_be_disabled()

        review.get_by_text(f'종류 원문 · {len(LONG_SPECIES)}자', exact=True).click()
        expect(review.get_by_text(LONG_SPECIES, exact=True)).to_be_visible()
        species.fill(short_species)
        selected = answer['candidates'][1]
        dialog.get_by_role('button', name=selected['name_ko']+' 선택', exact=True).click()
        expect(dialog.get_by_label('캐릭터 이름', exact=True)).to_have_value(selected['name_ko'])
        assert not registry.list()  # Selecting a candidate is not registration.
        dialog.get_by_role('button', name='캐릭터 저장', exact=True).click()
        expect(dialog).to_have_count(0)
        saved = registry.list()
        assert len(saved)==1 and saved[0]['species']==short_species
        assert saved[0]['name_ko']==selected['name_ko'] and saved[0]['personality']==selected['personality']
        assert 'needs_review' not in saved[0] and LONG_SPECIES not in str(saved[0])
        assert len(adapter.bodies)==1 and len(budget.reservations)==1 and len(budget.finished)==1
        assert sum(url.endswith('/profiles/save') for url in posts)==1 and not errors
        context.close()
