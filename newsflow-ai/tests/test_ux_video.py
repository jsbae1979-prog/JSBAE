"""Focused simplified Video Studio flows; all media and data are temporary fixtures."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import AppSetting, NewsArticle, RenderJob
from newsflow.intelligence.service import IntelligenceService
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import FakeTTS, WindowsTTS


@pytest.fixture
def studio_draft(app, monkeypatch):
    monkeypatch.setattr("newsflow.gui.video_routes.sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [{"name": "Heami", "culture": "ko-KR"}])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: ["supertonic:F1"])
    with app.state.sessions.begin() as session:
        session.add(NewsArticle(
            title="영상 화면 검증용 뉴스", summary="합성 기사입니다.", publisher="합성 출처", source_id=1,
            url="https://example.com/ux-video", canonical_url="https://example.com/ux-video",
        ))
    service = IntelligenceService(app.state.sessions)
    app.state.video.engine = FakeRenderAdapter()
    app.state.video.tts = FakeTTS()
    return service.generate(service.analyze([1]), 30)


def advanced_editing(html):
    return re.search(r'<details[^>]*id="video-advanced-editing"[^>]*>(.*?)</details>', html, re.DOTALL).group(1)


def test_simple_form_keeps_advanced_fields_and_explicit_review(client, studio_draft):
    response = client.get(f"/video?draft_id={studio_draft}")
    assert response.status_code == 200
    html = response.text
    advanced = advanced_editing(html)
    assert not re.search(r'<details[^>]*id="video-advanced-editing"[^>]*\bopen', html)
    for name in ("font_size", "subtitle_y", "images", "asset_permission"):
        assert f'name="{name}"' in advanced
    assert 'id="video-ai-link"' in advanced
    for name in ("duration", "voice", "reviewed", "external_tts_consent"):
        assert f'name="{name}"' in html and f'name="{name}"' not in advanced
    assert 'name="reviewed" value="true" required' in html
    assert 'name="csrf_token"' in html and 'href="https://example.com/ux-video"' in html
    assert "script-src 'self'" in response.headers["content-security-policy"]


@pytest.mark.parametrize("voice", ["Heami", "supertonic:F1", "elevenlabs", "offline-silence"])
def test_stored_preferences_are_reused_without_writes(client, app, studio_draft, voice):
    values = {"voice": voice, "font_size": "56", "subtitle_y": "1280"}
    with app.state.sessions.begin() as session:
        for key, value in values.items():
            session.add(AppSetting(key="video_default_" + key, value=value))
    for _ in range(2):
        html = client.get(f"/video?draft_id={studio_draft}").text
        assert f'<option value="{voice}" selected>' in html
        assert '<option value="56" selected>' in html and '<option value="1280" selected>' in html
        with app.state.sessions() as session:
            assert {key: session.get(AppSetting, "video_default_" + key).value for key in values} == values


def test_unavailable_saved_voice_is_not_replaced_by_silence_or_paid_engine(client, app, studio_draft):
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="video_default_voice", value="Missing Voice"))
    html = client.get(f"/video?draft_id={studio_draft}").text
    assert '<option value="Missing Voice" selected>' in html
    assert 'value="offline-silence" selected' not in html and 'value="elevenlabs" selected' not in html
    assert "저장한 음성을 사용할 수 없습니다" in html
    response = client.post("/video/render", data={
        "csrf_token": csrf(client), "draft_id": studio_draft, "duration": 30,
        "voice": "Missing Voice", "reviewed": "true",
    })
    assert response.status_code == 422
    with app.state.sessions() as session:
        assert session.scalar(select(RenderJob)) is None


def test_render_still_requires_csrf_review_and_preserves_fake_result_boundary(client, app, studio_draft):
    data = {"draft_id": studio_draft, "duration": 30, "voice": "offline-silence"}
    assert client.post("/video/render", data=data).status_code == 403
    data["csrf_token"] = csrf(client)
    assert client.post("/video/render", data=data).status_code == 422
    data["reviewed"] = "true"
    response = client.post("/video/render", data=data, follow_redirects=False)
    assert response.status_code == 303
    app.state.video.future.result(timeout=15)
    html = client.get(response.headers["location"]).text
    assert "실제 MP4가 아니며" in html and '<video class="video-preview"' not in html
    assert 'id="video-output-details"' in html and "합성 출처" in html
