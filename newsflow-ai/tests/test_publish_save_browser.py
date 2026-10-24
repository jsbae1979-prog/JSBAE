"""A successful local review save must clear its unsaved-navigation warning."""
from pathlib import Path

from test_model_picker_browser import browser as browser_fixture

browser = browser_fixture
JS = Path(__file__).resolve().parents[1] / 'src/newsflow/static/js'


def test_saved_publish_review_reloads_without_unsaved_warning(browser):
    context = browser.new_context()
    page = context.new_page()
    html = '''<meta charset="utf-8"><form method="post" action="/workspace" data-unified-publish-form data-publish-review>
      <label>제목<input name="title" value="합성"></label>
      <p data-publish-unsaved hidden>저장하지 않은 변경</p>
      <button>검토 저장</button></form>'''
    # Every request is fulfilled inside the browser; there is no server or upload.
    context.route('**/*', lambda route: route.fulfill(status=200,content_type='text/html',body=html))
    page.goto('http://127.0.0.1:18765/workspace')
    page.add_script_tag(content=(JS/'app.js').read_text(encoding='utf-8'))
    page.add_script_tag(content=(JS/'publish_workspace.js').read_text(encoding='utf-8'))
    dialogs = []
    def dialog(dialog):
        dialogs.append(dialog.type)
        dialog.accept()  # A synthetic unsaved-navigation prompt only, no service approval.
    page.on('dialog',dialog)
    page.get_by_label('제목').fill('합성 수정')
    with page.expect_navigation():
        page.get_by_role('button',name='검토 저장').click()
    assert dialogs == [], 'Already-saved review incorrectly prompts before reloading'
    context.close()


def test_workspace_resume_reloads_same_task_instead_of_leaving_stale_review(browser):
    context = browser.new_context()
    page = context.new_page()
    documents = []
    def respond(route):
        if route.request.resource_type == 'document':
            documents.append('document')
        html = f'''<meta charset="utf-8"><h1>화면 {len(documents)}</h1>
          <form method="post" action="/?task=fixture" data-easy-form>
          <input name="workspace" value="true"><button type="submit">계속</button>
          <p data-submit-error></p></form>'''
        route.fulfill(status=200,content_type='text/html; charset=utf-8',body=html)
    context.route('**/*',respond)
    page.goto('http://127.0.0.1:18765/?task=fixture#workspace-detail')
    page.add_script_tag(content=(JS/'autopilot.js').read_text(encoding='utf-8'))
    page.get_by_role('button',name='계속',exact=True).click()
    from playwright.sync_api import expect
    expect(page.get_by_role('heading')).to_have_text('화면 2')
    assert len(documents)==2
    context.close()
