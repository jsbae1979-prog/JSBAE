"""High-risk UX acceptance only; inherits the approved disposable Windows boundary.

The byte-only media fixture is for journals/restore, never playback/FFmpeg proof.
"""

import hashlib
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import SimpleNamespace as NS

from test_full_app_forms import client as client  # noqa: PLC0414 - pytest fixture reuse
from test_full_app_forms import token


def synthetic_video(app):
    from newsflow.db.models import ContentDraft, IntelligenceRun, RenderJob, VideoProject

    sources = {"articles": [{"sources": [{"url": "https://example.invalid/synthetic"}]}]}
    with app.state.sessions.begin() as s:
        run = IntelligenceRun(
            kind="script",
            status="success",
            provider="offline",
            options={},
            evidence={},
            result={},
            message="synthetic",
        )
        s.add(run)
        s.flush()
        draft = ContentDraft(run_id=run.id, duration=30, content={}, sources=sources)
        s.add(draft)
        s.flush()
        project = VideoProject(
            draft_id=draft.id, title="합성 복원·검토", duration=30, snapshot={}, sources=sources
        )
        s.add(project)
        s.flush()
        row = RenderJob(
            project_id=project.id,
            status="success",
            output_name="video-" + "b" * 32 + ".mp4",
            metadata_json={"playable": True},
        )
        s.add(row)
        s.flush()
        identifier = row.id
        name = row.output_name
    app.state.video.outputs.mkdir(parents=True, exist_ok=True)
    path = app.state.video.outputs / name
    path.write_bytes(b"synthetic journal media; not a playable MP4")
    return identifier, path


def test_trash_restore_requires_confirmation_and_rejects_changed_media(client):
    c, app = client
    from newsflow.db.models import RenderJob, WorkspaceRemoval

    identifier, path = synthetic_video(app)
    original = path.read_bytes()
    csrf = token(c)
    data = {"csrf_token": csrf}
    assert c.post(f"/workspace/videos/{identifier}/remove", data=data).status_code == 422
    assert path.read_bytes() == original
    assert (
        c.post(f"/workspace/videos/{identifier}/remove", data={**data, "confirm": "true"}).status_code == 303
    )
    key = f"video:{identifier}"
    archived = app.state.video.root / "trash/videos" / path.name
    assert not path.exists() and archived.read_bytes() == original
    with app.state.sessions() as s:
        row = s.get(WorkspaceRemoval, key)
        assert row.detail["state"] == "trashed"
        assert row.detail["sha256"] == hashlib.sha256(original).hexdigest()
        assert s.get(RenderJob, identifier).status == "success"
    restore = {**data, "item": key}
    assert c.post("/workspace/trash/restore", data=restore).status_code == 422
    archived.write_bytes(b"changed synthetic media")
    assert c.post("/workspace/trash/restore", data={**restore, "confirm": "true"}).status_code == 409
    assert archived.exists() and not path.exists()
    archived.write_bytes(original)
    assert c.post("/workspace/trash/restore", data={**restore, "confirm": "true"}).status_code == 303
    assert path.read_bytes() == original and not archived.exists()
    with app.state.sessions() as s:
        assert s.get(WorkspaceRemoval, key) is None


def test_schedule_pause_resume_keeps_revision_and_never_dispatches(client, monkeypatch):
    c, app = client
    from sqlalchemy import select

    from newsflow.db.models import ScheduledRun

    calls = []
    monkeypatch.setattr(app.state.scheduler, "_dispatch", lambda *a, **k: calls.append(a))
    csrf = token(c)
    result = c.post(
        "/schedules",
        data={
            "csrf_token": csrf,
            "name": "합성 안전 예약",
            "kind": "daily",
            "local_time": "09:00",
            "source": "sample",
            "duration": 30,
            "platform": "youtube",
            "voice": "offline-silence",
        },
    )
    assert result.status_code == 303

    def row():
        return c.get("/api/studio/modules/automation").json()["collections"]["schedules"][0]

    first = row()
    assert first["status"] == "paused"

    def change(action, revision, consent=False):
        return c.post(
            f"/schedules/{first['id']}/state",
            data={
                "csrf_token": csrf,
                "action": action,
                "revision": revision,
                "consent": str(consent).lower(),
            },
        )

    assert change("enable", first["revision"]).status_code == 422
    assert change("enable", first["revision"], True).status_code == 303
    active = row()
    assert active["status"] == "active" and active["revision"] > first["revision"]
    assert change("pause", first["revision"]).status_code == 409
    assert change("pause", active["revision"]).status_code == 303
    paused = row()
    assert paused["status"] == "paused"
    assert change("enable", paused["revision"], True).status_code == 303
    assert row()["status"] == "active" and calls == []
    with app.state.sessions() as s:
        assert list(s.scalars(select(ScheduledRun))) == []


def test_unknown_image_is_not_replayed_or_misclassified_as_news_card(client):
    c, app = client
    from sqlalchemy import select

    from newsflow.db.models import IntelligenceRun
    from newsflow.publishing.image_generation import ImageGenerationError

    class Unknown:
        calls = 0

        def generate(self, *args, **kwargs):
            self.calls += 1
            raise ImageGenerationError("synthetic_timeout", uncertain=True)

    fake = Unknown()
    app.state.image_generation.adapter = fake
    app.state.image_generation.keys = NS(
        key=lambda: "synthetic-only-key", status=lambda: {"configured": True}
    )
    csrf = token(c)
    response = c.post(
        "/image-studio/drafts",
        data={
            "csrf_token": csrf,
            "prompt": "합성 결과 불명 보호",
            "model": "gpt-image-2.5-flare-2026-09-08",
            "provider": "openai",
            "size": "1024x1024",
            "quality": "low",
        },
    )
    assert response.status_code == 303
    identifier = c.get("/api/studio/modules/images").json()["collections"]["drafts"][0]["id"]
    for _ in range(2):
        assert (
            c.post(
                f"/image-studio/{identifier}/generate",
                data={"csrf_token": csrf, "consent": "true", "reviewed": "true"},
            ).status_code
            == 303
        )
    item = c.get("/api/studio/modules/images").json()["collections"]["drafts"][0]
    assert fake.calls == 1 and item["status"] == "unknown" and item["mediaUrl"] is None
    assert c.get(f"/image-studio/{identifier}/file").status_code != 200
    assert (
        c.post(
            f"/image-studio/{identifier}/reuse",
            data={"csrf_token": csrf, "reviewed": "true", "target": "news"},
        ).status_code
        == 422
    )
    with app.state.sessions() as s:
        rows = list(s.scalars(select(IntelligenceRun).where(IntelligenceRun.kind == "feed_image")))
        assert len(rows) == 1 and rows[0].status == "unknown"
        assert rows[0].options["style"] == "studio" and rows[0].options["draft_id"] == identifier
        assert rows[0].result["usage"] is None


def test_character_quote_approval_and_unknown_submission_are_one_shot(client):
    c, app = client
    from PIL import Image

    from newsflow.character.higgsfield_client import HiggsfieldVideoClient
    from newsflow.character.schema import Storyboard
    from newsflow.intelligence.api_settings import FakeAPIBudgetService, save_api_settings

    save_api_settings(
        app.state.sessions,
        "claude_api",
        model="claude-sonnet-4-6",
        approved=True,
        search_enabled=False,
        search_approved=False,
        monthly_limit_usd="30",
        input_price_per_1m="3",
        output_price_per_1m="15",
        search_price_per_1k="10",
    )

    class Writer:
        calls = 0

        def __init__(self):
            self.last_usage = {"prompt_tokens": 100, "completion_tokens": 200}

        def write(self, payload, options):
            self.calls += 1
            return Storyboard.model_validate(
                {
                    "plan": {
                        "situation": "합성 아침",
                        "contrast": "분주함과 여유",
                        "punchline": "잠깐의 휴식",
                    },
                    "title": "합성 이야기",
                    "hook_caption": "분주한 아침",
                    "scenes": [
                        {
                            "seconds": 10,
                            "role": role,
                            "action": "The character calmly holds a cup in an office.",
                            "caption": "합성 장면",
                            "sfx": "",
                        }
                        for role in ["setup", "contrast", "punchline"]
                    ],
                    "end_caption": "합성 이야기 끝",
                }
            )

    class Video:
        calls = 0
        uploads = 0
        credential = staticmethod(lambda: "synthetic-only-higgsfield-key")
        payload = staticmethod(HiggsfieldVideoClient.payload)

        def upload_reference(self, path):
            self.uploads += 1
            return "https://example.invalid/synthetic-reference.png"

        def estimate(self, payload):
            return "0.50"

        def submit_scene(self, *args):
            self.calls += 1
            raise TimeoutError("synthetic unknown")

    writer, video = Writer(), Video()
    service = app.state.character
    service.writer = writer
    service.video = video
    service.video_override = video
    service.keys = NS(status=lambda: {"configured": True})
    service.budget = FakeAPIBudgetService(app.state.sessions)
    image = BytesIO()
    Image.new("RGB", (144, 256), "brown").save(image, "PNG")
    csrf = token(c)
    saved = c.post(
        "/character",
        data={
            "csrf_token": csrf,
            "topic": "합성 이야기",
            "episode_limit": "5",
            "day_limit": "20",
            "script_model": "claude-sonnet-4-6",
        },
        files={"reference": ("synthetic.png", image.getvalue(), "image/png")},
    )
    assert saved.status_code == 303, saved.text
    job = service.listing()[0]
    identifier = job["id"]

    def act(action, **extra):
        return c.post(f"/character/{identifier}/{action}", data={"csrf_token": csrf, **extra})

    act("write")
    assert writer.calls == 0 and service.read(identifier)["state"] == "needs_script"
    act("write", consent="true")
    assert writer.calls == 1 and service.read(identifier)["state"] == "script_review"
    act("prepare", consent="true")
    assert video.uploads == 0
    act("prepare", consent="true", reviewed="true")
    quoted = service.read(identifier)
    assert quoted["state"] == "quoted" and quoted["quote_total_usd"] == "1.50"
    act("submit", quote_hash=quoted["quote_hash"])
    assert video.calls == 0
    act("submit", consent="true", quote_hash="0" * 64)
    assert video.calls == 0
    act("submit", consent="true", quote_hash=quoted["quote_hash"])
    unknown = service.read(identifier)
    assert unknown["state"] == "submission_unknown" and unknown["scenes"][0]["state"] == "unknown"
    act("submit", consent="true", quote_hash=quoted["quote_hash"])
    assert video.calls == 1 and service.read(identifier) == unknown


def test_publish_review_and_final_approval_are_separate_and_unknown_is_locked(client, monkeypatch):
    c, app = client
    from pydantic import SecretStr

    from newsflow.oauth.contracts import YOUTUBE_UPLOAD_SCOPE
    from newsflow.publishing.auth import TokenBundle
    from newsflow.publishing.live import LivePublishingService
    from newsflow.publishing.media import FakeMediaInspector
    from newsflow.publishing.service import PublishingService
    from newsflow.publishing.unified import UnifiedPublishingService

    class Connections:
        calls = 0

        def access_for_upload(self, account_id, *, consent=False):
            assert consent is True
            self.calls += 1
            return TokenBundle(
                access_token=SecretStr("synthetic-never-sent"),
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                scopes=(YOUTUBE_UPLOAD_SCOPE,),
            ), "UC" + "a" * 22

    class Adapter:
        calls = 0

        def upload(self, *args):
            self.calls += 1
            raise RuntimeError("synthetic uncertain result")

    identifier, path = synthetic_video(app)
    inspector = FakeMediaInspector()
    connections = Connections()
    adapter = Adapter()
    local = PublishingService(app.state.sessions, app.state.video.outputs, inspector)
    account = local.add_account("youtube", "합성 계정", "youtube_channel")
    live = LivePublishingService(
        app.state.sessions, app.state.video.outputs, connections, inspector, lambda: adapter
    )
    unified = UnifiedPublishingService(
        app.state.sessions, app.state.video.outputs, live, app.state.instagram, inspector
    )
    app.state.unified_publishing = unified
    monkeypatch.setattr(app.state.youtube, "status", lambda: {"accounts": [{"id": account, "ready": True}]})
    csrf = token(c)
    fields = {
        "csrf_token": csrf,
        "render_job_id": identifier,
        "target": "youtube",
        "title": "합성 검토",
        "description": "합성 자료입니다.",
        "hashtags": "뉴스",
        "youtube_account": account,
        "youtube_category_id": "25",
        "content_reviewed": "true",
        "copyright_confirmed": "true",
        "sources_confirmed": "true",
        "ai_disclosure": "not_required",
    }
    assert c.post("/publishing/unified/local-draft", data=fields).status_code == 303
    assert unified.local_draft(identifier)["approval"] is False
    review_response = c.post("/publishing/unified/review", data=fields)
    assert review_response.status_code == 303, review_response.text
    cohort = unified.for_video(identifier)
    assert cohort["reviewed"] and cohort["can_execute"]
    assert adapter.calls == connections.calls == 0
    url = f"/publishing/unified/{cohort['id']}/execute"
    assert (
        c.post(
            url, data={"csrf_token": csrf, "approval_token": cohort["approval_token"], "made_for_kids": "no"}
        ).status_code
        == 422
    )
    assert (
        c.post(
            url,
            data={"csrf_token": csrf, "approval_token": "0" * 64, "consent": "true", "made_for_kids": "no"},
        ).status_code
        == 422
    )
    assert adapter.calls == connections.calls == 0
    approval = {
        "csrf_token": csrf,
        "approval_token": cohort["approval_token"],
        "consent": "true",
        "made_for_kids": "no",
        "privacy": "private",
    }
    assert c.post(url, data=approval).status_code == 303
    result = unified.get(cohort["id"])
    assert result["locked"] and not result["can_execute"]
    assert result["results"][0]["status"] == "unknown" and adapter.calls == 1
    c.post(url, data=approval)
    assert adapter.calls == 1 and unified.get(cohort["id"])["results"][0]["status"] == "unknown"
    assert path.exists()
