"""Real JSON route, synthetic state, disposable Windows Actions only."""

from copy import deepcopy
from io import BytesIO

import pytest
from PIL import Image
from test_full_app_forms import client as client  # noqa: PLC0414 - reuse approved Windows-only fixture


@pytest.mark.parametrize(
    "status", ["quoted", "clips_review", "retry_quoted", "submission_unknown", "completed"]
)
def test_character_scene_display_preserves_jobs_and_approval_boundary(client, status):
    c, app = client
    png = BytesIO()
    Image.new("RGB", (128, 128), (60, 80, 120)).save(png, format="PNG")
    service = app.state.character
    job = service.create("Synthetic character display", "5", "20", reference=png.getvalue())
    if not isinstance(job, dict):
        job = service.read(job)
    job.update(
        state=status,
        script={
            "title": "Synthetic",
            "plan": {
                "situation": "Synthetic office",
                "contrast": "Busy and calm",
                "punchline": "A quiet ending",
            },
            "hook_caption": "Synthetic start",
            "end_caption": "Synthetic end",
            "scenes": [
                {
                    "seconds": 10,
                    "caption": f"Caption {i}",
                    "action": f"Action {i}",
                    "role": ["setup", "build", "punchline"][i - 1],
                    "sfx": "",
                }
                for i in range(1, 4)
            ],
        },
        scenes=[
            {
                "position": i,
                "state": "not_submitted",
                "quote_usd": "0.20",
                "payload": {"image_urls": ["https://private.invalid/reference"]},
                "idempotency_key": f"PRIVATE-IDEMPOTENCY-{i}",
            }
            for i in range(1, 4)
        ],
        quote_total_usd="0.60",
        quote_hash="old-approval",
        retry_hash="new-approval",
        retry={
            "position": 2,
            "quote_usd": "0.25",
            "at": "2026-10-27T00:00:00+00:00",
            "key_id": "PRIVATE-KEY-ID",
            "original": "PRIVATE-ORIGINAL",
        },
    )
    from newsflow.character.schema import Character, Storyboard, prompts

    story = Storyboard.model_validate(job["script"])
    job["script"] = story.model_dump()
    job["prompts"] = prompts(story, Character.model_validate(job["character"]))
    job["plan_hash"] = service.plan_hash(job)
    service.save(job)
    before = deepcopy(service.read(job["id"]))
    response = c.get("/api/studio/modules/characters")
    assert response.status_code == 200, response.text
    row = next(x for x in response.json()["collections"]["jobs"] if x["id"] == job["id"])
    assert [x["position"] for x in row["scenes"]] == [1, 2, 3]
    assert [x["seconds"] for x in row["scenes"]] == [10, 10, 10]
    assert [x["action"] for x in row["scenes"]] == ["Action 1", "Action 2", "Action 3"]
    assert all(x["mediaUrl"] is None for x in row["scenes"])
    assert row["mediaUrl"] is None
    if status == "retry_quoted":
        assert row["retry_hash"] == "new-approval"
        assert row["retryQuote"] == {"position": 2, "quote_usd": "0.25", "at": "2026-10-27T00:00:00+00:00"}
    else:
        assert "retryQuote" not in row
    for forbidden in ("private.invalid", "PRIVATE-IDEMPOTENCY", "PRIVATE-KEY-ID", "PRIVATE-ORIGINAL"):
        assert forbidden not in response.text
    assert service.read(job["id"]) == before

