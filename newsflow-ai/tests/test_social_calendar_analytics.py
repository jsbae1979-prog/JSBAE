from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text, update
from test_social_platforms import extended, options  # noqa: F401
from test_unified_publishing import arguments, environment, instagram_environment, save  # noqa: F401

from newsflow.db.models import (
    PublishDraft,
    PublishSchedule,
    SocialMetric,
    SocialMetricRun,
    utcnow,
)
from newsflow.publishing.analytics import (
    MONETARY,
    SCOPES,
    AnalyticsAdapter,
    AnalyticsService,
    number,
    recommend,
)
from newsflow.publishing.calendar import PublishingCalendar, local_time, month_view
from newsflow.publishing.platforms import PlatformBlocked
from newsflow.publishing.service import ConflictError, PublishingError


@pytest.fixture
def calendar_env(request):
    env = request.getfixturevalue("extended")
    cohort = save(env, accounts={"youtube": env.accounts["youtube"], "instagram": env.accounts["instagram"]})
    env.cohort = cohort
    env.calendar = PublishingCalendar(env.sessions, env.service, synthetic_dispatch=env.service.execute)
    env.now = utcnow()
    env.due = env.now + timedelta(hours=1)
    return env


def test_kst_and_month_boundaries():
    assert local_time("2026-10-20T00:30") == datetime(2026, 10, 19, 15, 30, tzinfo=UTC)
    view = month_view([], "2026-12")
    assert view["previous"] == "2026-11" and view["next"] == "2027-01"
    assert len(view["weeks"][0]) == 7


@pytest.mark.parametrize("value", ["", "tomorrow", "2026-10-20T00:30+09:00", "2026-10-20T00:30:01"])
def test_ambiguous_calendar_times_rejected(value):
    with pytest.raises(PublishingError):
        local_time(value)


def test_calendar_save_change_cas_and_cancel_preserve_review(calendar_env):
    env = calendar_env
    identifier = env.calendar.save(env.cohort, env.due, now=env.now)
    row = env.calendar.rows()[0]
    assert row.status == "paused" and not row.approval
    with pytest.raises(ConflictError):
        env.calendar.save(env.cohort, env.due, now=env.now)
    env.calendar.arm(identifier, row.revision, arguments(env, env.cohort), now=env.now)
    armed = env.calendar.rows()[0]
    env.calendar.save(env.cohort, env.due + timedelta(hours=1), revision=armed.revision, now=env.now)
    changed = env.calendar.rows()[0]
    assert not changed.approval and changed.status == "paused"
    with pytest.raises(ConflictError):
        env.calendar.cancel(identifier, row.revision)
    env.calendar.cancel(identifier, changed.revision)
    assert env.calendar.rows()[0].status == "cancelled"
    assert env.service.get(env.cohort)["reviewed"]
    assert not env.yt_adapter.calls and not env.ig_adapter.calls


def test_calendar_production_activation_cannot_be_enabled_by_saved_approval(calendar_env):
    env = calendar_env
    identifier = env.calendar.save(env.cohort, env.due, now=env.now)
    production = PublishingCalendar(env.sessions, env.service)
    with pytest.raises(PublishingError):
        production.arm(identifier, 1, arguments(env, env.cohort), now=env.now)
    assert production.tick(now=env.due) == 0
    assert not env.yt_adapter.calls


@pytest.mark.parametrize(
    "missing", ["approval_token", "consent", "made_for_kids", "instagram_public_consent"]
)
def test_calendar_approval_boundaries(calendar_env, missing):
    env = calendar_env
    identifier = env.calendar.save(env.cohort, env.due, now=env.now)
    args = arguments(env, env.cohort)
    del args[missing]
    with pytest.raises(PublishingError):
        env.calendar.arm(identifier, 1, args, now=env.now)
    assert env.calendar.rows()[0].status == "paused"


def test_calendar_tiktok_requires_direct_user_interaction(request):
    env = request.getfixturevalue("extended")
    cohort = save(env, accounts={"tiktok": env.accounts["tiktok"]})
    calendar = PublishingCalendar(env.sessions, env.service, synthetic_dispatch=env.service.execute)
    identifier = calendar.save(cohort, utcnow() + timedelta(hours=1))
    with pytest.raises(PublishingError, match="TikTok"):
        calendar.arm(identifier, 1, options(env, cohort))


def test_calendar_claim_once_and_reuses_platform_journals(calendar_env):
    env = calendar_env
    identifier = env.calendar.save(env.cohort, env.due, now=env.now)
    env.calendar.arm(identifier, 1, arguments(env, env.cohort), now=env.now)
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(lambda _: env.calendar.tick(now=env.due), range(2))) == 1
    assert len(env.yt_adapter.calls) == 1 and env.ig_adapter.calls.count("publish") == 1
    assert env.calendar.tick(now=env.due + timedelta(seconds=30)) == 0


def test_calendar_recovers_unknown_and_missed_without_burst(calendar_env):
    env = calendar_env
    identifier = env.calendar.save(env.cohort, env.due, now=env.now)
    env.calendar.arm(identifier, 1, arguments(env, env.cohort), now=env.now)
    env.calendar.recover(now=env.due + timedelta(seconds=1))
    assert env.calendar.rows()[0].status == "missed"
    assert env.calendar.tick(now=env.due + timedelta(days=1)) == 0
    with env.sessions.begin() as s:
        s.execute(update(PublishSchedule).where(PublishSchedule.id == identifier).values(status="running"))
    env.calendar.recover(now=env.due)
    assert env.calendar.rows()[0].status == "unknown"
    assert not env.yt_adapter.calls


def test_changed_draft_after_schedule_stops_dispatch(calendar_env):
    env = calendar_env
    identifier = env.calendar.save(env.cohort, env.due, now=env.now)
    env.calendar.arm(identifier, 1, arguments(env, env.cohort), now=env.now)
    with env.sessions.begin() as s:
        s.execute(
            update(PublishDraft)
            .where(PublishDraft.id == env.service.get(env.cohort)["targets"][0]["draft_id"])
            .values(title="변경", revision=2)
        )
    env.calendar.tick(now=env.due)
    assert env.calendar.rows()[0].status == "unknown"
    assert not env.yt_adapter.calls and not env.ig_adapter.calls


class MetricTransport:
    def __init__(self, platform):
        self.platform, self.calls, self.fail = platform, [], False
        self.channel = "UCsynthetic"
        self.rows = [["2026-09-01", 100, 2, 1, 0.25]]
        self.empty = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.fail:
            raise TimeoutError("private-token-should-not-leak")
        if "/youtube/v3/videos" in url:
            return {
                "items": [
                    {
                        "id": "video1",
                        "snippet": {"channelId": self.channel, "publishedAt": "2026-09-01T03:00:00Z"},
                    }
                ]
            }
        if "youtubeanalytics" in url:
            return {
                "columnHeaders": [
                    {"name": n}
                    for n in ("day", "views", "subscribersGained", "subscribersLost", "estimatedRevenue")
                ],
                "rows": [] if self.empty else self.rows,
            }
        if self.platform == "tiktok":
            return {
                "error": {"code": "ok"},
                "data": {"videos": [{"id": "video1", "view_count": 23, "like_count": None}]},
            }
        return {
            "data": []
            if self.empty
            else [
                {
                    "name": "views" if self.platform == "instagram" else "total_video_views",
                    "values": [{"value": 23}],
                }
            ]
        }


@pytest.mark.parametrize("platform", ["youtube", "instagram", "tiktok", "facebook"])
def test_metric_response_is_provider_specific_missing_not_zero(platform):
    transport = MetricTransport(platform)
    result = AnalyticsAdapter(platform, transport).fetch(
        "video1", "UCsynthetic", SCOPES[platform], date(2026, 9, 1), date(2026, 9, 7)
    )
    values = result["windows"][0]["values"]
    assert "estimatedRevenue" not in values
    assert any(v in {"100", "23"} for v in values.values())
    assert result["basis"] == ("America/Los_Angeles" if platform == "youtube" else "lifetime_snapshot")


def test_revenue_requires_separate_permission_and_is_estimated_usd():
    transport = MetricTransport("youtube")
    result = AnalyticsAdapter("youtube", transport).fetch(
        "video1", "UCsynthetic", SCOPES["youtube"] | {MONETARY}, date(2026, 9, 1), date(2026, 9, 7)
    )
    assert result["windows"][0]["values"]["estimatedRevenue"] == "0.25"
    assert "estimatedRevenue" in transport.calls[-1][1] and "currency=USD" in transport.calls[-1][1]


def test_wrong_channel_or_scope_cannot_collect_metrics():
    transport = MetricTransport("youtube")
    adapter = AnalyticsAdapter("youtube", transport)
    with pytest.raises(PublishingError):
        adapter.fetch("video1", "OTHER", SCOPES["youtube"], date(2026, 9, 1), date(2026, 9, 7))
    assert len(transport.calls) == 1
    with pytest.raises(PublishingError):
        adapter.fetch("video1", "UCsynthetic", {"youtube.upload"}, date(2026, 9, 1), date(2026, 9, 7))
    assert len(transport.calls) == 1


@pytest.mark.parametrize("value", [True, -1, "NaN", "Infinity", "-0.1", {}, "1e99"])
def test_bad_metric_numbers_rejected(value):
    with pytest.raises(PublishingError):
        number(value)


def test_metric_persistence_fake_isolation_failure_and_repeat_update(calendar_env):
    env = calendar_env
    result = env.service.execute(env.cohort, **arguments(env, env.cohort))
    job_id = result["targets"][0]["job_id"]
    transport = MetricTransport("youtube")
    binding = {
        "job_id": job_id,
        "account_id": env.accounts["youtube"],
        "platform": "youtube",
        "identity": "UCsynthetic",
        "remote_id": "video1",
        "scopes": SCOPES["youtube"] | {MONETARY},
        "synthetic": True,
    }
    service = AnalyticsService(
        env.sessions,
        synthetic_binding=lambda _: binding,
        adapters={"youtube": AnalyticsAdapter("youtube", transport)},
    )
    for _ in range(2):
        assert service.collect(job_id, date(2026, 9, 1), date(2026, 9, 7), consent=True) == 4
    with env.sessions() as s:
        assert s.scalar(select(func.count()).select_from(SocialMetric)) == 4
    assert service.dashboard()["totals"]["views"] is None
    assert service.dashboard(synthetic=True)["totals"]["views"] == 100
    transport.fail = True
    with pytest.raises(PublishingError):
        service.collect(job_id, date(2026, 9, 1), date(2026, 9, 7), consent=True)
    assert service.dashboard(synthetic=True)["totals"]["views"] == 100
    with env.sessions() as s:
        assert "private-token" not in str([r.message for r in s.scalars(select(SocialMetricRun))])
    with pytest.raises(PlatformBlocked):
        AnalyticsService(env.sessions).collect(job_id, date(2026, 9, 1), date(2026, 9, 7), consent=True)


def recommendation_rows():
    rows = []
    for job in range(12):
        stamp = datetime(2026, 9, 1, 1 if job < 6 else 10, tzinfo=UTC) + timedelta(days=job)
        first = stamp.astimezone(ZoneInfo("America/Los_Angeles")).date()
        for day in range(7):
            rows.append(
                SimpleNamespace(
                    job_id=job,
                    account_id=1,
                    platform="youtube",
                    metric="views",
                    period_basis="America/Los_Angeles",
                    period_start=(first + timedelta(days=day)).isoformat(),
                    published_at=stamp,
                    value="10" if job < 6 else "20",
                )
            )
    return rows


def test_recommendations_require_comparable_complete_windows_and_one_account():
    rows = recommendation_rows()
    result = recommend(rows, account_id=1, now=datetime(2026, 10, 19, tzinfo=UTC))
    assert result["ready"] and result["hours"][0] == {"hour": 19, "samples": 6, "median": "140"}
    assert not recommend(rows, account_id=2)["ready"]
    assert not recommend(rows[:7], account_id=1)["ready"]
    assert not recommend([r for i, r in enumerate(rows) if i % 7 != 0], account_id=1)["ready"]


def test_additive_schema_and_existing_tables_remain(app):
    with app.state.engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0018"
        names = {r[0] for r in connection.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {
        "news_articles",
        "publish_drafts",
        "publish_schedules",
        "social_metrics",
        "social_metric_runs",
    } <= names


def test_copied_database_cannot_duplicate_scheduled_publication(calendar_env, tmp_path):
    from newsflow.db.session import make_engine, session_factory
    from newsflow.migrate_data import migrate_data

    env = calendar_env
    identifier = env.calendar.save(env.cohort, env.due, now=env.now)
    env.calendar.arm(identifier, 1, arguments(env, env.cohort), now=env.now)
    # Fixture database may have a different name; make a separate SQLite backup, not a production file.
    import sqlite3

    source_copy = tmp_path / "source-copy"
    source_copy.mkdir()
    with (
        sqlite3.connect(env.sessions.kw["bind"].url.database) as original,
        sqlite3.connect(source_copy / "newsflow.db") as copy,
    ):
        original.backup(copy)
        # This service fixture uses Base.metadata.create_all rather than Alembic.
        # Tag only the synthetic backup with its actual current schema revision.
        copy.execute("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL)")
        copy.execute("INSERT INTO alembic_version VALUES ('0015')")
    target = tmp_path / "destination"
    migrate_data(source_copy, target)
    engine = make_engine(target / "newsflow.db")
    try:
        with session_factory(engine)() as s:
            row = s.get(PublishSchedule, identifier)
            assert row.status == "paused" and not row.approval
        assert env.calendar.rows()[0].status == "armed"
    finally:
        engine.dispose()
