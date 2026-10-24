"""Only injected transports; no service credentials, OAuth, uploads or provider network."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from sqlalchemy import select, update
from test_unified_publishing import (
    arguments,
    environment,  # noqa: F401
    instagram_environment,  # noqa: F401
    save,
)

from newsflow.db.models import PublishEvidence, PublishJob
from newsflow.publishing.extensions import ExtendedPublishingService
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.platforms import (
    REQUIREMENTS,
    FacebookPublisher,
    PlatformBlocked,
    TikTokPublisher,
    upload_url,
)
from newsflow.publishing.service import PublishingError


class Transport:
    def __init__(self, platform):
        self.platform, self.calls, self.fail_at = platform, [], None
        self.waiting = False
        self.creator = {
            "creator_nickname": "합성 크리에이터",
            "privacy_level_options": ["SELF_ONLY"],
            "max_video_post_duration_sec": 60,
            "comment_disabled": False,
            "duet_disabled": True,
            "stitch_disabled": True,
        }

    def request(self, method, url, *, payload=None, stream=None, headers=None):
        self.calls.append((method, url, deepcopy(payload)))
        if self.fail_at == len(self.calls):
            raise TimeoutError("Bearer DO-NOT-LOG synthetic-private-detail")
        if stream:
            assert stream.read()
            return {"success": True}
        if "creator_info" in url:
            return {"data": self.creator, "error": {"code": "ok"}}
        if "/video/init/" in url:
            return {
                "error": {"code": "ok"},
                "data": {
                    "publish_id": "v_pub_file~v2.12345",
                    "upload_url": "https://open-upload.tiktokapis.com/video/?upload_token=DO-NOT-LOG",
                },
            }
        if "/status/fetch/" in url:
            return {
                "error": {"code": "ok"},
                "data": {"status": "PROCESSING_UPLOAD" if self.waiting else "PUBLISH_COMPLETE"},
            }
        if payload and payload.get("upload_phase") == "start":
            return {
                "video_id": "12345",
                "upload_url": "https://rupload.facebook.com/video-upload/v26.0/12345",
            }
        if payload and payload.get("upload_phase") == "finish":
            return {"success": True}
        return {
            "status": {
                "video_status": "processing" if self.waiting else "ready",
                "publishing_phase": {
                    "status": "in_progress" if self.waiting else "completed",
                    "publish_status": "published",
                },
            }
        }


@pytest.fixture
def extended(request):
    env = request.getfixturevalue("environment")
    env.transports, env.extensions = {}, {}
    for platform, kind in (("tiktok", "tiktok_creator"), ("facebook", "facebook_page")):
        account_id = env.service.local.add_account(platform, "합성 " + platform, kind)
        env.accounts[platform] = account_id
        transport = Transport(platform)

        def binding(identifier, *, _account=account_id, _platform=platform):
            return {
                "account_id": _account,
                "platform": _platform,
                "identity": "10001",
                "synthetic": True,
                "tasks": ["CREATE_CONTENT"],
                "scopes": REQUIREMENTS[_platform]["scopes"],
            }

        service = ExtendedPublishingService(
            env.sessions,
            env.service.outputs,
            platform,
            inspector=FakeMediaInspector(),
            synthetic_binding=binding,
            adapter=(TikTokPublisher if platform == "tiktok" else FacebookPublisher)(transport),
        )
        env.transports[platform], env.extensions[platform] = transport, service
    env.service.extensions = env.extensions
    return env


def options(env, cohort):
    return {
        **arguments(env, cohort),
        "extension_options": {
            "facebook": {"public_consent": True},
            "tiktok": {"privacy": "SELF_ONLY", "music_consent": True},
        },
    }


def test_four_platform_delivery_reuses_review_and_durable_no_replay(extended):
    env = extended
    cohort = save(env)
    result = env.service.execute(cohort, **options(env, cohort))
    assert {t["platform"]: t["status"] for t in result["targets"]} == {
        "youtube": "complete",
        "instagram": "complete",
        "tiktok": "simulated",
        "facebook": "simulated",
    }
    calls = {k: list(v.calls) for k, v in env.transports.items()}
    env.service.recover()
    env.service.execute(cohort, **options(env, cohort))
    assert calls == {k: v.calls for k, v in env.transports.items()}
    with env.sessions() as s:
        assert "DO-NOT-LOG" not in str([e.payload for e in s.scalars(select(PublishEvidence))])
        assert {j.platform for j in s.scalars(select(PublishJob))} == set(env.accounts)


@pytest.mark.parametrize("platform", ["tiktok", "facebook"])
@pytest.mark.parametrize("fail_at", [1, 2, 3, 4])
def test_timeout_at_each_network_boundary_never_replays(extended, platform, fail_at):
    env = extended
    env.transports[platform].fail_at = fail_at
    cohort = save(env, accounts={platform: env.accounts[platform]})
    result = env.service.execute(cohort, **options(env, cohort))
    assert result["targets"][0]["status"] == "unknown"
    calls = list(env.transports[platform].calls)
    env.extensions[platform].recover()
    env.service.recover()
    env.service.execute(cohort, **options(env, cohort))
    assert calls == env.transports[platform].calls
    with env.sessions() as s:
        assert "DO-NOT-LOG" not in str([e.payload for e in s.scalars(select(PublishEvidence))])


@pytest.mark.parametrize("platform", ["tiktok", "facebook"])
def test_waiting_continues_with_status_only_never_second_upload(extended, platform):
    env = extended
    transport = env.transports[platform]
    transport.waiting = True
    cohort = save(env, accounts={platform: env.accounts[platform]})
    result = env.service.execute(cohort, **options(env, cohort))
    assert result["targets"][0]["status"] == "waiting"
    before = len(transport.calls)
    transport.waiting = False
    result = env.service.execute(cohort, **options(env, cohort))
    assert result["targets"][0]["status"] == "simulated"
    assert len(transport.calls) == before + 1
    assert "status" in transport.calls[-1][1]


def test_concurrent_submission_has_one_transport_sequence(extended):
    env = extended
    cohort = save(env, accounts={"facebook": env.accounts["facebook"]})
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: env.service.execute(cohort, **options(env, cohort)), range(2)))
    assert len(env.transports["facebook"].calls) == 4
    assert any(r["targets"][0]["status"] == "simulated" for r in results)


@pytest.mark.parametrize("missing", ["consent", "extension_options"])
def test_additional_approvals_before_any_original_platform_call(extended, missing):
    env = extended
    cohort = save(env)
    args = options(env, cohort)
    del args[missing]
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **args)
    assert not env.yt_adapter.calls and not env.ig_adapter.calls
    assert all(not t.calls for t in env.transports.values())


@pytest.mark.parametrize("field", ["content_reviewed", "copyright_confirmed", "sources_confirmed"])
def test_existing_reviews_still_mandatory(extended, field):
    env = extended
    cohort = save(env, **{field: False})
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **options(env, cohort))
    assert all(not t.calls for t in env.transports.values())


def test_cross_account_and_real_credential_injection_blocked(extended):
    env = extended
    service = env.extensions["facebook"]
    original = service.binding
    cohort = save(env, accounts={"facebook": env.accounts["facebook"]})
    target = env.service.get(cohort)["targets"][0]
    for changes in ({"account_id": 999}, {"synthetic": False}, {"platform": "youtube"}, {"scopes": []}):
        service.binding = lambda identifier, changes=changes: {**original(identifier), **changes}
        with pytest.raises(PlatformBlocked):
            service.execute(
                target["draft_id"],
                target["revision"],
                consent=True,
                options={"public_consent": True},
                expected_identity="10001",
            )
        assert not env.transports["facebook"].calls


def test_default_production_adapters_cannot_make_requests():
    with pytest.raises(PlatformBlocked):
        TikTokPublisher().creator()
    with pytest.raises(PlatformBlocked):
        FacebookPublisher().initialize(
            account="1001",
            caption="a",
            size=100,
            duration=30,
            options={"public_consent": True},
            ai_generated=False,
        )


@pytest.mark.parametrize(
    "value",
    [
        "http://open-upload.tiktokapis.com/a",
        "https://open-upload.tiktokapis.com.evil/a",
        "https://user:pw@open-upload.tiktokapis.com/a",
        "https://127.0.0.1/a",
        "https://open-upload.tiktokapis.com:8765/a",
        "https://open-upload.tiktokapis.com/a#secret",
    ],
)
def test_untrusted_upload_urls_rejected(value):
    with pytest.raises(PublishingError):
        upload_url(value, "open-upload.tiktokapis.com")


@pytest.mark.parametrize(
    "bad",
    [
        {"privacy": "PUBLIC_TO_EVERYONE", "music_consent": True},
        {"privacy": "SELF_ONLY"},
        {"privacy": "SELF_ONLY", "music_consent": True, "allow_duet": True},
        {"privacy": "SELF_ONLY", "music_consent": True, "branded": True, "brand_consent": True},
    ],
)
def test_tiktok_fresh_creator_rules_before_init(bad):
    transport = Transport("tiktok")
    with pytest.raises(PublishingError):
        TikTokPublisher(transport).initialize(
            account="1001", caption="합성", size=100, duration=30, options=bad, ai_generated=True
        )
    assert len(transport.calls) == 1 and "creator_info" in transport.calls[0][1]


def test_restart_quarantines_unfinished_extension(extended):
    env = extended
    cohort = save(env, accounts={"facebook": env.accounts["facebook"]})
    env.service.execute(cohort, **options(env, cohort))
    with env.sessions.begin() as s:
        s.execute(update(PublishJob).where(PublishJob.platform == "facebook").values(status="ext_running"))
    before = list(env.transports["facebook"].calls)
    assert env.extensions["facebook"].recover() == 1
    assert env.extensions["facebook"].results()[0]["status"] == "unknown"
    assert before == env.transports["facebook"].calls


def test_channel_rebinding_after_review_stops_all_platform_transmission(extended):
    env = extended
    cohort = save(env)
    service = env.extensions["facebook"]
    original = service.binding
    service.binding = lambda account: {**original(account), "identity": "20002"}
    with pytest.raises(PublishingError, match="계정"):
        env.service.execute(cohort, **options(env, cohort))
    assert not env.yt_adapter.calls and not env.ig_adapter.calls
    assert all(not t.calls for t in env.transports.values())


def test_tiktok_status_keeps_official_public_id_distinct_from_request_id():
    class PublicStatus:
        def request(self, *args, **kwargs):
            return {
                "error": {"code": "ok"},
                "data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": ["123456789"]},
            }

    result = TikTokPublisher(PublicStatus()).check("v_pub_file~v2.12345")
    assert result == {"status": "complete", "remote_id": "123456789"}


def test_facebook_page_task_and_rolling_limit_stop_before_submit(extended):
    from datetime import timedelta

    from newsflow.db.models import utcnow

    env = extended
    cohort = save(env, accounts={"facebook": env.accounts["facebook"]})
    target = env.service.get(cohort)["targets"][0]
    service = env.extensions["facebook"]
    original = service.binding
    service.binding = lambda account: {**original(account), "tasks": []}
    with pytest.raises(PlatformBlocked):
        service.execute(
            target["draft_id"],
            target["revision"],
            consent=True,
            options={"public_consent": True},
            expected_identity="10001",
        )
    service.binding = original
    with env.sessions.begin() as session:
        for i in range(30):
            session.add(
                PublishJob(
                    draft_id=target["draft_id"],
                    platform="facebook",
                    status="unknown",
                    message="합성 기존 요청",
                    idempotency_key=f"synthetic-limit-{i}",
                    created_at=utcnow() - timedelta(hours=1),
                )
            )
    with pytest.raises(PublishingError, match="한도"):
        service.execute(
            target["draft_id"],
            target["revision"],
            consent=True,
            options={"public_consent": True},
            expected_identity="10001",
        )
    assert not env.transports["facebook"].calls
