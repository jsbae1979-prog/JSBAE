"""Scoped new-card acknowledgement; no real API or operating DB."""
import copy
import re

import pytest
import test_claude_feed_cards as cards
from conftest import csrf
from sqlalchemy import select
from test_api_settings import configured

from newsflow.db.models import APIRequestReservation, AuditLog, NewsArticle

prepared = cards.prepared
deny_external = cards.deny_external


def unknown(service, name="old:timeout"):
    item = service.budget.reserve(provider="claude_api", request_id=name, kind="analysis",
        model=cards.MODEL, max_output_tokens=2000, key_store=service.keys)
    service.budget.finish(item.id, status="unknown")
    return item.id


def snapshot(service, identifier):
    with service.sessions() as session:
        row = session.get(APIRequestReservation, identifier)
        return {c.name: copy.deepcopy(getattr(row, c.name)) for c in row.__table__.columns}


def test_explicit_scoped_consent_preserves_unknown_and_never_repeats(prepared):
    service, news = prepared
    old = unknown(service)
    before = snapshot(service, old)
    state = service.readiness(news)
    assert not state["ready"] and state["unknown_review"]["ready"]
    assert not service.adapter.calls
    token = state["unknown_review"]["token"]
    for args in ({}, {"review_token": token}, {"review_consent": True}):
        blocked = cards.call(service, news, **args)
        assert service.get(blocked).status == "blocked"
    assert not service.adapter.calls
    result = cards.call(service, news, review_token=token, review_consent=True)
    assert service.get(result).status == "success"
    assert cards.call(service, news, review_token=token, review_consent=True) == result
    assert len(service.adapter.calls) == 1 and snapshot(service, old) == before
    with service.sessions() as session:
        logs = list(session.scalars(select(AuditLog).where(AuditLog.event == "api_feed_card_once_ack")))
        assert len(logs) == 1 and "new_feed_card_once" in logs[0].message
    # Neither search nor unrelated scripts inherit the card acknowledgement.
    assert not service.budget.readiness("claude_api", service.keys, "search")["ready"]
    assert not service.budget.readiness("claude_api", service.keys, "script")["ready"]


@pytest.mark.parametrize("change", ["source", "record", "token", "approval", "monthly", "pending"])
def test_stale_or_unapproved_card_review_cannot_dispatch(prepared, change):
    service, news = prepared
    old = unknown(service)
    token = service.readiness(news)["unknown_review"]["token"]
    if change == "source":
        with service.sessions.begin() as session:
            session.get(NewsArticle, news).summary = "변경된 합성 뉴스 자료입니다."
    elif change == "record":
        with service.sessions.begin() as session:
            session.get(APIRequestReservation, old).reserved_usd = "9.165"
    elif change == "token":
        token = "a" * 64
    elif change == "approval":
        configured(service.sessions, approved=False)
    elif change == "monthly":
        configured(service.sessions, monthly_limit_usd="1")
        with service.sessions.begin() as session:
            session.get(APIRequestReservation, old).estimated_usd = "2"
    else:
        with service.sessions.begin() as session:
            session.get(APIRequestReservation, old).status = "reserved"
    result = cards.call(service, news, review_token=token, review_consent=True)
    assert service.get(result).status == "blocked" and not service.adapter.calls
    with service.sessions() as session:
        assert not list(session.scalars(select(AuditLog).where(AuditLog.event == "api_feed_card_once_ack")))


def test_timeout_after_acknowledgement_never_resends(prepared):
    service, news = prepared
    old = unknown(service)
    before = snapshot(service, old)
    token = service.readiness(news)["unknown_review"]["token"]
    service.adapter.failure = TimeoutError()
    result = cards.call(service, news, review_token=token, review_consent=True)
    assert service.get(result).status == "unknown"
    assert cards.call(service, news, review_token=token, review_consent=True) == result
    assert len(service.adapter.calls) == 1 and snapshot(service, old) == before


def test_form_get_has_unchecked_review_and_csrf_protection(client, prepared):
    service, news = prepared
    old = unknown(service)
    before = snapshot(service, old)
    response = client.get(f"/image-posts?article_id={news}")
    assert response.status_code == 200
    form = re.search(r'<form[^>]+action="/image-posts/claude-card"[^>]*>(.*?)</form>', response.text, re.DOTALL)[1]
    checkbox = re.search(r'<input[^>]+name="review_consent"[^>]*>', form)[0]
    assert "checked" not in checkbox and "required" in checkbox
    token = re.search(r'name="review_token" value="([a-f0-9]{64})"', form)[1]
    assert "disabled" not in re.search(r'<button[^>]+type="submit"[^>]*>', form)[0]
    assert snapshot(service, old) == before and not service.adapter.calls
    body = {"article_id": news, "model": cards.MODEL, "consent": "true",
            "review_token": token, "review_consent": "true"}
    assert client.post("/image-posts/claude-card", data=body).status_code == 403
    response = client.post("/image-posts/claude-card", data={**body, "csrf_token": csrf(client)})
    assert response.status_code == 200 and len(service.adapter.calls) == 1
    assert snapshot(service, old) == before
