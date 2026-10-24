"""C-stage shared UI only; isolated DB/media and no provider network calls."""

from unittest.mock import Mock

import pytest
from conftest import csrf
from sqlalchemy import select
from test_instagram_gui import instagram_ui as instagram_fixture
from test_settings_simplification import Document
from test_youtube_gui import forbid_external_calls  # noqa: F401 - autouse network guard
from test_youtube_gui import youtube_media as media_fixture
from test_youtube_gui import youtube_ui as youtube_fixture

from newsflow.db.models import AppSetting, PublishDraft
from newsflow.publishing.unified import UnifiedPublishingService

instagram_ui = instagram_fixture
youtube_ui = youtube_fixture
youtube_media = media_fixture


@pytest.fixture
def unified(app, instagram_ui, youtube_ui):
    service = UnifiedPublishingService(app.state.sessions, app.state.video.outputs,
                                      youtube_ui[1], instagram_ui[1], app.state.publishing_inspector)
    app.state.unified_publishing = service
    return service


def values(client, media, youtube, instagram, **changes):
    return {"csrf_token": csrf(client), "render_job_id": media, "target": "both",
            "youtube_account": youtube[2], "instagram_account": instagram[2], "title": "통합 검토 영상",
            "description": "합성 자료입니다.", "hashtags": "#합성", "youtube_category_id": "25", "content_reviewed": "true",
            "copyright_confirmed": "true", "sources_confirmed": "true", "ai_disclosure": "disclose", **changes}


def test_workspace_has_one_target_and_no_external_activity(unified, client, youtube_media, youtube_ui, instagram_ui):
    page = client.get(f"/?video={youtube_media}&publish_platform=unified")
    assert page.status_code == 200
    assert 'id="publish-workspace"' in page.text and 'id="youtube-publish"' not in page.text
    assert "YouTube + Instagram" in page.text and "MP4만 저장" in page.text
    assert "https://example.com/synthetic-news" in page.text
    assert 'preload="none"' in page.text
    assert not youtube_ui[0].calls and not instagram_ui[0].calls
    assert not youtube_ui[1].calls and not instagram_ui[1].calls
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"


def test_common_review_saves_two_independent_drafts_and_unchecked_execution_consent(
    unified, client, app, youtube_media, youtube_ui, instagram_ui,
):
    response = client.post("/publishing/unified/review", data=values(client, youtube_media, youtube_ui, instagram_ui),
                           follow_redirects=False)
    assert response.status_code == 303
    page = client.get(response.headers["location"])
    assert page.status_code == 200
    cohort = unified.for_video(youtube_media)
    dom = Document(page.text)
    forms = dom.find("form", action=f"/publishing/unified/{cohort['id']}/execute")
    assert len(forms) == 1
    approvals = [node for node in dom.find("input", type="checkbox") if forms[0] in node.ancestors]
    assert {node.attrs["name"] for node in approvals} == {"consent", "youtube_public_consent", "instagram_public_consent"}
    assert all("checked" not in node.attrs for node in approvals)
    with app.state.sessions() as session:
        drafts = list(session.scalars(select(PublishDraft)))
        assert {draft.platform for draft in drafts} == {"youtube", "instagram"}
        assert len({draft.media_sha256 for draft in drafts}) == 1
    assert not youtube_ui[1].calls and not instagram_ui[1].calls


@pytest.mark.parametrize("field", ["content_reviewed", "sources_confirmed", "copyright_confirmed"])
def test_missing_review_never_offers_publish(unified, client, youtube_media, youtube_ui, instagram_ui, field):
    response = client.post("/publishing/unified/review", data=values(client, youtube_media, youtube_ui, instagram_ui,
                           **{field: "false"}))
    assert response.status_code == 200
    assert not unified.for_video(youtube_media)["can_execute"]
    assert "/execute\"" not in response.text


def test_local_download_and_old_urls_work_without_connected_accounts(unified, client, youtube_media, youtube_ui, instagram_ui):
    youtube_ui[0].channel["ready"] = False
    instagram_ui[0].account["ready"] = False
    for suffix in ("&publish_platform=unified", "", "&publish_platform=instagram"):
        page = client.get(f"/?video={youtube_media}{suffix}")
        assert page.status_code == 200
    assert client.get(f"/video/jobs/{youtube_media}/file?download=true").status_code == 200
    response = client.post("/publishing/unified/review", data=values(client, youtube_media, youtube_ui, instagram_ui))
    assert response.status_code == 422 and "MP4 저장" in response.text
    assert not youtube_ui[1].calls and not instagram_ui[1].calls


def test_execute_route_keeps_platform_approval_flags_and_refresh_is_read_only(
    unified, client, youtube_media, youtube_ui, instagram_ui,
):
    client.post("/publishing/unified/review", data=values(client, youtube_media, youtube_ui, instagram_ui))
    cohort = unified.for_video(youtube_media)
    unified.execute = Mock(return_value=cohort)
    data = {"csrf_token": csrf(client), "approval_token": cohort["approval_token"], "consent": "true",
            "made_for_kids": "no", "instagram_public_consent": "true"}
    response = client.post(f"/publishing/unified/{cohort['id']}/execute", data=data, follow_redirects=False)
    assert response.status_code == 303
    unified.execute.assert_called_once_with(cohort["id"], approval_token=cohort["approval_token"], consent=True,
        privacy="private", made_for_kids=False, youtube_public_consent=False, instagram_public_consent=True)
    assert client.get(response.headers["location"]).status_code == 200
    assert unified.execute.call_count == 1


@pytest.mark.parametrize("path", ["/publishing/unified/review", "/publishing/unified/1/execute",
                                  "/instagram/relay-config", "/instagram/connect/1/cancel", "/instagram/connect/1/page"])
def test_c_mutations_require_csrf_and_same_origin(client, path):
    for data, origin in [({"csrf_token": csrf(client)}, "https://foreign.example"),
                         ({"csrf_token": "wrong"}, "http://127.0.0.1")]:
        assert client.post(path, data=data, headers={"Origin": origin}).status_code == 403


def test_relay_setup_saves_nonsecret_config_without_login_or_other_setting_changes(client, app, monkeypatch):
    monkeypatch.setattr("webbrowser.open", Mock(side_effect=AssertionError("no browser on save")))
    with app.state.sessions() as session:
        before = dict(session.execute(select(AppSetting.key, AppSetting.value)).all())
    data = {"csrf_token": csrf(client), "url": "https://relay.example.com", "app_id": "123456"}
    assert client.post("/instagram/relay-config", data=data).status_code == 422
    response = client.post("/instagram/relay-config", data={**data, "consent": "true"})
    assert response.status_code == 200 and "Facebook으로 Instagram 연결" in response.text
    with app.state.sessions() as session:
        after = dict(session.execute(select(AppSetting.key, AppSetting.value)).all())
    assert {key: value for key, value in after.items() if not key.startswith("instagram.relay.")} == before
    assert after["instagram.relay.url"] == "https://relay.example.com"
    assert after["instagram.relay.app_id"] == "123456"
    assert app.state.instagram.accounts() == []


def test_instagram_page_selection_and_cancel_only_after_explicit_form(client, app, instagram_ui):
    connection = instagram_ui[0]
    connection.status = lambda: {"accounts": [], "connection_supported": True, "pending": True,
        "pending_account_id": 7, "awaiting_page": True, "pages": [{"id": "10001", "name": "합성 페이지", "instagram_id": "17840001"}]}
    connection.select_page, connection.cancel = Mock(), Mock()
    page = client.get("/simple-settings")
    assert page.status_code == 200 and "합성 페이지" in page.text
    data = {"csrf_token": csrf(client), "page_id": "10001"}
    assert client.post("/instagram/connect/7/page", data=data).status_code == 422
    assert not connection.select_page.called
    assert client.post("/instagram/connect/7/page", data={**data, "consent": "true"}, follow_redirects=False).status_code == 303
    connection.select_page.assert_called_once_with(7, "10001", consent=True)
    assert client.post("/instagram/connect/7/cancel", data={"csrf_token": csrf(client)}, follow_redirects=False).status_code == 303
    connection.cancel.assert_called_once_with(7)


def test_unexpected_publish_error_is_redacted(unified, client, youtube_media, youtube_ui, instagram_ui):
    client.post("/publishing/unified/review", data=values(client, youtube_media, youtube_ui, instagram_ui))
    cohort = unified.for_video(youtube_media)
    unified.execute = Mock(side_effect=ValueError("SYNTHETIC-SECRET-NEVER-ECHO"))
    response = client.post(f"/publishing/unified/{cohort['id']}/execute", data={"csrf_token": csrf(client),
                           "approval_token": cohort["approval_token"], "consent": "true"})
    assert response.status_code == 422 and "SYNTHETIC-SECRET" not in response.text
    assert "자동 재시도하지 않습니다" in response.text
