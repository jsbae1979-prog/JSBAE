"""One production preference transaction; existing approval and secret stores stay separate."""

from fastapi import APIRouter, Form, HTTPException, Request

from newsflow.db.models import AppSetting, utcnow
from newsflow.easy_setup import (
    PAUSE_CHOICES,
    RATE_CHOICES,
    SetupError,
    initial_state,
    validate_voice_preferences,
    voice_choice_catalog,
)
from newsflow.intelligence.settings import SettingsError, studio_model
from newsflow.video.engine import FFmpegAdapter, RenderError
from newsflow.video.tts import TTSError

from .production_context import ACQUISITION_LABELS, CATEGORY_LABELS, PERIOD_LABELS, acquisition_preferences
from .production_status import production_context
from .routes import go, page

router = APIRouter()


def settings_page(request: Request, saved: bool = False):
    response = page(request, "simple_settings.html", active="simple-settings", saved=saved,
                    rates=RATE_CHOICES, pauses=PAUSE_CHOICES, **production_context(request))
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/production/preferences")
def preferences(request: Request, provider: str = Form(max_length=20), model: str = Form(max_length=80),
                source: str = Form(max_length=10), duration: int = Form(), platform: str = Form(max_length=20),
                voice: str = Form(max_length=200), rate: str = Form(max_length=3), pause_ms: str = Form(max_length=4),
                video_provider: str = Form(max_length=20), acquisition_policy: str | None = Form(None, max_length=10),
                category: str | None = Form(None, max_length=20), period: str | None = Form(None, max_length=10)):
    if (source not in {"sample", "feeds"} or duration not in {30, 45, 60}
            or platform not in {"youtube", "instagram"} or video_provider not in {"off", "higgsfield"}):
        raise HTTPException(422, "뉴스·길이·목적지·영상 방식을 다시 선택해 주세요.")
    sessions = request.app.state.sessions
    previous_acquisition = acquisition_preferences(sessions)
    acquisition = {"acquisition_policy": acquisition_policy, "category": category, "period": period}
    for key, choices in (("acquisition_policy", ACQUISITION_LABELS), ("category", CATEGORY_LABELS),
                         ("period", PERIOD_LABELS)):
        acquisition[key] = acquisition[key] if acquisition[key] is not None else previous_acquisition[key]
        if acquisition[key] not in choices:
            raise HTTPException(422, "뉴스 확보 방식·분야·기간을 다시 선택해 주세요.")
    try:
        model = studio_model(provider, model)
        with sessions() as session:
            current = initial_state(session)["values"]
        # Preserve an unchanged unavailable choice. Choosing/changing a voice requires validation.
        if (voice, rate, pause_ms) != (current["voice"], current["rate"], current["pause_ms"]):
            validate_voice_preferences(voice, rate, pause_ms)
        elif rate not in RATE_CHOICES or pause_ms not in PAUSE_CHOICES:
            raise SetupError("발화 속도와 문장 쉼을 다시 선택해 주세요.")
    except (SettingsError, SetupError) as exc:
        raise HTTPException(422, str(exc)) from None
    values = {"studio_provider": provider, "studio_model_" + provider: model,
              "autopilot_source": source, "autopilot_duration": str(duration), "autopilot_platform": platform,
              "video_default_voice": voice, "video_default_rate": rate, "video_default_pause_ms": pause_ms,
              "video_ai_provider": video_provider}
    values.update({"autopilot_" + key: value for key, value in acquisition.items()})
    with sessions.begin() as session:
        for key, value in values.items():
            row = session.get(AppSetting, key)
            if row:
                row.value = value
            else:
                session.add(AppSetting(key=key, value=value))
    return go("/simple-settings?saved=true")


@router.post("/production/check-local")
def check_local(request: Request, engine: str = Form(max_length=20)):
    """Explicit local install checks only: no synthesis, authentication or network operations."""
    if engine not in {"ffmpeg", "supertonic", "windows"}:
        raise HTTPException(422, "로컬 점검할 항목을 다시 선택해 주세요.")
    record = {"checked_at": utcnow().isoformat(), "ok": False}
    try:
        if engine == "ffmpeg":
            renderer = request.app.state.video.engine
            FFmpegAdapter(getattr(renderer, "ffmpeg", None), getattr(renderer, "ffprobe", None)).check()
        else:
            candidates = [item for item in voice_choice_catalog() if item["engine"] == engine and item["available"]]
            if not candidates:
                raise SetupError("사용 가능한 로컬 음성이 없습니다.")
            validate_voice_preferences(candidates[0]["name"], "0", "250")
        record["ok"] = True
    except (SetupError, TTSError, RenderError, OSError):
        pass
    cache = dict(getattr(request.app.state, "production_checks", {}))
    cache[engine] = record
    request.app.state.production_checks = cache
    return go("/simple-settings#selected-video" if engine == "ffmpeg" else "/simple-settings#selected-voice")
