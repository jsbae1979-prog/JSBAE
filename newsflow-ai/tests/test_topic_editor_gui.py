"""Safe local topic editing with isolated data; no API, CLI or voice process."""

import json
import re
from copy import deepcopy

import pytest
from conftest import csrf
from test_single_workspace import stored_values

from newsflow.db.models import AutopilotArtifact, AutopilotJob, ContentDraft, IntelligenceRun
from newsflow.intelligence.news_usage import assess_news_usage, safe_topic_script
from newsflow.video.supertonic_tts import SupertonicTTS
from newsflow.video.tts import WindowsTTS


@pytest.fixture(autouse=True)
def no_external_process_or_api(monkeypatch):
    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: pytest.fail("No live HTTP"))
    monkeypatch.setattr("subprocess.Popen", lambda *_a, **_k: pytest.fail("No CLI or voice process"))
    monkeypatch.setattr(WindowsTTS, "voice_details", lambda self: [])
    monkeypatch.setattr(SupertonicTTS, "voices", lambda self: [])


@pytest.fixture
def topic_draft(app):
    evidence = {"news_usage": "STANDARD", "articles": [{
        "id": 1, "title": "반도체 뉴스 목록", "summary": "합성 주제 참고 자료", "category": "it",
        "url": "https://example.com/technology/", "publisher": "Fixture", "published_at": None,
        "sources": [{"publisher": "Fixture", "url": "https://example.com/technology/"}],
    }]}
    evidence["news_usage_result"] = assess_news_usage(evidence)
    script = safe_topic_script(evidence, 60)
    job_id = "b" * 32
    with app.state.sessions.begin() as session:
        run = IntelligenceRun(kind="script", provider="local_topic_template", status="success",
                              options={"model": "local_topic_template"}, evidence=evidence,
                              result=script, message="합성 로컬 대본")
        session.add(run)
        session.flush()
        draft = ContentDraft(run_id=run.id, duration=60, content=script, sources=evidence,
                             review_status="review_required")
        session.add(draft)
        session.add(AutopilotJob(id=job_id, active_slot=1, mode="guided", source="feeds", duration=60,
                                platform="youtube", content_mode="real", ai_mode="claude_api",
                                status="waiting_review", current_stage="script", progress=50,
                                stage_results={"request": {"news_usage": "STANDARD"}}))
        session.flush()
        session.add(AutopilotArtifact(job_id=job_id, kind="content_draft_id", reference=str(draft.id)))
        return draft.id, job_id, deepcopy(script), deepcopy(evidence)


def test_topic_editor_only_offers_known_local_variants_and_workspace_return(client, app, topic_draft):
    draft_id, job_id, script, _ = topic_draft
    before = stored_values(app)
    response = client.get(f"/ai?draft_id={draft_id}&return_to=https://foreign.example")
    assert response.status_code == 200
    html = response.text
    assert "실제 처리: 주제 설명 템플릿" in html and "원문 사실 NOT VERIFIED" in html
    assert "추가 AI 호출 없음" in html and "보도 기반 미확인 초안:" not in html
    assert f'href="/?task={job_id}#workspace-detail"' in html and "foreign.example" not in html
    assert 'action="/ai/analyze"' not in html and 'action="/ai/generate"' not in html
    for name in ("title", "hook", "summary", "closing", "narration", "material"):
        assert all("readonly" in tag for tag in re.findall(rf'<(?:input|textarea)\b[^>]*name="{name}"[^>]*>', html))
    assert 'data-topic-editor-form' in html and 'data-topic-narration-short' in html
    assert re.search(r'<button[^>]*data-short-caption[^>]*disabled[^>]*>미확인 자막 유지</button>', html)
    choices = response.context["topic_options"]
    assert len(choices) == len(script["scenes"])
    assert choices[0]["protected"] and len(choices[0]["captions"]) == 1
    assert any(choice["short"] != choice["full"] for choice in choices)
    assert stored_values(app) == before


def test_save_short_narration_reorder_and_caption_preserves_review_and_source(client, app, topic_draft):
    draft_id, job_id, script, evidence = topic_draft
    page = client.get(f"/ai?draft_id={draft_id}")
    short = page.context["topic_options"][2]["short"]
    assert short != script["scenes"][2]["narration"]
    script["scenes"][2]["narration"] = short
    script["scenes"][2]["caption"] = "반도체"
    script["scenes"][1:] = reversed(script["scenes"][1:])
    before = stored_values(app)
    response = client.post(f"/ai/drafts/{draft_id}", data={
        "csrf_token": csrf(client), "revision": 1, "content": json.dumps(script, ensure_ascii=False),
    }, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/ai?draft_id={draft_id}"
    with app.state.sessions() as session:
        saved = session.get(ContentDraft, draft_id)
        assert saved.content == script and saved.sources == evidence and saved.revision == 2
        assert saved.review_status == "review_required"
        assert session.get(AutopilotJob, job_id).status == "waiting_review"
    after = client.get(response.headers["location"])
    assert f'href="/?task={job_id}#workspace-detail"' in after.text
    # Variants stay attached to scene roles after a saved reorder.
    assert after.context["topic_options"][2]["short"] == short
    assert stored_values(app) == before


def test_tampered_readonly_claim_and_missing_consent_guards_do_not_save(client, app, topic_draft):
    draft_id, _, script, evidence = topic_draft
    script["scenes"][1]["narration"] = "이번 제품의 매출이 9999억 원으로 확정되었습니다."
    payload = {"revision": 1, "content": json.dumps(script, ensure_ascii=False)}
    assert client.post(f"/ai/drafts/{draft_id}", data=payload).status_code == 403
    payload["csrf_token"] = csrf(client)
    assert client.post(f"/ai/drafts/{draft_id}", data=payload,
                       headers={"Origin": "https://foreign.example"}).status_code == 403
    response = client.post(f"/ai/drafts/{draft_id}", data=payload)
    assert response.status_code == 422 and "미확인 사실" in response.json()["detail"]
    with app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        assert draft.revision == 1 and draft.sources == evidence
        assert "9999" not in str(draft.content)


def test_ordinary_editor_is_preserved_and_unrelated_draft_cannot_choose_task(client, app, topic_draft):
    draft_id, job_id, _, evidence = topic_draft
    with app.state.sessions.begin() as session:
        original = session.get(ContentDraft, draft_id)
        evidence.pop("news_usage")
        evidence.pop("news_usage_result")
        other = ContentDraft(run_id=original.run_id, duration=60, content=original.content, sources=evidence)
        session.add(other)
        session.flush()
        other_id = other.id
    page = client.get(f"/ai?draft_id={other_id}&task={job_id}")
    assert page.status_code == 200 and page.context["workspace_return"] == "/"
    assert not page.context["topic_editor"] and 'action="/ai/analyze"' in page.text
    title = re.search(r'<input\b[^>]*name="title"[^>]*>', page.text).group(0)
    assert "readonly" not in title
