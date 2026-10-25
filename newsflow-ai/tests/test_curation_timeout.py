"""Bounded longer curation wait, with no real clocks, API, CLI or production data."""
import json
from types import SimpleNamespace

import pytest
from conftest import csrf
from curation_wire_fixture import wire_output
from sqlalchemy import select
from test_curation_all import extend_collection
from test_google_news_trends import NOW, CuratorResponse, article, no_external_calls, prepared

from newsflow.db.models import APIRequestReservation, AppSetting, ContentDraft, IntelligenceRun
from newsflow.intelligence import api_providers
from newsflow.intelligence.api_providers import AnthropicProvider
from newsflow.intelligence.curation import (
    CURATION_TIMEOUT_SECONDS,
    curation_output_tokens,
    enrich,
    validate_ranking,
)
from newsflow.intelligence.provider import MAX_TIMEOUT_SECONDS, Options, ProviderTimeoutError

__all__ = ["no_external_calls", "prepared"]
MODEL = "claude-sonnet-4-6"


def test_longer_timeout_is_opt_in_and_still_bounded():
    assert Options().timeout == 20
    assert Options(MODEL, timeout=60).timeout == 60
    assert Options(MODEL, timeout=CURATION_TIMEOUT_SECONDS).timeout == MAX_TIMEOUT_SECONDS == 300
    with pytest.raises(ValueError):
        Options(MODEL, timeout=301)
    with pytest.raises(ValueError):
        Options(MODEL, timeout=0)


@pytest.mark.parametrize("timeout,delay,success", [
    (60, 65, False), (180, 181, False), (300, 181, True), (300, 299, True), (300, 301, False),
])
def test_fake_late_eighty_one_article_response_and_deadline(monkeypatch, timeout, delay, success):
    evidence = enrich({"articles": [{**article(), "id": i} for i in range(1, 82)],
                       "groups": [[i] for i in range(1, 82)]}, None, NOW, top_k=3)
    output = CuratorResponse("claude_api").analyze(evidence, Options())
    raw = json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(wire_output(output))}],
                      "usage": {"input_tokens": 5000, "output_tokens": 4000}}).encode()
    clock, requests = [0.0], []

    class Response:
        def __init__(self):
            self.data = raw

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, size):
            block, self.data = self.data[:size], self.data[size:]
            return block

    class Opener:
        def open(self, request, timeout):
            requests.append((request, timeout))
            clock[0] += delay
            return Response()

    monkeypatch.setattr(api_providers, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr("urllib.request.build_opener", lambda *_: Opener())
    provider = AnthropicProvider(lambda: "fixture-key-not-a-real-secret")
    options = Options(MODEL, timeout=timeout, max_tokens=7000)
    if success:
        result = validate_ranking(provider.analyze(evidence, options), evidence)
        assert len(result["comparisons"]) == 81 and len(result["ranking"]) == 3
        assert provider.last_usage["total_tokens"] == 9000
    else:
        with pytest.raises(ProviderTimeoutError) as caught:
            provider.analyze(evidence, options)
        assert "fixture-key" not in str(caught.value)
        assert provider.last_usage is None
    assert len(requests) == 1 and requests[0][1] == timeout
    body = json.loads(requests[0][0].data)
    assert body["model"] == MODEL and "tools" not in body
    assert len(json.loads(body["messages"][0]["content"])["evidence"]["articles"]) == 81
    assert not provider.last_retried
    assert provider.last_elapsed_ms == delay * 1000


@pytest.mark.parametrize("fail", [False, True])
def test_route_passes_longer_wait_once_and_preserves_unknown(client, app, prepared, fail):
    _, adapter, _mode, _, _ids = prepared
    ctx = extend_collection(app, 81)
    seen = []
    original = adapter.analyze

    def analyze(evidence, options):
        seen.append(options)
        if fail:
            adapter.calls.append("analysis")
            raise ProviderTimeoutError("untrusted provider detail")
        return original(evidence, options)

    adapter.analyze = analyze
    with app.state.sessions() as session:
        settings = {r.key: r.value for r in session.scalars(select(AppSetting))}
    data = {"csrf_token": csrf(client), "consent": "true", "collection_context_id": ctx["run_id"]}
    response = client.post("/news/curation/analyze", data=data)
    assert response.status_code == (422 if fail else 200), response.text
    assert len(seen) == 1 and seen[0].timeout == 300
    assert seen[0].max_tokens == (100_000 if _mode == "claude_api" else 7000)
    assert client.get("/").status_code == 200
    # A changed timeout is not a new request identity, even across a page reload.
    repeated = client.post("/news/curation/analyze", data={**data, "timeout": "180"})
    assert repeated.status_code == (409 if fail else 200)
    assert adapter.calls == ["analysis"] and len(seen) == 1
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        reservation = session.scalar(select(APIRequestReservation))
        assert run.options["timeout"] == 300 and len(run.evidence["articles"]) == 81
        assert run.options["base_max_tokens"] == seen[0].max_tokens
        assert run.options["script_prompt_version"] == "v2"
        assert run.options["max_tokens"] == min(100_000 if _mode == "claude_api" else 9000, seen[0].max_tokens + 400)
        assert reservation.status == ("unknown" if fail else "success")
        assert reservation.bounds["search_calls"] == 0 and reservation.test_only
        assert session.scalar(select(ContentDraft)) is None
        after = {r.key: r.value for r in session.scalars(select(AppSetting))}
        assert all(after[key] == value for key, value in settings.items())
        if fail:
            assert "untrusted provider detail" not in run.message
        else:
            assert len(run.result["ranking"]) == 3


def test_hundred_thousand_ceiling_is_model_specific_and_keeps_other_defaults():
    assert curation_output_tokens("claude_api", MODEL) == 100_000
    assert Options(MODEL, max_tokens=100_000).max_tokens == 100_000
    assert Options(MODEL).max_tokens == Options().max_tokens == 1800
    for mode, model in (("openai", "gpt-4.1-mini"), ("claude_api", "claude-haiku-4-5-20251001"),
                        ("claude_api", "claude-opus-4-6"), ("claude_code", MODEL)):
        assert curation_output_tokens(mode, model) == 7000
    for value in (100_001, True, 100_000.0, "100000"):
        with pytest.raises(ValueError):
            Options(MODEL, max_tokens=value)
    with pytest.raises(ValueError):
        Options("claude-haiku-4-5-20251001", max_tokens=100_000)


def test_real_adapter_sends_requested_ceiling_once_and_records_actual_usage(monkeypatch):
    evidence = enrich({"articles": [article()], "groups": [[1]]}, None, NOW, top_k=3)
    output = wire_output(CuratorResponse("claude_api").analyze(evidence, Options()))
    response = json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(output)}],
                           "usage": {"input_tokens": 1000, "output_tokens": 8500}}).encode()
    calls = []
    adapter = AnthropicProvider(lambda: "fixture-key-only")
    monkeypatch.setattr(adapter, "_open", lambda request, timeout, limit: calls.append(
        (json.loads(request.data), timeout, limit)) or response)
    adapter.analyze(evidence, Options(MODEL, timeout=300, max_tokens=100_000))
    assert len(calls) == 1 and calls[0][0]["max_tokens"] == 100_000
    assert calls[0][1] == 300 and calls[0][2] == api_providers.MAX_RESPONSE_BYTES
    assert "tools" not in calls[0][0] and not adapter.last_retried
    assert adapter.last_usage["completion_tokens"] == 8500
