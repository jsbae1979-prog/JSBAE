"""Preserve the operating workspace while connecting the final production contracts. Fake data only."""
import pytest
from sqlalchemy import select

from newsflow.db.models import AppSetting, IntelligenceRun, NewsArticle


@pytest.mark.parametrize("path", ["/", "/news", "/ai", "/video", "/queue", "/analytics", "/simple-settings",
                                 "/sources", "/video/tts", "/image-posts", "/video-ai-settings"])
def test_existing_workspace_is_accessible_without_provider_requests(client, app, path):
    with app.state.sessions() as session:
        before = list(session.scalars(select(IntelligenceRun.id)))
        settings = {row.key: row.value for row in session.scalars(select(AppSetting))}
        articles = list(session.scalars(select(NewsArticle.id)))
    response = client.get(path)
    assert response.status_code == 200
    assert "<h1" in response.text
    with app.state.sessions() as session:
        assert list(session.scalars(select(IntelligenceRun.id))) == before
        assert {row.key: row.value for row in session.scalars(select(AppSetting))} == settings
        assert list(session.scalars(select(NewsArticle.id))) == articles


def test_new_create_screen_exposes_review_choice_and_keeps_media_types(client):
    text = client.get("/create").text
    assert 'name="script_review" value="true" form="quick-production" checked' in text
    assert 'name="production_options_version" value="2"' in text
    dashboard = client.get("/").text
    assert '오늘의 뉴스를,' in dashboard and '다음 영상으로.' in dashboard
    assert 'href="/image-posts"' in dashboard and '쇼츠 영상' in dashboard
    assert '보관 기사 검색' in dashboard


def test_pricing_and_single_image_delivery_are_both_connected(app):
    assert app.state.video_ai.model_pricing is not None
    assert app.state.image_posts.delivery is not None
    assert app.state.image_posts.generation is app.state.image_generation
    assert app.state.image_posts.cards is app.state.claude_cards
    assert app.state.image_generation.cards is app.state.claude_cards
    routes = app.openapi()['paths']
    assert '/instagram/image-delivery-config' in routes
    assert '/video/ai/plans/{plan_id}/voice-consent' in routes
