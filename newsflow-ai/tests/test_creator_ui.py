"""Creator views reuse existing contracts. Synthetic records only, no remote calls."""
import hashlib
from copy import deepcopy

import pytest
from conftest import csrf
from test_single_workspace import stored_values, video_fixture

from newsflow.db.models import ContentDraft, RenderJob
from newsflow.intelligence.provider import FakeProvider, Options
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS


@pytest.fixture(autouse=True)
def local_only(monkeypatch):
    def blocked(*args, **kwargs):
        pytest.fail("Creator UI must not call remote services or launch authentication")
    monkeypatch.setattr("urllib.request.OpenerDirector.open", blocked)
    monkeypatch.setattr("subprocess.Popen", blocked)
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda _: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda _: [])


@pytest.mark.parametrize("path", ["/", "/create", "/videos", "/queue", "/simple-settings", "/news"])
def test_navigation_and_read_only_views_preserve_settings_and_security(client, app, path):
    before = stored_values(app)
    response = client.get(path)
    assert response.status_code == 200
    for href in ("/create", "/videos", "/queue", "/simple-settings"):
        assert f'href="{href}"' in response.text
    assert "script-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"
    assert stored_values(app) == before
    assert "UI 데모" not in response.text  # Only the isolated launcher labels a demo.


def test_topic_search_honestly_uses_existing_news_search_not_new_generation_contract(client):
    response = client.get("/")
    assert 'action="/news" method="get" data-topic-search' in response.text
    assert 'id="home-topic" name="q"' in response.text
    assert "이미 수집해 보관한 기사만 검색합니다" in response.text
    assert "보관 기사 검색" in response.text
    assert "기사를 선택한 뒤 분석·대본 작성" in response.text
    assert "새 기사 URL 가져오기" in response.text
    assert '<option value="VERIFIED"' not in response.text
    create = client.get("/create").text
    assert 'action="/autopilot/quick-start"' in create and 'name="csrf_token"' in create
    for step in ("영상 제작 전에 대본 확인하기", "실제 제작 AI", "자동 제작 시작", "뉴스 자료"):
        assert step in create
    assert '<input name="topic"' not in create  # No field silently discarded by the backend.


def test_editor_shares_guarded_existing_media_without_touching_output(client, app):
    media = video_fixture(app, "긴 한글 제목 " * 12)
    path = app.state.video.outputs / media["output_name"]
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    page = client.get(f'/ai?draft_id={media["draft_id"]}')
    assert page.context["preview"]["id"] == media["id"]
    assert 'data-editor-player' in page.text and 'autoplay' not in page.text
    assert f'action="/ai/drafts/{media["draft_id"]}"' in page.text
    assert "기존 영상은 유지" in page.text and "저장만으로 음성·유료 AI를 호출하지 않습니다" in page.text
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert client.get(f'/video/jobs/{media["id"]}/file').content == path.read_bytes()


@pytest.mark.parametrize("status,playable,exists", [("running", True, True), ("success", False, True), ("success", True, False)])
def test_editor_never_invents_a_preview_for_invalid_output(client, app, status, playable, exists):
    media = video_fixture(app, "영상 확인 필요", status=status, playable=playable, exists=exists)
    page = client.get(f'/ai?draft_id={media["draft_id"]}')
    assert page.context["preview"] is None
    assert 'data-editor-player' not in page.text
    assert '이 대본으로 영상 구성' in page.text and f'/video?draft_id={media["draft_id"]}' in page.text


def test_scene_edit_save_uses_revision_and_leaves_existing_video_unchanged(client, app):
    media = video_fixture(app, "편집 검증")
    evidence = {"articles": [{"title": "편집 검증", "sources": []}]}
    script = FakeProvider().complete(evidence, 45, Options(model="offline"))
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, media["draft_id"])
        draft.content = script
    page = client.get(f'/ai?draft_id={media["draft_id"]}')
    assert page.text.count('data-edit-scene=') == 3
    updated = deepcopy(script)
    updated["scenes"][1]["caption"] = "직접 수정한 자막 · 확인 필요"
    import json
    payload = {"revision": 1, "content": json.dumps(updated, ensure_ascii=False)}
    assert client.post(f'/ai/drafts/{media["draft_id"]}', data=payload).status_code == 403
    payload["csrf_token"] = csrf(client)
    assert client.post(f'/ai/drafts/{media["draft_id"]}', data=payload).status_code == 200
    assert client.post(f'/ai/drafts/{media["draft_id"]}', data=payload).status_code == 409
    with app.state.sessions() as session:
        saved = session.get(ContentDraft, media["draft_id"])
        assert saved.revision == 2 and saved.content == updated
        assert saved.review_status != "approved"
        assert session.get(RenderJob, media["id"]).status == "success"


def test_library_loads_thumbnails_instead_of_all_media(client, app):
    media = video_fixture(app, "나의 영상")
    page = client.get("/videos")
    assert '<video ' not in page.text
    assert f'/video/jobs/{media["id"]}/thumbnail' in page.text
    assert f'/ai?draft_id={media["draft_id"]}' in page.text
    assert "실제 게시 기능은 연결하지 않았습니다" not in page.text
