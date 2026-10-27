"""Original model-setting forms and immutable job selections; approved Windows only."""

from copy import deepcopy

from test_full_app_forms import client as client  # noqa: PLC0414 - pytest fixture reuse
from test_full_app_forms import token


def test_creation_defaults_restore_independently_without_mutating_saved_jobs(client):
    c, app = client
    from newsflow.creation.catalog import DEFAULTS, IMAGE_MODELS

    csrf = token(c)
    initial = deepcopy(DEFAULTS["image"])
    response = c.post(
        "/image-studio/drafts", data={"csrf_token": csrf, "prompt": "합성 모델 고정 확인", **initial}
    )
    assert response.status_code == 303, response.text
    identifier = c.get("/api/studio/modules/images").json()["collections"]["drafts"][0]["id"]
    frozen = deepcopy(app.state.image_studio.get(identifier).options["selection"])
    selected = {"provider": "openai", "model": IMAGE_MODELS[1], "size": "864x1536", "quality": "high"}
    saved = c.post("/image-studio/defaults", data={"csrf_token": csrf, **selected})
    assert saved.status_code == 303, saved.text
    restored = c.get("/api/studio/modules/images").json()["catalog"]["imageDefaults"]
    assert restored == selected
    assert app.state.image_studio.get(identifier).options["selection"] == frozen
    assert (
        c.post(
            "/image-studio/defaults", data={"csrf_token": csrf, **selected, "provider": "claude_api"}
        ).status_code
        == 422
    )
    assert c.get("/api/studio/modules/images").json()["catalog"]["imageDefaults"] == selected
    char_before = c.get("/api/studio/modules/characters").json()["catalog"]["characterDefaults"]
    char_selected = {**char_before, "script_model": "claude-haiku-4-5-20251001"}
    result = c.post(
        "/character-defaults",
        data={
            "csrf_token": csrf,
            "script_model": char_selected["script_model"],
            "video_model": char_selected["video_model"],
        },
    )
    assert result.status_code == 303, result.text
    assert c.get("/api/studio/modules/characters").json()["catalog"]["characterDefaults"] == char_selected
    assert c.get("/api/studio/modules/images").json()["catalog"]["imageDefaults"] == selected
    response = c.post(
        "/ai/preferences",
        data={
            "csrf_token": csrf,
            "provider": "claude_api",
            "model": "claude-sonnet-4-6",
            "return_to": "settings",
        },
    )
    assert response.status_code == 303, response.text
    read = c.get("/api/studio/modules/shorts").json()
    assert read["formDefaults"]["intelligence_analyze"] == {
        "provider": "claude_api",
        "model": "claude-sonnet-4-6",
    }
    assert c.get("/api/studio/modules/characters").json()["catalog"]["characterDefaults"] == char_selected
    assert app.state.image_studio.get(identifier).options["selection"] == frozen
    assert (
        c.post(
            f"/image-studio/{identifier}/reuse",
            data={"csrf_token": csrf, "reviewed": "true", "target": "news"},
        ).status_code
        == 422
    )
    assert c.get("/api/studio/modules/images").json()["collections"]["drafts"][0]["status"] == "saved"


def test_provider_key_form_targets_fake_store_without_returning_secret(client):
    c, app = client

    class FakeKeys:
        def __init__(self):
            self.saved = []

        def save(self, value):
            self.saved.append(value)

        def status(self):
            return {"configured": bool(self.saved)}

        def key(self):
            raise AssertionError("Key loading/decryption is forbidden in this test")

    stores = {provider: FakeKeys() for provider in ("openai", "claude_api")}
    app.state.api_keys = stores
    csrf = token(c)
    for provider, store in stores.items():
        marker = "SYNTHETIC-KEY-ONLY-" + provider
        path = f"/api-settings/{provider}/key"
        assert c.post(path, data={"api_key": marker}).status_code == 403
        assert store.saved == []
        response = c.post(path, data={"csrf_token": csrf, "api_key": marker})
        assert response.status_code == 303, response.text
        assert store.saved == [marker]
        assert marker not in response.text
        assert marker not in c.get("/api/studio/modules/settings").text
    assert stores["openai"].saved != stores["claude_api"].saved
