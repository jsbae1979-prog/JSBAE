"""SerpApi key, bounded wire contract, isolated storage and Trends/Claude integration. Fake only."""
import json
import urllib.error
from copy import deepcopy
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
import test_google_news_trends as curation_tests
from conftest import csrf
from sqlalchemy import select

from newsflow.db.models import (
    APIRequestReservation,
    AppSetting,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
)
from newsflow.intelligence.credentials import FakeCipher
from newsflow.news.curator import Curator
from newsflow.news.rss_adapter import MAX_BYTES
from newsflow.news.serpapi import SerpApiAdapter, SerpApiError, SerpApiKeys, parse_result
from newsflow.news.serpapi_settings import context

no_external_calls = curation_tests.no_external_calls
prepared = curation_tests.prepared
KEY = "a" * 64
RESULT = {"search_metadata": {"status": "Success", "json_endpoint": "https://example.com/?api_key=do-not-save"},
          "news_results": [
              {"title": "solar battery 연구 발표", "link": "https://example.com/solar",
               "source": {"name": "합성 출처 A"}, "iso_date": "2026-10-20T05:00:00Z"},
              {"highlight": {"title": "배터리 연구 계획 공개", "link": "https://example.org/battery",
                             "source": {"name": "합성 출처 B"}, "snippet": "배터리 연구 계획에 대한 합성 설명입니다.",
                             "date": "3 hours ago"},
               "stories": [{"title": "solar battery 연구 발표", "link": "https://example.com/solar",
                            "source": {"name": "합성 출처 A"}}]}]}


class FakeSerpApi:
    test_only = True

    def __init__(self, error=None):
        self.calls, self.error = 0, error

    def search(self):
        self.calls += 1
        if self.error:
            raise self.error
        return parse_result(deepcopy(RESULT))


@pytest.fixture
def setup_serpapi(app, monkeypatch):
    monkeypatch.delenv("NEWSFLOW_SERPAPI_KEY", raising=False)
    keys = SerpApiKeys(app.state.config.data_dir, FakeCipher())
    fake = FakeSerpApi()
    app.state.serpapi_keys, app.state.serpapi_adapter = keys, fake
    return keys, fake


def register(client, key=KEY, approved=True):
    return client.post("/serpapi/settings", data={"csrf_token": csrf(client), "api_key": key,
                                                "approved": str(approved).lower()})


def collect(client, token=None, consent=True):
    return client.post("/news/curation/serpapi", data={"csrf_token": csrf(client),
                       "request_token": token or uuid4().hex, "consent": str(consent).lower()})


def test_settings_register_replace_no_request_plaintext_or_other_setting_loss(client, app, setup_serpapi):
    keys, adapter = setup_serpapi
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="preserve_existing_provider", value="claude_api"))
    text = client.get("/simple-settings").text
    assert "SerpApi" in text and "키 미등록" in text
    assert register(client).status_code == 200
    assert keys.key() == KEY and KEY.encode() not in keys.path.read_bytes()
    text = client.get("/simple-settings").text
    assert "✓ 키 등록됨" in text and "실제 인증·수집 미검증" in text
    assert KEY not in text and 'value="' + KEY not in text
    assert adapter.calls == 0 and context(app.state.sessions, keys)["can_request"]
    generation = context(app.state.sessions, keys)["generation"]
    assert register(client, key="invalid").status_code == 422
    oversized = KEY + "x" * 300
    failure = register(client, key=oversized)
    assert failure.status_code == 422 and oversized not in failure.text
    assert context(app.state.sessions, keys)["generation"] == generation and keys.key() == KEY
    assert register(client, key="b" * 64, approved=False).status_code == 200
    assert not context(app.state.sessions, keys)["can_request"] and keys.key() == "b" * 64
    with app.state.sessions() as session:
        assert session.get(AppSetting, "preserve_existing_provider").value == "claude_api"
        assert all(KEY not in row.value for row in session.scalars(select(AppSetting)))
        assert session.scalar(select(IntelligenceRun)) is None
    assert adapter.calls == 0


def test_parse_nested_news_unknown_summary_date_no_article_download():
    articles, metadata = parse_result(RESULT)
    assert len(articles) == 2 and articles[0].published_at is not None
    assert articles[0].summary == "" and articles[1].published_at is None
    assert metadata["provider_billed_credits"] is None and metadata["summary_missing"] == 1
    assert "do-not-save" not in json.dumps(metadata)


@pytest.mark.parametrize("mutation,code", [
    (lambda d: d.update(error="Invalid API key SECRET"), "auth_failed"),
    (lambda d: d.update(error="Your account has run out of searches SECRET"), "usage_limited"),
    (lambda d: d["search_metadata"].update(status="Processing"), "bad_response"),
    (lambda d: d.update(news_results=[]), "empty"),
    (lambda d: d["news_results"][0].update(link="http://127.0.0.1/private"), "bad_response"),
])
def test_invalid_empty_private_results_safe_and_no_pagination(mutation, code):
    data = deepcopy(RESULT)
    mutation(data)
    with pytest.raises(SerpApiError) as error:
        parse_result(data)
    assert error.value.code == code and "SECRET" not in str(error.value)


def test_fixed_wire_key_location_tls_redirect_policy_and_safe_response(setup_serpapi, monkeypatch):
    keys, _ = setup_serpapi
    keys.save(KEY)
    adapter = SerpApiAdapter(keys)
    calls = []

    def response(request, timeout):
        calls.append(request)
        params = parse_qs(urlsplit(request.full_url).query)
        assert urlsplit(request.full_url).hostname == "serpapi.com"
        assert params == {"engine": ["google_news"], "hl": ["ko"], "gl": ["kr"], "api_key": [KEY],
                          "output": ["json"], "no_cache": ["false"]}
        assert "async" not in params and 1 <= timeout <= 60
        return json.dumps(RESULT).encode()

    monkeypatch.setattr(adapter, "_open", response)
    assert len(adapter.search()[0]) == 2 and len(calls) == 1
    monkeypatch.setattr(adapter, "_open", lambda *_: json.dumps({"error": KEY}).encode())
    with pytest.raises(SerpApiError) as error:
        adapter.search()
    assert KEY not in str(error.value)


@pytest.mark.parametrize("error,code", [(TimeoutError(), "timeout_unknown"),
                                        (urllib.error.URLError("secret"), "network_unknown"),
                                        (urllib.error.HTTPError("https://secret", 429, "secret", {}, None), "usage_limited"),
                                        (urllib.error.HTTPError("https://secret", 401, "secret", {}, None), "auth_failed")])
def test_transport_never_retries_or_echoes_url(setup_serpapi, monkeypatch, error, code):
    keys, _ = setup_serpapi
    keys.save(KEY)
    adapter, calls = SerpApiAdapter(keys), []

    def fail(*_):
        calls.append(1)
        raise error

    monkeypatch.setattr(adapter, "_open", fail)
    with pytest.raises(SerpApiError) as caught:
        adapter.search()
    assert caught.value.code == code and "secret" not in str(caught.value)
    assert calls == [1]


def test_response_size_bounded(setup_serpapi, monkeypatch):
    keys, _ = setup_serpapi
    keys.save(KEY)
    adapter = SerpApiAdapter(keys)
    monkeypatch.setattr(adapter, "_open", lambda *_: b" " * (MAX_BYTES + 1))
    with pytest.raises(SerpApiError):
        adapter.search()


def test_consent_registration_and_saved_usage_approval_are_all_required(client, app, setup_serpapi):
    _, adapter = setup_serpapi
    assert collect(client).status_code == 422
    assert register(client, approved=False).status_code == 200
    assert collect(client).status_code == 422
    assert register(client).status_code == 200
    assert collect(client, consent=False).status_code == 422
    assert adapter.calls == 0
    with app.state.sessions() as session:
        assert session.scalar(select(IntelligenceRun)) is None


def test_serpapi_trends_claude_reuses_news_keeps_sources_and_review(client, app, fake, prepared, setup_serpapi):
    _, ai, _, _, _ = prepared
    _keys, adapter = setup_serpapi
    assert register(client).status_code == 200
    rss_calls = list(fake.calls)
    token = uuid4().hex
    assert collect(client, token).status_code == 200
    assert collect(client, token).status_code == 200
    assert adapter.calls == 1 and fake.calls == rss_calls  # Fresh Trends snapshot reused, never Google RSS.
    ctx = Curator(app.state.coordinator).context()
    assert ctx["ready"] and ctx["collection"]["duplicates"] == 2
    assert client.post("/news/curation/analyze", data={"csrf_token": csrf(client), "collection_context_id": ctx["run_id"],
                                                      "consent": "true"}).status_code == 200
    with app.state.sessions() as session:
        analysis = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == "analysis"))
        analysis_id = analysis.id
        assert all(a["search_provenance"]["provider"] == "serpapi" for a in analysis.evidence["articles"])
        assert all("SerpApi" in a["search_provenance"]["summary_kind"] for a in analysis.evidence["articles"])
    assert client.post("/news/curation/generate", data={"csrf_token": csrf(client), "analysis_id": analysis_id,
                                                       "rank": 1, "duration": 30, "consent": "true"}).status_code == 200
    with app.state.sessions() as session:
        draft = session.scalar(select(ContentDraft))
        assert draft.review_status == "review_required" and draft.duration == 30
        assert all("원문 RSS 요약" not in n["message"] for n in draft.review_notes)
        assert all(a["sources"] for a in draft.sources["articles"])
        assert session.scalar(select(NewsSource).where(NewsSource.url == "https://serpapi.com/google-news-api")).enabled is False
        assert all(KEY not in json.dumps(r.result) and KEY not in json.dumps(r.evidence)
                   for r in session.scalars(select(IntelligenceRun)))
        assert len(list(session.scalars(select(APIRequestReservation)))) == 2
    assert adapter.calls == 1 and ai.calls == ["analysis", "script"]
    assert "Fake 검증 기록" in client.get("/simple-settings#serpapi").text


@pytest.mark.parametrize("code", ["auth_failed", "usage_limited", "timeout_unknown"])
def test_failed_request_and_unknown_retained_no_replay_or_fallback(client, app, fake, setup_serpapi, code):
    keys, adapter = setup_serpapi
    register(client)
    adapter.error = SerpApiError(code)
    token = uuid4().hex
    assert collect(client, token).status_code == 422
    assert collect(client, token).status_code == 422
    assert adapter.calls == 1 and fake.calls == []
    with app.state.sessions() as session:
        run = session.scalar(select(IntelligenceRun))
        assert run.status == ("unknown" if code == "timeout_unknown" else "failed")
        assert run.result["error_code"] == code and run.result["provider_billed_credits"] is None
        assert session.scalar(select(NewsArticle)) is None
    state = context(app.state.sessions, keys)
    assert state["last"]["code"] == code
    text = client.get("/simple-settings").text
    assert ("인증 실패" if code == "auth_failed" else "크레딧 확인 필요" if code == "usage_limited" else "결과를 확인하지 못했습니다") in text
    register(client, key="c" * 64)
    assert context(app.state.sessions, keys)["last"] is None


def test_csrf_cross_origin_key_save_and_search_guards(client, setup_serpapi):
    _, adapter = setup_serpapi
    assert client.post("/serpapi/settings", data={"api_key": KEY}).status_code == 403
    assert client.post("/news/curation/serpapi", data={"request_token": uuid4().hex}).status_code == 403
    assert client.post("/serpapi/settings", data={"csrf_token": csrf(client), "api_key": KEY},
                       headers={"Origin": "https://attacker.example.com"}).status_code == 403
    assert adapter.calls == 0
