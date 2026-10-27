"""Investigate the existing 42px label failure without changing CSS or its test."""
import json
import os
from pathlib import Path

from conftest import app as app_fixture
from conftest import client as client_fixture
from conftest import fake as fake_fixture
from conftest import rss as rss_fixture
from playwright.sync_api import expect
from test_model_picker_browser import browser as browser_fixture
from test_workspace_access_browser import page as page_fixture

app, client, fake, rss = app_fixture, client_fixture, fake_fixture, rss_fixture
browser, page = browser_fixture, page_fixture


def test_mobile_voice_label_click_and_keyboard(page):
    page.set_viewport_size({'width': 390, 'height': 844})
    page.goto('http://127.0.0.1/')
    page.locator('[data-sidebar-menu]>summary').click()
    page.locator('[data-sidebar-tools]>summary').click()
    link = page.locator('.workspace-nav a[href="/voices"]')
    expect(link).to_be_visible()
    geometry = link.evaluate('''el => {
        const r=el.getBoundingClientRect(), s=el.querySelector('span'), t=s.getBoundingClientRect();
        return {link:{x:r.x,y:r.y,width:r.width,height:r.height}, label:{width:t.width,height:t.height},
            clipped:s.scrollHeight>s.clientHeight || s.scrollWidth>s.clientWidth,
            hit:el.contains(document.elementFromPoint(r.x+r.width/2,r.y+r.height/2))};
    }''')
    assert geometry['link']['width'] >= 44 and geometry['link']['height'] >= 44
    assert not geometry['clipped'] and geometry['hit']
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
    output = Path(os.environ['NEWSFLOW_VALIDATION_OUTPUT']) / 'mobile'
    output.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output / 'voice-menu-390.png'))
    link.click()
    expect(page).to_have_url('http://127.0.0.1/voices')
    page.goto('http://127.0.0.1/')
    page.locator('[data-sidebar-menu]>summary').click()
    page.locator('[data-sidebar-tools]>summary').click()
    link = page.locator('.workspace-nav a[href="/voices"]')
    link.focus()
    expect(link).to_be_focused()
    page.keyboard.press('Enter')
    expect(page).to_have_url('http://127.0.0.1/voices')
    (output / 'access.json').write_text(json.dumps({**geometry,'click':'PASS','keyboard':'PASS',
        'viewport':'390x844','css_modified':False,'legacy_height_assertion_unchanged':True},indent=2),encoding='utf-8')
