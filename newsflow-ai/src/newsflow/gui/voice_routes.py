"""Korean voice settings: SAPI voices, rate/pause defaults, local preview audio and human listening records."""

from __future__ import annotations

import re
import sys
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from newsflow.easy_setup import (
    LISTENING_ITEMS,
    LISTENING_VALUES,
    LISTENING_VERDICTS,
    PAUSE_CHOICES,
    POLICY_GUIDE,
    RATE_CHOICES,
    VOICE_INSTALL_GUIDE,
    SetupError,
    listening_summary,
    preview_preferences,
    record_listening,
    save_voice_preferences,
    speech_preferences,
    voice_catalog,
    voice_choice_catalog,
)
from newsflow.intelligence.korean import speech_seconds
from newsflow.video.speech_text import normalize_for_speech
from newsflow.video.tts import (
    PREVIEW_MAX_SECONDS,
    PREVIEW_TEXT,
    SpeechSettings,
    TTSError,
    TTSPolicyError,
    WindowsTTS,
)

from .routes import go, page

router = APIRouter()
_PREVIEW = re.compile(r"preview-[0-9a-f]{32}\.wav")
_EMPTY_REPORT = {"sapi": [], "onecore_only": [], "registry_read": "unavailable"}


def _preview_dir(request: Request):
    directory = request.app.state.config.data_dir / "voice-preview"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _windows() -> bool:
    return sys.platform == "win32"


def _voices() -> tuple[list[dict], list[dict], str, dict]:
    """Selectable voices come only from the SAPI catalog; the registry report just explains an empty list."""
    try:
        catalog = voice_catalog()
    except TTSPolicyError:
        return [], [], "blocked_policy", {"state": "blocked_policy", **_EMPTY_REPORT}
    except TTSError:
        return [], [], "unavailable", {"state": "unavailable", **_EMPTY_REPORT}
    korean = [v for v in catalog if v["culture"].lower().startswith("ko-")]
    report = {"state": "available" if korean else "not_installed", **_EMPTY_REPORT, "sapi": korean}
    if not korean and _windows():
        report = WindowsTTS().korean_voice_report(sapi=[])
    return catalog, korean, report["state"], report


@router.get("/voices", response_class=HTMLResponse)
def voices(request: Request, preview: str = "", saved: bool = False, listened: bool = False) -> HTMLResponse:
    sessions = request.app.state.sessions
    catalog, korean, state, report = _voices()
    voice, _size, _position = preview_preferences(sessions)
    choices = voice_choice_catalog(catalog)
    speech = speech_preferences(sessions)
    playable = bool(preview) and _PREVIEW.fullmatch(preview) is not None and (_preview_dir(request) / preview).is_file()
    sample_spoken = normalize_for_speech(PREVIEW_TEXT)
    return page(
        request, "voices.html", active="simple-settings", catalog=catalog, korean=korean, state=state, report=report,
        voice=voice, speech=speech, rates=RATE_CHOICES, pauses=PAUSE_CHOICES, preview=preview if playable else "",
        voice_choices=choices, saved_voice_listed=any(item['name'] == voice for item in choices),
        saved=saved, listened=listened, windows=_windows(), sample_text=PREVIEW_TEXT, sample_spoken=sample_spoken,
        sample_estimate=speech_seconds(sample_spoken, speech.rate, speech.pause_ms),
        voice_installed=any(item['name'] == voice and item['available'] for item in choices),
        install_guide=VOICE_INSTALL_GUIDE, policy_guide=POLICY_GUIDE, listening=listening_summary(sessions),
        listening_items=LISTENING_ITEMS, listening_values=LISTENING_VALUES, listening_verdicts=LISTENING_VERDICTS,
    )


@router.post("/voices")
def save(
    request: Request, voice: str = Form(max_length=200), rate: str = Form("0", max_length=3),
    pause_ms: str = Form("250", max_length=4),
) -> RedirectResponse:
    try:
        save_voice_preferences(request.app.state.sessions, voice, rate, pause_ms)
    except SetupError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/voices?saved=true")


@router.post("/voices/preview")
def preview(
    request: Request, voice: str = Form(max_length=200), rate: str = Form("0", max_length=3),
    pause_ms: str = Form("250", max_length=4),
) -> RedirectResponse:
    """Synthesize the fixed sample sentence with the chosen voice; never other text."""
    if rate not in RATE_CHOICES or pause_ms not in PAUSE_CHOICES:
        raise HTTPException(422, "제공된 발화 속도와 문장 쉼을 선택하세요.")
    _catalog, korean, _state, _report = _voices()
    if voice == "offline-silence" or not any(v["name"] == voice for v in korean):
        raise HTTPException(422, "미리 듣기는 설치된 한국어 음성을 선택했을 때만 가능합니다.")
    directory = _preview_dir(request)
    for old in directory.glob("preview-*"):
        if old.is_file() and not old.is_symlink():
            old.unlink(missing_ok=True)
    name = f"preview-{uuid4().hex}.wav"
    tts = getattr(request.app.state.video, "tts", None) or WindowsTTS()
    try:
        if hasattr(tts, "preview"):
            tts.preview(directory / name, voice, SpeechSettings(int(rate), int(pause_ms)))
        else:
            tts.synthesize(
                PREVIEW_TEXT, directory / name, voice, PREVIEW_MAX_SECONDS, SpeechSettings(int(rate), int(pause_ms)),
            )
    except TTSError as exc:
        raise HTTPException(422, str(exc)) from None
    return go(f"/voices?preview={name}")


@router.get("/voices/preview/{name}")
def preview_file(request: Request, name: str) -> FileResponse:
    if not _PREVIEW.fullmatch(name):
        raise HTTPException(404, "미리 듣기 파일이 없습니다.")
    target = _preview_dir(request) / name
    if not target.is_file() or target.is_symlink():
        raise HTTPException(404, "미리 듣기 파일이 없습니다.")
    return FileResponse(target, media_type="audio/wav", filename=name, content_disposition_type="inline")


@router.post("/voices/listening")
async def listening(request: Request) -> RedirectResponse:
    """Human listening record: validated and stored as submitted; the app never computes the verdict."""
    form = await request.form()
    values = {str(k): v for k, v in form.items() if k != "csrf_token" and isinstance(v, str)}
    if any(len(v) > 500 for v in values.values()):
        raise HTTPException(422, "입력값이 너무 깁니다.")
    try:
        record_listening(request.app.state.config.data_dir, request.app.state.sessions, values)
    except SetupError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/voices?listened=true")
