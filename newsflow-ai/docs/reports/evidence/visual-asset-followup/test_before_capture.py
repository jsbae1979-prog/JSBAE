from conftest import app, fake, rss
from test_visual_asset_followup import browser, capture, no_external

__all__ = ['app', 'fake', 'rss', 'browser', 'no_external']

def test_before(app, fake, browser, tmp_path):
    capture(app, fake, browser, tmp_path, check=False)
