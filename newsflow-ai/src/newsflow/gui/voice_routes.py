"""Korean voice settings: installed SAPI voices, rate/pause defaults and local preview audio."""

from __future__ import annotations

import re
import sys
from uuid import uuid4

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from newsflow.easy_setup import (
    PAUSE_CHOICES,
    RATE_CHOICES,
    SetupError,
    preview_preferences,
    save_voice_preferences,
    speech_preferences,
    voice_catalog,
)
from newsflow.intelligence.korean import speech_seconds
from newsflow.video.tts import PREVIEW_TEXT, SpeechSettings, TTSError, WindowsTTS

from .routes import go, page

router = APIRouter()
_PREVIEW = re.compile(r"preview-[0-9a-f]{32}\.wav")


def _preview_dir(request: Request):
    directory = request.app.state.config.data_dir / "voice-preview"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _voices() -> tuple[list[dict], list[dict], str]:
    try:
        catalog = voice_catalog()
    except TTSError:
        return [], [], "unavailable"
    korean = [v for v in catalog if v["culture"].lower().startswith("ko-")]
    return catalog, korean, "available" if korean else "not_installed"


@router.get("/voices", response_class=HTMLResponse)
def voices(request: Request, preview: str = "", saved: bool = False) -> HTMLResponse:
    sessions = request.app.state.sessions
    catalog, korean, state = _voices()
    voice, _size, _position = preview_preferences(sessions)
    speech = speech_preferences(sessions)
    playable = bool(preview) and _PREVIEW.fullmatch(preview) is not None and (_preview_dir(request) / preview).is_file()
    return page(
        request, "voices.html", active="simple-settings", catalog=catalog, korean=korean, state=state,
        voice=voice, speech=speech, rates=RATE_CHOICES, pauses=PAUSE_CHOICES, preview=preview if playable else "",
        saved=saved, windows=sys.platform == "win32", sample_text=PREVIEW_TEXT,
        sample_estimate=speech_seconds(PREVIEW_TEXT, speech.rate, speech.pause_ms),
        voice_installed=voice == "offline-silence" or any(v["name"] == voice for v in korean),
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
    _catalog, korean, _state = _voices()
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
            tts.synthesize(PREVIEW_TEXT, directory / name, voice, 20, SpeechSettings(int(rate), int(pause_ms)))
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
