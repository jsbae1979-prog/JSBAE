"""Stored TOP 3 image selection stays independent from character video settings."""
from copy import deepcopy
from types import SimpleNamespace

from sqlalchemy import func, select
from image_selection_fixture import selected
from test_api_settings import sessions

from newsflow.db.models import ImagePost, IntelligenceRun
from newsflow.publishing.image_selection import selection
from newsflow.studio.read_models import module_view


def test_image_module_reads_saved_top3_without_character_only_keys(sessions, monkeypatch):
    def stored_selection(analysis_id):
        with sessions() as session:
            return selection(session, analysis_id)

    state = SimpleNamespace(sessions=sessions, studio_synthetic=True, video=SimpleNamespace(),
                            image_posts=SimpleNamespace(selection=stored_selection))
    app = SimpleNamespace(state=state)
    analysis_id, article_ids, _draft_id = selected.__wrapped__(app, monkeypatch)
    with sessions() as session:
        original = deepcopy(session.get(IntelligenceRun, analysis_id).result)
        run_count = session.scalar(select(func.count()).select_from(IntelligenceRun))
    result = module_view(SimpleNamespace(app=app, state=SimpleNamespace()), "images")
    assert result["module"] == "images"
    selections = result["collections"]["selections"]
    group = next(item for item in selections if item["id"] == analysis_id)
    assert group["status"] == "success"
    assert [item["rank"] for item in group["ranking"]] == [1, 2, 3]
    assert set(article_ids) == {article_id for item in group["ranking"] for article_id in item["article_ids"]}
    for item in group["ranking"]:
        assert item["title"] and item["body"] and item["references"]
        assert not {"studio_selection", "duration", "model", "claude_model"}.intersection(item)
    with sessions() as session:
        assert session.get(IntelligenceRun, analysis_id).result == original
        assert session.scalar(select(func.count()).select_from(IntelligenceRun)) == run_count
        assert session.scalar(select(func.count()).select_from(ImagePost)) == 0
