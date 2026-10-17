"""A single approval coordinates the existing platform services with Fake transports."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from test_instagram_live import environment as instagram_environment  # noqa: F401 - pytest fixture reuse
from test_live_publishing import Adapter as YouTubeAdapter
from test_live_publishing import Connections as YouTubeConnections

from newsflow.db.models import PublishDraft, PublishEvidence, PublishJob
from newsflow.oauth.instagram import InstagramConnectionError
from newsflow.publishing.instagram import InstagramUploadError
from newsflow.publishing.live import LivePublishingService
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.service import ConflictError, PublishingError
from newsflow.publishing.unified import UnifiedPublishingService
from newsflow.publishing.youtube import YouTubeUploadError


@pytest.fixture
def environment(request):
    instagram, sessions, original_draft, path, ig_connections, ig_adapter = request.getfixturevalue("instagram_environment")
    yt_connections, yt_adapter = YouTubeConnections(), YouTubeAdapter()
    youtube = LivePublishingService(sessions, instagram.outputs, yt_connections,
                                    FakeMediaInspector(), lambda: yt_adapter)
    with sessions() as session:
        draft = session.get(PublishDraft, original_draft)
        render_id, ig_account = draft.render_job_id, draft.account_id
    yt_account = youtube.local.add_account("youtube", "합성 YouTube 채널", "youtube_channel")
    service = UnifiedPublishingService(sessions, instagram.outputs, youtube, instagram, FakeMediaInspector())
    return SimpleNamespace(service=service, sessions=sessions, render_id=render_id, path=path,
                           accounts={"youtube": yt_account, "instagram": ig_account},
                           yt_connections=yt_connections, yt_adapter=yt_adapter,
                           ig_connections=ig_connections, ig_adapter=ig_adapter)


def save(env, *, accounts=None, **changes):
    fields = {"title": "통합 게시 검토", "description": "확보한 자료의 범위에서 제작했습니다.", "hashtags": "뉴스",
              "content_reviewed": True, "copyright_confirmed": True, "sources_confirmed": True,
              "ai_disclosure": "not_required", **changes}
    return env.service.save_review(env.render_id, accounts or env.accounts, **fields)


def arguments(env, cohort):
    return {"consent": True, "approval_token": env.service.get(cohort)["approval_token"],
            "privacy": "private", "made_for_kids": False, "instagram_public_consent": True}


def test_one_review_dispatches_both_existing_services_and_preserves_independent_results(environment):
    env = environment
    cohort = save(env)
    review = env.service.get(cohort)
    assert review["reviewed"] and review["can_execute"] and not review["locked"]
    assert review["metadata"]["hashtags"] == ["뉴스"]
    result = env.service.execute(cohort, **arguments(env, cohort))
    assert {row["platform"]: row["status"] for row in result["results"]} == {"youtube": "complete", "instagram": "complete"}
    assert all(row["url"].startswith("https://") for row in result["results"])
    assert result["locked"] and not result["can_execute"]
    assert len(env.yt_adapter.calls) == 1
    assert env.ig_adapter.calls == ["create", "upload", "status", "publish", "result"]
    with env.sessions() as session:
        jobs = list(session.scalars(select(PublishJob)))
        assert len(jobs) == 2 and jobs[0].draft_id != jobs[1].draft_id
        assert {job.platform for job in jobs} == {"youtube", "instagram"}
        evidence = list(session.scalars(select(PublishEvidence)))
        assert all("nf-synthetic-never-sent" not in str(item.payload) for item in evidence)


@pytest.mark.parametrize("missing", ["consent", "approval_token", "made_for_kids", "instagram_public_consent"])
def test_all_selected_platform_approvals_are_required_before_any_external_request(environment, missing):
    env = environment
    cohort = save(env)
    options = arguments(env, cohort)
    del options[missing]
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **options)
    assert env.yt_connections.calls == env.ig_connections.calls == []
    assert env.yt_adapter.calls == env.ig_adapter.calls == []


def test_public_youtube_requires_separate_consent_before_either_platform(environment):
    env = environment
    cohort = save(env)
    options = {**arguments(env, cohort), "privacy": "public"}
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **options)
    assert env.yt_adapter.calls == env.ig_adapter.calls == []


@pytest.mark.parametrize("field", ["content_reviewed", "copyright_confirmed", "sources_confirmed"])
def test_incomplete_review_can_be_saved_but_cannot_execute(environment, field):
    env = environment
    cohort = save(env, **{field: False})
    review = env.service.get(cohort)
    assert not review["reviewed"] and not review["can_execute"] and review["checks"]
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **arguments(env, cohort))
    assert env.yt_adapter.calls == env.ig_adapter.calls == []


@pytest.mark.parametrize("platform", ["youtube", "instagram"])
def test_only_selected_platform_is_dispatched(environment, platform):
    env = environment
    cohort = save(env, accounts={platform: env.accounts[platform]})
    options = arguments(env, cohort)
    if platform == "youtube":
        options["instagram_public_consent"] = False
    else:
        options["made_for_kids"] = None
    result = env.service.execute(cohort, **options)
    assert result["platforms"] == [platform]
    assert bool(env.yt_adapter.calls) is (platform == "youtube")
    assert bool(env.ig_adapter.calls) is (platform == "instagram")


@pytest.mark.parametrize("platform", ["youtube", "instagram"])
def test_one_platform_failure_does_not_cancel_other_or_replay_success(environment, platform):
    env = environment
    cohort = save(env)
    if platform == "youtube":
        env.yt_adapter.outcome = YouTubeUploadError("permission")
    else:
        env.ig_adapter.failure["upload"] = InstagramUploadError("permission")
    result = env.service.execute(cohort, **arguments(env, cohort))
    states = {row["platform"]: row["status"] for row in result["results"]}
    assert states[platform] == "failed"
    assert states["instagram" if platform == "youtube" else "youtube"] == "complete"
    before = len(env.yt_adapter.calls), list(env.ig_adapter.calls)
    env.service.execute(cohort, **arguments(env, cohort))
    assert (len(env.yt_adapter.calls), env.ig_adapter.calls) == before


def test_instagram_processing_waits_for_next_explicit_click_without_replaying_youtube(environment):
    env = environment
    env.ig_adapter.processing = "IN_PROGRESS"
    cohort = save(env)
    result = env.service.execute(cohort, **arguments(env, cohort))
    assert [row["status"] for row in result["results"]] == ["complete", "waiting"]
    assert result["can_execute"]
    assert env.ig_adapter.calls == ["create", "upload", "status"]
    before = len(env.yt_connections.calls), len(env.yt_adapter.calls), list(env.ig_adapter.calls)
    for _ in range(2):
        env.service.get(cohort)
        env.service.for_video(env.render_id)
    assert (len(env.yt_connections.calls), len(env.yt_adapter.calls), env.ig_adapter.calls) == before
    env.ig_adapter.processing = "FINISHED"
    restarted = UnifiedPublishingService(env.sessions, env.service.outputs, env.service.youtube,
                                         env.service.instagram, FakeMediaInspector())
    assert restarted.recover() == 0
    result = restarted.execute(cohort, **arguments(env, cohort))
    assert all(row["status"] == "complete" for row in result["results"])
    assert len(env.yt_connections.calls) == len(env.yt_adapter.calls) == 1
    assert env.ig_adapter.calls == ["create", "upload", "status", "status", "publish", "result"]


def test_authentication_blocked_platform_is_not_retried_and_other_can_succeed(environment):
    env = environment
    def blocked(*_args, **_kwargs):
        raise InstagramConnectionError("auth_relay_required")
    env.ig_connections.access_for_upload = blocked
    cohort = save(env)
    result = env.service.execute(cohort, **arguments(env, cohort))
    assert [row["status"] for row in result["results"]] == ["complete", "blocked"]
    assert result["results"][1]["error_code"] == "auth_relay_required"
    env.service.execute(cohort, **arguments(env, cohort))
    assert len(env.yt_adapter.calls) == 1 and env.ig_adapter.calls == []


def test_instagram_continuation_does_not_require_completed_youtube_decisions_again(environment):
    env = environment
    env.ig_adapter.processing = "IN_PROGRESS"
    cohort = save(env)
    first = {**arguments(env, cohort), "privacy": "public", "youtube_public_consent": True}
    env.service.execute(cohort, **first)
    assert [row["status"] for row in env.service.get(cohort)["results"]] == ["complete", "waiting"]
    before = len(env.yt_connections.calls), len(env.yt_adapter.calls)
    env.ig_adapter.processing = "FINISHED"
    result = env.service.execute(cohort, consent=True, approval_token=arguments(env, cohort)["approval_token"],
                                 made_for_kids=None, youtube_public_consent=False, instagram_public_consent=True)
    assert all(row["status"] == "complete" for row in result["results"])
    assert (len(env.yt_connections.calls), len(env.yt_adapter.calls)) == before
    assert env.ig_adapter.calls == ["create", "upload", "status", "status", "publish", "result"]


@pytest.mark.parametrize("change", ["file", "revision", "metadata", "token"])
def test_changed_review_or_file_cannot_execute(environment, change):
    env = environment
    cohort = save(env)
    options = arguments(env, cohort)
    if change == "file":
        env.path.write_bytes(b"changed")
    elif change == "token":
        options["approval_token"] = "0" * 64
    else:
        draft_id = env.service.get(cohort)["targets"][0]["draft_id"]
        with env.sessions.begin() as session:
            draft = session.get(PublishDraft, draft_id)
            if change == "revision":
                draft.revision += 1
            else:
                draft.title = "직접 변경된 제목"
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **options)
    assert env.yt_adapter.calls == env.ig_adapter.calls == []


def test_repeated_review_save_keeps_drafts_and_failed_result(environment):
    env = environment
    cohort = save(env)
    env.ig_adapter.failure["upload"] = InstagramUploadError("unknown")
    env.service.execute(cohort, **arguments(env, cohort))
    with env.sessions() as session:
        before = session.scalar(select(func.count()).select_from(PublishDraft))
    assert save(env) == cohort
    with env.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublishDraft)) == before
    assert env.service.get(cohort)["results"][1]["status"] == "unknown"
    with pytest.raises(ConflictError):
        save(env, title="전송 후 바뀐 제목")


def test_adding_other_platform_reuses_completed_platform_result_without_authentication(environment):
    env = environment
    first = save(env, accounts={"youtube": env.accounts["youtube"]})
    env.service.execute(first, **arguments(env, first))
    both = save(env)
    assert both != first
    env.service.execute(both, **arguments(env, both))
    assert len(env.yt_connections.calls) == len(env.yt_adapter.calls) == 1
    assert env.ig_adapter.calls.count("publish") == 1
    assert all(row["status"] == "complete" for row in env.service.get(both)["results"])


def test_changed_unstarted_draft_can_be_reviewed_without_reusing_stale_snapshot(environment):
    env = environment
    old = save(env)
    with env.sessions.begin() as session:
        draft = session.get(PublishDraft, env.service.get(old)["targets"][0]["draft_id"])
        draft.revision += 1
    new = save(env)
    assert new != old and env.service.get(new)["reviewed"]
    env.service.execute(new, **arguments(env, new))
    assert len(env.yt_adapter.calls) == 1


def test_new_review_invalidates_old_unstarted_caption_approval(environment):
    env = environment
    old = save(env)
    current = save(env, title="새 검토 제목")
    assert current != old and not env.service.get(old)["can_execute"]
    env.service.execute(old, **arguments(env, old))
    assert env.yt_adapter.calls == env.ig_adapter.calls == []
    env.service.execute(current, **arguments(env, current))
    assert len(env.yt_adapter.calls) == 1
    assert env.yt_adapter.calls[0][1]["title"] == "새 검토 제목"


def test_concurrent_buttons_do_not_duplicate_either_platform(environment):
    env = environment
    cohort = save(env)
    options = arguments(env, cohort)
    with ThreadPoolExecutor(max_workers=2) as workers:
        list(workers.map(lambda _: env.service.execute(cohort, **options), range(2)))
    assert len(env.yt_adapter.calls) == 1 and env.ig_adapter.calls.count("create") == 1
    assert env.ig_adapter.calls.count("publish") == 1


def test_restart_quarantines_wrapper_intent_without_touching_platform_history(environment):
    env = environment
    cohort = save(env)
    target = env.service._claim(cohort, "youtube", {"consent": True})
    assert target is not None
    assert env.service.recover() == 1 and env.service.recover() == 0
    env.service.execute(cohort, **arguments(env, cohort))
    assert env.yt_adapter.calls == [] and env.ig_adapter.calls.count("publish") == 1
    assert env.service.get(cohort)["results"][0]["status"] == "unknown"


def test_restart_recovers_committed_success_and_ready_container_without_any_network(environment):
    env = environment
    cohort = save(env)
    yt = env.service._claim(cohort, "youtube", {"consent": True})
    env.service.youtube.execute(yt["draft_id"], yt["revision"], consent=True)
    ig = env.service._claim(cohort, "instagram", {"consent": True})
    job = env.service.instagram.prepare(ig["draft_id"], ig["revision"], consent=True)
    env.service._finish(cohort, "instagram", job_id=job)
    env.service.instagram.check(job, consent=True)
    before = len(env.yt_connections.calls), len(env.yt_adapter.calls), list(env.ig_adapter.calls)
    assert env.service.recover() == 2
    assert [row["status"] for row in env.service.get(cohort)["results"]] == ["complete", "waiting"]
    assert (len(env.yt_connections.calls), len(env.yt_adapter.calls), env.ig_adapter.calls) == before
    env.service.execute(cohort, **arguments(env, cohort))
    assert len(env.yt_adapter.calls) == 1 and env.ig_adapter.calls.count("create") == 1
    assert env.ig_adapter.calls.count("publish") == 1


def test_invalid_platform_or_account_mapping_does_not_create_review(environment):
    env = environment
    for accounts in ({"wrong": 1}, {"youtube": env.accounts["instagram"]}, {"youtube": True}):
        with pytest.raises(PublishingError):
            save(env, accounts=accounts)
    assert env.service.for_video(env.render_id) is None
