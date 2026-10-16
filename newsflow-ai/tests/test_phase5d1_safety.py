"""No live credentials or network: billing uncertainty must survive ticks and restarts."""
import json
from decimal import Decimal

import pytest
from conftest import csrf
from sqlalchemy import select
from test_ai_video_service import (
    KEY,
    MODEL,
    PROMPT,
    calls,
    confirm,
    generated_plan,
    ready_studio,
    revision,
    scenes,
    usage,
)
from test_ai_video_service import (
    studio as studio_fixture,
)

from newsflow.db.models import AIVideoScene, VideoAIUsage
from newsflow.video.ai.contracts import ClipRequest, ProviderInputError
from newsflow.video.ai.higgsfield import HiggsfieldProvider
from newsflow.video.ai.model_contracts import CONTRACTS, INCOMPATIBLE, check_model_contract
from newsflow.video.ai.preflight import inspect_setup
from newsflow.video.ai.service import AIVideoCoordinator, AIVideoError
from newsflow.video.ai.settings import LEDGER_INVALID, check_budget, read_settings, save_model

studio = studio_fixture


@pytest.mark.parametrize("response", [408, 429, 500, 503, "disconnect", "bad_accept"])
def test_protocol_submit_only_once_across_repeated_ticks_and_restart(studio, response):
    ready_studio(studio)
    sent = []

    def request(host, method, path, body, headers, timeout):
        sent.append(method)
        if response == "disconnect":
            raise ConnectionError(KEY)
        if response == "bad_accept":
            return 202, b'{}'
        return response, json.dumps({"detail": KEY}).encode()

    provider = HiggsfieldProvider(lambda: KEY, requester=request)
    studio.service.injected = provider
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)
    for _ in range(5):
        studio.service.tick()
    recovered = AIVideoCoordinator(studio.sessions, studio.data_dir, studio.app.state.video, provider=provider)
    recovered.recover()
    for _ in range(4):
        recovered.tick()
    assert sent == ["POST"]
    assert scenes(studio, plan_id)[0].status == "unknown"
    assert [(r.status, r.estimated_cost) for r in usage(studio)] == [("unknown", "0.5")]
    assert studio.service.readiness()["usage"]["spent"] == Decimal("0.5")
    with pytest.raises(AIVideoError):
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", True)
    assert KEY not in scenes(studio, plan_id)[0].message


@pytest.mark.parametrize("restart", [False, True])
def test_phase5d_persisted_requeue_is_quarantined_without_post_or_refund(studio, restart):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)
    with studio.sessions.begin() as session:
        scene = session.get(AIVideoScene, scenes(studio, plan_id)[0].id)
        scene.clip_meta = {"requeues": 1}
    if restart:
        studio.service.recover()
    for _ in range(4):
        studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "unknown"
    assert [r.status for r in usage(studio)] == ["unknown"]
    assert calls(studio.provider, "submit") == []


def test_restart_queries_existing_request_and_preserves_ready_clip(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT, 1: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    first, active, *_ = scenes(studio, plan_id)
    assert first.status == "ready"
    original = studio.service.clip_path(first.id).read_bytes()
    before = len(calls(studio.provider, "submit"))
    restored = AIVideoCoordinator(studio.sessions, studio.data_dir, studio.app.state.video, provider=studio.provider)
    restored.recover()
    restored.tick()
    assert len(calls(studio.provider, "submit")) == before
    assert calls(studio.provider, "status")[-1] == active.request_id
    assert studio.service.clip_path(first.id).read_bytes() == original
    assert scenes(studio, plan_id)[1].request_id == active.request_id


@pytest.mark.parametrize("bad", ["", "NaN", "-1", "secret-not-money"])
def test_corrupt_ledger_blocks_approval_and_worker_without_printing_value(studio, bad):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)
    with studio.sessions.begin() as session:
        session.scalar(select(VideoAIUsage)).estimated_cost = bad
    assert LEDGER_INVALID in studio.service.readiness()["reasons"]
    with studio.sessions() as session:
        from newsflow.video.ai.settings import VideoSettingsError
        with pytest.raises(VideoSettingsError, match="비용 기록"):
            check_budget(session, read_settings(studio.sessions), plan_id, Decimal(0))
    studio.service.tick()
    assert calls(studio.provider, "submit") == []
    assert bad == "" or bad not in scenes(studio, plan_id)[0].message


@pytest.mark.parametrize("path", sorted(INCOMPATIBLE))
def test_known_incompatible_schema_is_rejected_before_credential_or_network(path):
    def forbidden(*args):
        pytest.fail("must not read keys or call network")
    with pytest.raises(ProviderInputError) as exc:
        HiggsfieldProvider(forbidden, requester=forbidden).submit(ClipRequest(path, PROMPT, 5, "720p"))
    assert not exc.value.sent


@pytest.mark.parametrize("path", sorted(CONTRACTS))
def test_dated_model_contract_limits(path):
    seconds, resolutions = CONTRACTS[path]
    assert check_model_contract(path, (seconds[0],), resolutions[0])[0] == "PASS"
    assert check_model_contract(path, (100,), resolutions[0])[0] == "FAIL"
    assert check_model_contract(path, (seconds[0],), "invalid")[0] == "FAIL"


def test_preflight_never_sends_reserves_or_claims_actual_billing(studio, monkeypatch):
    ready_studio(studio)
    monkeypatch.setattr(studio.service.keys, "key", lambda: KEY)
    monkeypatch.setattr(studio.service.keys, "status", lambda: {"configured": True})
    save_model(studio.sessions, path=MODEL, model_id=studio.service.models()[0].id, label="모델",
               price_per_second="0.1", durations="5", resolution="720p", confirmed=True)
    report = inspect_setup(studio.sessions, studio.service.keys)
    assert report["external_api_calls"] == report["new_reservations"] == 0
    assert not report["submit_auto_retry"]
    assert report["actual_service"] == report["actual_billing"] == "NOT VERIFIED"
    assert KEY not in json.dumps(report)
    assert usage(studio) == [] and studio.provider.calls == []
    assert not report["local_ready"]  # unknown user-entered model is not a verified contract


def test_preflight_post_csrf_and_secret_nonexposure(client, monkeypatch):
    service = client.app.state.video_ai
    def broken():
        raise OSError(KEY)
    monkeypatch.setattr(service.keys, "key", broken)
    route = "/video-ai-settings/preflight"
    assert client.post(route).status_code == 403
    token = csrf(client)
    assert client.post(route, data={"csrf_token": token}, headers={"Origin": "https://evil.example"}).status_code == 403
    response = client.post(route, data={"csrf_token": token})
    assert response.status_code == 200 and "외부 API 호출 0건" in response.text
    assert KEY not in response.text and "NOT VERIFIED" in response.text
    assert "default-src" in response.headers["content-security-policy"]
    with client.app.state.sessions() as session:
        assert list(session.scalars(select(VideoAIUsage))) == []
