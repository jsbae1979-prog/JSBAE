"""New synthetic OAuth binding into the existing reviewed TikTok publishing engine."""

import pytest
from test_social_platforms import Transport
from test_tiktok_connection import build, connect
from test_unified_publishing import arguments, environment, instagram_environment, save  # noqa: F401

from newsflow.oauth.tiktok_protocol import TikTokError
from newsflow.publishing.extensions import ExtendedPublishingService
from newsflow.publishing.media import FakeMediaInspector
from newsflow.publishing.platforms import TikTokPublisher
from newsflow.publishing.service import PublishingError


@pytest.fixture
def connected(request, tmp_path):
    env = request.getfixturevalue("environment")
    auth = build(env.sessions, tmp_path / "tiktok-credentials")
    account = connect(auth)
    transport = Transport("tiktok")
    service = ExtendedPublishingService(env.sessions, env.service.outputs, "tiktok", inspector=FakeMediaInspector(),
        synthetic_binding=auth.service.synthetic_binding, adapter=TikTokPublisher(transport))
    env.service.extensions = {"tiktok": service}
    env.accounts = {"tiktok": account}
    env.auth, env.transport, env.extension = auth, transport, service
    yield env
    auth.service.close()


def approved(env, cohort):
    return {**arguments(env, cohort), "extension_options": {"tiktok": {"privacy": "SELF_ONLY", "music_consent": True}}}


def test_fake_connection_review_publish_and_restart_no_duplicate(connected):
    env = connected
    cohort = save(env)
    result = env.service.execute(cohort, **approved(env, cohort))
    assert result["targets"][0]["status"] == "simulated"
    calls = list(env.transport.calls)
    assert len(calls) == 4
    env.service.recover()
    env.service.execute(cohort, **approved(env, cohort))
    assert env.transport.calls == calls


@pytest.mark.parametrize("missing", ["consent", "extension_options"])
def test_login_permission_does_not_replace_publish_approval(connected, missing):
    env = connected
    cohort = save(env)
    values = approved(env, cohort)
    values.pop(missing)
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **values)
    assert env.transport.calls == []


def test_revoked_connection_stops_transmission_even_after_review(connected):
    env = connected
    cohort = save(env)
    values = approved(env, cohort)
    env.auth.service.revoke(env.accounts["tiktok"], consent=True)
    with pytest.raises((TikTokError, PublishingError)):
        env.service.execute(cohort, **values)
    assert env.transport.calls == []


def test_unknown_publication_does_not_resubmit_after_restart(connected):
    env = connected
    env.transport.fail_at = 3
    cohort = save(env)
    env.service.execute(cohort, **approved(env, cohort))
    assert env.service.get(cohort)["targets"][0]["status"] == "unknown"
    calls = list(env.transport.calls)
    env.extension.recover()
    env.service.recover()
    env.service.execute(cohort, **approved(env, cohort))
    assert env.transport.calls == calls
