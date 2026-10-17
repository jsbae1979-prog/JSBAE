"""YouTube UI contracts use isolated records and Fake connections/uploads only."""

from __future__ import annotations

import http.client
import urllib.request
from dataclasses import dataclass, field
from unittest.mock import Mock
from uuid import uuid4

import pytest
from conftest import csrf
from sqlalchemy import select
from test_settings_simplification import Document

from newsflow.db.models import (
    AppSetting,
    ContentDraft,
    IntelligenceRun,
    PlatformAccount,
    PublishDraft,
    PublishValidation,
    RenderJob,
    VideoProject,
)
from newsflow.publishing.media import FakeMediaInspector
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS

MEDIA = {"format": "mp4", "playable": True, "video_codec": "h264", "audio_codec": "aac",
         "width": 1080, "height": 1920, "duration": 30.0, "fps": 30.0, "audio_channels": 2}


@dataclass
class FakeConnections:
    channel: dict
    calls: list = field(default_factory=list)
    configured: bool = True
    failure: bool = False

    def status(self):
        return {"client_configured": self.configured, "storage_supported": True, "pending": False,
                "accounts": [dict(self.channel)]}

    def save_client(self, raw_json):
        if self.failure:
            raise ValueError("SYNTHETIC-CLIENT-SECRET-NEVER-REFLECT")
        self.calls.append(("client", raw_json))

    def begin(self, *, consent, account_id=None):
        self.calls.append(("begin", consent, account_id))
        return self.channel["id"]

    def cancel(self, account_id):
        self.calls.append(("cancel", account_id))


@dataclass
class FakeUploads:
    calls: list = field(default_factory=list)
    failure: bool = False

    def results(self):
        return []

    def execute(self, draft_id, revision, **options):
        self.calls.append((draft_id, revision, options))
        if self.failure:
            raise RuntimeError("SYNTHETIC-UPLOAD-TOKEN-NEVER-REFLECT")
        return 1


@pytest.fixture(autouse=True)
def forbid_external_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("YouTube GUI tests must not contact a remote service")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", forbidden)
    monkeypatch.setattr(http.client.HTTPSConnection, "request", forbidden)
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: [])


@pytest.fixture
def youtube_ui(app):
    with app.state.sessions.begin() as session:
        account = PlatformAccount(platform="youtube", label="합성 테스트 채널", account_type="youtube_channel",
                                  status="configured", scopes=[], api_ready=True)
        session.add(account)
        session.flush()
        account_id = account.id
    connections = FakeConnections({"id": account_id, "label": "합성 테스트 채널", "channel_id": "UC" + "x" * 22,
                                   "status": "connected", "ready": True, "error_code": None, "expires_at": None,
                                   "message": "합성 연결 상태", "refresh_needed": False})
    uploads = FakeUploads()
    app.state.youtube, app.state.live_publishing = connections, uploads
    app.state.publishing_inspector = FakeMediaInspector(MEDIA.copy())
    return connections, uploads, account_id


@pytest.fixture
def youtube_media(app, youtube_ui):
    sources = {"articles": [{"title": "합성 뉴스 출처", "sources": [
        {"url": "https://example.com/synthetic-news", "publisher": "합성 출처"}]}]}
    with app.state.sessions.begin() as session:
        run = IntelligenceRun(kind="script", status="success", provider="offline", options={"model": "offline"},
                              evidence=sources, result={}, message="YouTube GUI synthetic fixture")
        session.add(run)
        session.flush()
        script = ContentDraft(run_id=run.id, duration=30, sources=sources,
                              content={"title": "합성 영상", "hook": "합성", "summary": "검토용", "scenes": []})
        session.add(script)
        session.flush()
        project = VideoProject(draft_id=script.id, title="합성 영상", duration=30,
                               snapshot=script.content, sources=sources)
        session.add(project)
        session.flush()
        render = RenderJob(project_id=project.id, status="success", progress=100,
                           output_name=f"video-{uuid4().hex}.mp4", message="Synthetic UI fixture, not real media",
                           metadata_json={**MEDIA, "adapter": "synthetic-ui-only"})
        session.add(render)
        session.flush()
        render_id, filename = render.id, render.output_name
    app.state.video.outputs.mkdir(parents=True, exist_ok=True)
    (app.state.video.outputs / filename).write_bytes(b"SYNTHETIC_YOUTUBE_UI_BYTES_NOT_REAL_MP4")
    return render_id


def review_values(client, render_id, account_id, **changes):
    values = {"csrf_token": csrf(client), "render_job_id": render_id, "account_id": account_id,
              "title": "합성 뉴스 검토 영상", "description": "사용자 검토를 위한 합성 영상입니다.",
              "hashtags": "#합성", "content_reviewed": "true", "copyright_confirmed": "true",
              "sources_confirmed": "true", "ai_disclosure": "disclose"}
    values.update(changes)
    return values


def save_review(client, app, youtube_ui, youtube_media, **changes):
    response = client.post("/youtube/draft", data=review_values(client, youtube_media, youtube_ui[2], **changes),
                           follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == f"/?video={youtube_media}#youtube-publish"
    with app.state.sessions() as session:
        return session.scalar(select(PublishDraft).order_by(PublishDraft.id.desc())).id


def test_settings_show_channel_without_login_upload_or_setting_changes(youtube_ui, client, app):
    connections, uploads, _ = youtube_ui
    with app.state.sessions() as session:
        before = dict(session.execute(select(AppSetting.key, AppSetting.value)).all())
    response = client.get("/simple-settings")
    assert response.status_code == 200 and 'id="youtube"' in response.text
    assert "합성 테스트 채널" in response.text
    dom = Document(response.text)
    login_form = dom.find("form", action="/youtube/connect")[0]
    consents = [node for node in dom.find("input", name="consent") if login_form in node.ancestors]
    assert consents and all("checked" not in node.attrs for node in consents)
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    with app.state.sessions() as session:
        assert dict(session.execute(select(AppSetting.key, AppSetting.value)).all()) == before
    assert connections.calls == uploads.calls == []


def test_client_registration_error_never_echoes_json_or_secret(youtube_ui, client):
    connections, _, _ = youtube_ui
    connections.failure = True
    response = client.post("/youtube/client", data={"csrf_token": csrf(client),
                          "client_json": '{"secret":"SYNTHETIC-CLIENT-SECRET-NEVER-REFLECT"}'})
    assert response.status_code == 422
    assert "SYNTHETIC-CLIENT-SECRET" not in response.text and "OAuth JSON" in response.text


@pytest.mark.parametrize("consent", [None, "false", "true"])
def test_google_login_requires_explicit_consent(youtube_ui, client, consent):
    connections, _, account_id = youtube_ui
    values = {"csrf_token": csrf(client), "account_id": account_id}
    if consent is not None:
        values["consent"] = consent
    response = client.post("/youtube/connect", data=values, follow_redirects=False)
    assert response.status_code == (303 if consent == "true" else 422)
    assert connections.calls == ([("begin", True, account_id)] if consent == "true" else [])


def test_pending_login_can_be_cancelled_without_upload(youtube_ui, client):
    connections, uploads, account_id = youtube_ui
    response = client.post(f"/youtube/connect/{account_id}/cancel", data={"csrf_token": csrf(client)},
                           follow_redirects=False)
    assert response.status_code == 303
    assert connections.calls == [("cancel", account_id)] and not uploads.calls


@pytest.mark.parametrize("path,origin,valid_token", [
    ("/youtube/connect", "https://foreign.example", True),
    ("/youtube/client", "null", True),
    ("/youtube/publish/1", "http://127.0.0.1", False),
    ("/youtube/draft", "http://127.0.0.1", False),
])
def test_youtube_actions_keep_origin_and_csrf_gates(youtube_ui, client, path, origin, valid_token):
    token = csrf(client)
    response = client.post(path, data={"csrf_token": token if valid_token else "invalid", "consent": "true"},
                           headers={"Origin": origin})
    assert response.status_code == 403
    assert youtube_ui[0].calls == youtube_ui[1].calls == []


@pytest.mark.parametrize("field,key", [("content_reviewed", "content_review"),
                                      ("copyright_confirmed", "copyright_review"),
                                      ("sources_confirmed", "source_review")])
def test_saved_review_keeps_missing_required_confirmation_blocked(youtube_ui, youtube_media, client, app, field, key):
    draft_id = save_review(client, app, youtube_ui, youtube_media, **{field: "false"})
    with app.state.sessions() as session:
        row = session.scalar(select(PublishValidation).where(PublishValidation.draft_id == draft_id))
        assert next(item for item in row.results if item["key"] == key)["status"] == "fail"
    page = client.get(f"/?video={youtube_media}")
    assert page.status_code == 200 and 'id="youtube-publish"' in page.text
    assert not youtube_ui[1].calls
    dom = Document(page.text)
    submit_forms = dom.find("form", action=f"/youtube/publish/{draft_id}")
    for form in submit_forms:
        buttons = [node for node in dom.find("button", type="submit") if form in node.ancestors]
        assert not buttons or all("disabled" in button.attrs for button in buttons)


def test_review_ready_channel_and_sources_are_kept_in_same_workspace(youtube_ui, youtube_media, client, app):
    draft_id = save_review(client, app, youtube_ui, youtube_media)
    response = client.get(f"/?video={youtube_media}")
    assert response.status_code == 200
    assert "https://example.com/synthetic-news" in response.text
    assert f'action="/youtube/publish/{draft_id}"' in response.text
    dom = Document(response.text)
    privacy = dom.find("select", name="privacy")[0]
    options = [node for node in dom.find("option") if privacy in node.ancestors]
    assert "selected" in next(node for node in options if node.attrs["value"] == "private").attrs
    assert not youtube_ui[0].calls and not youtube_ui[1].calls


def test_unready_channel_cannot_save_publish_draft(youtube_ui, youtube_media, client, app):
    youtube_ui[0].channel["ready"] = False
    response = client.post("/youtube/draft", data=review_values(client, youtube_media, youtube_ui[2]))
    assert response.status_code == 422
    with app.state.sessions() as session:
        assert session.scalar(select(PublishDraft)) is None


def test_private_upload_is_explicit_and_refresh_does_not_repeat_it(youtube_ui, youtube_media, client, app):
    draft_id = save_review(client, app, youtube_ui, youtube_media)
    response = client.post(f"/youtube/publish/{draft_id}", data={"csrf_token": csrf(client), "revision": 1,
                           "made_for_kids": "no", "consent": "true"}, follow_redirects=False)
    assert response.status_code == 303
    assert youtube_ui[1].calls == [(draft_id, 1, {"privacy": "private", "made_for_kids": False,
                                                "consent": True, "public_consent": False})]
    assert client.get(response.headers["location"]).status_code == 200
    assert len(youtube_ui[1].calls) == 1


@pytest.mark.parametrize("changes", [{"made_for_kids": ""}, {"consent": "false"},
                                     {"privacy": "public"}, {"privacy": "unlisted"}])
def test_upload_missing_decision_or_public_consent_does_not_execute(youtube_ui, youtube_media, client, app, changes):
    draft_id = save_review(client, app, youtube_ui, youtube_media)
    values = {"csrf_token": csrf(client), "revision": 1, "made_for_kids": "no", "consent": "true"}
    response = client.post(f"/youtube/publish/{draft_id}", data={**values, **changes})
    assert response.status_code == 422 and not youtube_ui[1].calls


def test_upload_error_is_safe_and_never_replayed(youtube_ui, youtube_media, client, app):
    draft_id = save_review(client, app, youtube_ui, youtube_media)
    youtube_ui[1].failure = True
    response = client.post(f"/youtube/publish/{draft_id}", data={"csrf_token": csrf(client), "revision": 1,
                           "made_for_kids": "no", "consent": "true"})
    assert response.status_code == 422 and "SYNTHETIC-UPLOAD-TOKEN" not in response.text
    assert "자동 재시도하지 않습니다" in response.text
    assert len(youtube_ui[1].calls) == 1
    assert client.get(f"/?video={youtube_media}").status_code == 200
    assert len(youtube_ui[1].calls) == 1


def test_publishing_error_does_not_expose_unexpected_provider_message(youtube_ui, youtube_media, client, app):
    draft_id = save_review(client, app, youtube_ui, youtube_media)
    youtube_ui[1].execute = Mock(side_effect=ValueError("SYNTHETIC-RESPONSE-SECRET"))
    response = client.post(f"/youtube/publish/{draft_id}", data={"csrf_token": csrf(client), "revision": 1,
                           "made_for_kids": "yes", "privacy": "public", "public_consent": "true", "consent": "true"})
    assert response.status_code == 422 and "SYNTHETIC-RESPONSE-SECRET" not in response.text
    assert youtube_ui[1].execute.call_count == 1
