"""Actual React reference-storage state against synthetic local records only."""
from playwright.sync_api import expect

from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_character_episode_schema import image, profile
from newsflow.character.registry import CharacterRegistry


def local_page(browser, app, origin):
    context = browser.new_context(viewport={'width': 1366, 'height': 768})
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(origin+'/') else route.abort())
    page = context.new_page()
    posts = []
    page.on('request', lambda request: posts.append((request.method, request.url)) if request.method not in {'GET', 'HEAD'} else None)
    page.goto(origin+'/studio/characters')
    return context, page, posts


def store_posts(posts):
    return [row for row in posts if row[1].endswith('/api/studio/characters/library')]


def test_selected_upload_becomes_stored_only_after_success_without_duplicate_save(app, browser):
    with local_server(app) as origin:
        context, page, posts = local_page(browser, app, origin)
        checkbox = page.get_by_label('참조 이미지 보관', exact=True)
        status = page.get_by_label('참조 이미지 보관 상태', exact=True)
        expect(checkbox).to_be_disabled()
        expect(checkbox).not_to_be_checked()
        expect(status).to_have_count(0)
        upload = page.get_by_label('캐릭터 참조 이미지 업로드', exact=True)
        upload.set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': image()})
        expect(status).to_have_text('보관 여부 확인 전')
        expect(checkbox).not_to_be_checked()
        assert not app.state.image_studio.characters()
        checkbox.check()
        expect(status).to_have_text('보관됨')
        expect(checkbox).to_be_checked()
        expect(checkbox).to_be_disabled()
        assert len(store_posts(posts)) == 1 and len(app.state.image_studio.characters()) == 1
        dimensions = checkbox.bounding_box()
        assert dimensions and dimensions['width'] == 18 and dimensions['height'] == 18

        # Registering the same selected File reuses the acknowledged library asset.
        page.get_by_role('button', name='새 캐릭터 등록', exact=True).click()
        dialog = page.get_by_role('dialog', name='새 캐릭터 등록', exact=True)
        values = profile('저장 확인 토끼')
        for label, key in [('캐릭터 이름','name_ko'), ('종류','species'), ('외형 · 영어','appearance'),
                           ('성격','personality'), ('고정 스타일 · 영어','style_lock')]:
            dialog.get_by_label(label, exact=True).fill(values[key])
        for label, key in [('이야기의 세계','world'), ('반복되는 상황','setup'), ('캐릭터만의 반응','reaction')]:
            dialog.get_by_label(label, exact=True).fill(values['comedy_formula'][key])
        dialog.get_by_role('button', name='캐릭터 저장', exact=True).click()
        expect(dialog).to_have_count(0)
        assert len(store_posts(posts)) == 1
        assert len(CharacterRegistry(app.state.config.data_dir, app.state.image_studio).list()) == 1
        page.get_by_role('button', name='참조 이미지 업로드', exact=True).click()
        upload.set_input_files({'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': image('green')})
        expect(status).to_have_text('보관 여부 확인 전')
        expect(checkbox).not_to_be_checked()
        assert len(store_posts(posts)) == 1  # Prior preference does not auto-save another image.
        assert len(app.state.image_studio.characters()) == 1
        assert all(method != 'DELETE' for method, _ in posts)
        context.close()


def test_profile_asset_is_not_mislabeled_as_library_storage(app, browser):
    studio = app.state.image_studio
    saved = CharacterRegistry(app.state.config.data_dir, studio).save(profile(), studio.asset_bytes(image()))
    assert studio.assets() and not studio.characters()
    with local_server(app) as origin:
        context, page, posts = local_page(browser, app, origin)
        page.get_by_role('button', name='내 캐릭터', exact=True).click()
        page.get_by_label('저장된 캐릭터', exact=True).select_option('profile:'+saved['id'])
        page.get_by_role('button', name='참조 이미지 업로드', exact=True).click()
        checkbox = page.get_by_label('참조 이미지 보관', exact=True)
        status = page.get_by_label('참조 이미지 보관 상태', exact=True)
        expect(status).to_have_text('아직 보관 안 됨')
        expect(checkbox).not_to_be_checked()
        checkbox.check()
        expect(status).to_have_text('보관됨')
        expect(checkbox).to_be_disabled()
        assert len(store_posts(posts)) == 1 and studio.characters()[0]['id'] == saved['asset']
        context.close()


def test_existing_library_reference_is_checked_without_a_write_after_reload(app, browser):
    row = app.state.image_studio.save_character(image(), '기존 합성 이미지')
    with local_server(app) as origin:
        context, page, posts = local_page(browser, app, origin)
        for _ in range(2):
            page.get_by_role('button', name='내 캐릭터', exact=True).click()
            page.get_by_label('저장된 캐릭터', exact=True).select_option('image:'+row['id'])
            page.get_by_role('button', name='참조 이미지 업로드', exact=True).click()
            expect(page.get_by_label('참조 이미지 보관 상태', exact=True)).to_have_text('보관됨')
            checkbox = page.get_by_label('참조 이미지 보관', exact=True)
            expect(checkbox).to_be_checked()
            expect(checkbox).to_be_disabled()
            assert not posts
            page.reload()
        assert app.state.image_studio.characters() == [{k:v for k,v in row.items() if k != 'created'}]
        context.close()


def test_failed_store_does_not_display_saved_or_retry(app, browser):
    with local_server(app) as origin:
        context, page, posts = local_page(browser, app, origin)
        context.route('**/api/studio/characters/library', lambda route: route.fulfill(status=409, json={'detail': '합성 저장 실패'}))
        page.get_by_label('캐릭터 참조 이미지 업로드', exact=True).set_input_files(
            {'name': 'synthetic.png', 'mimeType': 'image/png', 'buffer': image()})
        checkbox = page.get_by_label('참조 이미지 보관', exact=True)
        checkbox.click()  # The failed response correctly restores unchecked immediately.
        expect(page.get_by_text('합성 저장 실패', exact=True)).to_be_visible()
        expect(page.get_by_label('참조 이미지 보관 상태', exact=True)).to_have_text('보관 여부 확인 전')
        expect(checkbox).not_to_be_checked()
        expect(checkbox).to_be_enabled()
        assert len(store_posts(posts)) == 1 and not app.state.image_studio.characters()
        context.close()
