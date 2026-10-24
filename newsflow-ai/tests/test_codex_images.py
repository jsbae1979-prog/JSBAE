"""No real CLI, account, provider or operating data access in these tests."""
import base64
import copy
import json
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import csrf
from PIL import Image
from sqlalchemy import select
from test_codex_adapter import FakeRPC, effective_config
from test_image_posts import article

from newsflow.db.models import AIUsage, AppSetting
from newsflow.intelligence import codex
from newsflow.intelligence.provider import ProviderTimeoutError
from newsflow.publishing import codex_images as native
from newsflow.publishing.image_generation import (
    ImageGenerationError,
    ImageGenerationService,
    clean_codex_image,
)
from newsflow.publishing.service import PublishingError

OFFLINE_TOOL_MODE = native.bundled_tool_mode


def png():
    output = BytesIO()
    Image.new("RGB", (800, 1000), "#204050").save(output, "PNG")
    return output.getvalue()


def events():
    return [
        {"method": "item/completed", "params": {"item": {
            "type": "imageGeneration", "id": "image-1", "status": "completed", "savedPath": None,
            "result": base64.b64encode(png()).decode()}}},
        {"method": "thread/tokenUsage/updated", "params": {
            "tokenUsage": {"last": {"inputTokens": 10, "outputTokens": 20}}}},
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    ]


class ImageServer(FakeRPC):
    available = True

    def call(self, method, params):
        if method == "modelProvider/capabilities/read":
            self.calls.append((method, params))
            return {"imageGeneration": self.available, "webSearch": False}
        return super().call(method, params)


@pytest.fixture(autouse=True)
def no_live(monkeypatch):
    def denied(*a, **k):
        raise AssertionError("Unexpected external call")
    monkeypatch.setattr(codex.subprocess, "Popen", denied)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", denied)
    monkeypatch.setattr(codex, "cli_path", lambda: Path("fixture-codex.exe"))
    monkeypatch.setattr(codex.CodexProvider, "version", staticmethod(lambda _: codex.TESTED_VERSION))
    monkeypatch.setattr(native, "bundled_tool_mode", lambda *_: "direct")
    monkeypatch.setattr("newsflow.easy_setup.voice_catalog", list)
    # Never inventory the actual user's generated images in a fake test.
    monkeypatch.setattr(native, "output_roots", lambda folder: (folder.resolve(),))


@pytest.fixture
def connection(monkeypatch):
    def install(server):
        starts = []
        def start(path, folder, deadline, cancel):
            starts.append((path, folder, deadline))
            server.cancel = cancel
            return server
        monkeypatch.setattr(native, "start_image_server", start)
        return native.CodexImageAdapter(), starts
    return install


def test_only_image_feature_enabled_no_news_policy_change():
    config = effective_config()
    with pytest.raises(codex.CodexError):
        native.image_guard(config)
    config["features"]["image_generation"] = True
    native.image_guard(config)
    with pytest.raises(codex.CodexError):
        codex.configuration_guard(config, False)
    assert codex.config_for(False)["features.image_generation"] is False
    assert native.image_config()["features.image_generation"] is True
    for field in ("shell_tool", "view_image", "apps", "plugins", "hooks", "multi_agent", "browser_use"):
        bad = copy.deepcopy(config)
        bad["features"][field] = True
        with pytest.raises(codex.CodexError):
            native.image_guard(bad)


def test_exec_and_computer_tool_safety_checks_unchanged():
    config = effective_config()
    config["features"].update(image_generation=True)
    native.image_guard(config)
    with pytest.raises(codex.CodexError):
        codex.configuration_guard(config, False)  # News-only guard remains unchanged.
    for change in ({"shell_tool": True}, {"unified_exec": True}, {"unified_exec": None}, {"computer_use": True}):
        bad = copy.deepcopy(config)
        bad["features"].update(change)
        with pytest.raises(codex.CodexError):
            native.image_guard(bad)


def test_unsafe_effective_config_never_reaches_account_query(tmp_path):
    calls = []
    class UnsafeConfig:
        def __init__(self, *args):
            self.closed = False
        def call(self, method, params):
            calls.append(method)
            assert method == "config/read", "Account or inference called before effective safety validation"
            config = effective_config()
            config["features"].update(image_generation=True, shell_tool=True, unified_exec=True)
            return {"config": config}
        def close(self):
            self.closed = True
    with pytest.raises(codex.CodexError, match="codex_isolation"):
        native.start_image_server("fake", tmp_path, 1000, None, rpc_factory=UnsafeConfig)
    assert calls == ["config/read", "config/read"]


def test_config_probe_disables_mcp_before_any_thread(tmp_path):
    opened = []
    class ConfigServer:
        def __init__(self, path, folder, overrides, deadline, cancel):
            self.closed = False
            self.overrides = overrides.copy()
            opened.append(self)
        def call(self, method, params):
            assert method == "config/read"
            config = effective_config()
            config["features"]["image_generation"] = True
            config["mcp_servers"] = {"external": {"enabled": len(opened) == 1}}
            config["hooks"] = {"SessionStart": ["SECRET"] if len(opened) == 1 else []}
            return {"config": config}
        def close(self):
            self.closed = True
    result = native.start_image_server("fake", tmp_path, 1000, None, rpc_factory=ConfigServer)
    assert opened[0].closed and not result.closed
    assert result.overrides["mcp_servers.external.enabled"] is False
    assert result.overrides["hooks.SessionStart"] == []
    result.close()


def test_native_success_one_turn_with_no_fallback(connection):
    server = ImageServer(events=events())
    adapter, starts = connection(server)
    raw, usage = adapter.generate("합성 뉴스 · 출처")
    assert raw == png() and usage["total_tokens"] == 30
    assert adapter.last_model == "fixture-model" and server.closed
    assert len(starts) == 1
    turns = [p for m, p in server.calls if m == "turn/start"]
    assert len(turns) == 1 and turns[0]["sandboxPolicy"]["networkAccess"] is False
    thread = next(p for m, p in server.calls if m == "thread/start")
    assert thread["allowProviderModelFallback"] is False and thread["ephemeral"] is True
    assert not Path(thread["cwd"]).exists()  # Owned subprocess closed before directory cleanup.
    assert not adapter.cancel()


@pytest.mark.parametrize("account,limits,available,code", [
    (None, {}, True, "codex_auth"),
    ("apiKey", {}, True, "codex_billing"),
    ("chatgpt", {"ordinaryUsageAllowed": False}, True, "codex_usage"),
    ("chatgpt", {}, True, "codex_usage"),
    ("chatgpt", {"ordinaryUsageAllowed": True}, False, "codex_image_unavailable"),
])
def test_account_or_capability_rejects_before_inference(connection, account, limits, available, code):
    server = ImageServer(events=events(), account_type=account, limits=limits)
    server.available = available
    adapter, _ = connection(server)
    with pytest.raises(ImageGenerationError) as caught:
        adapter.generate("test")
    assert caught.value.code == code and not caught.value.uncertain
    assert not any(m == "turn/start" for m, _ in server.calls)
    assert server.closed


@pytest.mark.parametrize("kind", ["commandExecution", "mcpToolCall", "webSearch", "fileChange", "dynamicToolCall"])
def test_unexpected_tool_stops_without_retry(connection, kind):
    server = ImageServer(events=[{"method": "item/started", "params": {"item": {"type": kind}}}])
    adapter, _ = connection(server)
    with pytest.raises(ImageGenerationError) as caught:
        adapter.generate("test")
    assert caught.value.code == "codex_isolation" and caught.value.uncertain
    assert len([m for m, p in server.calls if m == "turn/start"]) == 1
    assert server.sent[-1]["method"] == "turn/interrupt" and server.closed


@pytest.mark.parametrize("failure,code", [(ProviderTimeoutError(), "codex_image_timeout"),
    (codex.CodexError("codex_cancelled"), "codex_cancelled")])
def test_timeout_cancel_preserve_uncertainty(connection, failure, code):
    server = ImageServer(events=events())
    server.failure = failure
    adapter, _ = connection(server)
    with pytest.raises(ImageGenerationError) as caught:
        adapter.generate("test")
    assert caught.value.code == code and caught.value.uncertain
    assert server.closed


def test_multiple_images_missing_image_and_usage_limit(connection):
    for stream, expected in [
        ([events()[0], {"method": "item/started", "params": {"item": {
            "type": "imageGeneration", "id": "image-2"}}}], "codex_multiple_images"),
        ([events()[-1]], "codex_no_completed_image"),
        ([{"method": "item/completed", "params": {"item": {"type": "imageGeneration", "id": "i",
            "status": "failed", "failure": {"type": "usageLimitExceeded", "limitId": "SECRET"}}}}],
         "codex_image_usage_limited"),
    ]:
        server = ImageServer(events=stream)
        adapter, _ = connection(server)
        with pytest.raises(ImageGenerationError) as caught:
            adapter.generate("test")
        assert caught.value.code == expected and "SECRET" not in str(caught.value)
        assert server.closed


def test_file_result_only_fresh_images_inside_output_root(tmp_path):
    allowed = tmp_path / "generated"
    allowed.mkdir()
    old = allowed / "old.png"
    old.write_bytes(png())
    before = native.inventory((allowed,))
    fresh = allowed / "new.png"
    fresh.write_bytes(png())
    outside = tmp_path / "private.png"
    outside.write_bytes(png())
    now = time.time()
    assert native.result_bytes({"savedPath": str(fresh)}, (allowed,), before, now) == png()
    for path in (old, outside, allowed / ".." / "private.png"):
        with pytest.raises(ValueError):
            native.result_bytes({"savedPath": str(path)}, (allowed,), before, now)
    with pytest.raises(ValueError):
        native.result_bytes({"result": "https://example.com/image.png"}, (allowed,), before, now)
    with pytest.raises(ValueError):
        native.result_bytes({"savedPath": str(fresh)}, (allowed,), before, now + 10)


def test_native_decoder_keeps_full_composition_and_rejects_invalid():
    raw = clean_codex_image(png())
    with Image.open(BytesIO(raw)) as image:
        assert image.format == "JPEG" and image.size == (1024, 1280) and "exif" not in image.info
    for bad in (b"not image", b"x" * (12*1024*1024+1)):
        with pytest.raises(ImageGenerationError):
            clean_codex_image(bad)
    out = BytesIO()
    Image.new("RGB", (1000, 500)).save(out, "PNG")
    with pytest.raises(ImageGenerationError):
        clean_codex_image(out.getvalue())


class FakeNative:
    last_model = "fixture-codex-model"
    def __init__(self):
        self.calls = []
        self.failure = None
    def generate(self, prompt, key):
        assert key is None
        self.calls.append(prompt)
        if self.failure:
            raise self.failure
        return png(), {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}


@pytest.fixture
def prepared(app):
    service = app.state.image_generation
    service.codex_adapter = FakeNative()
    def no_key():
        pytest.fail("Codex must not read an OpenAI API key")
    service.keys = SimpleNamespace(key=no_key, status=lambda: {"configured": False})
    return service, article(app)


ARGS = {"title": "도서관 독서 모임", "body": "합성 시험 뉴스입니다.", "consent": True, "reviewed": True}


def test_reviews_settings_and_sources_preserved_whole_image_no_template(prepared, app, monkeypatch):
    service, news = prepared
    with app.state.sessions() as session:
        settings = {s.key: s.value for s in session.scalars(select(AppSetting))}
    for override in ({"consent": False}, {"reviewed": False}, {"body": "x" * 201}):
        with pytest.raises(PublishingError):
            service.generate_codex(news, **(ARGS | override))
    assert service.codex_adapter.calls == []
    first = service.generate_codex(news, **ARGS)
    run = service.get(first)
    assert run.provider == "codex" and run.status == "success"
    assert "https://example.com/image-news" in service.codex_adapter.calls[0]
    assert run.result["usage_scope"] == "codex_turn_tokens_only"
    def denied(*a, **k):
        pytest.fail("Never overlay a local template onto the whole image")
    monkeypatch.setattr("newsflow.publishing.image_posts.artwork", denied)
    monkeypatch.setattr("newsflow.publishing.image_posts.card_artwork", denied)
    post_id = app.state.image_posts.create(news, title=ARGS["title"], body=ARGS["body"],
        generated_id=first, reviewed=True, rights=True, sources_confirmed=True, ai_disclosure="not_required")
    post = app.state.image_posts.get(post_id)
    assert post.sources["image_provider"] == "codex" and "claude_card_run_id" not in post.sources
    assert post.ai_disclosure == "disclose" and post.sources["articles"][0]["id"] == news
    with app.state.sessions() as session:
        assert all(session.get(AppSetting, k).value == v for k, v in settings.items())
        usage = session.scalar(select(AIUsage).where(AIUsage.run_id == first))
        assert usage.provider == "codex" and usage.model == "fixture-codex-model"


@pytest.mark.parametrize("failure,status", [(None, "success"),
    (ImageGenerationError("codex_image_timeout"), "unknown"),
    (ImageGenerationError("codex_image_unavailable", uncertain=False), "failed")])
def test_durable_claim_never_retries_or_falls_back_after_restart(prepared, failure, status):
    service, news = prepared
    service.codex_adapter.failure = failure
    first = service.generate_codex(news, **ARGS)
    assert service.get(first).status == status
    rebuilt = ImageGenerationService(service.sessions, service.outputs.parent.parent, service.keys,
                                    cards=service.cards, codex_adapter=service.codex_adapter)
    rebuilt.recover()
    assert rebuilt.generate_codex(news, **ARGS) == first
    assert len(service.codex_adapter.calls) == 1


def test_gui_get_no_account_requests_post_requires_csrf_and_reviews(client, prepared):
    service, news = prepared
    response = client.get(f"/image-posts?article_id={news}")
    assert response.status_code == 200 and "Codex로 전체 이미지" in response.text
    assert "로그인·이미지 생성 권한 미검증" in response.text
    assert not service.codex_adapter.calls
    url = "/image-posts/generate-codex-image"
    data = {"article_id": news, **ARGS}
    assert client.post(url, data=data).status_code == 403
    data["csrf_token"] = csrf(client)
    assert client.post(url, data=data, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, data=data | {"reviewed": False}).status_code == 422
    response = client.post(url, data=data)
    assert response.status_code == 200 and "Codex 생성 결과 · 최종 검토 필요" in response.text
    assert len(service.codex_adapter.calls) == 1
    assert client.get(str(response.url)).status_code == 200
    assert client.post(url, data=data).status_code == 200
    assert len(service.codex_adapter.calls) == 1
    assert service.get(service.recent(news)[0].id).provider == "codex"


def test_startup_diagnostics_survive_service_failure_without_replay(prepared):
    service, news = prepared
    error = ImageGenerationError("codex_image_config_error", uncertain=False)
    error.diagnostics = {"stage": "initialize", "exit_code": 2,
                         "stderr_categories": ["unknown_config_field", "SECRET_VALUE"], "stderr": "SECRET_VALUE"}
    service.codex_adapter.failure = error
    identifier = service.generate_codex(news, **ARGS)
    run = service.get(identifier)
    assert run.status == "failed" and run.result["diagnostics"] == {
        "stage": "initialize", "exit_code": 2, "stderr_categories": ["unknown_config_field"]}
    assert "SECRET_VALUE" not in str(run.result)
    assert service.generate_codex(news, **ARGS) == identifier
    assert len(service.codex_adapter.calls) == 1


def test_transport_diagnostics_reach_adapter_without_inference(monkeypatch):
    from newsflow.publishing.codex_image_rpc import ImageTransportError

    def fail(*a, **k):
        raise ImageTransportError("codex_image_startup_error", {"stage": "initialize", "exit_code": 2})
    monkeypatch.setattr(native, "start_image_server", fail)
    with pytest.raises(ImageGenerationError) as caught:
        native.CodexImageAdapter().generate("synthetic input")
    assert caught.value.uncertain is False
    assert caught.value.diagnostics == {"stage": "initialize", "exit_code": 2,
                                       "image_started": 0, "image_completed": 0, "agent_messages": 0}


@pytest.mark.parametrize("mode", ["code_mode_only", "code_mode", "unknown", "unspecified"])
def test_unverified_tool_mode_blocks_before_thread_and_inference(connection, monkeypatch, mode):
    server = ImageServer(events=events())
    adapter, _ = connection(server)
    monkeypatch.setattr(native, "bundled_tool_mode", lambda *_: mode)
    with pytest.raises(ImageGenerationError) as caught:
        adapter.generate("synthetic image request")
    assert caught.value.code == "codex_image_tool_mode_unverified"
    assert caught.value.uncertain is False and caught.value.usage is None
    assert caught.value.diagnostics["tool_mode"] == mode
    assert not any(method in {"thread/start", "turn/start"} for method, _ in server.calls)
    assert server.closed


@pytest.mark.parametrize("catalog,expected", [
    ([{"slug": "fixture-model", "tool_mode": "code_mode_only"}], "code_mode_only"),
    ({"models": [{"slug": "fixture-model", "tool_mode": "direct"}]}, "direct"),
    ([{"slug": "fixture-model"}], "unspecified"),
    ([{"slug": "fixture-model", "tool_mode": {"secret": "SECRET"}}], "unknown"),
    ([{"slug": "fixture-model"}, {"slug": "fixture-model"}], "unknown"),
    ([], "unknown"), (None, "unknown"),
])
def test_catalog_uses_offline_bundled_command_only(monkeypatch, catalog, expected):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 5 and kwargs["check"] is False
        return SimpleNamespace(returncode=0, stdout=json.dumps(catalog).encode())
    monkeypatch.setattr(native.subprocess, "run", run)
    assert OFFLINE_TOOL_MODE("fixture-codex.exe", "fixture-model") == expected
    assert calls == [["fixture-codex.exe", "debug", "models", "--bundled"]]


@pytest.mark.parametrize("status,expected", [("completed", "codex_image_text_without_image"),
                                            ("failed", "codex_image_turn_failed"),
                                            ("interrupted", "codex_image_turn_failed")])
def test_text_only_or_failed_turn_preserves_usage_without_raw_response(connection, status, expected):
    stream = [{"method": "item/completed", "params": {"item": {
        "type": "agentMessage", "text": "Image tool is unavailable. SECRET_VALUE"}}},
        events()[1], {"method": "turn/completed", "params": {"turn": {
            "status": status, "error": {"codexErrorInfo": "badRequest", "message": "SECRET_VALUE"}}}}]
    server = ImageServer(events=stream)
    adapter, _ = connection(server)
    with pytest.raises(ImageGenerationError) as caught:
        adapter.generate("synthetic image request")
    error = caught.value
    assert error.code == expected and error.uncertain
    assert error.usage == {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    assert error.diagnostics["turn_status"] == status
    assert error.diagnostics["turn_error"] == "badRequest"
    assert error.diagnostics["text_outcome"] == "tool_unavailable"
    assert error.diagnostics["image_completed"] == 0
    assert "SECRET_VALUE" not in str(error.diagnostics)
    assert sum(method == "turn/start" for method, _ in server.calls) == 1


def test_image_success_with_agent_text_is_not_rejected(connection):
    server = ImageServer(events=[{"method": "item/completed", "params": {"item": {
        "type": "agentMessage", "text": "Your image is ready."}}}, *events()])
    adapter, _ = connection(server)
    raw, usage = adapter.generate("synthetic image request")
    assert raw == png() and usage["total_tokens"] == 30


def test_failure_usage_persisted_once_without_claim_replay(prepared):
    service, news = prepared
    error = ImageGenerationError("codex_image_text_without_image")
    error.usage = {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    error.diagnostics = {"turn_status": "completed", "text_outcome": "tool_unavailable",
                         "turn_error": "SECRET", "response": "SECRET"}
    service.codex_adapter.failure = error
    identifier = service.generate_codex(news, **ARGS)
    run = service.get(identifier)
    assert run.status == "unknown" and run.result["usage"] == error.usage
    assert run.result["diagnostics"] == {"turn_status": "completed", "text_outcome": "tool_unavailable"}
    assert "SECRET" not in str(run.result)
    assert service.generate_codex(news, **ARGS) == identifier
    with service.sessions() as session:
        rows = session.scalars(select(AIUsage).where(AIUsage.run_id == identifier)).all()
        assert len(rows) == 1 and rows[0].provider == "codex"
    assert len(service.codex_adapter.calls) == 1
