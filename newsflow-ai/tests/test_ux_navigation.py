"""Simple navigation and home reflect saved settings and actual job snapshots."""

import re

from newsflow.db.models import AppSetting, NewsArticle, NewsSource
from newsflow.intelligence.settings import read_studio_settings, write_studio_settings


def test_workspace_two_destinations_and_two_production_choices(client):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    primary = re.search(r'<nav aria-label="주 메뉴"[^>]*>(.*?)</nav>', html, re.DOTALL).group(1)
    assert re.findall(r'href="([^"]+)"', primary) == ["/", "/simple-settings"]
    for label in ("작업실", "설정"):
        assert label in primary
    assert 'class="advanced-nav"' not in html
    settings = client.get("/simple-settings").text
    advanced = re.search(r'<section[^>]*id="advanced"[^>]*>(.*?)</section>', settings, re.DOTALL).group(1)
    for destination in ("/news", "/ai", "/video", "/sources", "/queue", "/publishing"):
        assert f'href="{destination}"' in advanced
    assert 'href="/operations"' in settings  # scheduling group owns this entry
    assert 'href="/ai"' not in html and 'href="/video"' not in html
    form = re.search(r'<form action="/autopilot/quick-start".*?</form>', html, re.DOTALL).group(0)
    assert re.findall(r'<select[^>]+name="([^"]+)"', form) == ["source", "duration"]
    assert 'name="csrf_token"' in form and 'method="post"' in form
    assert 'name="provider"' not in form and 'name="voice"' not in form
    assert "뉴스 영상 제작 시작" in form
    assert "완성한 영상이 여기에 모입니다" in html
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
        "id": "fixture-review", "duration": 45, "status": "waiting_review", "current_stage": "script",
        "message": "대본 확인을 기다립니다.", "progress": 50, "render_job_id": None,
        "ai_mode": "offline", "stage_label": "대본 작성", "updated_at": "2026-10-16T12:00:00Z",
    }])
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'value="feeds" selected' in html and 'value="45" selected' in html
    assert read_studio_settings(app.state.sessions)["provider"] == "codex"
    assert "선택한 AI의 자동 실행은 지원하지 않습니다" in html
    assert "대본과 원문 확인 후 제작" in html
    assert '<progress value="50" max="100"' in html
    assert 'href="/?task=fixture-review#workspace-detail"' in html
    assert '<script>alert(' not in html
    assert "최근 뉴스</h2>" not in html  # only production and results on home
