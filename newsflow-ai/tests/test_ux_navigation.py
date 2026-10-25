"""Simple navigation and home reflect saved settings and actual job snapshots."""

import re

from newsflow.db.models import AppSetting, NewsArticle, NewsSource
from newsflow.intelligence.settings import read_studio_settings, write_studio_settings


def test_workspace_two_destinations_and_two_production_choices(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    primary = re.search(r'<nav aria-label="주 메뉴"[^>]*>(.*?)</nav>', html, re.DOTALL).group(1)
    tools = primary.split('<details class="sidebar-tools"', 1)[1]
    primary = primary.split('<details class="sidebar-tools"', 1)[0]
    assert re.findall(r'href="([^"]+)"', primary) == [
        "/", "/create", "/news", "/?show=tasks", "/videos", "/queue", "/simple-settings"]
    assert all(f'href="{path}"' in tools for path in ("/ai", "/analytics", "/character", "/image-posts", "/voices", "/schedules"))
    for label in ("홈", "쇼츠 만들기", "뉴스 선택", "작업 현황", "내 영상", "게시", "설정"):
        assert label in primary
    assert 'href="/create"' in html and 'class="advanced-nav"' not in html
    settings = client.get("/simple-settings").text
    assert 'id="settings-advanced-tools"' not in settings  # Removed duplicate tool menu stays removed.
    assert 'id="advanced"' in settings
    for destination in ("/schedules", "/operations", "/sources"):
        assert f'href="{destination}"' in settings
    creation = client.get("/create").text
    form = re.search(r'<form action="/autopilot/quick-start".*?</form>', creation, re.DOTALL).group(0)
    assert 'class="studio-job-options"' in form
    assert re.findall(r'<select[^>]+name="([^"]+)"', form) == [
        "duration", "source", "category", "period", "news_usage"]
    for name in ("voice_method", "video_method", "acquisition_policy"):
        assert re.search(rf'<input[^>]*type="hidden"[^>]*name="{name}"', form)
    assert '<option value="VERIFIED"' not in form
    assert 'name="csrf_token"' in form and 'method="post"' in form
    assert 'name="provider"' not in form and 'name="voice"' not in form
    assert re.search(r'<input[^>]*name="script_review"[^>]*form="quick-production"[^>]*checked', creation)
    assert "자동 제작 시작" in form and "첫 쇼츠가 기다리고 있어요" in html
    assert '<progress ' not in html  # no invented progress when no job exists
    assert "script-src 'self'" in response.headers["content-security-policy"]


def test_home_preserves_defaults_and_shows_review_snapshot_safely(client, app, monkeypatch):
    write_studio_settings(app.state.sessions, "codex", "default")
    with app.state.sessions.begin() as session:
        for key, value in (("autopilot_source", "feeds"), ("autopilot_duration", "45")):
            row = session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))
        source = NewsSource(name="Fixture", url="https://example.com/ux-feed", enabled=True)
        session.add(source)
        session.flush()
        for number in range(5):
            session.add(NewsArticle(title=f'<script>alert({number})</script>',
                                    url=f"https://example.com/ux-{number}",
                                    canonical_url=f"https://example.com/ux-{number}",
                                    source_id=source.id, publisher="Fixture", category="IT"))
    monkeypatch.setattr(app.state.autopilot, "list_jobs", lambda *args: [{
        "id": "fixture-review", "duration": 45, "source": "feeds",
        "status": "waiting_review", "current_stage": "script",
        "message": "대본 확인을 기다립니다.", "progress": 50, "render_job_id": None,
        "ai_mode": "offline", "stage_label": "대본 작성", "updated_at": "2026-10-16T12:00:00Z",
    }])
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    creation = client.get("/create").text
    assert 'value="feeds" selected' in creation and 'value="45" selected' in creation
    assert read_studio_settings(app.state.sessions)["provider"] == "codex"
    assert response.context["production"]["policy_states"]["ai_web"]["supported"] is False
    assert response.context["production"]["policy_states"]["rss"]["supported"] is True
    assert 'name="script_review"' in creation and "영상 제작 전에 대본 확인하기" in creation
    assert '<progress ' not in html  # stage labels, not an estimated percentage
    assert "대본 작성" in html
    assert 'href="/?task=fixture-review#workspace-detail"' in html
    assert '<script>alert(' not in html
    assert "최근 뉴스</h2>" not in html  # only production and results on home
