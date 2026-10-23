"""Simple navigation and home reflect saved settings and actual job snapshots."""

import re

from newsflow.db.models import AppSetting, NewsArticle, NewsSource
from newsflow.intelligence.settings import read_studio_settings, write_studio_settings


def test_workspace_two_destinations_and_two_production_choices(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    primary = re.search(r'<nav aria-label="주 메뉴"[^>]*>(.*?)</nav>', html, re.DOTALL).group(1)
    assert re.findall(r'href="([^"]+)"', primary) == [
        "/", "/news", "/ai", "/videos", "/queue", "/analytics", "/simple-settings"]
    for label in ("대시보드", "뉴스 수집", "AI 대본", "영상 제작", "게시 허브", "성과 분석", "설정"):
        assert label in primary
    assert 'href="/create"' in html and 'class="advanced-nav"' not in html
    settings = client.get("/simple-settings").text
    assert 'id="settings-advanced-tools"' not in settings  # Removed duplicate tool menu stays removed.
    assert 'id="advanced"' in settings
    for destination in ("/schedules", "/operations", "/sources"):
        assert f'href="{destination}"' in settings
    form = re.search(r'<form action="/autopilot/quick-start".*?</form>', html, re.DOTALL).group(0)
    assert 'class="easy-advanced studio-production-options"' in form
    assert re.findall(r'<select[^>]+name="([^"]+)"', form) == [
        "source", "duration", "category", "period", "voice_method", "video_method", "acquisition_policy", "news_usage"]
    assert '<option value="VERIFIED"' not in form
    assert 'name="csrf_token"' in form and 'method="post"' in form
    assert 'name="provider"' not in form and 'name="voice"' not in form
    assert 'name="script_review" value="true" checked' in form
    assert "쇼츠 만들기" in form and "첫 쇼츠가 기다리고 있어요" in html
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
    assert 'value="feeds" selected' in html and 'value="45" selected' in html
    assert read_studio_settings(app.state.sessions)["provider"] == "codex"
    assert "AI 웹 뉴스 조사 BLOCKED" in html
    assert response.context["production"]["policy_states"]["rss"]["supported"] is True
    assert "대본과 원문 확인 후 제작" in html
    assert '<progress ' not in html  # stage labels, not an estimated percentage
    assert "대본 작성" in html
    assert 'href="/?task=fixture-review#workspace-detail"' in html
    assert '<script>alert(' not in html
    assert "최근 뉴스</h2>" not in html  # only production and results on home
