"""Content navigation is GET-only; existing generation/review policies stay untouched."""
import hashlib
import io
from copy import deepcopy

from PIL import Image
from playwright.sync_api import expect
from test_character_shorts import png
from test_model_picker_browser import browser as browser  # noqa: PLC0414
from test_single_workspace import video_fixture
from test_studio_structure import image_records
from test_workspace_access_browser import page as page  # noqa: PLC0414

from newsflow.db.models import ImagePost


def test_mixed_work_filters_and_single_preview_do_not_execute_or_change_records(page, app):
    video_fixture(app, '보존할 합성 뉴스 영상')
    _article, post_id = image_records(app)
    buffer = io.BytesIO()
    Image.new('RGB', (1080, 1350), '#17395f').save(buffer, format='JPEG')
    raw = buffer.getvalue()
    with app.state.sessions.begin() as session:
        post = session.get(ImagePost, post_id)
        post.sha256 = hashlib.sha256(raw).hexdigest()
        app.state.image_posts.outputs.mkdir(parents=True, exist_ok=True)
        (app.state.image_posts.outputs / post.filename).write_bytes(raw)
    job_id = app.state.character.create('합성 캐릭터 작업', '1', '1', reference=png())
    job = app.state.character.read(job_id)
    job['state'] = 'submission_unknown'
    app.state.character.save(job)
    original = deepcopy(job)
    page.goto('http://127.0.0.1/')
    expect(page.locator('.workflow-format-links .button')).to_have_count(3)
    expect(page.locator('.dash-recent')).to_contain_text('캐릭터 쇼츠')
    expect(page.locator('.dash-preview video')).to_have_count(1)
    expect(page.locator('.dash-preview img')).to_have_count(0)
    expect(page.locator('.dash-preview')).to_contain_text('보존할 합성 뉴스 영상')
    page.locator('.dash-metric').filter(has_text='진행·검토').click()
    page.wait_for_load_state('networkidle')
    page.locator('[data-studio-work-filter=review]').click()
    expect(page.locator('[data-studio-work-filter=review]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.studio-all-work [data-studio-task]:visible')).to_have_count(1)
    expect(page.locator('.studio-all-work [data-studio-task]:visible')).to_contain_text('최종 확인 필요')
    page.locator('[data-studio-work-filter=attention]').click()
    expect(page.locator('.studio-all-work [data-studio-task]:visible')).to_have_count(1)
    expect(page.locator('.studio-all-work [data-studio-task]:visible')).to_contain_text('캐릭터 쇼츠')
    page.locator('[data-studio-work-filter=saved]').click()
    expect(page.locator('.studio-all-work [data-studio-task]:visible')).to_have_count(1)
    page.locator('[data-studio-work-filter=running]').click()
    expect(page.locator('[data-studio-work-empty]')).to_be_visible()
    assert app.state.character.read(job_id) == original
    with app.state.sessions() as session:
        assert session.get(ImagePost, post_id).caption == '합성 본문'
    assert (app.state.image_posts.outputs / post.filename).read_bytes() == raw


def test_archive_categories_do_not_navigate_to_collection(page):
    page.goto('http://127.0.0.1/')
    page.locator('[data-dash-news-category="경제"]').click()
    expect(page.locator('[data-dash-news-category="경제"]')).to_have_attribute('aria-current', 'true')
    expect(page.locator('[data-dash-news-status]')).to_contain_text('새 수집·AI 호출 없음')
    expect(page).to_have_url('http://127.0.0.1/')
    assert page.locator('[data-dash-news-category]').count() == 9
    expect(page.locator('#quick-production')).to_have_count(0)
