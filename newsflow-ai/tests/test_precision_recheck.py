from copy import deepcopy
from test_character_precision import precision
from test_character_precision_browser import dist,browser,local_server,browser_context
from playwright.sync_api import expect
import pytest


@pytest.mark.parametrize('last_choice',['saved','new','initial'])
def test_review_latest_work_selection_wins(precision,browser,monkeypatch,last_choice):
    f=precision;first=f.w;second=f.create()
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[];held=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.route('**/api/studio/character-precision/'+first['id'],lambda route:held.append(route))
        page.goto(origin+'/studio/characters?precision='+(first['id'] if last_choice=='initial' else ''))
        picker=page.locator('.precision-toolbar select')
        expect(picker.locator('option')).to_have_count(3)
        if last_choice!='initial':picker.select_option(first['id'])
        page.wait_for_timeout(100)
        assert len(held)==1
        if last_choice=='new':
            page.get_by_role('button',name='새 작품',exact=True).click()
            expected=''
        else:
            picker.select_option(second['id']);expected=second['id']
            expect(page.get_by_role('region',name='정밀 제작').locator('.precision-progress')).to_be_visible()
        expect(picker).to_have_value(expected)
        # An old error is also irrelevant after switching to a new draft.
        if last_choice=='new':held[0].fulfill(status=500,json={'detail':'old read failed'})
        else:held[0].fulfill(status=200,json=first)
        page.wait_for_timeout(300)
        assert picker.input_value()==expected
        assert page.url.split('precision=')[1].split('&')[0]==expected
        expect(page.get_by_text('작품을 불러오지 못했습니다. 다시 선택해 주세요.',exact=True)).to_have_count(0)
        assert not posts and not f.adapter.calls and not f.writer.calls
        context.close()



@pytest.mark.parametrize('shape',['missing_characters','null_scene','missing_scenes'])
def test_review_invalid_candidate_editor_survives(precision,browser,monkeypatch,shape):
    f=precision
    class MalformedWriter:
        response_received=True
        last_reserved_usd='0'
        last_candidate={'scenes':[{'no':1,'description':'Incomplete stored AI output'}]}
        def generate(self,*a,**kw):raise ValueError('synthetic schema failure')
    writer=MalformedWriter()
    if shape=='null_scene':writer.last_candidate={'scenes':[None]}
    if shape=='missing_scenes':writer.last_candidate={'note':'incomplete synthetic output'}
    f.s.authoring=writer
    failed=f.s.write_story(f.w['id'],f.w['revision'],True)
    assert failed['state']=='story_failed'
    original=deepcopy(failed['story_attempts'][0]['candidate'])
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+failed['id'])
        page.get_by_text('직접 작성·복구',exact=True).click()
        page.get_by_role('button',name='보관된 스토리 편집',exact=True).click()
        page.wait_for_timeout(300)
        popup=page.get_by_role('dialog',name='장면 내용 수정')
        expect(popup).to_be_visible()
        expect(popup.get_by_role('status')).to_contain_text('빈 항목을 채운 뒤 저장')
        expect(popup.get_by_label('편집할 장면').locator('option')).to_have_count(5)
        if shape=='missing_characters':expect(popup.get_by_label('장면 설명',exact=True)).to_have_value('Incomplete stored AI output')
        popup.get_by_role('button',name='장면 저장 · 무료').click()
        expect(popup.get_by_role('alert')).to_be_visible()
        expect(popup.get_by_text('등장 캐릭터를 선택하세요.',exact=True)).to_be_visible()
        popup.get_by_label('장면 설명',exact=True).fill('User supplies the missing description')
        expect(popup.get_by_label('장면 설명',exact=True)).to_have_value('User supplies the missing description')
        assert f.s.read(f.w['id'])['story_attempts'][0]['candidate']==original
        visible=popup.count()
        assert not posts and not f.adapter.calls and f.s.read(f.w['id'])==failed
        context.close()
        assert not errors, errors
        assert visible==1



def test_recovered_candidate_can_save_without_changing_stored_response(precision,browser,monkeypatch):
    f=precision;candidate=deepcopy(f.story)
    candidate['scenes'][0].pop('characters')
    candidate['provider_note']='Retain only in original response'
    candidate['scenes'][0]['provider_note']='Not an editable scene field'
    w=f.s.read(f.w['id']);w['state']='story_failed'
    w['story_attempts']=[{'state':'failed','candidate':candidate}];f.s.save(w)
    original=deepcopy(w['story_attempts'])
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    f.app.state.image_studio=f.images
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();posts=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        page.get_by_text('직접 작성·복구',exact=True).click()
        page.get_by_role('button',name='보관된 스토리 편집',exact=True).click()
        popup=page.get_by_role('dialog',name='장면 내용 수정')
        popup.get_by_role('checkbox',name=f.chars[0]['name_ko'],exact=True).check()
        popup.get_by_role('button',name='장면 저장 · 무료').click()
        expect(popup).not_to_be_visible()
        saved=f.s.read(w['id'])
        assert saved['state']=='images'
        assert saved['scenario']['scenes'][0]['characters']==[f.ids[0]]
        assert saved['scenario']['scenes'][0]['description']==candidate['scenes'][0]['description']
        assert saved['story_attempts']==original
        assert len(posts)==1 and posts[0].endswith('/edit')
        assert not f.writer.calls and not f.adapter.calls and not f.video.sent
        context.close()


def test_extra_candidate_scenes_are_not_silently_discarded(precision,browser,monkeypatch):
    f=precision;candidate=deepcopy(f.story);candidate['scenes'].append(deepcopy(candidate['scenes'][0]))
    w=f.s.read(f.w['id']);w['state']='story_failed';w['story_attempts']=[{'state':'failed','candidate':candidate}];f.s.save(w)
    monkeypatch.setattr('newsflow.gui.character_precision_routes.service',lambda request:f.s)
    with local_server(f.app) as origin:
        context=browser_context(browser,origin);page=context.new_page();errors=[];posts=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.goto(origin+'/studio/characters?precision='+w['id'])
        page.get_by_text('직접 작성·복구',exact=True).click()
        page.get_by_role('button',name='보관된 스토리 편집',exact=True).click()
        expect(page.get_by_role('alert')).to_contain_text('보관된 장면 수가 설정과 다릅니다')
        expect(page.get_by_role('dialog',name='장면 내용 수정')).to_have_count(0)
        page.get_by_role('button',name='직접 작성',exact=True).click()
        expect(page.get_by_role('dialog',name='장면 내용 수정')).to_be_visible()
        assert f.s.read(w['id'])==w and not posts and not errors
        context.close()
