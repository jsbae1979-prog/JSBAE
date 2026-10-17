"""Isolated Instagram workspace contracts. No provider or operating data access."""

from dataclasses import dataclass, field

import pytest
from conftest import csrf
from sqlalchemy import select
from test_settings_simplification import Document
from test_youtube_gui import (
    forbid_external_calls,  # noqa: F401 - reused autouse network guard
    review_values,
)
from test_youtube_gui import (
    youtube_media as media_fixture,
)
from test_youtube_gui import (
    youtube_ui as connections_fixture,
)

from newsflow.db.models import AppSetting, PlatformAccount, PublishDraft, PublishJob

youtube_media = media_fixture
youtube_ui = connections_fixture


@dataclass
class FakeInstagram:
    account: dict
    calls: list = field(default_factory=list)

    def status(self):
        return {"configured": True, "connection_supported": True, "accounts": [self.account]}

    def begin(self, **options):
        self.calls.append(options)


@dataclass
class FakePublishing:
    calls: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    failure: bool = False

    def results(self):
        return self.rows

    def prepare(self, identifier, **options):
        self.calls.append(("prepare", identifier, options))
        if self.failure:
            raise RuntimeError("SYNTHETIC-META-TOKEN-NEVER-REFLECT")

    def check(self, identifier, **options):
        self.calls.append(("check", identifier, options))

    def publish(self, identifier, **options):
        self.calls.append(("publish", identifier, options))


@pytest.fixture
def instagram_ui(app, youtube_ui):
    with app.state.sessions.begin() as session:
        account = PlatformAccount(platform="instagram", label="합성 Reels 계정", account_type="business",
                                  status="configured", scopes=[], api_ready=True)
        session.add(account)
        session.flush()
        account_id = account.id
    connections = FakeInstagram({"id": account_id, "label": "합성 Reels 계정", "instagram_id": "17840001",
                                 "page_id": "10001", "status": "connected", "ready": True,
                                 "message": "합성 연결 상태"})
    publishing = FakePublishing()
    app.state.instagram, app.state.instagram_publishing = connections, publishing
    return connections, publishing, account_id


def save_review(client, app, instagram_ui, render_id, **changes):
    response = client.post("/instagram/draft", data=review_values(client, render_id, instagram_ui[2], **changes),
                           follow_redirects=False)
    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/?video={render_id}&publish_platform=instagram#instagram-publish"
    with app.state.sessions() as session:
        return session.scalar(select(PublishDraft).where(PublishDraft.platform == "instagram")
                              .order_by(PublishDraft.id.desc())).id


def test_default_connection_is_honestly_blocked_without_meta_requests(client, app):
    page = client.get("/simple-settings")
    assert page.status_code == 200 and 'id="instagram"' in page.text
    assert "BLOCKED · 공식 로그인 연결 준비 필요" in page.text
    assert "공유 App Secret" in page.text
    assert not Document(page.text).find("form", action="/instagram/connect")
    response = client.post("/instagram/connect", data={"csrf_token": csrf(client), "consent": "true"})
    assert response.status_code == 422 and "HTTPS" in response.text
    assert app.state.instagram.accounts() == []


def test_settings_are_read_only_and_consent_unchecked(instagram_ui, youtube_ui, client, app):
    with app.state.sessions() as session:
        before = dict(session.execute(select(AppSetting.key, AppSetting.value)).all())
    page = client.get("/simple-settings")
    assert page.status_code == 200
    assert "합성 Reels 계정" in page.text and "합성 테스트 채널" in page.text
    dom = Document(page.text)
    form = dom.find("form", action="/instagram/connect")[0]
    assert all("checked" not in node.attrs for node in dom.find("input", name="consent") if form in node.ancestors)
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"
    with app.state.sessions() as session:
        assert dict(session.execute(select(AppSetting.key, AppSetting.value)).all()) == before
    assert not instagram_ui[0].calls and not instagram_ui[1].calls
    assert not youtube_ui[0].calls and not youtube_ui[1].calls


@pytest.mark.parametrize("consent", ["false", "true"])
def test_connection_requires_consent(instagram_ui, client, consent):
    response = client.post("/instagram/connect", data={"csrf_token": csrf(client), "consent": consent},
                           follow_redirects=False)
    assert response.status_code == (303 if consent == "true" else 422)
    assert instagram_ui[0].calls == ([{"consent": True}] if consent == "true" else [])


def test_one_video_has_platform_choice_and_independent_reviews(instagram_ui, youtube_media, client, app):
    youtube_response = client.post("/youtube/draft", data=review_values(client, youtube_media,
                                    app.state.youtube.channel["id"]), follow_redirects=False)
    assert youtube_response.status_code == 303
    draft_id = save_review(client, app, instagram_ui, youtube_media)
    with app.state.sessions() as session:
        assert {draft.platform for draft in session.scalars(select(PublishDraft))} == {"youtube", "instagram"}
    page = client.get(f"/?video={youtube_media}&publish_platform=instagram")
    assert page.status_code == 200 and 'id="instagram-publish"' in page.text
    assert f'action="/instagram/prepare/{draft_id}"' in page.text
    assert 'id="youtube-publish"' not in page.text
    assert "https://example.com/synthetic-news" in page.text
    assert f'href="/?video={youtube_media}#youtube-publish"' in page.text
    original = client.get(f"/?video={youtube_media}")
    assert original.status_code == 200 and 'id="youtube-publish"' in original.text
    assert 'id="instagram-publish"' not in original.text
    assert not instagram_ui[1].calls


@pytest.mark.parametrize("field", ["content_reviewed", "copyright_confirmed", "sources_confirmed"])
def test_missing_review_hides_upload(instagram_ui, youtube_media, client, app, field):
    draft_id = save_review(client, app, instagram_ui, youtube_media, **{field: "false"})
    page = client.get(f"/?video={youtube_media}&publish_platform=instagram")
    assert page.status_code == 200 and f'action="/instagram/prepare/{draft_id}"' not in page.text


def test_prepare_requires_consent_and_refresh_never_repeats(instagram_ui, youtube_media, client, app):
    draft_id = save_review(client, app, instagram_ui, youtube_media)
    values = {"csrf_token": csrf(client), "revision": 1}
    assert client.post(f"/instagram/prepare/{draft_id}", data=values).status_code == 422
    response = client.post(f"/instagram/prepare/{draft_id}", data={**values, "consent": "true"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert client.get(response.headers["location"]).status_code == 200
    assert instagram_ui[1].calls == [("prepare", draft_id, {"revision": 1, "consent": True})]


def test_ready_job_requires_exact_account_file_and_public_approval(instagram_ui, youtube_media, client, app):
    draft_id = save_review(client, app, instagram_ui, youtube_media)
    with app.state.sessions.begin() as session:
        job = PublishJob(draft_id=draft_id, platform="instagram", status="ig_ready", idempotency_key="synthetic-ig",
                         message="Synthetic processing complete")
        session.add(job)
        session.flush()
        job_id = job.id
    instagram_ui[1].rows = [{"id": job_id, "render_job_id": youtube_media, "account_id": instagram_ui[2],
                            "instagram_id": "17840001", "media_sha256": "a" * 64, "status": "ig_ready",
                            "message": "합성 처리 완료", "can_check": True, "can_publish": True}]
    page = client.get(f"/?video={youtube_media}&publish_platform=instagram")
    assert page.status_code == 200
    dom = Document(page.text)
    form = dom.find("form", action=f"/instagram/publish/{job_id}")[0]
    approvals = [node for node in dom.find("input") if form in node.ancestors and node.attrs.get("type") == "checkbox"]
    assert len(approvals) == 2 and all("checked" not in node.attrs for node in approvals)
    values = {"csrf_token": csrf(client), "account_id": instagram_ui[2], "media_sha256": "a" * 64,
              "consent": "true"}
    assert client.post(f"/instagram/publish/{job_id}", data=values).status_code == 422
    assert not instagram_ui[1].calls
    response = client.post(f"/instagram/publish/{job_id}", data={**values, "public_consent": "true"},
                           follow_redirects=False)
    assert response.status_code == 303
    assert instagram_ui[1].calls == [("publish", job_id, {"account_id": instagram_ui[2],
                                     "media_sha256": "a" * 64, "consent": True, "public_consent": True})]


@pytest.mark.parametrize("path", ["/instagram/connect", "/instagram/draft", "/instagram/prepare/1",
                                  "/instagram/check/1", "/instagram/publish/1"])
def test_mutations_require_origin_and_csrf(instagram_ui, client, path):
    token = csrf(client)
    for values, origin in [({"csrf_token": token}, "https://foreign.example"),
                           ({"csrf_token": "wrong"}, "http://127.0.0.1")]:
        assert client.post(path, data=values, headers={"Origin": origin}).status_code == 403
    assert not instagram_ui[0].calls and not instagram_ui[1].calls


def test_upstream_error_never_reflects_secret_or_retries(instagram_ui, youtube_media, client, app):
    draft_id = save_review(client, app, instagram_ui, youtube_media)
    instagram_ui[1].failure = True
    response = client.post(f"/instagram/prepare/{draft_id}", data={"csrf_token": csrf(client), "revision": 1,
                           "consent": "true"})
    assert response.status_code == 422 and "SYNTHETIC-META-TOKEN" not in response.text
    assert "자동 재시도하지 않습니다" in response.text
    assert client.get(f"/?video={youtube_media}&publish_platform=instagram").status_code == 200
    assert len(instagram_ui[1].calls) == 1


def test_unready_account_cannot_save_or_reuse_youtube_draft(instagram_ui, youtube_media, client, app):
    instagram_ui[0].account["ready"] = False
    response = client.post("/instagram/draft", data=review_values(client, youtube_media, instagram_ui[2]))
    assert response.status_code == 422
    with app.state.sessions() as session:
        assert session.scalar(select(PublishDraft)) is None
