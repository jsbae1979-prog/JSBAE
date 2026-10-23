"""Card errors keep finite metadata, never provider text, and never replay."""
import hashlib
import json

import pytest
import test_full_image_pipeline as full
from sqlalchemy import select
from test_full_image_pipeline import PLAN, generate, plan

from newsflow.db.models import APIRequestReservation, AppSetting, IntelligenceRun
from newsflow.intelligence.provider import Options, ProviderHTTPResponseError
from newsflow.publishing.claude_cards import ClaudeCardAdapter
from newsflow.publishing.service import PublishingError


@pytest.fixture
def pipeline(app):
    return full.pipeline.__wrapped__(app)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No real network in card diagnostics tests")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", deny)


@pytest.mark.parametrize("document,stage,stop", [
    ({"stop_reason": "max_tokens", "content": []}, "incomplete_response", "max_tokens"),
    ({"stop_reason": "refusal", "content": []}, "incomplete_response", "refusal"),
    ({"stop_reason": "end_turn", "content": [{"type": "thinking", "text": "SECRET"}]},
     "response_text", "end_turn"),
    ({"stop_reason": "end_turn", "content": [{"type": "text", "text": "SECRET invalid JSON"}]},
     "result_json", "end_turn"),
])
def test_wire_stage_retained_without_response_and_no_retry(pipeline, monkeypatch, document, stage, stop):
    cards, images, news = pipeline
    calls = []
    adapter = ClaudeCardAdapter(lambda: "sk-synthetic-key-not-a-real-secret")
    def wire(request, timeout, limit):
        calls.append(request)
        return json.dumps(document | {"usage": {"input_tokens": 20, "output_tokens": 10}}).encode()
    monkeypatch.setattr(adapter, "_open", wire)
    cards.adapter = adapter
    identifier = plan(cards, news)
    run = cards.get(identifier)
    assert run.status == "unknown"
    assert run.result["failure_reason"] == stage and run.result["stop_reason"] == stop
    assert "SECRET" not in json.dumps(run.result) + run.message
    assert plan(cards, news) == identifier and len(calls) == 1
    assert not images.adapter.calls
    with pytest.raises(PublishingError):
        generate(images, news, identifier)
    with cards.sessions() as session:
        reservation = session.scalar(select(APIRequestReservation))
        assert reservation.status == "unknown" and reservation.usage["search_calls"] == 0


@pytest.mark.parametrize("change,expected", [
    ({"body": "가" * 201}, {"field": "body", "rule": "string_too_long"}),
    ({"image_prompt": "가" * 2501}, {"field": "image_prompt", "rule": "string_too_long"}),
    ({"SECRET_EXTRA_FIELD": "SECRET_VALUE"}, {"field": "other", "rule": "extra_forbidden"}),
])
def test_validation_field_rule_only_and_no_silent_truncation(pipeline, change, expected):
    cards, images, news = pipeline
    cards.adapter.change = change
    identifier = plan(cards, news)
    run = cards.get(identifier)
    assert run.status == "unknown" and run.result["failure_reason"] == "card_schema"
    assert expected in run.result["validation"] and "plan" not in run.result
    assert "SECRET" not in json.dumps(run.result) + run.message
    assert plan(cards, news) == identifier and len(cards.adapter.calls) == 1
    assert not images.adapter.calls


@pytest.mark.parametrize("change,stage", [
    ({"source_article_ids": [999]}, "source_binding"),
    ({"source_article_ids": [1, 1]}, "source_binding"),
    ({"image_prompt": "sk-fake-claude-card-not-a-real-key"}, "secret_protection"),
    ({"title": "English", "body": "No Korean"}, "language_validation"),
])
def test_source_secret_language_guards_remain(pipeline, change, stage):
    cards, images, news = pipeline
    cards.adapter.change = change
    identifier = plan(cards, news)
    run = cards.get(identifier)
    assert run.status == "unknown" and run.result["failure_reason"] == stage
    assert "sk-fake" not in json.dumps(run.result)
    assert plan(cards, news) == identifier and not images.adapter.calls


def test_http_rejection_classified_without_remote_text(pipeline, monkeypatch):
    cards, images, news = pipeline
    adapter = ClaudeCardAdapter(lambda: "sk-synthetic-key-not-a-real-secret")
    def rejected(body, options):
        raise ProviderHTTPResponseError(400, "invalid_request_error", "schema_invalid", ["schema"])
    monkeypatch.setattr(adapter, "_post", rejected)
    cards.adapter = adapter
    identifier = plan(cards, news)
    result = cards.get(identifier).result
    assert result["failure_reason"] == "request_rejected" and result["http_status"] == 400
    assert result["request_issue"] == "schema_invalid" and not images.adapter.calls


def test_full_plan_instructions_state_local_bounds_and_single_request(monkeypatch):
    adapter = ClaudeCardAdapter(lambda: "sk-synthetic-key-not-a-real-secret")
    calls = []
    def wire(request, timeout, limit):
        calls.append(json.loads(request.data))
        return json.dumps({"stop_reason": "end_turn", "content": [
            {"type": "text", "text": json.dumps(PLAN)}]}).encode()
    monkeypatch.setattr(adapter, "_open", wire)
    assert adapter.plan_image({"source_article_ids": [1]}, Options(model="claude-sonnet-4-6")) == PLAN
    assert len(calls) == 1
    for bound in ("title 1..60", "body 1..200", "image_prompt 20..2500"):
        assert bound in calls[0]["system"]
    assert "tools" not in calls[0]


@pytest.mark.parametrize("old_status", ["success", "unknown"])
def test_changed_instruction_preserves_v1_claim_and_reuses_success(pipeline, old_status):
    cards, images, news = pipeline
    source = cards.context(news, None, None, None)
    old_key = "claude-card:" + hashlib.sha256(json.dumps(
        ["claude-sonnet-4-6", source, None, "claude-full-image-v1"],
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:38]
    old_result = {"plan": PLAN} if old_status == "success" else {"error_code": "card_response_or_request"}
    with cards.sessions.begin() as session:
        old = IntelligenceRun(kind="feed_card", provider="claude_api", status=old_status,
                              options={"purpose": "full_image"}, evidence=source,
                              result=old_result, message="Preserved synthetic record")
        session.add(old)
        session.flush()
        old_id = old.id
        session.add(AppSetting(key=old_key, value=str(old_id)))
    identifier = plan(cards, news)
    assert plan(cards, news) == identifier
    if old_status == "success":
        assert identifier == old_id and not cards.adapter.calls
    else:
        assert identifier != old_id and len(cards.adapter.calls) == 1
        assert cards.get(identifier).options["prompt_version"] == "claude-full-image-v2"
    with cards.sessions() as session:
        preserved = session.get(IntelligenceRun, old_id)
        assert preserved.status == old_status and preserved.result == old_result
        assert session.get(AppSetting, old_key).value == str(old_id)
    assert not images.adapter.calls
