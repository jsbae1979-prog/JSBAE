"""History-trash bridge, real unlink only in synthetic temp profiles."""
import json
import pytest
from conftest import csrf
from newsflow.character.visibility import set_visibility
from newsflow.character.schema import CharacterError
from test_library_visibility import character, markers
from test_library_purge import purge
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from playwright.sync_api import expect


def old_trash(app, topic='합성 휴지통 작업'):
    item=character(app);identifier=item.split(':')[1]
    job=app.state.character.read(identifier);job['topic']=topic;app.state.character.save(job)
    set_visibility(app.state.character,identifier,'history',True)
    return item


def test_legacy_trash_purge_preserves_journal_and_blocks_restore(app,client):
    item=old_trash(app);identifier=item.split(':')[1];folder=app.state.character.folder(identifier)
    before=(folder/'jobs.json').read_bytes()
    assert 'library:'+item not in markers(app)
    assert purge(client,[item]).status_code==200
    assert (folder/'jobs.json').read_bytes()==before and not (folder/'reference.png').exists()
    assert markers(app)['library:'+item]['state']=='purged'
    assert client.get('/api/studio/modules/characters').json()['collections']['jobs']==[]
    with pytest.raises(CharacterError):set_visibility(app.state.character,identifier,'history',False)


def test_legacy_mixed_selection_failure_changes_nothing(app,client):
    item=old_trash(app);active=character(app)
    before=markers(app);reference=app.state.character.folder(item.split(':')[1])/'reference.png'
    assert purge(client,[item,active]).status_code==409
    assert reference.exists() and markers(app)==before
    assert purge(client,[item],confirm='false').status_code==422 and markers(app)==before


def test_recent_hidden_only_is_not_trash(app,client):
    item=character(app);identifier=item.split(':')[1]
    set_visibility(app.state.character,identifier,'recent',True)
    assert purge(client,[item]).status_code==409 and not markers(app)


def test_history_trash_selection_cancel_then_synthetic_purge(app,browser,tmp_path):
    ids=[old_trash(app,'합성 삭제 대상 A'),old_trash(app,'합성 삭제 대상 B')]
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1366,'height':768})
        ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        page=ctx.new_page();posts=[];errors=[]
        page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(origin+'/studio/characters')
        page.get_by_role('button',name='작업 이력',exact=True).click()
        history=page.get_by_role('dialog',name='작업 이력',exact=True)
        history.get_by_role('button',name='휴지통 보기',exact=True).click()
        history.get_by_role('checkbox',name='휴지통 전체 선택',exact=True).check()
        expect(history.get_by_text('2개 선택',exact=True)).to_be_visible()
        history.get_by_role('button',name='선택 완전 삭제',exact=True).click()
        dialog=page.get_by_role('alertdialog',name='선택 작업 완전 삭제',exact=True)
        expect(dialog).to_contain_text('앱에서 복원할 수 없습니다')
        dialog.get_by_role('button',name='취소',exact=True).click()
        assert not posts
        for w,h in [(1366,768),(1920,1080)]:
            page.set_viewport_size({'width':w,'height':h})
            expect(history.get_by_role('button',name='선택 완전 삭제',exact=True)).to_be_visible()
            boxes=history.locator('input[type=checkbox]').evaluate_all('(es)=>es.map(e=>e.getBoundingClientRect().width)')
            assert all(14<=w<=20 for w in boxes)
            page.screenshot(path=str(tmp_path/f'character-trash-{w}.png'))
        history.get_by_role('checkbox',name='합성 삭제 대상 B 완전 삭제 선택',exact=True).uncheck()
        history.get_by_role('button',name='선택 완전 삭제',exact=True).click()
        expect(dialog).to_contain_text('선택한 작업 1개')
        dialog.get_by_role('button',name='완전 삭제',exact=True).click()
        expect(history.get_by_role('checkbox',name='합성 삭제 대상 A 완전 삭제 선택',exact=True)).to_have_count(0)
        expect(history.get_by_role('checkbox',name='합성 삭제 대상 B 완전 삭제 선택',exact=True)).to_be_visible()
        assert len(posts)==1 and posts[0].endswith('/api/studio/library/purge') and not errors
        assert markers(app)['library:'+ids[0]]['state']=='purged' and 'library:'+ids[1] not in markers(app)
        ctx.close()
