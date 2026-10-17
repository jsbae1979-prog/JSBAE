"""API shorts orchestration uses injected response contracts only; no network or media."""

from copy import deepcopy
from threading import Event
from uuid import uuid4

import pytest
import test_api_news_pipeline
from sqlalchemy import select
from test_api_news_pipeline import MODELS, settled, start

from newsflow.autopilot.contracts import AutopilotConflict, AutopilotError, BackendError
from newsflow.db.models import APIRequestReservation, AppSetting, AutopilotJob, ContentDraft, IntelligenceRun
from newsflow.intelligence.provider import ProviderAuthError, ProviderTimeoutError

api_pipeline = test_api_news_pipeline.api_pipeline


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: pytest.fail("No live HTTP"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI or render processes"))


def context_for(pipeline, identifier):
    coordinator, _, _, sessions, _, _ = pipeline
    with sessions() as session:
        return coordinator._context(session, session.get(AutopilotJob, identifier))


@pytest.mark.parametrize("usage", ["QUICK", "STANDARD"])
@pytest.mark.parametrize("duration", [30, 45, 60])
def test_api_contract_reaches_both_adapters_and_reuses_all_completed_ids(api_pipeline, monkeypatch, usage, duration):
    coordinator, backend, provider, sessions, mode, rss = api_pipeline
    captured = []
    analyze, complete = provider.analyze, provider.complete

    def capture_analysis(evidence, options):
        captured.append(("analysis", deepcopy(evidence), options.model, None))
        return analyze(evidence, options)

    def capture_script(evidence, seconds, options):
        captured.append(("script", deepcopy(evidence), options.model, seconds))
        return complete(evidence, seconds, options)

    monkeypatch.setattr(provider, "analyze", capture_analysis)
    monkeypatch.setattr(provider, "complete", capture_script)
    identifier = start(api_pipeline, duration=duration, news_usage=usage)
    job = settled(api_pipeline, identifier)
    assert job["status"] == "waiting_review", job
    assert job["script_method"] == "api_grounded_v1"
    assert job["analysis_provider"] == job["script_provider"] == mode
    assert [item[0] for item in captured] == ["analysis", "script"]
    for _, evidence, model, _ in captured:
        assert model == MODELS[mode]
        assert evidence["news_usage"] == usage
        assert evidence["script_method"] == "api_grounded_v1"
        assert evidence["news_usage_result"]["verification_status"] == "NOT VERIFIED"
        assert evidence["articles"][0]["sources"]
        assert evidence["news_usage_contract"]
    assert captured[1][3] == duration
    assert captured[1][1]["analysis_result"]
    context = context_for(api_pipeline, identifier)
    expected = {key: context[key] for key in ("search_run_id", "analysis_run_id", "script_run_id", "content_draft_id")}
    # Re-enter each stage with the durable journal, as after interruption or refresh.
    for stage in ("collect", "select", "script"):
        context.update(backend.execute(stage, context, Event(), lambda *_: None, context.__setitem__))
    assert {key: context[key] for key in expected} == expected
    assert coordinator.recover() == 0
    assert provider.calls == ["search", "analysis", "script"] and rss.calls == []
    with sessions() as session:
        reservations = list(session.scalars(select(APIRequestReservation)))
        assert [row.kind for row in reservations] == ["search", "analysis", "script"]
        assert [row.bounds["search_calls"] for row in reservations] == [1, 0, 0]
        assert all(row.test_only and row.status == "success" for row in reservations)
        draft = session.get(ContentDraft, job["content_draft_id"])
        assert draft.review_status == "review_required"
        assert draft.duration == duration


@pytest.mark.parametrize("stage", ["analysis", "script"])
@pytest.mark.parametrize("error", [ProviderTimeoutError, ProviderAuthError])
def test_failed_api_stage_never_retries_or_uses_local_template(api_pipeline, monkeypatch, stage, error):
    coordinator, backend, provider, sessions, mode, rss = api_pipeline
    called_run_ids = []

    def fail(*_):
        provider.calls.append(stage)
        # The operation ID and cost reservation already exist before dispatch.
        with sessions() as session:
            run = session.scalar(select(IntelligenceRun).where(IntelligenceRun.kind == stage))
            called_run_ids.append(run.id)
            assert run.status == "running" and run.options["autopilot_job_id"]
            assert session.scalar(select(APIRequestReservation).where(APIRequestReservation.kind == stage))
        raise error()

    monkeypatch.setattr(provider, "analyze" if stage == "analysis" else "complete", fail)
    identifier = start(api_pipeline, news_usage="STANDARD")
    job = settled(api_pipeline, identifier)
    assert job["status"] == "failed" and job["retryable"] is False
    expected_calls = ["search", "analysis"] + (["script"] if stage == "script" else [])
    assert provider.calls == expected_calls and rss.calls == []
    with pytest.raises(AutopilotConflict):
        coordinator.retry(identifier, job["revision"])
    context = context_for(api_pipeline, identifier)
    assert context[f"{stage}_run_id"] == called_run_ids[0]
    with pytest.raises(BackendError):
        backend.execute("select" if stage == "analysis" else "script", context, Event(), lambda *_: None, lambda *_: None)
    assert provider.calls == expected_calls
    with sessions() as session:
        runs = list(session.scalars(select(IntelligenceRun)))
        assert all(run.provider == mode for run in runs)
        assert session.scalar(select(ContentDraft)) is None
        reservation = session.scalar(select(APIRequestReservation).where(APIRequestReservation.kind == stage))
        assert reservation.status == ("unknown" if error is ProviderTimeoutError else "failed")


def test_new_verified_job_blocks_before_spending_or_search(api_pipeline):
    _, _, provider, sessions, _, rss = api_pipeline
    job = settled(api_pipeline, start(api_pipeline, news_usage="VERIFIED"))
    assert job["status"] == "failed" and job["error_code"] == "news_evidence_required"
    assert provider.calls == rss.calls == []
    with sessions() as session:
        assert session.scalar(select(IntelligenceRun)) is None
        assert session.scalar(select(APIRequestReservation)) is None


def test_unapproved_request_does_not_dispatch_or_change_settings(api_pipeline):
    _, _, provider, sessions, _, rss = api_pipeline
    with sessions() as session:
        before = {row.key: row.value for row in session.scalars(select(AppSetting))}
    with pytest.raises(AutopilotError):
        start(api_pipeline, external_consent=False)
    with sessions() as session:
        assert {row.key: row.value for row in session.scalars(select(AppSetting))} == before
        assert session.scalar(select(APIRequestReservation)) is None
    assert provider.calls == rss.calls == []


def test_review_resume_keeps_selected_voice_and_never_regenerates_script(api_pipeline, monkeypatch):
    coordinator, backend, provider, _, _, _ = api_pipeline
    identifier = start(api_pipeline, news_usage="QUICK", duration=45, voice="elevenlabs:explicit-test-voice")
    job = settled(api_pipeline, identifier)
    rendered = []

    def render(context, *_):
        rendered.append(context)
        raise BackendError(code="render_failed", retryable=False)

    monkeypatch.setattr(backend, "_render", render)
    coordinator.resume(identifier, job["revision"])
    coordinator.future.result(timeout=15)
    assert rendered[0]["voice"] == "elevenlabs:explicit-test-voice"
    assert rendered[0]["duration"] == 45
    assert rendered[0]["content_draft_id"] == job["content_draft_id"]
    assert provider.calls == ["search", "analysis", "script"]


def test_restored_success_cannot_change_provider_or_model(api_pipeline):
    _, backend, provider, _, _, _ = api_pipeline
    identifier = start(api_pipeline)
    job = settled(api_pipeline, identifier)
    context = context_for(api_pipeline, identifier)
    context["ai_model"] = "unapproved-model"
    for stage in ("select", "script"):
        with pytest.raises(BackendError):
            backend.execute(stage, context, Event(), lambda *_: None, lambda *_: None)
    assert job["status"] == "waiting_review"
    assert provider.calls == ["search", "analysis", "script"]


def test_request_identity_cannot_upgrade_legacy_job_to_api(api_pipeline):
    coordinator, _, provider, sessions, _, _ = api_pipeline
    identity = uuid4().hex
    settled(api_pipeline, start(api_pipeline, request_id=identity))
    with sessions.begin() as session:
        row = session.get(AutopilotJob, identity)
        request = dict(row.stage_results["request"])
        request.pop("script_method")
        row.stage_results = {**row.stage_results, "request": request}
    with pytest.raises(AutopilotConflict):
        start(api_pipeline, request_id=identity)
    assert coordinator.recover() == 0
    assert provider.calls == ["search", "analysis", "script"]
