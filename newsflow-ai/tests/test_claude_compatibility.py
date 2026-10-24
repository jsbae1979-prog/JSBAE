"""Boundary checks for the preserved local Claude implementation on the new base."""
import json
import urllib.error
from io import BytesIO

from conftest import csrf
from sqlalchemy import select
from test_claude_feed_cards import MODEL
from test_full_image_pipeline import FakePlanner, pipeline, plan

from newsflow.db.models import ImagePost
from newsflow.publishing.claude_cards import ClaudeCardAdapter

__all__ = ["pipeline"]


def test_real_adapter_http_rejection_is_finite_and_never_replayed(pipeline, monkeypatch):
    cards, images, article = pipeline
    adapter = ClaudeCardAdapter(cards.keys.key)
    attempts = []

    def rejected(request, timeout, limit):
        attempts.append(request)
        body = {"error": {"type": "invalid_request_error",
                          "message": "Invalid JSON schema: SECRET_REMOTE_VALUE schema"}}
        raise urllib.error.HTTPError(request.full_url, 400, "SECRET_REASON", {},
                                     BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr(adapter, "_open", rejected)
    cards.adapter = adapter
    identifier = plan(cards, article)
    run = cards.get(identifier)
    assert run.status == "unknown"
    assert run.result["failure_reason"] == "request_rejected"
    assert run.result["http_status"] == 400
    assert run.result["request_issue"] == "schema_invalid"
    assert "SECRET" not in json.dumps(run.result) + run.message
    assert plan(cards, article) == identifier and len(attempts) == 1
    assert not images.adapter.calls


def test_plan_and_failed_image_never_offer_a_local_template_fallback(client, pipeline):
    cards, images, article = pipeline
    cards.adapter = FakePlanner()
    identifier = plan(cards, article)
    url = f"/image-posts?article_id={article}&card_id={identifier}"
    for _ in range(2):
        page = client.get(url)
        assert page.status_code == 200
        assert 'action="/image-posts/generate-card-image"' in page.text
        assert 'action="/image-posts/create"' not in page.text
    assert len(cards.adapter.calls) == 1 and not images.adapter.calls
    images.adapter.failure = TimeoutError("SECRET_TIMEOUT")
    body = {"article_id": article, "card_id": identifier, "consent": "true",
            "plan_reviewed": "true", "csrf_token": csrf(client)}
    for _ in range(2):
        page = client.post("/image-posts/generate-card-image", data=body)
        assert page.status_code == 200
        assert 'action="/image-posts/create"' not in page.text
    assert len(images.adapter.calls) == 1 and cards.get(identifier).options["model"] == MODEL
    with cards.sessions() as session:
        assert not list(session.scalars(select(ImagePost)))
