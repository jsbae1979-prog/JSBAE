"""Per-video categories survive review/restart and reach the official upload payload; Fake only."""

import json

import pytest
from sqlalchemy import select, text
from test_unified_publishing import arguments, environment, instagram_environment, save  # noqa: F401
from test_youtube_upload import CHANNEL, bundle, media, payload, successful_transport  # noqa: F401

from newsflow.db.models import PublishDraft, PublishEvidence
from newsflow.db.session import migrate
from newsflow.publishing.categories import YOUTUBE_CATEGORIES
from newsflow.publishing.service import ConflictError, PublishingError
from newsflow.publishing.youtube import YouTubeUploadAdapter, YouTubeUploadError


@pytest.mark.parametrize("category", YOUTUBE_CATEGORIES)
def test_all_offered_categories_reach_official_metadata(request, category):
    path, digest = request.getfixturevalue("media")
    credentials = request.getfixturevalue("bundle")
    transport = successful_transport()
    YouTubeUploadAdapter(transport).upload(path, payload(youtube_category_id=category), credentials, CHANNEL, digest)
    assert json.loads(transport.calls[0][3])["snippet"]["categoryId"] == category


@pytest.mark.parametrize("category", ["", "999", "<script>", 25, None, True])
def test_bad_category_never_opens_upload_transport(request, category):
    path, digest = request.getfixturevalue("media")
    transport = successful_transport()
    with pytest.raises(YouTubeUploadError):
        YouTubeUploadAdapter(transport).upload(path, payload(youtube_category_id=category),
                                               request.getfixturevalue("bundle"), CHANNEL, digest)
    assert transport.calls == []


def test_selected_category_saved_sent_and_change_invalidates_previous_approval(request):
    env = request.getfixturevalue("environment")
    cohort = save(env, youtube_category_id="27")
    review = env.service.get(cohort)
    with env.sessions() as session:
        draft = session.get(PublishDraft, review["targets"][0]["draft_id"])
        assert draft.youtube_category_id == "27"
    new = save(env, youtube_category_id="28")
    assert env.service.get(new)["metadata"]["youtube_category_id"] == "28"
    old_result = env.service.execute(cohort, **arguments(env, cohort))
    assert all(t["status"] == "superseded" for t in old_result["targets"])
    assert env.yt_adapter.calls == []
    env.service.execute(new, **arguments(env, new))
    assert env.yt_adapter.calls[0][1]["youtube_category_id"] == "28"
    with env.sessions() as session:
        records = list(session.scalars(select(PublishEvidence).where(PublishEvidence.kind == "instagram_state")))
        assert records and all("youtube_category_id" not in row.payload["metadata"] for row in records)
    with pytest.raises(ConflictError):
        save(env, youtube_category_id="17")
    count = len(env.yt_adapter.calls)
    env.service.recover()
    env.service.execute(new, **arguments(env, new))
    assert len(env.yt_adapter.calls) == count


def test_legacy_review_keeps_snapshot_and_is_not_republished(request):
    env = request.getfixturevalue("environment")
    cohort = save(env)
    review = env.service.get(cohort)
    assert "youtube_category_id" not in review["metadata"]
    assert "youtube_category_id" not in review["targets"][0]["snapshot"]
    env.service.execute(cohort, **arguments(env, cohort))
    assert env.yt_adapter.calls[0][1]["youtube_category_id"] == "25"
    assert save(env) == cohort
    env.service.execute(cohort, **arguments(env, cohort))
    assert len(env.yt_adapter.calls) == 1


def test_0014_upgrade_preserves_data_and_legacy_category(request):
    env = request.getfixturevalue("environment")
    cohort = save(env)
    engine = env.sessions.kw["bind"]
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE publish_drafts DROP COLUMN youtube_category_id")
        before = connection.exec_driver_sql("SELECT * FROM publish_drafts ORDER BY id").mappings().all()
        connection.exec_driver_sql("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('0014')")
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0015"
        after = connection.exec_driver_sql("SELECT * FROM publish_drafts ORDER BY id").mappings().all()
    assert [{k: v for k, v in row.items() if k != "youtube_category_id"} for row in after] == [dict(r) for r in before]
    assert {row["youtube_category_id"] for row in after} == {"25"}
    assert env.service.get(cohort)["reviewed"]


def test_edit_without_category_keeps_saved_choice_and_revision_gate(request):
    env = request.getfixturevalue("environment")
    cohort = save(env, youtube_category_id="17")
    target = env.service.get(cohort)["targets"][0]
    with env.sessions() as session:
        draft = session.get(PublishDraft, target["draft_id"])
        fields = {name: getattr(draft, name) for name in ("platform", "title", "description", "account_id", "ai_disclosure")}
        fields["hashtags"] = " ".join(draft.hashtags)
    env.service.local.edit(draft.id, draft.revision, **fields)
    with env.sessions() as session:
        assert session.get(PublishDraft, draft.id).youtube_category_id == "17"
    with pytest.raises(PublishingError):
        env.service.execute(cohort, **arguments(env, cohort))
