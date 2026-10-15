"""Phase 5D AIVideoCoordinator end to end with the Fake provider (no network, no real key).

The background worker is never started here: ``wake`` is replaced per coordinator and every
test drives the worker with ``tick()`` / ``recover()`` directly so nothing races the asserts.
Composition uses FakeRenderAdapter + FakeTTS; only clip download/validation uses real ffmpeg.
"""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.config import Settings
from newsflow.db.models import (
    AIVideoPlan,
    AIVideoScene,
    ContentDraft,
    NewsArticle,
    NewsSource,
    RenderJob,
    Scene,
    VideoAIUsage,
    VideoProject,
    utcnow,
)
from newsflow.intelligence.credentials import FakeCipher
from newsflow.intelligence.service import IntelligenceService
from newsflow.main import create_app
from newsflow.video.ai.contracts import (
    ERROR_MESSAGES,
    ProviderAuthError,
    ProviderUnavailable,
    VideoProviderError,
)
from newsflow.video.ai.fake import FakeVideoProvider
from newsflow.video.ai.keys import VIDEO_ENV_NAME, VideoAIKeyStore
from newsflow.video.ai.policy import DEFAULT_PROMPT, STYLE_GUARD
from newsflow.video.ai.service import (
    CLIP_GONE_MESSAGE,
    CLIP_LOST_MESSAGE,
    CLIP_UNREADABLE,
    CLIP_UNREADABLE_KEPT,
    COMPOSE_STARTED,
    DRAFT_CHANGED,
    MAX_REFETCHES,
    MAX_REQUEUES,
    REFETCH_KEPT_FINAL,
    REFETCH_KEPT_MESSAGE,
    TIMEOUT_OPEN_MESSAGE,
    AIVideoCoordinator,
    AIVideoError,
)
from newsflow.video.ai.settings import CURRENCY_CHANGED, list_models, month_start, save_model, write_settings
from newsflow.video.engine import FakeRenderAdapter
from newsflow.video.tts import FakeTTS

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe not installed",
)

MODEL = "vendor/model/text-to-video"
OTHER_MODEL = "vendor/other/text-to-video"
PROMPT = "도시 경제를 상징하는 푸른 추상 파동"
KEY = "keyid1234:secretvalue-ABCDEFGH"

# Every scene/plan message the coordinator may store: fixed sentences only, never provider prose.
SERVICE_MESSAGES = {
    "", "제출 대기 중", "공급사에 제출 중", "공급사 대기열에 등록됨", "공급사 대기열", "공급사에서 생성 중",
    "생성 완료 · 안전 검사 후 내려받는 중", "생성 영상 준비됨 · 원본 뉴스와의 관계를 검토하세요.",
    "재시작 후 생성 결과를 다시 확인합니다.", "제출 전에 취소했습니다.", "공급사 대기열에서 취소했습니다.",
    "사용자가 결과 불명 요청을 실패로 확정했습니다. 예상 비용은 이번 달 사용량에 남습니다.",
    "대본이 바뀌었거나 체험 뉴스여서 제출하지 않았습니다.",
    "모델 설정이 바뀌어 제출하지 않았습니다. 장면을 다시 확인하세요.",
    "프롬프트가 현재 정책을 통과하지 못해 제출하지 않았습니다. 프롬프트를 고친 뒤 다시 확인하세요.",
    "완료된 결과를 다시 확인해 내려받습니다(추가 생성 요청 없음).",
    "AI 영상 공급사가 '사용 안 함'이라 상태 확인을 멈췄습니다. 공급사를 다시 켜면 이어서 확인합니다.",
    "확인 뒤에 유료 생성 승인이 다시 저장되어 이전 확인으로는 제출하지 않았습니다. 예상 비용을 다시 확인하세요.",
    "작업별 한도가 확인 뒤에 낮아져 제출하지 않았습니다. 예상 비용을 다시 확인하세요.",
    TIMEOUT_OPEN_MESSAGE,
    CLIP_LOST_MESSAGE,
    REFETCH_KEPT_MESSAGE,
    REFETCH_KEPT_FINAL,
    REFETCH_KEPT_MESSAGE + " " + ERROR_MESSAGES["video_ai_disk_full"],
    CLIP_GONE_MESSAGE,
    "달이 바뀌어 지난달의 확인으로는 제출하지 않았습니다. 예상 비용을 다시 확인하세요.",
}
STATUS_RETRY = "상태 확인 실패 · 다음 확인에서 다시 시도합니다. "
SETTINGS_CHANGED = "설정이 바뀌어 AI 영상 생성 조건을 만족하지 않아 제출하지 않았습니다. "
READINESS_REASONS = (
    "AI 영상 공급사가 '사용 안 함'입니다. 기본 FFmpeg 제작만 사용합니다.",
    "AI 영상 유료 생성 승인이 저장되지 않았습니다.",
    "작업별 한도와 월 한도가 없습니다.",
    "이번 달 AI 영상 한도를 모두 사용했습니다.",
    "AI 영상 API 키가 없습니다.",
    "공식 문서 확인과 초당 단가를 입력한 모델이 없습니다.",
)
PLAN_MESSAGES = {
    "장면별로 카드·로컬 이미지·AI 생성 중 하나를 고르세요. 기본은 카드(외부 호출 없음)입니다.",
    "최종 합성 승인됨 · 기존 FFmpeg 제작 경로로 MP4를 만듭니다.",
    "최종 합성을 시작하지 못했습니다. 제작 중인 영상이 끝난 뒤 다시 시도하세요.",
}
PLAN_CONFIRMED = re.compile(r"유료 생성 \d+개 장면 확인됨 · 예상 [0-9.]+ (USD|KRW)")
NOT_RETRYABLE = "생성할 AI 장면이 없습니다. 장면 소재를 'AI 생성'으로 바꾸세요."
STALE_TOTAL = "표시된 예상 비용이 바뀌었습니다. 새로고침해 다시 확인하세요."
STALE_REVISION = "다른 화면에서 계획이 바뀌었습니다. 새로고침 후 다시 저장하세요."
TRIAL = "체험(합성) 뉴스 대본은 외부 AI 영상 공급사로 보내지 않습니다."
SECRET_PROMPT = "프롬프트에 비밀정보가 포함되어 보낼 수 없습니다."
DISCARD_NEEDED = ("장면 {}의 받아 둔 유료 AI 영상(또는 다시 받을 수 있는 결과)이 버려집니다. "
                  "그 장면의 '받아 둔 유료 AI 영상 버리기'에 체크한 뒤 저장하세요.")
BLOCKED = ("실제 뉴스 현장·기록 영상이나 실존 인물처럼 보이게 하는 표현은 사용할 수 없습니다. "
           "추상적인 배경·상징 화면으로 바꿔 쓰세요.")


@dataclass
class Studio:
    app: object
    service: AIVideoCoordinator
    provider: FakeVideoProvider
    draft_id: int

    @property
    def sessions(self):
        return self.app.state.sessions

    @property
    def data_dir(self) -> Path:
        return self.service.root


def add_article(app, article_id_hint: str, source_id: int = 1) -> int:
    with app.state.sessions.begin() as session:
        article = NewsArticle(
            title=f"AI 영상 서비스 테스트 뉴스 {article_id_hint}", summary="합성 요약",
            url=f"https://example.com/news/{article_id_hint}", canonical_url=f"https://example.com/news/{article_id_hint}",
            source_id=source_id, publisher="합성 언론",
        )
        session.add(article)
        session.flush()
        return article.id


def make_draft(app, article_id: int) -> int:
    ai = IntelligenceService(app.state.sessions)
    return ai.generate(ai.analyze([article_id]), 30)


@pytest.fixture
def studio(tmp_path, fake, monkeypatch):
    monkeypatch.delenv(VIDEO_ENV_NAME, raising=False)
    provider = FakeVideoProvider(steps=1)
    app = create_app(Settings(data_dir=tmp_path / "data"), fake, video_provider=provider)
    service = app.state.video_ai
    # Tests drive the worker with tick(); no background thread may race the direct calls.
    monkeypatch.setattr(service, "wake", lambda: None)
    draft_id = make_draft(app, add_article(app, "1"))
    app.state.video.engine, app.state.video.tts = FakeRenderAdapter(), FakeTTS()
    studio = Studio(app, service, provider, draft_id)
    yield studio
    service.close()
    app.state.video.close()
    assert_fixed_messages(studio)
    app.state.engine.dispose()


def configure(studio: Studio, *, job: str = "5", monthly: str = "20", provider: str = "higgsfield",
              approved: bool = True, max_active: int = 2, timeout: int = 30) -> None:
    write_settings(
        studio.sessions, provider=provider, host="api.higgsfield.ai", approved=approved, monthly_limit=monthly,
        job_limit=job, currency="USD", max_active=max_active, timeout_minutes=timeout, poll_seconds=10,
    )


def add_model(studio: Studio, path: str = MODEL, price: str = "0.1", confirmed: bool = True, model_id: int | None = None):
    # A single allowed length of 5 s keeps the real ffmpeg clips short (10 s scenes loop a 5 s clip).
    return save_model(studio.sessions, path=path, label="시험 모델", price_per_second=price, durations="5",
                      resolution="720p", confirmed=confirmed, model_id=model_id)


def ready_studio(studio: Studio, **settings) -> None:
    configure(studio, **settings)
    add_model(studio)


def revision(studio: Studio, plan_id: int) -> int:
    with studio.sessions() as session:
        return session.get(AIVideoPlan, plan_id).revision


def plan_row(studio: Studio, plan_id: int) -> AIVideoPlan:
    with studio.sessions() as session:
        plan = session.get(AIVideoPlan, plan_id)
        session.expunge(plan)
        return plan


def scenes(studio: Studio, plan_id: int) -> list[AIVideoScene]:
    with studio.sessions() as session:
        rows = list(session.scalars(
            select(AIVideoScene).where(AIVideoScene.plan_id == plan_id).order_by(AIVideoScene.position)))
        session.expunge_all()
        return rows


def usage(studio: Studio, plan_id: int | None = None) -> list[VideoAIUsage]:
    with studio.sessions() as session:
        query = select(VideoAIUsage).order_by(VideoAIUsage.id)
        if plan_id is not None:
            query = query.where(VideoAIUsage.plan_id == plan_id)
        rows = list(session.scalars(query))
        session.expunge_all()
        return rows


def edit_scene(studio: Studio, plan_id: int, position: int, **values) -> None:
    with studio.sessions.begin() as session:
        scene = session.scalar(select(AIVideoScene).where(
            AIVideoScene.plan_id == plan_id, AIVideoScene.position == position))
        for key, value in values.items():
            setattr(scene, key, value)


def generated_plan(studio: Studio, prompts: dict[int, str] | None = None, draft_id: int | None = None) -> int:
    plan_id = studio.service.create_plan(draft_id or studio.draft_id, 30)
    prompts = prompts if prompts is not None else {0: PROMPT}
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": position, "source": "generated", "prompt": prompt, "model_path": MODEL}
        for position, prompt in prompts.items()
    ])
    return plan_id


def confirm(studio: Studio, plan_id: int) -> int:
    estimate = studio.service.estimate(plan_id)
    assert estimate["can_submit"], estimate["problems"]
    return studio.service.confirm_generation(plan_id, revision(studio, plan_id), estimate["total"], True)


def confirm_as_shown(studio: Studio, plan_id: int) -> int:
    """Confirm the total the cost screen shows, even when that screen lists problems."""
    shown = studio.service.estimate(plan_id)["total"]
    return studio.service.confirm_generation(plan_id, revision(studio, plan_id), shown, True)


def calls(provider: FakeVideoProvider, kind: str) -> list[str]:
    """Second element of each recorded call of ``kind`` (model path for submit, request id otherwise)."""
    return [call[1] for call in provider.calls if call[0] == kind]


def submit_keys(provider: FakeVideoProvider) -> list[str | None]:
    return [call[2] for call in provider.calls if call[0] == "submit"]


def refusal(excinfo: pytest.ExceptionInfo) -> tuple[str, int]:
    return str(excinfo.value), excinfo.value.status


def assert_fixed_messages(studio: Studio) -> None:
    """Every stored message is a fixed sentence: no provider prose, URLs, request ids or prompts."""
    fixed_errors = set(ERROR_MESSAGES.values())
    with studio.sessions() as session:
        scene_rows = list(session.scalars(select(AIVideoScene)))
        plan_rows = list(session.scalars(select(AIVideoPlan)))
        prompts = [s.prompt for s in scene_rows if s.prompt and s.prompt != DEFAULT_PROMPT]
        for scene in scene_rows:
            message = scene.message
            if message in SERVICE_MESSAGES or message in fixed_errors:
                pass
            elif message.startswith(STATUS_RETRY):
                assert message[len(STATUS_RETRY):] in fixed_errors | {""}, message
            elif message.startswith(SETTINGS_CHANGED):
                rest = message[len(SETTINGS_CHANGED):]
                for reason in READINESS_REASONS:
                    rest = rest.replace(reason, "")
                assert not rest.strip(), message
            else:
                raise AssertionError(f"unexpected scene message: {message!r}")
            assert scene.error_code is None or scene.error_code.startswith("video_ai_"), scene.error_code
        for plan in plan_rows:
            assert plan.message in PLAN_MESSAGES or PLAN_CONFIRMED.fullmatch(plan.message), plan.message
        for text in [s.message for s in scene_rows] + [p.message for p in plan_rows]:
            for forbidden in ("http", "fake-", "fake.invalid", "[fake:", "PROSE", STYLE_GUARD, KEY, *prompts):
                assert forbidden not in text, (forbidden, text)


def small_png(studio: Studio, name: str = "bg.png") -> str:
    Image.new("RGB", (64, 64), (20, 90, 160)).save(studio.app.state.video.assets / name, format="PNG")
    return name


# --------------------------------------------------------------------------- default off and the gate


def test_default_off_no_injected_provider_estimate_lists_problems_and_confirm_is_refused(app, monkeypatch):
    monkeypatch.delenv(VIDEO_ENV_NAME, raising=False)
    service = app.state.video_ai
    woke = []
    monkeypatch.setattr(service, "wake", lambda: woke.append(1))
    ai = IntelligenceService(app.state.sessions)
    with app.state.sessions.begin() as session:
        session.add(NewsArticle(title="기본 꺼짐 뉴스", summary="요약", url="https://example.com/off",
                                canonical_url="https://example.com/off", source_id=1, publisher="합성 언론"))
    draft_id = ai.generate(ai.analyze([1]), 30)
    plan_id = service.create_plan(draft_id, 30)
    assert service.injected is None and service.provider() is None and service.provider_name() == "off"
    with app.state.sessions() as session:
        assert session.get(AIVideoPlan, plan_id).status == "draft"
    estimate = service.estimate(plan_id)
    assert estimate["can_submit"] is False and estimate["total"] == "0" and estimate["scenes"] == []
    for reason in (
        "AI 영상 공급사가 '사용 안 함'입니다. 기본 FFmpeg 제작만 사용합니다.",
        "AI 영상 유료 생성 승인이 저장되지 않았습니다.",
        "작업별 한도와 월 한도가 없습니다.",
        "AI 영상 API 키가 없습니다.",
        "공식 문서 확인과 초당 단가를 입력한 모델이 없습니다.",
        NOT_RETRYABLE,
    ):
        assert reason in estimate["problems"]
    # No confirmed model: a scene cannot even be switched to 'generated'.
    with pytest.raises(AIVideoError) as excinfo:
        service.update_scenes(plan_id, 1, [{"position": 0, "source": "generated", "prompt": PROMPT, "model_path": MODEL}])
    assert refusal(excinfo) == ("장면 1의 모델을 공식 문서 확인·단가 입력이 끝난 목록에서 고르세요.", 422)
    with pytest.raises(AIVideoError) as excinfo:
        service.confirm_generation(plan_id, 1, "0", True)
    message, status = refusal(excinfo)
    assert status == 422 and message == " ".join(estimate["problems"])
    service.tick()  # nothing to do and nothing to call
    with app.state.sessions() as session:
        assert session.scalar(select(VideoAIUsage)) is None
        assert {s.status for s in session.scalars(select(AIVideoScene))} == {"planned"}
    assert woke == []
    service.close()
    app.state.video.close()


def test_injected_fake_but_settings_off_refuses_and_never_calls_the_provider(studio):
    add_model(studio)
    plan_id = generated_plan(studio)
    estimate = studio.service.estimate(plan_id)
    assert estimate["can_submit"] is False and estimate["total"] == "0.5"
    assert "AI 영상 유료 생성 승인이 저장되지 않았습니다." in estimate["problems"]
    assert "작업별 한도와 월 한도가 없습니다." in estimate["problems"]
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", True)
    assert excinfo.value.status == 422 and "AI 영상 유료 생성 승인이 저장되지 않았습니다." in str(excinfo.value)
    studio.service.tick()
    assert studio.provider.calls == [] and usage(studio) == []
    assert scenes(studio, plan_id)[0].status == "planned"


def test_unchecked_confirmation_is_refused(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", False)
    assert refusal(excinfo) == ("예상 비용과 유료 생성을 확인한다는 항목에 체크하세요.", 422)
    assert usage(studio) == []


# --------------------------------------------------------------------------- full flow


@needs_ffmpeg
def test_full_flow_card_local_and_generated_scene_to_composition(studio):
    ready_studio(studio)
    studio.provider.steps = 2  # tick 1 submits (queued), tick 2 completes and downloads
    service, sessions = studio.service, studio.sessions
    plan_id = service.create_plan(studio.draft_id, 30)
    assert plan_row(studio, plan_id).status == "draft" and plan_row(studio, plan_id).provider == "fake"
    material = small_png(studio)
    with pytest.raises(AIVideoError) as excinfo:
        service.update_scenes(plan_id, 1, [{"position": 1, "source": "local", "material": material}])
    assert refusal(excinfo) == ("로컬 이미지를 쓰려면 소재 이용 권한을 확인하세요.", 422)
    service.update_scenes(plan_id, 1, [
        {"position": 0, "source": "card"},
        {"position": 1, "source": "local", "material": material},
        {"position": 2, "source": "generated", "prompt": PROMPT, "model_path": MODEL},
    ], asset_permission=True)
    assert plan_row(studio, plan_id).status == "draft"
    rows = scenes(studio, plan_id)
    assert [s.source for s in rows] == ["card", "local", "generated"]
    assert rows[2].clip_seconds == 5 and rows[2].estimated_cost == "0.5" and rows[0].estimated_cost == ""

    estimate = service.estimate(plan_id)
    assert estimate == {
        "scenes": [{"position": 2, "seconds": 5, "model": MODEL, "cost": "0.5", "usable": True}], "total": "0.5", "currency": "USD",
        "plan_spent": "0", "job_limit": "5", "monthly_limit": "20", "month_spent": "0", "remaining": "20",
        "problems": [], "notices": [], "can_submit": True, "other_currency_spend": False,
    }
    assert estimate["scenes"][0]["usable"] is True
    assert service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", True) == 1
    plan = plan_row(studio, plan_id)
    assert plan.status == "generating" and plan.confirmed_at is not None
    assert plan.message == "유료 생성 1개 장면 확인됨 · 예상 0.5 USD"
    assert scenes(studio, plan_id)[2].status == "waiting" and scenes(studio, plan_id)[2].attempt == 1
    [reserved] = usage(studio, plan_id)
    assert (reserved.status, reserved.attempt, reserved.provider, reserved.model_path, reserved.seconds,
            reserved.estimated_cost, reserved.currency, reserved.request_id) == (
        "reserved", 1, "fake", MODEL, 5, "0.5", "USD", None)
    after = service.estimate(plan_id)
    assert after["plan_spent"] == "0.5" and after["month_spent"] == "0.5" and after["remaining"] == "19.5"

    service.tick()  # submit
    scene = scenes(studio, plan_id)[2]
    assert scene.status == "queued" and scene.request_id and scene.submitted_at is not None
    [submitted] = usage(studio, plan_id)
    assert submitted.status == "submitted" and submitted.request_id == scene.request_id
    assert calls(studio.provider, "submit") == [MODEL]
    [sent] = [job.request for job in studio.provider.jobs.values()]
    assert sent.prompt == f"{PROMPT}\n\n{STYLE_GUARD}"  # the style guard is always appended
    assert (sent.seconds, sent.resolution, sent.aspect_ratio) == (5, "720p", "9:16")
    assert plan_row(studio, plan_id).status == "generating"

    service.tick()  # poll -> completed -> download -> ffprobe
    scene = scenes(studio, plan_id)[2]
    assert scene.status == "ready" and scene.message == "생성 영상 준비됨 · 원본 뉴스와의 관계를 검토하세요."
    assert re.fullmatch(r"clip-[0-9a-f]{32}\.mp4", scene.clip_name)
    meta = scene.clip_meta
    assert meta["format"] == "mov" and meta["video_codec"] == "h264" and (meta["width"], meta["height"]) == (540, 960)
    assert 4.5 <= meta["duration"] <= 5.5 and meta["bytes"] > 0 and meta["has_audio"] is False
    assert re.fullmatch(r"[0-9a-f]{64}", meta["sha256"]) and meta["download_host"] == "fake.invalid"
    assert usage(studio, plan_id)[0].status == "completed"
    assert plan_row(studio, plan_id).status == "review"
    clip = service.clip_path(scene.id)
    assert clip.is_file() and clip.parent == studio.data_dir / "ai-clips" and clip.name == scene.clip_name

    # Composition needs every generated scene reviewed AND the relation statement.
    with pytest.raises(AIVideoError) as excinfo:
        service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("장면 3의 AI 생성 영상을 관계 검토에서 확인(체크)한 뒤 다시 승인하세요.", 422)
    service.review(plan_id, revision(studio, plan_id), set(), True)
    assert plan_row(studio, plan_id).reviewed_at is None and not scenes(studio, plan_id)[2].reviewed
    service.review(plan_id, revision(studio, plan_id), {2}, False)
    assert plan_row(studio, plan_id).reviewed_at is None and scenes(studio, plan_id)[2].reviewed
    with pytest.raises(AIVideoError) as excinfo:
        service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("원본 뉴스와 AI 생성 장면의 관계 검토를 먼저 저장하세요.", 422)
    service.review(plan_id, revision(studio, plan_id), {0, 1, 2}, True)
    assert plan_row(studio, plan_id).reviewed_at is not None
    with pytest.raises(AIVideoError) as excinfo:
        service.approve_compose(plan_id, revision(studio, plan_id), False)
    assert refusal(excinfo) == ("최종 합성을 승인한다는 항목에 체크하세요.", 422)
    with pytest.raises(AIVideoError) as excinfo:
        service.approve_compose(plan_id, revision(studio, plan_id) - 1, True)
    assert refusal(excinfo) == (STALE_REVISION, 409)

    job_id = service.approve_compose(plan_id, revision(studio, plan_id), True)
    plan = plan_row(studio, plan_id)
    assert plan.render_job_id == job_id and plan.approved_at is not None and plan.status in {"composing", "composed"}
    studio.app.state.video.future.result(timeout=30)
    with sessions() as session:
        job = session.get(RenderJob, job_id)
        project = session.get(VideoProject, job.project_id)
        rows = list(session.scalars(select(Scene).where(Scene.project_id == project.id).order_by(Scene.position)))
    assert job.status == "simulated" and project.ai_plan_id == plan_id
    assert [(r.material, r.clip_name, r.ai_generated) for r in rows] == [
        ("", None, False), (material, None, False), ("", scene.clip_name, True)]
    rendered = studio.app.state.video.engine.calls[-1].scenes
    assert rendered[0].clip is None and rendered[0].image is None
    assert rendered[1].image is not None and rendered[1].clip is None and not rendered[1].ai_generated
    assert rendered[2].clip is not None and rendered[2].ai_generated and rendered[2].clip_format == "mov"

    # Composition is final: no second render, no edits, no further paid generation.
    with pytest.raises(AIVideoError) as excinfo:
        service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("이미 최종 합성을 시작했습니다.", 409)
    with pytest.raises(AIVideoError) as excinfo:
        service.update_scenes(plan_id, revision(studio, plan_id), [{"position": 0, "source": "card"}])
    assert refusal(excinfo) == ("최종 합성을 시작한 계획은 바꿀 수 없습니다. 새 계획을 만드세요.", 409)
    assert calls(studio.provider, "submit") == [MODEL] and len(usage(studio)) == 1


class GatedRender(FakeRenderAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.gate = Event()

    def render(self, plan, work, tts, progress, cancel):
        assert self.gate.wait(10)
        return super().render(plan, work, tts, progress, cancel)


def test_plan_status_follows_the_render_job_after_composition_finishes(studio):
    """User-visible plan status must not stay 'composing' once the render job has ended."""
    gated = GatedRender()
    studio.app.state.video.engine = gated
    plan_id = studio.service.create_plan(studio.draft_id, 30)
    job_id = studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert plan_row(studio, plan_id).status == "composing"
    gated.gate.set()
    studio.app.state.video.future.result(timeout=10)
    with studio.sessions() as session:
        assert session.get(RenderJob, job_id).status == "simulated"
    shown = TestClient(studio.app, base_url="http://127.0.0.1").get(f"/api/video/ai/plans/{plan_id}").json()
    assert shown["status"] == "composed"


def test_failed_generated_scene_can_fall_back_to_card_and_compose(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:fail]"})
    confirm(studio, plan_id)
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "failed"
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("장면 1의 AI 생성 영상이 준비·검토되지 않았습니다. 기다리거나 카드로 바꾸세요.", 422)
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [{"position": 0, "source": "card"}])
    assert plan_row(studio, plan_id).status == "draft"
    job_id = studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.app.state.video.future.result(timeout=10)
    with studio.sessions() as session:
        project = session.get(VideoProject, session.get(RenderJob, job_id).project_id)
        assert project.ai_plan_id == plan_id
        assert not any(s.ai_generated or s.clip_name for s in session.scalars(
            select(Scene).where(Scene.project_id == project.id)))


def test_compose_refused_while_another_render_runs_and_plan_is_restored(studio):
    plan_id = studio.service.create_plan(studio.draft_id, 30)
    video = studio.app.state.video
    assert video.guard.acquire(blocking=False)
    try:
        with pytest.raises(AIVideoError) as excinfo:
            studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    finally:
        video.guard.release()
    assert refusal(excinfo) == ("이미 영상 제작이 실행 중입니다.", 409)
    plan = plan_row(studio, plan_id)
    assert plan.render_job_id is None and plan.approved_at is None
    assert plan.message == "최종 합성을 시작하지 못했습니다. 제작 중인 영상이 끝난 뒤 다시 시도하세요."
    with studio.sessions() as session:
        assert session.scalar(select(RenderJob)) is None


# --------------------------------------------------------------------------- confirmation races and limits


def test_stale_total_and_revision_mismatch_are_409(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    current = revision(studio, plan_id)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, current, "0.4", True)
    assert refusal(excinfo) == (STALE_TOTAL, 409)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, current + 7, "0.5", True)
    assert refusal(excinfo) == (STALE_REVISION, 409)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.update_scenes(plan_id, current - 1, [{"position": 1, "source": "card"}])
    assert refusal(excinfo) == (STALE_REVISION, 409)
    # The price changed after the user looked at the estimate: the old total is stale.
    model = studio.service.models()[0]
    add_model(studio, price="0.2", model_id=model.id)
    studio.service.update_scenes(plan_id, current, [{"position": 0, "source": "generated", "prompt": PROMPT,
                                                     "model_path": MODEL}])
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", True)
    assert refusal(excinfo) == (STALE_TOTAL, 409)
    assert usage(studio) == [] and studio.provider.calls == []
    assert {s.status for s in scenes(studio, plan_id)} == {"planned"}


def test_duplicate_confirm_while_waiting_creates_no_second_usage_row(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    assert confirm(studio, plan_id) == 1
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", True)
    message, status = refusal(excinfo)
    assert status == 422 and NOT_RETRYABLE in message
    with pytest.raises(AIVideoError):
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0", True)
    rows = usage(studio)
    assert len(rows) == 1 and rows[0].attempt == 1 and scenes(studio, plan_id)[0].attempt == 1
    studio.service.tick()
    studio.service.tick()
    assert len(calls(studio.provider, "submit")) == 1 and len(usage(studio)) == 1


def test_per_job_limit_refusal_counts_earlier_attempts(studio):
    ready_studio(studio, job="1", monthly="20")
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:fail]", 1: PROMPT + " [fake:fail]", 2: PROMPT})
    over = "작업별 한도를 넘습니다: 이 작업 사용 0 + 이번 요청 예상 1.5 > 한도 1 USD. 장면 수를 줄이거나 한도를 확인하세요."
    assert studio.service.estimate(plan_id)["problems"] == [over]  # the cost screen says so before any click
    with pytest.raises(AIVideoError) as excinfo:
        confirm_as_shown(studio, plan_id)
    assert refusal(excinfo) == (over, 422)
    assert usage(studio) == [] and {s.status for s in scenes(studio, plan_id)} == {"planned"}
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [{"position": 2, "source": "card"}])
    assert confirm(studio, plan_id) == 2
    studio.service.tick()
    assert [s.status for s in scenes(studio, plan_id)[:2]] == ["failed", "failed"]
    # Retrying the failed scenes would pass the per-job limit: the earlier attempts still count.
    with pytest.raises(AIVideoError) as excinfo:
        confirm_as_shown(studio, plan_id)
    assert refusal(excinfo) == (
        "작업별 한도를 넘습니다: 이 작업 사용 1 + 이번 요청 예상 1 > 한도 1 USD. 장면 수를 줄이거나 한도를 확인하세요.", 422)
    assert len(usage(studio)) == 2 and len(calls(studio.provider, "submit")) == 2


def test_monthly_limit_refusal_counts_other_plans(studio):
    ready_studio(studio, job="5", monthly="5")
    other = studio.service.create_plan(studio.draft_id, 30)
    with studio.sessions.begin() as session:
        session.add(VideoAIUsage(
            plan_id=other, scene_id=scenes(studio, other)[0].id, attempt=1, provider="fake", model_path=MODEL,
            seconds=5, estimated_cost="4.8", currency="USD", status="completed",
        ))
        # Known-not-sent requests never count toward the limit.
        session.add(VideoAIUsage(
            plan_id=other, scene_id=scenes(studio, other)[1].id, attempt=1, provider="fake", model_path=MODEL,
            seconds=5, estimated_cost="4", currency="USD", status="not_sent",
        ))
    plan_id = generated_plan(studio)
    estimate = studio.service.estimate(plan_id)
    over = "이번 달 AI 영상 한도를 넘습니다: 사용 4.8 + 이번 요청 예상 0.5 > 한도 5 USD."
    assert estimate["month_spent"] == "4.8" and estimate["remaining"] == "0.2"
    assert not estimate["can_submit"] and estimate["problems"] == [over]
    with pytest.raises(AIVideoError) as excinfo:
        confirm_as_shown(studio, plan_id)
    assert refusal(excinfo) == (over, 422)
    assert usage(studio, plan_id) == [] and studio.provider.calls == []


def test_max_active_bounds_concurrent_submissions(studio):
    ready_studio(studio, max_active=1)
    slow = PROMPT + " [fake:slow]"
    plan_id = generated_plan(studio, {0: slow, 1: slow, 2: slow})
    assert confirm(studio, plan_id) == 3
    studio.service.tick()
    assert sorted(s.status for s in scenes(studio, plan_id)) == ["queued", "waiting", "waiting"]
    studio.service.tick()
    assert sorted(s.status for s in scenes(studio, plan_id)) == ["in_progress", "waiting", "waiting"]
    assert len(calls(studio.provider, "submit")) == 1


# --------------------------------------------------------------------------- refused drafts and prompts


def test_trial_sample_draft_is_never_sent(studio):
    ready_studio(studio)
    with studio.sessions.begin() as session:
        sample = NewsSource(name="체험 피드", enabled=False, url=SAMPLE_URL)
        session.add(sample)
        session.flush()
        sample_id = sample.id
    trial_draft = make_draft(studio.app, add_article(studio.app, "sample", sample_id))
    plan_id = generated_plan(studio, draft_id=trial_draft)
    estimate = studio.service.estimate(plan_id)
    assert TRIAL in estimate["problems"] and estimate["can_submit"] is False
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), estimate["total"], True)
    assert refusal(excinfo) == (TRIAL, 422)
    studio.service.tick()
    assert usage(studio) == [] and studio.provider.calls == []


def test_draft_revision_change_refuses_confirm_and_compose(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    card_plan = studio.service.create_plan(studio.draft_id, 30)
    with studio.sessions.begin() as session:
        session.get(ContentDraft, studio.draft_id).revision += 1
    estimate = studio.service.estimate(plan_id)
    assert DRAFT_CHANGED in estimate["problems"]
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", True)
    assert refusal(excinfo) == (DRAFT_CHANGED, 422)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(card_plan, revision(studio, card_plan), True)
    assert refusal(excinfo) == (DRAFT_CHANGED, 409)
    with studio.sessions() as session:
        assert session.scalar(select(RenderJob)) is None
    assert usage(studio) == [] and studio.provider.calls == []


@pytest.mark.parametrize("change", ["settings_off", "draft_revision", "model_unconfirmed"])
def test_conditions_changed_after_confirm_cancel_waiting_scenes_as_not_sent(studio, change):
    ready_studio(studio)
    add_model(studio, path=OTHER_MODEL)  # keeps a usable model so only the used model's confirmation matters
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    if change == "settings_off":
        configure(studio, provider="off", approved=False)
        expected = SETTINGS_CHANGED + "AI 영상 유료 생성 승인이 저장되지 않았습니다."
    elif change == "draft_revision":
        with studio.sessions.begin() as session:
            session.get(ContentDraft, studio.draft_id).revision += 1
        expected = "대본이 바뀌었거나 체험 뉴스여서 제출하지 않았습니다."
    else:
        model = next(m for m in studio.service.models() if m.path == MODEL)
        add_model(studio, confirmed=False, model_id=model.id)
        expected = "모델 설정이 바뀌어 제출하지 않았습니다. 장면을 다시 확인하세요."
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code, scene.message) == ("canceled", "video_ai_canceled", expected)
    assert [row.status for row in usage(studio)] == ["not_sent"]
    assert studio.provider.calls == []
    assert studio.service.readiness()["usage"]["spent"] == 0


def test_blocked_prompt_phrase_is_refused_and_nothing_changes(studio):
    ready_studio(studio)
    plan_id = studio.service.create_plan(studio.draft_id, 30)
    for prompt in ("사고 현장 영상처럼 CCTV 화면", "photorealistic breaking news", "대통령 연설 장면"):
        with pytest.raises(AIVideoError) as excinfo:
            studio.service.update_scenes(plan_id, 1, [
                {"position": 0, "source": "generated", "prompt": prompt, "model_path": MODEL}])
        assert refusal(excinfo) == (f"장면 1: {BLOCKED}", 422)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.update_scenes(plan_id, 1, [{"position": 1, "source": "generated", "prompt": "   ", "model_path": MODEL}])
    assert refusal(excinfo) == ("장면 2: AI 생성 장면의 프롬프트를 입력하세요.", 422)
    assert revision(studio, plan_id) == 1
    assert [(s.source, s.prompt) for s in scenes(studio, plan_id)] == [("card", DEFAULT_PROMPT)] * 3


def test_prompt_stored_before_a_policy_change_is_never_sent_and_does_not_stall_the_worker(studio):
    """A stored prompt that no longer passes the policy (e.g. a phrase added in a later version)."""
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]", 1: PROMPT + " 두번째 [fake:slow]"})
    confirm(studio, plan_id)
    edit_scene(studio, plan_id, 0, prompt="cctv 화면 같은 장면")
    studio.service.tick()  # must not raise: one bad row cannot stop every other scene
    rows = scenes(studio, plan_id)
    assert rows[0].status not in {"waiting", "submitting", "queued"} and rows[0].request_id is None
    assert rows[1].status == "queued"
    assert all("cctv" not in job.request.prompt for job in studio.provider.jobs.values())
    by_scene = {row.scene_id: row.status for row in usage(studio)}
    assert by_scene[rows[0].id] == "not_sent"


@pytest.mark.parametrize("where", ["environment", "stored"])
def test_confirm_refuses_a_prompt_containing_the_key(studio, monkeypatch, where):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: f"{PROMPT} {KEY}"})  # saved while no key was configured
    if where == "environment":
        monkeypatch.setenv(VIDEO_ENV_NAME, KEY)
    else:
        store = VideoAIKeyStore(studio.app.state.config.data_dir, FakeCipher())
        store.save(KEY)
        studio.service.keys = store
    with pytest.raises(AIVideoError) as excinfo:
        confirm(studio, plan_id)
    assert refusal(excinfo) == (SECRET_PROMPT, 422)
    assert usage(studio) == [] and studio.provider.calls == [] and scenes(studio, plan_id)[0].status == "planned"


@pytest.mark.parametrize("where", ["environment", "stored"])
def test_update_scenes_never_stores_a_prompt_containing_the_key(studio, monkeypatch, where):
    """The key must never reach SQLite (or the plan page that renders the prompt)."""
    ready_studio(studio)
    if where == "environment":
        monkeypatch.setenv(VIDEO_ENV_NAME, KEY)
    else:
        store = VideoAIKeyStore(studio.app.state.config.data_dir, FakeCipher())
        store.save(KEY)
        studio.service.keys = store
    plan_id = studio.service.create_plan(studio.draft_id, 30)
    with pytest.raises(AIVideoError):
        studio.service.update_scenes(plan_id, 1, [
            {"position": 0, "source": "generated", "prompt": f"{PROMPT} {KEY}", "model_path": MODEL}])
    assert all(KEY not in s.prompt for s in scenes(studio, plan_id))
    assert studio.provider.calls == []


# --------------------------------------------------------------------------- provider outcomes


@pytest.mark.parametrize(("marker", "scene_status", "code", "usage_status", "has_request"), [
    ("[fake:auth]", "failed", "video_ai_auth_failed", "failed", False),
    ("[fake:credits]", "failed", "video_ai_credits", "failed", False),
    ("[fake:input]", "failed", "video_ai_bad_input", "failed", False),
    ("[fake:unavailable]", "failed", "video_ai_unavailable", "not_sent", False),
    ("[fake:ambiguous]", "unknown", "video_ai_unknown_submit", "unknown", False),
    ("[fake:nsfw]", "nsfw", "video_ai_nsfw", "failed", True),
    ("[fake:fail]", "failed", "video_ai_provider_failed", "failed", True),
    ("[fake:bad-clip]", "failed", "video_ai_clip_invalid", "completed", True),
])
def test_fake_failure_markers_map_to_scene_and_usage_states(studio, marker, scene_status, code, usage_status, has_request):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: f"{PROMPT} {marker}"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()  # a second pass never resubmits a finished or unknown scene
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code, scene.message) == (scene_status, code, ERROR_MESSAGES[code])
    assert scene.finished_at is not None and scene.clip_name is None
    [row] = usage(studio)
    assert row.status == usage_status and (row.request_id is not None) == has_request
    assert len(calls(studio.provider, "submit")) == 1
    assert plan_row(studio, plan_id).status == "review"
    assert not list((studio.data_dir / "ai-clips").glob("clip-*"))
    assert studio.service.readiness()["usage"]["spent"] == (Decimal(0) if usage_status == "not_sent" else Decimal("0.5"))
    if marker in ("[fake:nsfw]", "[fake:fail]"):
        assert calls(studio.provider, "fetch") == []


def test_rate_limited_submit_is_requeued_then_failed_after_max_requeues(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:rate]"})
    confirm(studio, plan_id)
    for attempt in range(1, MAX_REQUEUES + 1):
        studio.service.tick()
        scene = scenes(studio, plan_id)[0]
        assert scene.status == "waiting" and scene.clip_meta == {"requeues": attempt}
        assert scene.message == ERROR_MESSAGES["video_ai_rate_limited"] and scene.error_code is None
        assert [row.status for row in usage(studio)] == ["reserved"]
        assert plan_row(studio, plan_id).status == "generating"
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code) == ("failed", "video_ai_rate_limited")
    assert [row.status for row in usage(studio)] == ["failed"]
    assert len(calls(studio.provider, "submit")) == MAX_REQUEUES + 1
    studio.service.tick()
    assert len(calls(studio.provider, "submit")) == MAX_REQUEUES + 1


def test_idempotency_key_kept_across_requeues_and_renewed_after_a_definite_failure(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:rate]", 1: PROMPT + " [fake:fail]"})
    confirm(studio, plan_id)
    studio.service.tick()  # scene 1 (rate) is requeued, scene 2 (fail) is submitted and fails
    studio.service.tick()  # scene 1 is resent within the same attempt
    keys = submit_keys(studio.provider)
    assert len(keys) == 3 and keys[0] == keys[2] != keys[1]
    assert all(re.fullmatch(r"[0-9a-f]{32}", key) for key in keys)
    assert scenes(studio, plan_id)[1].status == "failed" and scenes(studio, plan_id)[1].submit_key == keys[1]
    edit_scene(studio, plan_id, 0, prompt=PROMPT)  # stop the rate limit marker for the retry below
    studio.service.cancel_scene(plan_id, revision(studio, plan_id), 0)
    confirm(studio, plan_id)
    renewed = {s.position: s.submit_key for s in scenes(studio, plan_id)}
    assert renewed[0] not in keys and renewed[1] not in keys  # only an unknown outcome keeps its key
    assert re.fullmatch(r"[0-9a-f]{32}", renewed[1])
    assert [(row.attempt, row.status) for row in usage(studio)] == [(1, "not_sent"), (1, "failed"), (2, "reserved"), (2, "reserved")]


def test_slow_generation_stays_in_progress(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "queued"
    for _ in range(3):
        studio.service.tick()
        scene = scenes(studio, plan_id)[0]
        assert scene.status == "in_progress" and scene.message == "공급사에서 생성 중"
    assert [row.status for row in usage(studio)] == ["submitted"]
    assert len(calls(studio.provider, "submit")) == 1 and calls(studio.provider, "fetch") == []
    assert plan_row(studio, plan_id).status == "generating" and studio.service.has_work()


def test_timeout_after_timeout_minutes_cancels_at_provider_and_fails(studio):
    ready_studio(studio, timeout=5)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    request_id = scenes(studio, plan_id)[0].request_id
    edit_scene(studio, plan_id, 0, submitted_at=utcnow() - timedelta(minutes=4))
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "in_progress" and calls(studio.provider, "cancel") == []
    edit_scene(studio, plan_id, 0, submitted_at=utcnow() - timedelta(minutes=6))
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    # Generation had started, so the cancel is refused: the scene closes as failed but stays refetchable.
    assert (scene.status, scene.error_code, scene.message) == ("failed", "video_ai_timeout", TIMEOUT_OPEN_MESSAGE)
    assert calls(studio.provider, "cancel") == [request_id]
    assert [row.status for row in usage(studio)] == ["failed"]
    assert plan_row(studio, plan_id).status == "review" and not studio.service.has_work()


def test_status_check_error_keeps_the_scene_and_retries_next_pass(studio, monkeypatch):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()

    def broken(request_id):
        raise ProviderUnavailable("PROSE from provider https://evil.invalid/ token=abc")

    monkeypatch.setattr(studio.provider, "status", broken)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert scene.status == "queued" and scene.message == STATUS_RETRY + ERROR_MESSAGES["video_ai_unavailable"]
    assert [row.status for row in usage(studio)] == ["submitted"]


def test_provider_prose_never_reaches_stored_messages(studio, monkeypatch):
    ready_studio(studio)
    prose = "PROSE from provider https://evil.invalid/x?token=abc fake-deadbeef"
    original = studio.provider.submit

    class OddError(VideoProviderError):
        code = "video_ai_odd"

    def submit(request):
        if "[p:auth]" in request.prompt:
            studio.provider.calls.append(("submit", request.model_path, request.idempotency_key))
            raise ProviderAuthError(prose)
        if "[p:boom]" in request.prompt:
            studio.provider.calls.append(("submit", request.model_path, request.idempotency_key))
            raise RuntimeError(prose)
        if "[p:odd]" in request.prompt:
            studio.provider.calls.append(("submit", request.model_path, request.idempotency_key))
            raise OddError(prose)
        return original(request)

    monkeypatch.setattr(studio.provider, "submit", submit)
    plan_id = generated_plan(studio, {0: PROMPT + " [p:auth]", 1: PROMPT + " [p:boom]", 2: PROMPT + " [p:odd]"})
    configure(studio, max_active=4)
    confirm(studio, plan_id)
    studio.service.tick()
    rows = scenes(studio, plan_id)
    assert [(s.status, s.error_code) for s in rows] == [
        ("failed", "video_ai_auth_failed"), ("unknown", "video_ai_unknown_submit"), ("failed", "video_ai_odd")]
    assert rows[0].message == ERROR_MESSAGES["video_ai_auth_failed"]
    assert rows[1].message == ERROR_MESSAGES["video_ai_unknown_submit"]
    assert rows[2].message == ERROR_MESSAGES["video_ai_failed"]
    assert [row.status for row in usage(studio)] == ["failed", "unknown", "failed"]
    assert_fixed_messages(studio)


# --------------------------------------------------------------------------- recovery and unknown outcomes


class Crash(BaseException):
    """Simulates the process dying while the submit request is in flight."""


def test_recover_turns_interrupted_submission_into_unknown_and_never_resubmits(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)

    def crash(request):
        studio.provider.calls.append(("submit", request.model_path, request.idempotency_key))
        raise Crash

    studio.provider.submit = crash
    with pytest.raises(Crash):
        studio.service.tick()
    del studio.provider.submit
    assert scenes(studio, plan_id)[0].status == "submitting"
    assert not studio.service.lock.is_locked
    studio.service.recover()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code, scene.message) == (
        "unknown", "video_ai_unknown_submit", ERROR_MESSAGES["video_ai_unknown_submit"])
    assert [row.status for row in usage(studio)] == ["unknown"]
    assert plan_row(studio, plan_id).status == "review" and not studio.service.has_work()
    studio.service.tick()
    studio.service.recover()
    studio.service.tick()
    assert len(calls(studio.provider, "submit")) == 1 and scenes(studio, plan_id)[0].status == "unknown"

    estimate = studio.service.estimate(plan_id)
    assert "결과 불명 장면을 먼저 실패로 확정하세요." in estimate["problems"] and not estimate["can_submit"]
    assert estimate["month_spent"] == "0.5"  # an unknown request may have been billed
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.resolve_unknown(plan_id, revision(studio, plan_id), 1)
    assert refusal(excinfo) == ("결과 불명 상태인 장면만 실패로 확정할 수 있습니다.", 409)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.resolve_unknown(plan_id, revision(studio, plan_id) + 1, 0)
    assert refusal(excinfo) == (STALE_REVISION, 409)
    studio.service.resolve_unknown(plan_id, revision(studio, plan_id), 0)
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code, scene.message) == (
        "failed", "video_ai_unknown_submit", "사용자가 결과 불명 요청을 실패로 확정했습니다. 예상 비용은 이번 달 사용량에 남습니다.")
    assert [row.status for row in usage(studio)] == ["unknown"]

    # A new, explicitly confirmed attempt gets its own usage row.
    estimate = studio.service.estimate(plan_id)
    assert estimate["can_submit"] and estimate["plan_spent"] == "0.5" and estimate["total"] == "0.5"
    assert confirm(studio, plan_id) == 1
    assert scenes(studio, plan_id)[0].attempt == 2
    assert [(row.attempt, row.status) for row in usage(studio)] == [(1, "unknown"), (2, "reserved")]
    studio.service.tick()
    assert len(calls(studio.provider, "submit")) == 2
    # The explicit resend after an unknown outcome reuses the first Idempotency-Key.
    first_key, second_key = submit_keys(studio.provider)
    assert first_key and re.fullmatch(r"[0-9a-f]{32}", first_key) and second_key == first_key
    assert [(row.attempt, row.status) for row in usage(studio)] == [(1, "unknown"), (2, "submitted")]
    assert studio.service.estimate(plan_id)["month_spent"] == "1"


def test_recover_resumes_downloading_scenes_and_removes_orphan_clips(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    edit_scene(studio, plan_id, 0, status="downloading")
    clips = studio.data_dir / "ai-clips"
    orphan = clips / ("clip-" + "a" * 32 + ".mp4")
    orphan.write_bytes(b"partial")
    unrelated = clips / "notes.txt"
    unrelated.write_text("keep")
    studio.service.recover()
    scene = scenes(studio, plan_id)[0]
    assert scene.status == "in_progress" and scene.message == "재시작 후 생성 결과를 다시 확인합니다."
    assert not orphan.exists() and unrelated.exists()
    assert [row.status for row in usage(studio)] == ["submitted"]
    studio.service.tick()
    assert len(calls(studio.provider, "submit")) == 1 and calls(studio.provider, "status")


def test_start_recovers_and_wakes_only_when_work_remains(studio):
    ready_studio(studio)
    woke = []
    studio.service.wake = lambda: woke.append(1)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    edit_scene(studio, plan_id, 0, status="submitting")
    woke.clear()  # confirm itself wakes the worker; only start() is under test here
    studio.service.start()
    assert scenes(studio, plan_id)[0].status == "unknown" and woke == []
    other = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, other)
    woke.clear()
    studio.service.start()
    assert woke == [1] and calls(studio.provider, "submit") == []
    assert scenes(studio, other)[0].status == "waiting"


def test_background_worker_runs_until_no_work_then_exits(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:fail]"})
    confirm(studio, plan_id)
    studio.service.poll_interval = 0.05
    AIVideoCoordinator.wake(studio.service)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (studio.service.has_work() or studio.service.thread is not None):
        time.sleep(0.05)
    assert scenes(studio, plan_id)[0].status == "failed"
    assert studio.service.thread is None
    assert len(calls(studio.provider, "submit")) == 1


# --------------------------------------------------------------------------- cancel


def test_cancel_waiting_scene_is_local_and_not_sent(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.cancel_scene(plan_id, revision(studio, plan_id), 1)
    assert refusal(excinfo) == ("제출 대기·대기열 상태인 장면만 취소할 수 있습니다.", 409)
    assert studio.service.cancel_scene(plan_id, revision(studio, plan_id), 0) == "canceled"
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code, scene.message) == ("canceled", "video_ai_canceled", "제출 전에 취소했습니다.")
    assert [row.status for row in usage(studio)] == ["not_sent"]
    studio.service.tick()
    assert studio.provider.calls == [] and plan_row(studio, plan_id).status == "review"
    assert studio.service.estimate(plan_id)["month_spent"] == "0"


def test_cancel_queued_scene_asks_the_provider(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    request_id = scenes(studio, plan_id)[0].request_id
    assert studio.service.cancel_scene(plan_id, revision(studio, plan_id), 0) == "canceled"
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code, scene.message) == (
        "canceled", "video_ai_canceled", "공급사 대기열에서 취소했습니다.")
    assert calls(studio.provider, "cancel") == [request_id]
    assert [row.status for row in usage(studio)] == ["canceled"]
    polls = len(calls(studio.provider, "status"))
    studio.service.tick()
    assert len(calls(studio.provider, "status")) == polls


def test_cancel_refused_when_started_or_provider_already_running(studio):
    ready_studio(studio)
    studio.provider.steps = 10
    plan_id = generated_plan(studio, {0: PROMPT, 1: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    rows = scenes(studio, plan_id)
    assert rows[0].status == "in_progress" and rows[1].status == "in_progress"
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.cancel_scene(plan_id, revision(studio, plan_id), 1)
    assert refusal(excinfo) == ("제출 대기·대기열 상태인 장면만 취소할 수 있습니다.", 409)
    # The database still says queued, but the provider has already started the job.
    edit_scene(studio, plan_id, 0, status="queued")
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.cancel_scene(plan_id, revision(studio, plan_id), 0)
    assert refusal(excinfo) == ("공급사에서 이미 처리를 시작해 취소할 수 없습니다. 완료를 기다리세요.", 409)
    assert scenes(studio, plan_id)[0].status == "queued"
    assert [row.status for row in usage(studio)] == ["submitted", "submitted"]


# --------------------------------------------------------------------------- edits after generation and clip access


def test_update_scenes_refuses_changes_while_generating(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.update_scenes(plan_id, revision(studio, plan_id), [{"position": 0, "source": "card"}])
    assert refusal(excinfo) == ("장면 1은 생성 중이라 바꿀 수 없습니다. 끝난 뒤 다시 시도하세요.", 409)
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": 0, "source": "generated", "prompt": PROMPT + " [fake:slow]", "model_path": MODEL}])
    assert scenes(studio, plan_id)[0].status == "waiting"


@needs_ffmpeg
def test_update_scenes_on_ready_scene_with_new_prompt_resets_clip_and_review(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert scene.status == "ready" and studio.service.clip_path(scene.id).is_file()
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    assert plan_row(studio, plan_id).reviewed_at is not None
    # Same generation inputs: the clip stays; any save still asks for a fresh plan review.
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": 0, "source": "generated", "prompt": PROMPT, "model_path": MODEL}])
    kept = scenes(studio, plan_id)[0]
    assert kept.status == "ready" and kept.clip_name == scene.clip_name and kept.reviewed
    assert plan_row(studio, plan_id).reviewed_at is None
    # A different prompt would throw the paid clip away: only an explicit 'discard' allows that.
    before = revision(studio, plan_id)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.update_scenes(plan_id, before, [
            {"position": 0, "source": "generated", "prompt": PROMPT + " 다른 색", "model_path": MODEL}])
    assert refusal(excinfo) == (DISCARD_NEEDED.format(1), 409)
    assert scenes(studio, plan_id)[0].clip_name == scene.clip_name and revision(studio, plan_id) == before
    for change in ({"source": "card"}, {"source": "generated", "prompt": PROMPT, "model_path": OTHER_MODEL}):
        with pytest.raises(AIVideoError):
            studio.service.update_scenes(plan_id, before, [{"position": 0, "prompt": PROMPT, **change}])
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": 0, "source": "generated", "prompt": PROMPT + " 다른 색", "model_path": MODEL, "discard": True}])
    reset = scenes(studio, plan_id)[0]
    assert (reset.status, reset.clip_name, reset.clip_meta, reset.reviewed, reset.error_code) == (
        "planned", None, None, False, None)
    assert plan_row(studio, plan_id).status == "draft"
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.clip_path(scene.id)
    assert refusal(excinfo) == ("검증된 생성 영상이 없습니다.", 404)
    estimate = studio.service.estimate(plan_id)
    assert estimate["can_submit"] and estimate["scenes"][0]["position"] == 0 and estimate["plan_spent"] == "0.5"


@needs_ffmpeg
def test_clip_path_only_for_ready_scenes_with_a_file(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    first = scenes(studio, plan_id)[0]
    for scene_id in (first.id, scenes(studio, plan_id)[1].id, 999_999):
        with pytest.raises(AIVideoError) as excinfo:
            studio.service.clip_path(scene_id)
        assert refusal(excinfo) == ("검증된 생성 영상이 없습니다.", 404)
    confirm(studio, plan_id)
    with pytest.raises(AIVideoError):
        studio.service.clip_path(first.id)  # waiting
    studio.service.tick()
    path = studio.service.clip_path(first.id)
    assert path.is_file() and path.stat().st_size > 1000
    path.unlink()
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.clip_path(first.id)
    assert refusal(excinfo) == ("생성 영상 파일이 없습니다.", 404)


def test_clip_path_with_tampered_name_is_a_fixed_404(studio, tmp_path):
    plan_id = studio.service.create_plan(studio.draft_id, 30)
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"outside")
    scene_id = scenes(studio, plan_id)[0].id
    for name in ("../../secret.mp4", str(outside), "clip-zz.mp4"):
        edit_scene(studio, plan_id, 0, status="ready", source="generated", clip_name=name)
        with pytest.raises(AIVideoError) as excinfo:
            studio.service.clip_path(scene_id)
        assert excinfo.value.status == 404
    edit_scene(studio, plan_id, 0, status="planned", source="card", clip_name=None)


# --------------------------------------------------------------------------- worker lock


def test_worker_file_lock_lets_only_one_coordinator_submit(studio, monkeypatch):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    other = AIVideoCoordinator(
        studio.sessions, studio.data_dir, studio.app.state.video, studio.service.keys, studio.provider, poll_interval=60)
    monkeypatch.setattr(other, "wake", lambda: None)
    try:
        # Another NewsFlow process owns the worker lock: this one neither submits nor recovers.
        studio.service.lock.acquire(timeout=0)
        try:
            edit_scene(studio, plan_id, 1, status="submitting")
            other.tick()
            other.recover()
            assert scenes(studio, plan_id)[1].status == "submitting"
            edit_scene(studio, plan_id, 1, status="planned")
            assert studio.provider.calls == [] and scenes(studio, plan_id)[0].status == "waiting"
        finally:
            studio.service.lock.release()

        # Both coordinators tick at the same time: only the lock holder submits.
        entered, original = Event(), studio.provider.submit

        def slow_submit(request):
            entered.set()
            time.sleep(0.15)
            return original(request)

        monkeypatch.setattr(studio.provider, "submit", slow_submit)
        errors: list[BaseException] = []

        def run(coordinator):
            try:
                coordinator.tick()
            except BaseException as exc:  # noqa: BLE001 - surfaced by the assert below
                errors.append(exc)

        first = Thread(target=run, args=(studio.service,))
        first.start()
        assert entered.wait(5)
        second = Thread(target=run, args=(other,))
        second.start()
        second.join(5)
        first.join(5)
        assert errors == [] and not first.is_alive() and not second.is_alive()
        assert len(calls(studio.provider, "submit")) == 1
        assert [row.status for row in usage(studio)] == ["submitted"]
        assert scenes(studio, plan_id)[0].status == "queued"
        other.tick()  # the lock was released by both: the other coordinator can poll now
        assert len(calls(studio.provider, "submit")) == 1 and calls(studio.provider, "status")
    finally:
        other.close()


# --------------------------------------------------------------------------- no-repay recovery and compose retry


class FailingRender(FakeRenderAdapter):
    def render(self, plan, work, tts, progress, cancel):
        from newsflow.video.engine import RenderError

        raise RenderError("엔진 실패", kind="render")


def ready_reviewed_plan(studio: Studio) -> tuple[int, AIVideoScene]:
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)
    studio.service.tick()  # submit
    studio.service.tick()  # completed -> download -> probe
    scene = scenes(studio, plan_id)[0]
    assert scene.status == "ready", scene.message
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    return plan_id, scene


@needs_ffmpeg
def test_failed_composition_can_be_retried_with_the_same_paid_clips(studio):
    plan_id, scene = ready_reviewed_plan(studio)
    studio.app.state.video.engine = FailingRender()
    first = studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.app.state.video.future.result(timeout=10)
    studio.service.sync()
    plan = plan_row(studio, plan_id)
    assert plan.status == "compose_failed" and plan.render_job_id == first
    # Edits are allowed again (the failed job is released) and the clip, review and cost stay.
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [{"position": 1, "source": "card"}])
    assert plan_row(studio, plan_id).render_job_id is None
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    studio.app.state.video.engine = FakeRenderAdapter()
    second = studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.app.state.video.future.result(timeout=10)
    studio.service.sync()
    assert second != first and plan_row(studio, plan_id).status == "composed"
    assert len(calls(studio.provider, "submit")) == 1 and [row.status for row in usage(studio)] == ["completed"]
    with studio.sessions() as session:
        job = session.get(RenderJob, second)
        project = session.get(VideoProject, job.project_id)
        clip_meta = scenes(studio, plan_id)[0].clip_meta
        assert project.snapshot["ai_clips"] == [{"position": 0, "name": scene.clip_name, "sha256": clip_meta["sha256"]}]
        assert job.metadata_json["ai_clips"] == project.snapshot["ai_clips"] and job.metadata_json["ai_plan_id"] == plan_id
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("이미 최종 합성을 시작했습니다.", 409)


@needs_ffmpeg
def test_a_clip_changed_after_review_is_refused_at_approval_and_becomes_refetchable(studio):
    plan_id, scene = ready_reviewed_plan(studio)
    path = studio.service.clips.path(scene.clip_name)
    path.write_bytes(path.read_bytes() + b"\x00")
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert excinfo.value.status == 409 and "'결과 다시 받기'" in str(excinfo.value)
    assert plan_row(studio, plan_id).render_job_id is None
    lost = scenes(studio, plan_id)[0]
    assert (lost.status, lost.error_code, lost.message) == ("failed", "video_ai_download_failed", CLIP_LOST_MESSAGE)
    studio.service.refetch(plan_id, revision(studio, plan_id), 0)  # the paid result, no new request
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "ready" and len(calls(studio.provider, "submit")) == 1


@needs_ffmpeg
def test_a_clip_changed_between_approval_and_render_fails_the_job_with_the_clip_hint(studio):
    plan_id, scene = ready_reviewed_plan(studio)
    gated = GatedRender()
    studio.app.state.video.engine = gated
    real_run = studio.app.state.video._run

    def tamper_then_run(identifier, tts, cancel):
        path = studio.service.clips.path(scene.clip_name)
        path.write_bytes(path.read_bytes() + b"\x00")
        gated.gate.set()
        return real_run(identifier, tts, cancel)

    studio.app.state.video._run = tamper_then_run
    job_id = studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.app.state.video.future.result(timeout=10)
    with studio.sessions() as session:
        job = session.get(RenderJob, job_id)
        assert job.status == "failed" and job.message.startswith("AI 생성 장면 파일(형식·검토한 파일과 같은지) 실패.")
    assert gated.calls == []
    studio.service.sync()
    assert plan_row(studio, plan_id).status == "compose_failed"


@needs_ffmpeg
def test_a_completed_clip_that_failed_validation_is_fetched_again_without_a_new_request(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:bad-clip]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code) == ("failed", "video_ai_clip_invalid") and scene.request_id
    assert [row.status for row in usage(studio)] == ["completed"]
    studio.provider.jobs[scene.request_id].bad_clip = False  # the provider's file is fine the second time
    studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    refetched = scenes(studio, plan_id)[0]
    assert refetched.status == "in_progress" and refetched.clip_meta == {"refetch_pending": True}
    assert refetched.message == "완료된 결과를 다시 확인해 내려받습니다(추가 생성 요청 없음)."
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    # A delivered clip starts a fresh count: only failed fetches use up the three refetches.
    assert scene.status == "ready" and scene.request_id == refetched.request_id
    assert "refetches" not in scene.clip_meta and "refetch_pending" not in scene.clip_meta
    assert len(calls(studio.provider, "submit")) == 1 and len(calls(studio.provider, "fetch")) == 2
    assert [(row.attempt, row.status) for row in usage(studio)] == [(1, "completed")]


@needs_ffmpeg
def test_refetch_is_limited_and_only_for_completed_but_undelivered_clips(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:bad-clip]", 1: PROMPT + " [fake:fail]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.refetch(plan_id, revision(studio, plan_id), 1)  # provider-side failure: nothing to fetch
    assert excinfo.value.status == 409
    for _ in range(3):
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
        studio.service.tick()
        assert scenes(studio, plan_id)[0].error_code == "video_ai_clip_invalid"
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    assert refusal(excinfo) == ("결과 다시 받기는 3번까지입니다. 카드로 바꾸거나 다시 생성하세요.", 409)
    assert len(calls(studio.provider, "submit")) == 2


def test_low_disk_space_keeps_the_paid_result_fetchable(studio, monkeypatch):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)
    usage_tuple = shutil.disk_usage(studio.data_dir)
    monkeypatch.setattr(
        "newsflow.video.ai.service.shutil.disk_usage", lambda path: usage_tuple._replace(free=10 * 1024 * 1024))
    studio.service.tick()  # submit, then (steps=1) completed -> disk check before any download
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code) == ("failed", "video_ai_disk_full") and scene.request_id
    assert scene.message == ERROR_MESSAGES["video_ai_disk_full"] and calls(studio.provider, "fetch") == []
    assert [row.status for row in usage(studio)] == ["completed"]


@needs_ffmpeg
def test_a_completed_result_is_downloaded_even_after_the_timeout(studio):
    """A long pause (app closed) must not throw away a finished, paid result."""
    ready_studio(studio, timeout=5)
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)
    studio.service.tick()
    edit_scene(studio, plan_id, 0, submitted_at=utcnow() - timedelta(minutes=60))
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "ready" and calls(studio.provider, "cancel") == []


def test_a_request_the_provider_no_longer_knows_fails_instead_of_polling_forever(studio, monkeypatch):
    from newsflow.video.ai.contracts import ProviderRequestMissing

    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()

    def missing(request_id):
        raise ProviderRequestMissing(status_code=404)

    monkeypatch.setattr(studio.provider, "status", missing)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code) == ("failed", "video_ai_request_missing")
    assert [row.status for row in usage(studio)] == ["failed"] and not studio.service.has_work()


def test_list_page_and_status_api_show_the_finished_composition(studio):
    plan_id = studio.service.create_plan(studio.draft_id, 30)
    job_id = studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.app.state.video.future.result(timeout=10)
    with studio.sessions() as session:
        assert session.get(RenderJob, job_id).status == "simulated"
    client = TestClient(studio.app, base_url="http://127.0.0.1")
    assert "최종 합성 완료" in client.get("/video/ai").text
    assert plan_row(studio, plan_id).status == "composed"


def test_a_half_of_a_key_pair_in_a_prompt_is_refused(studio, monkeypatch):
    ready_studio(studio)
    monkeypatch.setenv(VIDEO_ENV_NAME, KEY)
    plan_id = studio.service.create_plan(studio.draft_id, 30)
    secret = KEY.split(":", 1)[1]
    with pytest.raises(AIVideoError):
        studio.service.update_scenes(plan_id, 1, [
            {"position": 0, "source": "generated", "prompt": f"{PROMPT} {secret.upper()}", "model_path": MODEL}])
    assert all(secret not in s.prompt for s in scenes(studio, plan_id))


# --------------------------------------------------------------------------- review round 2: prices, locks, gates


def test_estimate_and_confirm_use_the_current_confirmed_price_not_the_saved_one(studio):
    ready_studio(studio, job="1", monthly="20")
    plan_id = generated_plan(studio)  # saved at 0.1/s x 5 s = 0.5
    assert studio.service.estimate(plan_id)["total"] == "0.5"
    model = next(m for m in studio.service.models() if m.path == MODEL)
    add_model(studio, price="4", model_id=model.id)  # re-confirmed at 4/s: 20 for the same scene
    estimate = studio.service.estimate(plan_id)
    assert estimate["total"] == "20" and estimate["scenes"][0]["cost"] == "20"
    assert not estimate["can_submit"] and "작업별 한도" in estimate["problems"][0]
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "20", True)
    assert excinfo.value.status == 422 and "작업별 한도" in str(excinfo.value)
    configure(studio, job="50", monthly="100")
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.confirm_generation(plan_id, revision(studio, plan_id), "0.5", True)
    assert refusal(excinfo) == (STALE_TOTAL, 409)
    assert usage(studio) == [] and studio.provider.calls == []
    add_model(studio, confirmed=False, model_id=model.id)
    problems = studio.service.estimate(plan_id)["problems"]
    assert "장면 1의 모델이 바뀌었거나 사용할 수 없습니다. 모델을 다시 고르세요." in problems


def test_a_price_change_after_confirmation_cancels_the_waiting_scene_unsent(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    model = next(m for m in studio.service.models() if m.path == MODEL)
    add_model(studio, price="0.2", model_id=model.id)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.message) == ("canceled", "모델 설정이 바뀌어 제출하지 않았습니다. 장면을 다시 확인하세요.")
    assert [row.status for row in usage(studio)] == ["not_sent"] and studio.provider.calls == []


def test_resaving_the_storyboard_never_changes_a_confirmed_scene(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    model = next(m for m in studio.service.models() if m.path == MODEL)
    save_model(studio.sessions, path=MODEL, label="시험 모델", price_per_second="0.1", durations="5,10",
               resolution="720p", confirmed=True, model_id=model.id)
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": 0, "source": "generated", "prompt": PROMPT, "model_path": MODEL}, {"position": 1, "source": "card"}])
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.clip_seconds, scene.estimated_cost) == ("waiting", 5, "0.5")
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.update_scenes(plan_id, revision(studio, plan_id), [
            {"position": 0, "source": "generated", "prompt": PROMPT + " 변경", "model_path": MODEL}])
    assert excinfo.value.status == 409
    # The model's lengths changed after confirmation (today it would be a 10 s / 1.0 clip), so the
    # 5 s / 0.5 reservation no longer matches: nothing is sent and the user confirms again.
    studio.service.tick()
    assert studio.provider.calls == [] and [(row.seconds, row.status) for row in usage(studio)] == [(5, "not_sent")]
    assert scenes(studio, plan_id)[0].message == "모델 설정이 바뀌어 제출하지 않았습니다. 장면을 다시 확인하세요."


def test_an_unknown_scene_is_locked_until_the_user_closes_it(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:ambiguous]"})
    confirm(studio, plan_id)
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "unknown"
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.update_scenes(plan_id, revision(studio, plan_id), [
            {"position": 0, "source": "generated", "prompt": PROMPT + " 다른 장면", "model_path": MODEL}])
    assert refusal(excinfo) == ("장면 1은 결과 불명 상태입니다. 먼저 실패로 확정한 뒤 바꾸세요.", 409)
    studio.service.resolve_unknown(plan_id, revision(studio, plan_id), 0)
    key = scenes(studio, plan_id)[0].submit_key
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": 0, "source": "generated", "prompt": PROMPT + " 다른 장면", "model_path": MODEL}])
    assert scenes(studio, plan_id)[0].submit_key is None and key  # a changed request never reuses the old key


def test_a_batch_that_fills_the_month_exactly_is_still_sent(studio):
    ready_studio(studio, job="0.5", monthly="0.5")
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status in {"queued", "ready", "in_progress", "downloading"}
    assert len(calls(studio.provider, "submit")) == 1
    assert "이번 달 AI 영상 한도를 모두 사용했습니다." in studio.service.readiness()["reasons"]  # no further confirmations


def test_a_status_failure_after_the_deadline_keeps_polling_then_closes_refetchably(studio, monkeypatch):
    ready_studio(studio, timeout=5)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    real_status = studio.provider.status

    def down(request_id):
        raise ProviderUnavailable()

    monkeypatch.setattr(studio.provider, "status", down)
    monkeypatch.setattr(studio.provider, "cancel", lambda request_id: False)  # generation already started
    edit_scene(studio, plan_id, 0, submitted_at=utcnow() - timedelta(minutes=6))
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert scene.status in {"queued", "in_progress"} and scene.message.startswith(STATUS_RETRY)
    edit_scene(studio, plan_id, 0, submitted_at=utcnow() - timedelta(minutes=11))
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code) == ("failed", "video_ai_timeout") and scene.request_id
    monkeypatch.setattr(studio.provider, "status", real_status)
    studio.provider.jobs[scene.request_id].slow = False
    studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "ready" and len(calls(studio.provider, "submit")) == 1


def test_a_failed_write_after_submit_keeps_the_request_id_and_never_resends(studio, monkeypatch):
    from sqlalchemy.exc import OperationalError

    ready_studio(studio)
    studio.provider.steps = 3
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    real = studio.service._record_submission
    failures = {"left": 5}

    def flaky(*args):
        if failures["left"]:
            failures["left"] -= 1
            raise OperationalError("UPDATE", {}, Exception("database is locked"))
        return real(*args)

    monkeypatch.setattr(studio.service, "_record_submission", flaky)
    monkeypatch.setattr(studio.service.stop, "wait", lambda delay=None: False)
    studio.service.tick()  # submit succeeds, the four writes fail: the id is kept in memory
    assert scenes(studio, plan_id)[0].status == "submitting" and len(studio.service.unsaved) == 1
    studio.service.tick()  # the database still refuses: nothing new is sent, the id is still kept
    assert len(studio.service.unsaved) == 1 and len(calls(studio.provider, "submit")) == 1
    studio.service.tick()  # stored now
    scene = scenes(studio, plan_id)[0]
    assert scene.request_id and scene.status in {"queued", "in_progress"} and not studio.service.unsaved
    assert len(calls(studio.provider, "submit")) == 1 and [row.status for row in usage(studio)] == ["submitted"]


# --------------------------------------------------------------------------- review round 3: gates every pass


def test_a_withdrawn_approval_cancels_waiting_scenes_even_while_slots_are_full(studio):
    ready_studio(studio, max_active=1)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]", 1: PROMPT + " 두번째"})
    confirm(studio, plan_id)
    studio.service.tick()
    assert [s.status for s in scenes(studio, plan_id)[:2]] == ["queued", "waiting"]
    configure(studio, approved=False, max_active=1)
    studio.service.tick()  # the only slot is busy, but the waiting scene is still gated
    configure(studio, approved=True, max_active=1)  # approved again: a new date, after the confirmation
    studio.service.tick()
    second = scenes(studio, plan_id)[1]
    assert second.status == "canceled" and second.request_id is None
    assert len(calls(studio.provider, "submit")) == 1
    assert [row.status for row in usage(studio)][1] == "not_sent"


def test_reapproval_after_confirmation_does_not_carry_the_old_confirmation(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    configure(studio, approved=False)
    configure(studio, approved=True)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.message) == (
        "canceled", "확인 뒤에 유료 생성 승인이 다시 저장되어 이전 확인으로는 제출하지 않았습니다. 예상 비용을 다시 확인하세요.")
    assert studio.provider.calls == []


def test_a_per_job_limit_lowered_after_confirmation_stops_the_send(studio):
    ready_studio(studio, job="5", monthly="20")
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    configure(studio, job="0.1", monthly="20")
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.message) == ("canceled", "작업별 한도가 확인 뒤에 낮아져 제출하지 않았습니다. 예상 비용을 다시 확인하세요.")
    assert studio.provider.calls == [] and [row.status for row in usage(studio)] == ["not_sent"]


def test_a_resend_after_unknown_gets_a_new_key_when_the_request_changed(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:ambiguous]"})
    confirm(studio, plan_id)
    studio.service.tick()
    first_key = scenes(studio, plan_id)[0].submit_key
    studio.service.resolve_unknown(plan_id, revision(studio, plan_id), 0)
    model = next(m for m in studio.service.models() if m.path == MODEL)
    save_model(studio.sessions, path=MODEL, label="시험 모델", price_per_second="0.1", durations="10",
               resolution="720p", confirmed=True, model_id=model.id)  # same prompt, now a 10 s clip
    confirm(studio, plan_id)
    assert scenes(studio, plan_id)[0].submit_key != first_key
    rows = usage(studio)
    assert [(row.seconds, row.resolution) for row in rows] == [(5, "720p"), (10, "720p")]


def test_a_timeout_the_provider_cancelled_is_closed_and_not_offered_for_refetch(studio):
    ready_studio(studio, timeout=5)
    studio.provider.steps = 3
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()  # submitted; the first status poll answers queued
    edit_scene(studio, plan_id, 0, submitted_at=utcnow() - timedelta(minutes=6), status="queued")
    studio.provider.jobs[scenes(studio, plan_id)[0].request_id].polls = 0
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.error_code) == ("canceled", "video_ai_timeout")
    assert [row.status for row in usage(studio)] == ["canceled"]
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    assert excinfo.value.status == 409
    # It goes into the next batch as a plain new generation: no claim of failed downloads.
    estimate = studio.service.estimate(plan_id)
    assert estimate["can_submit"] and [line["position"] for line in estimate["scenes"]] == [0]
    assert estimate["notices"] == []


@needs_ffmpeg
def test_a_refetchable_paid_result_is_not_rebought_by_the_next_batch(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:bad-clip]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    assert scenes(studio, plan_id)[0].error_code == "video_ai_clip_invalid"
    estimate = studio.service.estimate(plan_id)
    assert estimate["scenes"] == [] and estimate["problems"] == ["새로 생성할 AI 장면이 없습니다."]
    assert estimate["notices"] == [(
        "장면 1은 '결과 다시 받기'로 추가 비용 없이 받을 수 있어 새 유료 생성에 넣지 않습니다. "
        "다시 생성하려면 그 장면의 '받아 둔 유료 AI 영상 버리기'에 체크하고 프롬프트나 모델을 바꾸세요.")]
    with pytest.raises(AIVideoError):
        confirm_as_shown(studio, plan_id)
    assert len(calls(studio.provider, "submit")) == 1


def test_in_flight_scenes_say_why_checks_paused_when_the_provider_is_off(studio, monkeypatch):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    monkeypatch.setattr(studio.service, "provider", lambda: None)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert scene.status in {"queued", "in_progress"}
    assert scene.message == "AI 영상 공급사가 '사용 안 함'이라 상태 확인을 멈췄습니다. 공급사를 다시 켜면 이어서 확인합니다."


def test_close_stores_request_ids_still_held_in_memory(studio):
    from newsflow.video.ai.contracts import Submission

    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    scene = scenes(studio, plan_id)[0]
    edit_scene(studio, plan_id, 0, status="submitting")
    studio.service.unsaved.append((scene.id, scene.attempt, Submission("req-closing-0001", "queued")))
    studio.service.close()
    stored = scenes(studio, plan_id)[0]
    assert (stored.status, stored.request_id) == ("queued", "req-closing-0001") and not studio.service.unsaved



# --------------------------------------------------------------------------- review round 4: per-reservation approval


def test_a_later_batch_on_the_same_plan_does_not_launder_an_older_confirmation(studio):
    ready_studio(studio, max_active=1)
    busy = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, busy)
    studio.service.tick()  # the only slot is taken by the slow plan
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)  # scene 0 reserved under the first approval, waiting for a slot
    configure(studio, approved=False, max_active=1)
    configure(studio, approved=True, max_active=1)  # a new approval date
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": 1, "source": "generated", "prompt": PROMPT + " 둘째", "model_path": MODEL}])
    confirm(studio, plan_id)  # a later batch on the same plan, under the new approval
    edit_scene(studio, busy, 0, status="canceled")  # free the slot
    studio.service.tick()
    studio.service.tick()
    rows = {s.position: s for s in scenes(studio, plan_id)}
    assert rows[0].status == "canceled" and rows[0].request_id is None  # old confirmation never sent
    assert rows[1].request_id is not None  # the confirmation made under the new approval is sent


def test_an_approval_stamped_in_the_future_does_not_cancel_a_normal_confirmation(studio):
    """No wall-clock comparison: a clock that was ahead when approving does not block sending."""
    ready_studio(studio)
    with studio.sessions.begin() as session:
        from newsflow.db.models import AppSetting

        session.get(AppSetting, "video_ai_approved_at").value = (utcnow() + timedelta(hours=2)).isoformat()
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    studio.service.tick()
    assert scenes(studio, plan_id)[0].request_id is not None


def test_the_paused_message_is_replaced_once_status_checks_answer_again(studio, monkeypatch):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "in_progress"
    real = studio.service.provider
    monkeypatch.setattr(studio.service, "provider", lambda: None)
    studio.service.tick()
    monkeypatch.setattr(studio.service, "provider", real)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.message) == ("in_progress", "공급사에서 생성 중")



# --------------------------------------------------------------------------- review round 5


def test_one_refetchable_scene_does_not_block_confirming_the_others(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:bad-clip]", 1: PROMPT + " [fake:fail]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    estimate = studio.service.estimate(plan_id)
    assert [line["position"] for line in estimate["scenes"]] == [1] and estimate["can_submit"]
    assert estimate["notices"] and not estimate["problems"]


def test_a_reservation_from_last_month_is_not_sent_this_month(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    with studio.sessions.begin() as session:
        row = session.scalar(select(VideoAIUsage))
        row.created_at = row.created_at - timedelta(days=40)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert (scene.status, scene.message) == ("canceled", "달이 바뀌어 지난달의 확인으로는 제출하지 않았습니다. 예상 비용을 다시 확인하세요.")
    assert studio.provider.calls == []


# ---------------------------------------------------------------- paid results, script edits, currency


def ready_and_reviewed(studio: Studio) -> tuple[int, AIVideoScene]:
    ready_studio(studio)
    plan_id = generated_plan(studio)
    confirm(studio, plan_id)
    studio.service.tick()
    scene = scenes(studio, plan_id)[0]
    assert scene.status == "ready", scene.message
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    return plan_id, scene


@needs_ffmpeg
def test_a_ready_clip_stays_usable_when_its_model_is_no_longer_confirmed(studio):
    plan_id, scene = ready_and_reviewed(studio)
    model = next(m for m in list_models(studio.sessions) if m.path == MODEL)
    add_model(studio, confirmed=False, model_id=model.id)
    # The form posts the stored prompt back (browsers may change whitespace): nothing changed, nothing lost.
    studio.service.update_scenes(plan_id, revision(studio, plan_id), [
        {"position": 0, "source": "generated", "prompt": f"  {PROMPT}\r\n", "model_path": MODEL}])
    kept = scenes(studio, plan_id)[0]
    assert (kept.status, kept.clip_name, kept.prompt, kept.model_path) == ("ready", scene.clip_name, PROMPT, MODEL)
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    job_id = studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert job_id and len(calls(studio.provider, "submit")) == 1


@needs_ffmpeg
def test_an_unreadable_clip_refuses_composition_without_releasing_the_paid_result(studio, monkeypatch):
    plan_id, scene = ready_and_reviewed(studio)
    clip = studio.service.clip_path(scene.id)
    real_open = Path.open

    def locked(self, *args, **kwargs):
        if self == clip:
            raise PermissionError(13, "in use")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)
    before = revision(studio, plan_id)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, before, True)
    assert refusal(excinfo) == ("장면 1" + CLIP_UNREADABLE, 409)
    assert "다른 프로그램에서 열려 있는지" in CLIP_UNREADABLE and "'결과 다시 받기'" in CLIP_UNREADABLE
    kept = scenes(studio, plan_id)[0]
    assert (kept.status, kept.clip_name, kept.reviewed) == ("ready", scene.clip_name, True)
    assert studio.service.can_refetch(kept)  # a way out if it stays unreadable
    assert revision(studio, plan_id) == before and clip.is_file()
    with studio.sessions() as session:
        assert session.scalar(select(RenderJob)) is None
    monkeypatch.setattr(Path, "open", real_open)
    assert studio.service.approve_compose(plan_id, before, True)
    assert "unreadable" not in scenes(studio, plan_id)[0].clip_meta  # readable again


def edit_draft(studio: Studio, change) -> None:
    with studio.sessions.begin() as session:
        draft = session.get(ContentDraft, studio.draft_id)
        content = {**draft.content, "scenes": [dict(s) for s in draft.content["scenes"]]}
        change(content["scenes"])
        draft.content = content
        draft.revision += 1


@needs_ffmpeg
def test_rebase_takes_a_new_script_and_keeps_paid_clips_when_the_timing_is_unchanged(studio):
    plan_id, scene = ready_and_reviewed(studio)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.rebase(plan_id, revision(studio, plan_id))
    assert refusal(excinfo) == ("이미 최신 대본을 쓰고 있습니다.", 409)

    def retitle(items):
        items[0]["caption"], items[0]["narration"] = "바뀐 자막", "바뀐 내레이션입니다."

    edit_draft(studio, retitle)
    assert DRAFT_CHANGED in studio.service.estimate(plan_id)["problems"]
    studio.service.rebase(plan_id, revision(studio, plan_id))
    rebased = scenes(studio, plan_id)[0]
    assert (rebased.caption, rebased.narration) == ("바뀐 자막", "바뀐 내레이션입니다.")
    assert (rebased.status, rebased.clip_name, rebased.reviewed) == ("ready", scene.clip_name, False)
    plan = plan_row(studio, plan_id)
    with studio.sessions() as session:
        assert plan.draft_revision == session.get(ContentDraft, studio.draft_id).revision
    assert plan.reviewed_at is None and DRAFT_CHANGED not in studio.service.estimate(plan_id)["problems"]
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    assert studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert len(calls(studio.provider, "submit")) == 1


def test_rebase_refuses_a_script_whose_scene_timing_changed(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio)
    before = scenes(studio, plan_id)

    def longer(items):
        items[0]["seconds"] += 3

    edit_draft(studio, longer)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.rebase(plan_id, revision(studio, plan_id))
    assert refusal(excinfo) == (
        "대본의 장면 수나 장면 시간이 바뀌어 이 계획에 반영할 수 없습니다. 새 계획을 만드세요.", 409)
    assert [(s.caption, s.start_ms, s.end_ms) for s in scenes(studio, plan_id)] == [
        (s.caption, s.start_ms, s.end_ms) for s in before]
    assert DRAFT_CHANGED in studio.service.estimate(plan_id)["problems"]


@pytest.mark.parametrize(("stored", "reused"), [("", True), ("720p", True), ("1080p", False), ("changed", False)])
def test_resend_after_unknown_reuses_the_key_only_for_the_identical_request(studio, stored, reused):
    # Rows written before migration 0011 have resolution '': that build always sent the model's resolution.
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)

    def crash(request):
        studio.provider.calls.append(("submit", request.model_path, request.idempotency_key))
        raise Crash

    studio.provider.submit = crash
    with pytest.raises(Crash):
        studio.service.tick()
    del studio.provider.submit
    studio.service.recover()
    with studio.sessions.begin() as session:
        session.scalar(select(VideoAIUsage)).resolution = "" if stored == "changed" else stored
    if stored == "changed":
        # A legacy row cannot tell which resolution was sent once the model was saved again at another one.
        model = next(m for m in list_models(studio.sessions) if m.path == MODEL)
        save_model(studio.sessions, path=MODEL, label="시험 모델", price_per_second="0.1", durations="5",
                   resolution="1080p", confirmed=True, model_id=model.id)
    studio.service.resolve_unknown(plan_id, revision(studio, plan_id), 0)
    confirm(studio, plan_id)
    studio.service.tick()
    first, second = submit_keys(studio.provider)
    assert (second == first) is reused


def unknown_then_resolved(studio: Studio) -> tuple[int, str]:
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:slow]"})
    confirm(studio, plan_id)

    def crash(request):
        studio.provider.calls.append(("submit", request.model_path, request.idempotency_key))
        raise Crash

    studio.provider.submit = crash
    with pytest.raises(Crash):
        studio.service.tick()
    del studio.provider.submit
    studio.service.recover()
    studio.service.resolve_unknown(plan_id, revision(studio, plan_id), 0)
    return plan_id, submit_keys(studio.provider)[0]


@pytest.mark.parametrize("stop", ["user_cancel", "script_rebase"])
def test_an_identical_resend_keeps_its_key_after_a_cancel_before_sending(studio, stop):
    plan_id, first = unknown_then_resolved(studio)
    confirm(studio, plan_id)
    assert scenes(studio, plan_id)[0].status == "waiting"
    if stop == "user_cancel":
        studio.service.cancel_scene(plan_id, revision(studio, plan_id), 0)
    else:
        def caption(items):
            items[0]["caption"] = "고친 자막"

        edit_draft(studio, caption)
        studio.service.tick()  # the send gate cancels the waiting resend (script changed): not sent
        assert scenes(studio, plan_id)[0].error_code == "video_ai_canceled"
        studio.service.rebase(plan_id, revision(studio, plan_id))
    assert [row.status for row in usage(studio)] == ["unknown", "not_sent"]
    confirm(studio, plan_id)
    studio.service.tick()
    assert submit_keys(studio.provider) == [first, first]  # the possibly billed request is never doubled


def test_a_resend_that_was_answered_gets_a_new_key_next_time(studio):
    plan_id, first = unknown_then_resolved(studio)
    edit_scene(studio, plan_id, 0, prompt=PROMPT + " [fake:fail]")  # same request for the provider
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "failed"
    confirm(studio, plan_id)
    studio.service.tick()
    keys = submit_keys(studio.provider)
    assert keys[:2] == [first, first] and keys[2] != first


def test_a_refetch_that_hits_a_full_disk_does_not_use_up_a_refetch(studio, monkeypatch):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT})
    confirm(studio, plan_id)
    usage_tuple = shutil.disk_usage(studio.data_dir)
    monkeypatch.setattr(
        "newsflow.video.ai.service.shutil.disk_usage", lambda path: usage_tuple._replace(free=10 * 1024 * 1024))
    studio.service.tick()
    for _ in range(MAX_REFETCHES + 1):
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
        studio.service.tick()
        scene = scenes(studio, plan_id)[0]
        assert scene.error_code == "video_ai_disk_full" and int((scene.clip_meta or {}).get("refetches", 0)) == 0
    assert len(calls(studio.provider, "submit")) == 1


def test_a_plan_with_spend_in_another_currency_cannot_generate_more(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:fail]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    assert scenes(studio, plan_id)[0].status == "failed" and [r.currency for r in usage(studio)] == ["USD"]
    with studio.sessions.begin() as session:  # last month's USD spend; this month has none
        session.scalar(select(VideoAIUsage)).created_at = month_start() - timedelta(days=1)
    write_settings(
        studio.sessions, provider="higgsfield", host="api.higgsfield.ai", approved=True, monthly_limit="20000",
        job_limit="5000", currency="KRW", max_active=2, timeout_minutes=30, poll_seconds=10,
    )
    model = next(m for m in list_models(studio.sessions) if m.path == MODEL)
    add_model(studio, price="100", model_id=model.id)  # re-confirmed in the new currency
    estimate = studio.service.estimate(plan_id)
    assert CURRENCY_CHANGED in estimate["problems"] and not estimate["can_submit"]
    assert estimate["plan_spent"] == "0" and estimate["currency"] == "KRW"  # the USD spend is never shown as KRW
    assert estimate["other_currency_spend"] is True
    with pytest.raises(AIVideoError) as excinfo:
        confirm_as_shown(studio, plan_id)
    assert refusal(excinfo) == (CURRENCY_CHANGED, 422)
    assert len(calls(studio.provider, "submit")) == 1


@needs_ffmpeg
def test_an_unreadable_clip_is_fetched_again_and_a_failed_refetch_loses_nothing(studio, monkeypatch):
    plan_id, scene = ready_and_reviewed(studio)
    old = studio.service.clip_path(scene.id)
    real_open = Path.open

    def locked(self, *args, **kwargs):
        if self == old:
            raise PermissionError(13, "denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)
    with pytest.raises(AIVideoError):
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    # First refetch fails validation: the reviewed clip comes back as it was (ready, still flagged).
    studio.provider.jobs[scene.request_id].bad_clip = True
    studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    assert scenes(studio, plan_id)[0].status == "in_progress" and plan_row(studio, plan_id).reviewed_at is None
    studio.service.tick()
    kept = scenes(studio, plan_id)[0]
    assert (kept.status, kept.error_code, kept.clip_name, kept.message) == (
        "ready", None, scene.clip_name, REFETCH_KEPT_MESSAGE)
    assert kept.clip_meta["unreadable"] and kept.clip_meta["refetches"] == 1 and kept.clip_meta["sha256"] == scene.clip_meta["sha256"]
    assert studio.service.can_refetch(kept) and studio.service.holds_paid_result(kept)
    assert studio.service.estimate(plan_id)["scenes"] == []  # never bought again
    studio.service.recover()
    assert old.is_file()  # still referenced: a failed refetch never deletes the paid file
    studio.provider.jobs[scene.request_id].bad_clip = False
    studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    studio.service.tick()
    fresh = scenes(studio, plan_id)[0]
    assert fresh.status == "ready" and fresh.clip_name != scene.clip_name and not fresh.reviewed
    assert len(calls(studio.provider, "submit")) == 1
    monkeypatch.setattr(Path, "open", real_open)
    studio.service.recover()
    assert not old.exists() and studio.service.clip_path(fresh.id).is_file()


@needs_ffmpeg
def test_a_directory_at_the_clip_path_counts_as_a_lost_clip(studio):
    plan_id, scene = ready_and_reviewed(studio)
    clip = studio.service.clip_path(scene.id)
    clip.unlink()
    clip.mkdir()
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert excinfo.value.status == 409 and "없거나 바뀌었습니다" in str(excinfo.value)
    released = scenes(studio, plan_id)[0]
    assert (released.status, released.error_code, released.message) == (
        "failed", "video_ai_download_failed", CLIP_LOST_MESSAGE)
    assert studio.service.can_refetch(released)


@needs_ffmpeg
def test_a_stale_page_or_a_finished_plan_never_releases_clips(studio):
    plan_id, scene = ready_and_reviewed(studio)
    stale = revision(studio, plan_id)
    studio.service.approve_compose(plan_id, stale, True)
    studio.app.state.video.future.result(timeout=30)
    studio.service.sync()
    assert plan_row(studio, plan_id).status == "composed"
    studio.service.clip_path(scene.id).unlink()  # e.g. a data folder moved without ai-clips
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, stale, True)
    assert refusal(excinfo) == (STALE_REVISION, 409)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == (COMPOSE_STARTED, 409)
    kept = scenes(studio, plan_id)[0]
    assert (kept.status, kept.clip_name, kept.reviewed) == ("ready", scene.clip_name, True)
    assert plan_row(studio, plan_id).status == "composed"


@needs_ffmpeg
def test_an_unreadable_clip_whose_result_is_gone_is_kept_and_composes_once_readable(studio, monkeypatch):
    from newsflow.video.ai.contracts import ProviderRequestMissing

    plan_id, scene = ready_and_reviewed(studio)
    old = studio.service.clip_path(scene.id)
    real_open = Path.open

    def locked(self, *args, **kwargs):
        if self == old:
            raise PermissionError(13, "denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)
    with pytest.raises(AIVideoError):
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.service.refetch(plan_id, revision(studio, plan_id), 0)

    def missing(request_id):
        raise ProviderRequestMissing(status_code=404)

    monkeypatch.setattr(studio.provider, "status", missing)
    studio.service.tick()
    kept = scenes(studio, plan_id)[0]
    assert (kept.status, kept.clip_name, kept.message) == ("ready", scene.clip_name, REFETCH_KEPT_FINAL)
    assert kept.clip_meta["result_gone"] and not studio.service.can_refetch(kept)
    # Still locked: the refusal must not point at a '결과 다시 받기' button the page no longer shows.
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("장면 1" + CLIP_UNREADABLE_KEPT, 409)
    assert "결과 다시 받기" not in CLIP_UNREADABLE_KEPT and "받아 둔 유료 AI 영상 버리기" in CLIP_UNREADABLE_KEPT
    assert [row.status for row in usage(studio)] == ["completed"]
    monkeypatch.setattr(Path, "open", real_open)  # the user closed the other program
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("장면 1의 AI 생성 영상을 관계 검토에서 확인(체크)한 뒤 다시 승인하세요.", 422)
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    assert studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    final = scenes(studio, plan_id)[0]
    # Readable again, but the provider's answer is remembered: no refetch is ever offered again.
    assert final.clip_name == scene.clip_name and "unreadable" not in final.clip_meta and final.clip_meta["result_gone"]
    assert len(calls(studio.provider, "submit")) == 1


@needs_ffmpeg
def test_a_refetch_of_a_clip_that_is_readable_again_fetches_nothing(studio, monkeypatch):
    plan_id, scene = ready_and_reviewed(studio)
    old = studio.service.clip_path(scene.id)
    real_open = Path.open

    def locked(self, *args, **kwargs):
        if self == old:
            raise PermissionError(13, "denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)
    with pytest.raises(AIVideoError):
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    monkeypatch.setattr(Path, "open", real_open)
    before = len(studio.provider.calls)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    assert refusal(excinfo) == (
        "장면 1의 생성 영상 파일을 다시 읽을 수 있어 새로 받지 않았습니다. 최종 합성 승인을 다시 누르세요.", 409)
    kept = scenes(studio, plan_id)[0]
    assert (kept.status, kept.clip_name, kept.reviewed) == ("ready", scene.clip_name, True)
    assert "unreadable" not in kept.clip_meta and len(studio.provider.calls) == before
    assert studio.service.approve_compose(plan_id, revision(studio, plan_id), True)


@needs_ffmpeg
def test_a_directory_at_the_clip_path_is_lost_where_opening_it_is_a_permission_error(studio, monkeypatch):
    # Windows answers PermissionError (not IsADirectoryError) when a directory is opened as a file.
    plan_id, scene = ready_and_reviewed(studio)
    clip = studio.service.clip_path(scene.id)
    clip.unlink()
    clip.mkdir()
    real_open = Path.open

    def windows_open(self, *args, **kwargs):
        if self.is_dir():
            raise PermissionError(13, "Permission denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", windows_open)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert "없거나 바뀌었습니다" in str(excinfo.value)
    assert scenes(studio, plan_id)[0].message == CLIP_LOST_MESSAGE


@needs_ffmpeg
def test_approval_names_refetch_for_a_paid_result_not_yet_received(studio):
    ready_studio(studio)
    plan_id = generated_plan(studio, {0: PROMPT + " [fake:bad-clip]"})
    confirm(studio, plan_id)
    studio.service.tick()
    studio.service.tick()
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ((
        "장면 1의 AI 생성 영상을 아직 받지 못했습니다. 그 장면의 '결과 다시 받기'(추가 생성 요청 없음)로 받거나, "
        "'받아 둔 유료 AI 영상 버리기'에 체크한 뒤 카드로 바꾸세요."), 422)


def test_a_key_is_never_sent_with_two_different_request_bodies(studio, monkeypatch):
    from newsflow.video.ai.contracts import ProviderRateLimited

    plan_id, first = unknown_then_resolved(studio)  # attempt 1: 5 s, key K1, outcome unknown
    model = next(m for m in list_models(studio.sessions) if m.path == MODEL)
    sent = []
    real_submit = studio.provider.submit

    def record(request):
        sent.append((request.idempotency_key, request.seconds, request.resolution))
        return real_submit(request)

    monkeypatch.setattr(studio.provider, "submit", record)

    def lengths(value: str) -> None:
        save_model(studio.sessions, path=MODEL, label="시험 모델", price_per_second="0.1", durations=value,
                   resolution="720p", confirmed=True, model_id=model.id)

    lengths("10")
    confirm(studio, plan_id)  # attempt 2: 10 s, a new key

    def rate_limited(request):
        sent.append((request.idempotency_key, request.seconds, request.resolution))
        raise ProviderRateLimited()

    monkeypatch.setattr(studio.provider, "submit", rate_limited)
    studio.service.tick()  # the 10 s body went out under its key and came back 429: requeued
    monkeypatch.setattr(studio.provider, "submit", record)
    lengths("5")
    studio.service.tick()  # the send gate drops the 10 s reservation (model changed): not sent again
    assert [row.status for row in usage(studio)] == ["unknown", "not_sent"]
    confirm(studio, plan_id)  # attempt 3: 5 s again
    studio.service.tick()
    bodies = {}
    for key, seconds, resolution in sent:
        bodies.setdefault(key, set()).add((seconds, resolution))
    assert all(len(found) == 1 for found in bodies.values()), sent
    assert sent[-1][0] not in {first, sent[0][0]}  # neither the unknown 5 s key nor the 10 s key


def lock_clip(monkeypatch, clip: Path) -> None:
    real_open = Path.open

    def locked(self, *args, **kwargs):
        if self == clip:
            raise PermissionError(13, "denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)


@needs_ffmpeg
def test_a_refetch_stopped_by_a_full_disk_says_so_and_keeps_its_allowance(studio, monkeypatch):
    plan_id, scene = ready_and_reviewed(studio)
    lock_clip(monkeypatch, studio.service.clip_path(scene.id))
    with pytest.raises(AIVideoError):
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    usage_tuple = shutil.disk_usage(studio.data_dir)
    monkeypatch.setattr("newsflow.video.ai.service.shutil.disk_usage", lambda path: usage_tuple._replace(free=0))
    for _ in range(MAX_REFETCHES + 1):
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
        studio.service.tick()
        kept = scenes(studio, plan_id)[0]
        assert kept.status == "ready" and kept.clip_name == scene.clip_name
        assert kept.message == REFETCH_KEPT_MESSAGE + " " + ERROR_MESSAGES["video_ai_disk_full"]
        assert int(kept.clip_meta.get("refetches", 0)) == 0 and studio.service.can_refetch(kept)


@needs_ffmpeg
def test_three_failed_refetches_of_an_unreadable_clip_end_with_the_discard_choice(studio, monkeypatch):
    plan_id, scene = ready_and_reviewed(studio)
    lock_clip(monkeypatch, studio.service.clip_path(scene.id))
    with pytest.raises(AIVideoError):
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.provider.jobs[scene.request_id].bad_clip = True
    for attempt in range(1, MAX_REFETCHES + 1):
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
        studio.service.tick()
        kept = scenes(studio, plan_id)[0]
        assert kept.status == "ready" and kept.clip_meta["refetches"] == attempt
    assert kept.message == REFETCH_KEPT_FINAL and not studio.service.can_refetch(kept)
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert refusal(excinfo) == ("장면 1" + CLIP_UNREADABLE_KEPT, 409)
    assert studio.service.estimate(plan_id)["scenes"] == []  # still held: never bought again silently


@needs_ffmpeg
def test_a_kept_clip_lost_after_the_result_is_gone_is_not_offered_a_refetch(studio, monkeypatch):
    from newsflow.video.ai.contracts import ProviderRequestMissing

    plan_id, scene = ready_and_reviewed(studio)
    clip = studio.service.clip_path(scene.id)
    lock_clip(monkeypatch, clip)
    with pytest.raises(AIVideoError):
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    studio.service.refetch(plan_id, revision(studio, plan_id), 0)

    def missing(request_id):
        raise ProviderRequestMissing(status_code=404)

    monkeypatch.setattr(studio.provider, "status", missing)
    studio.service.tick()
    assert scenes(studio, plan_id)[0].clip_meta["result_gone"]
    monkeypatch.undo()
    clip.unlink()  # e.g. quarantined by antivirus
    studio.service.review(plan_id, revision(studio, plan_id), {0}, True)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.approve_compose(plan_id, revision(studio, plan_id), True)
    assert "공급사에도 결과가 더 없습니다" in str(excinfo.value) and "결과 다시 받기" not in str(excinfo.value)
    gone = scenes(studio, plan_id)[0]
    assert (gone.status, gone.message) == ("failed", CLIP_GONE_MESSAGE)
    assert not studio.service.can_refetch(gone) and not studio.service.holds_paid_result(gone)
    with pytest.raises(AIVideoError) as excinfo:
        studio.service.refetch(plan_id, revision(studio, plan_id), 0)
    assert excinfo.value.status == 409
    estimate = studio.service.estimate(plan_id)
    assert [line["position"] for line in estimate["scenes"]] == [0]
    assert estimate["notices"] == [
        "장면 1은 받아 둔 영상을 잃었고 공급사에도 결과가 더 없어 새 유료 생성에 포함됩니다(추가 비용)."]
    assert [row.status for row in usage(studio)] == ["completed"]  # the delivered clip's row is untouched
