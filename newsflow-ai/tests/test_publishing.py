"""Publishing foundation tests use synthetic media and never contact an SNS service."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from conftest import csrf
from pydantic import ValidationError
from sqlalchemy import MetaData, Table, func, inspect, select, text

from newsflow.db.models import (
    AppSetting,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    PlatformAccount,
    PublishAttempt,
    PublishDraft,
    PublishEvidence,
    PublishJob,
    PublishValidation,
    RenderJob,
    Scene,
    VideoProject,
)
from newsflow.db.session import make_engine, migrate, session_factory
from newsflow.intelligence.provider import OfflineProvider, Options
from newsflow.intelligence.service import IntelligenceService
from newsflow.publishing.adapters import (
    ExternalPublishingDisabled,
    FakePublisher,
    InstagramAdapter,
    PublishResult,
    YouTubeAdapter,
)
from newsflow.publishing.auth import (
    CredentialExpired,
    FakeCredentialVault,
    TokenBundle,
    UnavailableCredentialVault,
)
from newsflow.publishing.media import FakeMediaInspector, FFprobeMediaInspector, MediaInspectionError
from newsflow.publishing.repository import PublishJobRepository
from newsflow.publishing.service import (
    ConflictError,
    PublishingError,
    PublishingService,
)
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS

MEDIA = {
    "format": "mp4",
    "playable": True,
    "video_codec": "h264",
    "audio_codec": "aac",
    "width": 1080,
    "height": 1920,
    "duration": 30.0,
    "fps": 30.0,
    "audio_channels": 2,
}


@pytest.fixture
def publishing(app):
    with app.state.sessions.begin() as session:
        source = session.scalar(select(NewsSource))
        article = NewsArticle(
            title="게시 준비용 합성 뉴스",
            summary="기관 발표를 전했다는 합성 RSS 요약입니다.",
            url="https://example.com/publishing-source",
            canonical_url="https://example.com/publishing-source",
            source_id=source.id,
            publisher="합성 출처",
        )
        session.add(article)
        session.flush()
        article_id = article.id
    intelligence = IntelligenceService(app.state.sessions)
    script_id = intelligence.generate(intelligence.analyze([article_id]), 30)
    app.state.video.engine = FakeRenderAdapter()
    app.state.video.tts = FakeTTS()
    render_id = app.state.video.start(script_id, 30, reviewed=True)
    app.state.video.future.result(timeout=10)
    with app.state.sessions.begin() as session:
        job = session.get(RenderJob, render_id)
        # This is explicitly a synthetic file. Fake inspection verifies local workflow only.
        job.status = "success"
        job.metadata_json = {**MEDIA, "adapter": "fixture"}
        output = app.state.video.outputs / job.output_name
    inspector = FakeMediaInspector(MEDIA.copy())
    service = PublishingService(app.state.sessions, app.state.video.outputs, inspector)
    yield service, render_id, output, inspector
    app.state.video.close()


def create_draft(publishing, **changes):
    service, render_id, _output, _inspector = publishing
    values = {
        "render_job_id": render_id,
        "platform": "youtube",
        "title": "합성 뉴스 검토용 영상",
        "description": "사실 확인 후 게시할 합성 뉴스 초안입니다.",
        "hashtags": "#합성뉴스 #검토",
        "content_reviewed": True,
        "copyright_confirmed": True,
        "sources_confirmed": True,
        "ai_disclosure": "disclose",
    }
    values.update(changes)
    return service.create(**values)


def validation(app, identifier):
    with app.state.sessions() as session:
        return session.get(PublishValidation, identifier)


@pytest.mark.parametrize("adapter", [InstagramAdapter, YouTubeAdapter])
@pytest.mark.parametrize("approved", [False, True])
def test_real_adapters_cannot_execute_even_with_approval(adapter, approved):
    publisher = adapter()
    with patch("urllib.request.OpenerDirector.open") as network:
        with pytest.raises(ExternalPublishingDisabled):
            publisher.publish({"title": "synthetic"}, "fixture-only", approved=approved)
        with pytest.raises(ExternalPublishingDisabled):
            publisher.connect("synthetic-account", approved=approved)
        network.assert_not_called()
    assert publisher.real_publish_calls == 0 and publisher.real_oauth_calls == 0


def test_probe_argv_prevents_shell_and_remote_input_protocols(tmp_path, monkeypatch):
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "TOKEN-NOT-FOR-PROCESS")
    target = tmp_path / "한글 공백 $(command).mp4"
    payload = {
        "format": {"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "30.0"},
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1080,
                "height": 1920,
                "avg_frame_rate": "30/1",
            },
            {"codec_type": "audio", "codec_name": "aac", "channels": 2},
        ],
    }
    with (
        patch("newsflow.publishing.media.FFmpegAdapter.executable", return_value=tmp_path / "ffprobe.exe"),
        patch(
            "newsflow.publishing.media.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=json.dumps(payload).encode()),
        ) as call,
    ):
        result = FFprobeMediaInspector().inspect(target)
    assert result["width"] == 1080 and result["duration"] == 30.0
    args = call.call_args.args[0]
    assert isinstance(args, list) and args[-1] == str(target)
    assert args[args.index("-protocol_whitelist") + 1] == "file,pipe"
    assert args[args.index("-f") + 1] == "mov"
    assert call.call_args.kwargs["shell"] is False
    assert call.call_args.kwargs["timeout"] == 20
    assert "INSTAGRAM_ACCESS_TOKEN" not in call.call_args.kwargs["env"]


@pytest.mark.parametrize(
    "failure",
    [
        SimpleNamespace(returncode=1, stdout=b"SECRET-RAW-OUTPUT"),
        SimpleNamespace(returncode=0, stdout=b"not-json-SECRET"),
    ],
)
def test_probe_failures_do_not_reflect_command_output(tmp_path, failure):
    with (
        patch("newsflow.publishing.media.FFmpegAdapter.executable", return_value=tmp_path / "ffprobe.exe"),
        patch("newsflow.publishing.media.subprocess.run", return_value=failure),
        pytest.raises(MediaInspectionError) as error,
    ):
        FFprobeMediaInspector().inspect(tmp_path / "synthetic.mp4")
    assert "SECRET" not in str(error.value)


def test_token_bundle_repr_and_serialization_are_redacted():
    bundle = TokenBundle(
        access_token="SECRET-ACCESS-TOKEN",
        refresh_token="SECRET-REFRESH-TOKEN",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        scopes=("https://www.googleapis.com/auth/youtube.upload",),
    )
    for displayed in (str(bundle), repr(bundle), str(bundle.model_dump()), bundle.model_dump_json()):
        assert "SECRET-ACCESS-TOKEN" not in displayed and "SECRET-REFRESH-TOKEN" not in displayed
    assert bundle.access_token.get_secret_value() == "SECRET-ACCESS-TOKEN"


@pytest.mark.parametrize(
    "changes",
    [
        {"expires_at": datetime(2026, 1, 1)},
        {"unsupported_setting": "forbidden"},
    ],
)
def test_invalid_token_bundle_errors_do_not_include_credentials(changes):
    fields = {
        "access_token": "SECRET-MALFORMED-INPUT",
        "refresh_token": "SECRET-REFRESH-INPUT",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
    }
    fields.update(changes)
    with pytest.raises(ValidationError) as error:
        TokenBundle(**fields)
    assert "SECRET-MALFORMED-INPUT" not in str(error.value)
    assert "SECRET-REFRESH-INPUT" not in str(error.value)


def test_fake_vault_stores_only_ephemeral_isolated_secret_bundle():
    bundle = TokenBundle(
        access_token="SECRET-ONLY-IN-MEMORY", expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    vault = FakeCredentialVault()
    reference = vault.store(bundle)
    assert reference.startswith("fake:") and "SECRET" not in reference
    bundle.access_token = "SECRET-MUTATED-ORIGINAL"
    first = vault.load(reference)
    assert first.access_token.get_secret_value() == "SECRET-ONLY-IN-MEMORY"
    first.access_token = "SECRET-MUTATED-RETURNED"
    assert vault.load(reference).access_token.get_secret_value() == "SECRET-ONLY-IN-MEMORY"
    with pytest.raises(CredentialExpired):
        FakeCredentialVault().load(reference)


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_fake_vault_expired_or_revoked_credentials_are_unavailable(state):
    bundle = TokenBundle(
        access_token="SECRET-NOT-IN-ERROR",
        expires_at=datetime.now(UTC) + timedelta(hours=-1 if state == "expired" else 1),
    )
    vault = FakeCredentialVault()
    reference = vault.store(bundle)
    if state == "revoked":
        vault.delete(reference)
    with pytest.raises(CredentialExpired) as error:
        vault.load(reference)
    assert "SECRET" not in str(error.value)


@pytest.mark.parametrize("operation", ["store", "load", "delete"])
def test_production_vault_remains_unavailable_without_authorization(operation):
    vault = UnavailableCredentialVault()
    bundle = TokenBundle(
        access_token="SYNTHETIC-CREDENTIAL", expires_at=datetime.now(UTC) + timedelta(hours=1)
    )
    value = bundle if operation == "store" else "unconfigured-reference"
    with patch("urllib.request.OpenerDirector.open") as network:
        with pytest.raises(ExternalPublishingDisabled):
            getattr(vault, operation)(value)
        network.assert_not_called()


@pytest.mark.parametrize("platform", ["youtube", "instagram"])
def test_local_good_media_does_not_claim_real_platform_ready(publishing, app, platform):
    service, _render_id, output, inspector = publishing
    identifier = create_draft(publishing, platform=platform)
    result = validation(app, service.validate(identifier))
    assert result.status == "blocked"
    results = {item["key"]: item for item in result.results}
    for key in ("media", "video_profile", "content_review", "source_review", "copyright_review"):
        assert results[key]["status"] == "pass"
    for key in ("account", "permissions", "api_readiness", "official_policy"):
        assert results[key]["status"] in {"fail", "unverified"}
    if platform == "instagram":
        assert results["instagram_delivery"]["status"] in {"fail", "unverified"}
    assert inspector.calls == [output]
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, identifier)
        assert draft.state != "ready_to_publish"
        assert "https://example.com/publishing-source" in json.dumps(draft.sources)


@pytest.mark.parametrize(
    "change,key",
    [
        ({"content_reviewed": False}, "content_review"),
        ({"copyright_confirmed": False}, "copyright_review"),
        ({"sources_confirmed": False}, "source_review"),
        ({"ai_disclosure": "unreviewed"}, "ai_disclosure"),
    ],
)
def test_missing_review_cannot_simulate(publishing, app, change, key):
    service, *_ = publishing
    identifier = create_draft(publishing, **change)
    result = validation(app, service.validate(identifier))
    assert next(item for item in result.results if item["key"] == key)["status"] != "pass"
    fake = FakePublisher()
    with pytest.raises(PublishingError):
        PublishJobRepository(app.state.sessions).simulate(identifier, fake, approved=True)
    assert not fake.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"platform": "unsupported"},
        {"title": ""},
        {"title": "x" * 101},
        {"hashtags": "#good https://evil.example"},
        {"hashtags": " ".join(f"#tag{i}" for i in range(31))},
        {"ai_disclosure": "verified"},
        {"render_job_id": 99999},
    ],
)
def test_invalid_draft_inputs_not_persisted(publishing, app, changes):
    with pytest.raises(PublishingError):
        create_draft(publishing, **changes)
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublishDraft)) == 0


@pytest.mark.parametrize(
    "media",
    [
        {"video_codec": "vp9"},
        {"audio_codec": "opus"},
        {"width": 1920, "height": 1080},
        {"duration": 0},
        {"duration": 181},
        {"fps": 1},
    ],
)
def test_platform_media_profile_rejection(publishing, app, media):
    service, _render_id, _output, inspector = publishing
    inspector.metadata = {**MEDIA, **media}
    identifier = create_draft(publishing)
    result = validation(app, service.validate(identifier))
    assert result.status == "blocked"
    assert next(item for item in result.results if item["key"] == "video_profile")["status"] == "fail"


def test_youtube_korean_description_must_fit_byte_budget(publishing, app):
    service, *_ = publishing
    description = "한" * 2000
    assert len(description) < 5000 and len(description.encode("utf-8")) > 5000
    identifier = create_draft(publishing, description=description, hashtags="")
    result = validation(app, service.validate(identifier))
    assert next(item for item in result.results if item["key"] == "description")["status"] == "fail"
    assert result.status == "blocked"


@pytest.mark.parametrize("extra_byte", [0, 1])
def test_youtube_prepared_description_utf8_boundary(publishing, app, extra_byte):
    service, *_ = publishing
    description = "가" * 1600 + "a" * (200 + extra_byte)
    identifier = create_draft(publishing, description=description, hashtags="")
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, identifier)
        prepared = YouTubeAdapter().prepare(
            {"title": draft.title, "description": draft.description, "hashtags": draft.hashtags}
        )["snippet"]["description"]
    assert len(prepared.encode("utf-8")) == 5000 + extra_byte
    assert len(prepared) < 5000
    result = validation(app, service.validate(identifier))
    expected = "pass" if extra_byte == 0 else "fail"
    assert next(item for item in result.results if item["key"] == "description")["status"] == expected
    assert result.status == "blocked"


@pytest.mark.parametrize("extra_byte", [0, 1])
def test_youtube_description_byte_budget_includes_emitted_hashtags(publishing, app, extra_byte):
    service, *_ = publishing
    description = "가" * 1600 + "a" * (195 + extra_byte)
    identifier = create_draft(publishing, description=description, hashtags="#tag")
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, identifier)
        prepared = YouTubeAdapter().prepare(
            {"title": draft.title, "description": draft.description, "hashtags": draft.hashtags}
        )["snippet"]["description"]
    assert prepared.endswith("\n#tag")
    assert len(description.encode("utf-8")) < 5000
    assert len(prepared.encode("utf-8")) == 5000 + extra_byte
    result = validation(app, service.validate(identifier))
    expected = "pass" if extra_byte == 0 else "fail"
    assert next(item for item in result.results if item["key"] == "description")["status"] == expected
    assert result.status == "blocked"


@pytest.mark.parametrize("field", ["title", "description"])
def test_youtube_api_text_disallows_angle_brackets(publishing, app, field):
    service, *_ = publishing
    identifier = create_draft(publishing, **{field: "합성 <검토용> 텍스트"})
    result = validation(app, service.validate(identifier))
    assert next(item for item in result.results if item["key"] == field)["status"] == "fail"
    assert result.status == "blocked"


@pytest.mark.parametrize("extra_character", [0, 1])
def test_youtube_api_tag_budget_counts_separating_commas(publishing, app, extra_character):
    service, *_ = publishing
    tags = [f"t{i}" + "a" * 58 for i in range(8)] + ["t8" + "b" * (10 + extra_character)]
    assert len(set(tags)) == len(tags) and all(len(tag) <= 60 for tag in tags)
    identifier = create_draft(publishing, hashtags=" ".join("#" + tag for tag in tags))
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, identifier)
        prepared = YouTubeAdapter().prepare(
            {"title": draft.title, "description": draft.description, "hashtags": draft.hashtags}
        )["snippet"]
    assert sum(len(tag) for tag in prepared["tags"]) < 500
    assert len(",".join(prepared["tags"])) == 500 + extra_character
    result = validation(app, service.validate(identifier))
    expected = "pass" if extra_character == 0 else "fail"
    assert next(item for item in result.results if item["key"] == "hashtags")["status"] == expected
    assert result.status == "blocked"


def test_missing_media_does_not_trust_stored_render_metadata(publishing, app):
    service, _render_id, output, inspector = publishing
    identifier = create_draft(publishing)
    output.unlink()
    result = validation(app, service.validate(identifier))
    assert result.status == "blocked"
    assert next(item for item in result.results if item["key"] == "media")["status"] == "fail"
    assert not inspector.calls


def test_zero_byte_and_symlink_media_cannot_be_validated(publishing, app):
    service, _render_id, output, inspector = publishing
    identifier = create_draft(publishing)
    output.write_bytes(b"")
    result = validation(app, service.validate(identifier))
    assert next(item for item in result.results if item["key"] == "media")["status"] == "fail"
    output.write_bytes(b"synthetic-mp4")
    with patch.object(Path, "is_symlink", return_value=True):
        result = validation(app, service.validate(identifier))
    assert next(item for item in result.results if item["key"] == "media")["status"] == "fail"
    assert not inspector.calls


@pytest.mark.parametrize("error", [TimeoutError("SECRET-TOKEN"), RuntimeError("SECRET-TOKEN")])
def test_inspection_failure_records_safe_blocker(publishing, app, error):
    service, _render_id, _output, inspector = publishing
    identifier = create_draft(publishing)
    with patch.object(inspector, "inspect", side_effect=error):
        result = validation(app, service.validate(identifier))
    assert result.status == "blocked"
    assert "SECRET-TOKEN" not in json.dumps(result.results, ensure_ascii=False)
    assert next(item for item in result.results if item["key"] == "media")["status"] == "fail"


def test_render_output_traversal_blocked(publishing, app, tmp_path):
    _service, render_id, _output, inspector = publishing
    with app.state.sessions.begin() as session:
        session.get(RenderJob, render_id).output_name = "../outside.mp4"
    (tmp_path / "outside.mp4").write_bytes(b"user-data")
    with pytest.raises(PublishingError):
        create_draft(publishing)
    assert not inspector.calls


def test_saved_draft_edit_requires_revision_and_revalidation(publishing, app):
    service, *_ = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)
    with app.state.sessions() as session:
        sources = session.get(PublishDraft, identifier).sources
    edits = {
        "platform": "youtube",
        "title": "수정된 합성 제목",
        "description": "수정된 설명",
        "hashtags": "#합성",
        "content_reviewed": True,
        "copyright_confirmed": True,
        "sources_confirmed": True,
        "ai_disclosure": "disclose",
    }
    service.edit(identifier, 1, **edits)
    with pytest.raises(ConflictError):
        service.edit(identifier, 1, **edits)
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, identifier)
        assert draft.revision == 2 and draft.title == edits["title"] and draft.sources == sources
    fake = FakePublisher()
    with pytest.raises(PublishingError):
        PublishJobRepository(app.state.sessions).simulate(identifier, fake, approved=True)
    assert not fake.calls


def test_concurrent_edit_during_inspection_rejects_stale_validation(publishing, app):
    service, _render_id, _output, inspector = publishing
    identifier = create_draft(publishing)

    def edit_while_inspecting(_path):
        # A separate DB session commits while the original validation holds its old snapshot.
        service.edit(
            identifier,
            1,
            platform="youtube",
            title="검증 도중 수정된 제목",
            description="다른 요청에서 저장한 설명",
            hashtags="#수정",
            content_reviewed=True,
            copyright_confirmed=True,
            sources_confirmed=True,
            ai_disclosure="disclose",
        )
        return MEDIA.copy()

    with (
        patch.object(inspector, "inspect", side_effect=edit_while_inspecting),
        pytest.raises(ConflictError),
    ):
        service.validate(identifier)
    with app.state.sessions() as session:
        draft = session.get(PublishDraft, identifier)
        assert draft.revision == 2 and draft.title == "검증 도중 수정된 제목"
        assert draft.state == "unvalidated"
        assert session.scalar(select(func.count()).select_from(PublishValidation)) == 0
        assert session.scalar(select(PublishEvidence).where(PublishEvidence.kind == "validation")) is None


def test_fake_publish_requires_explicit_approval(publishing, app):
    service, *_ = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)
    fake = FakePublisher()
    with pytest.raises(PublishingError):
        PublishJobRepository(app.state.sessions).simulate(identifier, fake)
    assert not fake.calls
    with app.state.sessions() as session:
        assert session.scalar(select(PublishJob)) is None


@pytest.mark.parametrize("outcome", ["simulated", "unknown", "failed", "expired"])
def test_fake_results_persisted_without_real_success_or_automatic_retry(publishing, app, outcome):
    service, *_ = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)
    fake = FakePublisher(outcome)
    repository = PublishJobRepository(app.state.sessions)
    job_id = repository.simulate(identifier, fake, approved=True)
    restarted = PublishJobRepository(app.state.sessions)
    repeated = restarted.simulate(identifier, fake, approved=True)
    assert repeated == job_id and len(fake.calls) == 1
    with app.state.sessions() as session:
        job = session.get(PublishJob, job_id)
        assert job.status == outcome and job.status != "success"
        attempts = list(session.scalars(select(PublishAttempt).where(PublishAttempt.job_id == job_id)))
        assert len(attempts) == 1 and attempts[0].status == outcome
        assert session.scalar(select(PublishEvidence).where(PublishEvidence.draft_id == identifier))


def test_repository_cannot_accept_real_adapter(publishing, app):
    service, *_ = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)
    real = YouTubeAdapter()
    with pytest.raises(ExternalPublishingDisabled):
        PublishJobRepository(app.state.sessions).simulate(identifier, real, approved=True)
    assert real.real_publish_calls == 0 and real.real_oauth_calls == 0


def test_changed_media_invalidates_prior_validation(publishing, app):
    service, _render_id, output, _inspector = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)
    output.write_bytes(b"REPLACED-SYNTHETIC-MEDIA")
    fake = FakePublisher()
    with pytest.raises(PublishingError):
        PublishJobRepository(app.state.sessions).simulate(identifier, fake, approved=True)
    assert not fake.calls


def test_same_video_cannot_publish_twice_with_edited_metadata(publishing, app):
    service, *_ = publishing
    first = create_draft(publishing)
    second = create_draft(publishing, title="다른 제목으로 중복 요청")
    service.validate(first)
    service.validate(second)
    fake = FakePublisher("unknown")
    repository = PublishJobRepository(app.state.sessions)
    first_job = repository.simulate(first, fake, approved=True)
    try:
        second_job = repository.simulate(second, fake, approved=True)
    except ConflictError:
        second_job = first_job
    assert second_job == first_job and len(fake.calls) == 1
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublishJob)) == 1


def test_concurrent_duplicate_reserves_only_one_fake_attempt(publishing, app):
    service, *_ = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)
    entered, released = Event(), Event()

    class WaitingFake(FakePublisher):
        def publish(self, payload, idempotency_key, approved=False):
            entered.set()
            assert released.wait(5)
            return super().publish(payload, idempotency_key, approved)

    fake = WaitingFake("unknown")
    repository = PublishJobRepository(app.state.sessions)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(repository.simulate, identifier, fake, True)
        try:
            assert entered.wait(3)
            repeated = PublishJobRepository(app.state.sessions).simulate(identifier, fake, True)
        finally:
            released.set()
        assert future.result(timeout=5) == repeated
    assert len(fake.calls) == 1
    with app.state.sessions() as session:
        assert session.scalar(select(func.count()).select_from(PublishAttempt)) == 1


def test_restart_recovers_unfinished_simulation_as_unknown(publishing, app):
    service, *_ = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)
    repository = PublishJobRepository(app.state.sessions)
    job_id = repository.simulate(identifier, FakePublisher(), approved=True)
    with app.state.sessions.begin() as session:
        job = session.get(PublishJob, job_id)
        job.status, job.finished_at = "simulating", None
        session.scalar(select(PublishAttempt)).status = "simulating"
    restarted = PublishJobRepository(app.state.sessions)
    restarted.recover()
    fake = FakePublisher()
    assert restarted.simulate(identifier, fake, approved=True) == job_id
    assert not fake.calls
    with app.state.sessions() as session:
        job = session.get(PublishJob, job_id)
        assert job.status == "unknown" and job.finished_at
        assert session.scalar(select(PublishAttempt)).status == "unknown"


@pytest.mark.parametrize("raises", [False, True])
def test_fake_cannot_promote_untrusted_results_to_real_success(publishing, app, raises):
    service, *_ = publishing
    identifier = create_draft(publishing)
    service.validate(identifier)

    class UntrustedFake(FakePublisher):
        def publish(self, payload, idempotency_key, approved=False):
            if raises:
                raise RuntimeError("SECRET-TOKEN-IN-ERROR")
            return PublishResult("success", "SECRET-TOKEN-IN-MESSAGE", "https://evil.example/result")

    job_id = PublishJobRepository(app.state.sessions).simulate(identifier, UntrustedFake(), approved=True)
    with app.state.sessions() as session:
        job = session.get(PublishJob, job_id)
        assert job.status == "unknown" and "SECRET" not in job.message
        attempt = session.scalar(select(PublishAttempt))
        assert attempt.status == "unknown" and "SECRET" not in attempt.message
        evidence = list(session.scalars(select(PublishEvidence)))
        assert "SECRET" not in json.dumps([item.payload for item in evidence])
        assert "evil.example" not in json.dumps([item.payload for item in evidence])


def test_supplied_tokens_cannot_be_saved_in_draft_or_account(publishing, app, monkeypatch):
    service, *_ = publishing
    monkeypatch.setenv("INSTAGRAM_ACCESS_TOKEN", "ACCESS-TOKEN-DO-NOT-SAVE")
    with pytest.raises(PublishingError):
        create_draft(publishing, title="ACCESS-TOKEN-DO-NOT-SAVE")
    with pytest.raises(PublishingError):
        service.add_account("instagram", "ACCESS-TOKEN-DO-NOT-SAVE", "professional_business")
    with app.state.sessions() as session:
        assert session.scalar(select(PublishDraft)) is None
        assert session.scalar(select(PlatformAccount)) is None


def test_selected_account_must_match_platform(publishing, app):
    service, *_ = publishing
    account_id = service.add_account("instagram", "합성 계정", "professional_creator")
    with pytest.raises(PublishingError):
        create_draft(publishing, platform="youtube", account_id=account_id)
    with app.state.sessions() as session:
        assert session.scalar(select(PublishDraft)) is None


@pytest.mark.parametrize("state", ["expired", "revoked"])
def test_account_expiry_and_revocation_block_real_readiness(publishing, app, state):
    service, *_ = publishing
    account_id = service.add_account("youtube", "합성 계정 메모", "youtube_channel")
    with app.state.sessions.begin() as session:
        session.get(PlatformAccount, account_id).status = state
    identifier = create_draft(publishing, account_id=account_id)
    result = validation(app, service.validate(identifier))
    assert result.status == "blocked"
    assert next(item for item in result.results if item["key"] == "account")["status"] != "pass"
    fake = FakePublisher()
    with pytest.raises(PublishingError):
        PublishJobRepository(app.state.sessions).simulate(identifier, fake, approved=True)
    assert not fake.calls


def test_metadata_flags_cannot_enable_real_execution(publishing, app):
    service, *_ = publishing
    account_id = service.add_account("youtube", "합성 계정", "youtube_channel")
    with app.state.sessions.begin() as session:
        account = session.get(PlatformAccount, account_id)
        account.status = "configured"
        account.api_ready = True
        account.scopes = ["https://www.googleapis.com/auth/youtube.upload"]
        account.credential_ref = "fake-reference-only"
    identifier = create_draft(publishing, account_id=account_id)
    result = validation(app, service.validate(identifier))
    assert result.status == "blocked"
    assert next(item for item in result.results if item["key"] == "api_readiness")["status"] == "fail"
    assert next(item for item in result.results if item["key"] == "permissions")["status"] == "unverified"


def test_metadata_account_does_not_persist_tokens(publishing, app):
    service, *_ = publishing
    identifier = service.add_account("instagram", "합성 비즈니스 계정", "professional_business")
    with app.state.sessions() as session:
        assert session.get(PlatformAccount, identifier).status == "not_connected"
    columns = {column["name"] for column in inspect(app.state.engine).get_columns("platform_accounts")}
    assert not columns & {"access_token", "refresh_token", "client_secret", "api_key"}


def test_publishing_gui_post_csrf_escaping_and_key_nonexposure(publishing, app, client, monkeypatch):
    _service, render_id, *_ = publishing
    sentinel = "TOKEN-NEVER-EXPOSE-987"
    for key in ("NEWSFLOW_AI_API_KEY", "INSTAGRAM_ACCESS_TOKEN", "YOUTUBE_REFRESH_TOKEN"):
        monkeypatch.setenv(key, sentinel)
    response = client.get("/publishing")
    assert response.status_code == 200 and sentinel not in response.text
    token = csrf(client)
    values = {
        "csrf_token": token,
        "render_job_id": render_id,
        "platform": "youtube",
        "title": '<script>alert("unsafe")</script>',
        "description": "합성 검토용 설명",
        "hashtags": "#합성",
        "content_reviewed": "true",
        "copyright_confirmed": "true",
        "sources_confirmed": "true",
        "ai_disclosure": "disclose",
    }
    assert client.post("/publishing/drafts", data={**values, "csrf_token": "invalid"}).status_code == 403
    assert client.post("/publishing/drafts", data=values, headers={"Origin": "null"}).status_code == 403
    response = client.post("/publishing/drafts", data=values)
    assert response.status_code == 200 and sentinel not in response.text
    assert '<script>alert("unsafe")</script>' not in response.text
    assert "&lt;script&gt;" in response.text
    with app.state.sessions() as session:
        identifier = session.scalar(select(PublishDraft.id))
    with patch("newsflow.publishing.service.FFprobeMediaInspector.inspect", return_value=MEDIA.copy()):
        response = client.post(f"/publishing/drafts/{identifier}/validate", data={"csrf_token": token})
    assert response.status_code == 200 and 'data-state="blocked"' in response.text
    assert sentinel not in response.text
    with app.state.sessions() as session:
        assert session.scalar(select(PublishJob)) is None


def test_additive_0004_migration_preserves_phase3_data(tmp_path):
    engine = make_engine(tmp_path / "한글 공백 DB" / "migration.db")
    migration = Config()
    migration.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "src/newsflow/db/migrations")
    )
    with engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "0003")
    sessions = session_factory(engine)
    with sessions.begin() as session:
        source = NewsSource(name="기존 출처", url="https://example.com/legacy")
        session.add(source)
        session.flush()
        article = NewsArticle(
            title="기존 기사",
            url="https://example.com/legacy-news",
            canonical_url="https://example.com/legacy-news",
            source_id=source.id,
            publisher="기존 출처",
        )
        session.add(article)
        session.add(AppSetting(key="collection_timeout", value="7"))
    intelligence = IntelligenceService(sessions)
    analysis_id = intelligence.analyze([1])
    with sessions.begin() as session:
        # Use the real pre-0008/0009 columns when creating the migration fixture.
        analysis = session.get(IntelligenceRun, analysis_id)
        legacy_drafts = Table("content_drafts", MetaData(), autoload_with=session.connection())
        script_id = session.execute(legacy_drafts.insert().values(
            run_id=analysis_id, duration=30, revision=1, review_status="review_required",
            content=OfflineProvider().complete(analysis.evidence, 30, Options()), sources=analysis.evidence,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )).inserted_primary_key[0]
        script = session.execute(legacy_drafts.select().where(legacy_drafts.c.id == script_id)).one()
        legacy_projects = Table("video_projects", MetaData(), autoload_with=session.connection())
        project_id = session.execute(legacy_projects.insert().values(
            draft_id=script_id, title="기존 영상", duration=30,
            snapshot=script.content, sources=script.sources, created_at=datetime.now(UTC),
        )).inserted_primary_key[0]
        # Pre-0010 video_scenes has no clip_name/ai_generated columns; insert through the real table.
        legacy_scenes = Table("video_scenes", MetaData(), autoload_with=session.connection())
        session.execute(legacy_scenes.insert().values(
            project_id=project_id, position=0, start_ms=0, end_ms=30000,
            narration="기존 내레이션", caption="기존 자막", material="",
        ))
        session.add(RenderJob(project_id=project_id, output_name="legacy.mp4", status="interrupted"))
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0013"
    with sessions() as session:
        assert session.get(AppSetting, "collection_timeout").value == "7"
        assert session.get(NewsArticle, 1).title == "기존 기사"
        assert session.get(ContentDraft, script_id).sources["articles"]
        assert session.scalar(select(Scene)).caption == "기존 자막"
        assert session.scalar(select(RenderJob)).status == "interrupted"
        assert session.scalar(select(func.count()).select_from(PublishDraft)) == 0
    assert {
        "publish_drafts",
        "platform_accounts",
        "publish_validations",
        "publish_jobs",
        "publish_attempts",
        "publish_evidence",
    }.issubset(inspect(engine).get_table_names())
    engine.dispose()


@pytest.mark.parametrize("marker", ["metadata", "scene"])
def test_video_with_ai_generated_scenes_must_be_disclosed(publishing, app, marker):
    """Phase 5D: 'not_required' passes only for videos without any AI-generated scene."""
    service, render_id, *_ = publishing
    plain = create_draft(publishing, ai_disclosure="not_required")
    result = validation(app, service.validate(plain))
    assert next(item for item in result.results if item["key"] == "ai_disclosure")["status"] == "pass"
    with app.state.sessions.begin() as session:
        job = session.get(RenderJob, render_id)
        if marker == "metadata":
            job.metadata_json = {**job.metadata_json, "ai_generated_scenes": [0]}
        else:
            project = session.get(VideoProject, job.project_id)
            project.ai_plan_id = 1
            session.scalar(select(Scene).where(Scene.project_id == project.id, Scene.position == 0)).ai_generated = True
    for disclosure, expected in (("not_required", "fail"), ("disclose", "pass")):
        identifier = create_draft(publishing, ai_disclosure=disclosure, title=f"AI 장면 포함 {disclosure}")
        item = next(i for i in validation(app, service.validate(identifier)).results if i["key"] == "ai_disclosure")
        assert item["status"] == expected and "AI 생성 장면 포함 영상" in item["reason"]
