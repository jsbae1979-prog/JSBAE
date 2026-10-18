"""Selection follows an existing protected scene when the user reorders it."""
from pathlib import Path

from playwright.sync_api import expect
from test_model_picker_browser import browser as browser_fixture

browser = browser_fixture


def test_reordered_scene_keeps_correct_tab_and_readonly_content(browser):
    page = browser.new_page()
    page.route("**/*", lambda route: route.abort())
    page.set_content('''<form action="/ai/drafts/1"><div class="scene-tabs">
      <button type="button" data-edit-scene="0">장면 1</button>
      <button type="button" data-edit-scene="1">장면 2</button></div>
      <fieldset data-topic-scene><legend>장면 1</legend><button type="button" data-scene-up>위로</button>
        <input name="seconds" value="10"><textarea name="narration" readonly>첫 번째 보호 문장</textarea></fieldset>
      <fieldset data-topic-scene><legend>장면 2</legend><button type="button" data-scene-up>위로</button>
        <input name="seconds" value="10"><textarea name="narration" readonly>두 번째 보호 문장</textarea></fieldset>
      <p data-editor-dirty hidden>저장 필요</p></form>''')
    scripts = Path(__file__).resolve().parents[1] / "src/newsflow/static/js"
    page.add_script_tag(content=(scripts / "creator.js").read_text())
    page.add_script_tag(content=(scripts / "app.js").read_text())
    page.get_by_role("button", name="장면 2", exact=True).click()
    page.locator('fieldset:visible [data-scene-up]').click()
    expect(page.get_by_role("button", name="장면 1", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(page.locator('fieldset:visible textarea')).to_have_value("두 번째 보호 문장")
    expect(page.locator('fieldset:visible legend')).to_have_text("장면 1")
    assert page.locator('fieldset:visible textarea').get_attribute("readonly") is not None
    page.close()
