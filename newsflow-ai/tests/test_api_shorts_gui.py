"""API draft editing and honest consent text, using isolated fixtures only."""

import json
import re

import pytest
import test_topic_editor_gui
from conftest import csrf
from test_single_workspace import stored_values

from newsflow.db.models import ContentDraft, IntelligenceRun
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS

topic_draft = test_topic_editor_gui.topic_draft


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: pytest.fail("No live HTTP"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI or TTS"))
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: [])


def test_api_draft_is_editable_without_local_string_match_and_keeps_review(client, app, topic_draft):
    identifier, job_id, script, evidence = topic_draft
    evidence = {**evidence, "script_method": "api_grounded_v1"}
    with app.state.sessions.begin() as session:
        draft = session.get(ContentDraft, identifier)
        draft.sources = evidence
        run = session.get(IntelligenceRun, draft.run_id)
        run.provider, run.evidence = "claude_api", evidence
        run.options = {"model": "claude-sonnet-4-6"}
    before = stored_values(app)
    page = client.get(f"/ai?draft_id={identifier}")
    assert page.status_code == 200 and page.context["api_editor"]
    assert not page.context["topic_editor"] and page.context["topic_options"] == []
    assert "선택한 API가 작성한 미확인 초안" in page.text
    assert "주제 설명 템플릿 · 추가 AI 호출 없음" not in page.text
    assert 'action="/ai/analyze"' not in page.text
    for field in ("title", "hook", "narration", "caption", "material"):
        tags = re.findall(rf'<(?:input|textarea)\b[^>]*name="{field}"[^>]*>', page.text)
        assert tags and all("readonly" not in tag for tag in tags)
    script["scenes"][1]["narration"] = "반도체를 고를 때 사용 목적과 전력 소비를 함께 살펴볼 수 있습니다."
    response = client.post(f"/ai/drafts/{identifier}", data={
        "csrf_token": csrf(client), "revision": 1, "content": json.dumps(script, ensure_ascii=False),
    }, follow_redirects=False)
    assert response.status_code == 303
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, identifier)
        assert draft.content == script and draft.sources == evidence
        assert draft.revision == 2 and draft.review_status == "review_required"
    assert f'href="/?task={job_id}#workspace-detail"' in page.text
    assert stored_values(app) == before


def test_api_editor_preserves_csrf_origin_and_duration_validation(client, app, topic_draft):
    identifier, _, script, evidence = topic_draft
    with app.state.sessions.begin() as session:
        session.get(ContentDraft, identifier).sources = {**evidence, "script_method": "api_grounded_v1"}
    payload = {"revision": 1, "content": json.dumps(script, ensure_ascii=False)}
    assert client.post(f"/ai/drafts/{identifier}", data=payload).status_code == 403
    payload["csrf_token"] = csrf(client)
    assert client.post(f"/ai/drafts/{identifier}", data=payload,
                       headers={"Origin": "https://foreign.example"}).status_code == 403
    script["scenes"][0]["seconds"] += 1
    payload["content"] = json.dumps(script, ensure_ascii=False)
    assert client.post(f"/ai/drafts/{identifier}", data=payload).status_code == 422
    with app.state.sessions() as session:
        assert session.get(ContentDraft, identifier).revision == 1
