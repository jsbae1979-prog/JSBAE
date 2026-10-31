"""Video Studio; protected POST execution, same-origin media preview/download."""

from __future__ import annotations

import sys

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse, Response
from sqlalchemy import select

from newsflow.db.models import (
    ArticleThumbnail,
    AudioTrack,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    RenderJob,
    Scene,
    SubtitleTrack,
    VideoProject,
)
from newsflow.easy_setup import initial_state
from newsflow.video.engine import RenderError, load_image
from newsflow.video.service import RenderBusy, VideoError
from newsflow.video.tts import POLICY_MESSAGE, TTSError, TTSPolicyError, WindowsTTS

from .production_context import context_for_draft
from .routes import go, page
from .video_presentation import video_presentation

router = APIRouter()


@router.get("/video/tts", response_class=HTMLResponse)
def tts_settings(request: Request, sample: str = "", saved_voice: bool = False):
    return _tts_page(request, sample=sample, message="음성 선택을 저장했습니다." if saved_voice else "")


def _voice_catalog(request):
    from newsflow.video.elevenlabs_tts import ElevenLabsKeys
    from newsflow.video.elevenlabs_voices import ElevenLabsVoices

    root = request.app.state.video.root
    return ElevenLabsVoices(root, ElevenLabsKeys(root))


def _tts_page(request, *, sample="", message="", error=False):
    from newsflow.video.elevenlabs_tts import MODELS, ElevenLabsKeys, settings
    from newsflow.video.supertonic_tts import SupertonicTTS

    video = request.app.state.video
    catalog = _voice_catalog(request)
    preview = None
    if sample:
        try:
            if catalog.sample_path(sample).is_file():
                preview = catalog.voice(sample)
        except TTSError:
            pass
    response = page(request, "tts_settings.html", active="video", config=settings(video.sessions),
                    models=MODELS, key=ElevenLabsKeys(video.root).status(),
                    supertonic_ready=bool(SupertonicTTS().voices()), voice_catalog=catalog.cached(),
                    voice_message=message, voice_error=error, sample_voice=preview)
    if error:
        response.status_code = 422
    return response


@router.post("/video/tts/voices/load")
def load_elevenlabs_voices(request: Request, consent: bool = Form(False), more: bool = Form(False), scope: str = Form("saved", max_length=10)):
    if scope not in {"saved", "all"}:
        raise HTTPException(422, "음성 목록 범위를 확인하세요.")
    if not consent:
        return _tts_page(request, error=True, message="등록된 키로 음성 목록을 조회하는 데 동의하세요.")
    catalog = _voice_catalog(request)
    try:
        if scope == "all":
            catalog.load(more=more, all_voices=True)
        else:
            catalog.load(more=more)
    except TTSError as exc:
        catalog.record_failure(exc)
        return _tts_page(request, error=True, message=str(exc))
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"loaded": True})
    return go("/video/tts#elevenlabs-voices")


@router.post("/video/tts/voices/select")
def select_elevenlabs_voice(request: Request, voice_id: str = Form("", max_length=100), use_for_news: bool = Form(False)):
    from newsflow.video.elevenlabs_voices import select_voice

    try:
        select_voice(request.app.state.sessions, voice_id, _voice_catalog(request), use_for_news=use_for_news)
    except TTSError as exc:
        return _tts_page(request, error=True, message=str(exc))
    if request.headers.get("accept") == "application/json":
        return JSONResponse({"voiceId": voice_id})
    return go("/video/tts?saved_voice=true#elevenlabs-voices")


@router.post("/video/tts/voices/preview")
def preview_elevenlabs_voice(request: Request, voice_id: str = Form("", max_length=100),
                            sample_consent: bool = Form(False)):
    if not sample_consent:
        return _tts_page(request, error=True, message="공개 샘플 다운로드에 동의하세요. 음성 생성은 하지 않습니다.")
    try:
        _voice_catalog(request).prepare_sample(voice_id)
    except TTSError as exc:
        return _tts_page(request, error=True, message=str(exc))
    if request.headers.get('accept') == 'application/json':
        return JSONResponse({'mediaUrl':f'/video/tts/voices/{voice_id}/sample'})
    return go(f"/video/tts?sample={voice_id}#elevenlabs-voices")


@router.get("/video/tts/voices/{voice_id}/sample")
def elevenlabs_sample(request: Request, voice_id: str):
    # Media GET is local-cache-only. External downloads require the protected POST above.
    if (request.cookies.get("newsflow_csrf") != request.state.csrf
            or request.headers.get("sec-fetch-site") == "cross-site"
            or request.headers.get("origin", str(request.base_url).rstrip("/"))
            != str(request.base_url).rstrip("/")):
        raise HTTPException(403, "같은 앱 화면에서 샘플을 재생하세요.")
    try:
        path = _voice_catalog(request).sample_path(voice_id)
    except TTSError:
        raise HTTPException(404, "준비된 샘플이 없습니다.") from None
    if not path.is_file():
        raise HTTPException(404, "미리듣기 버튼으로 샘플을 먼저 준비하세요.")
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "private, no-store",
                                                               "X-Content-Type-Options": "nosniff"})


@router.post("/video/tts")
def save_tts(request: Request, enabled: bool = Form(False), voice_id: str = Form("", max_length=100),
             model: str = Form("eleven_multilingual_v2"), job_limit: int = Form(1000),
             commercial: bool = Form(True)):
    from newsflow.video.elevenlabs_tts import save_settings

    try:
        save_settings(request.app.state.sessions, enabled=enabled, voice_id=voice_id, model=model,
                      job_limit=job_limit, commercial=commercial)
    except TTSError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/video/tts")


@router.post("/video/tts/key")
def save_tts_key(request: Request, api_key: str = Form(min_length=20, max_length=256)):
    from newsflow.intelligence.credentials import CredentialError
    from newsflow.video.elevenlabs_tts import ElevenLabsKeys

    try:
        ElevenLabsKeys(request.app.state.video.root).save(api_key)
    except CredentialError as exc:
        raise HTTPException(422, str(exc)) from None
    return go("/video/tts")


@router.post("/video/tts/check")
def check_tts(request: Request, consent: bool = Form(False)):
    from newsflow.video.elevenlabs_tts import ElevenLabsTTS, settings

    if not consent:
        raise HTTPException(422, "API 키로 계정 한도를 조회하는 데 동의하세요. 음성 생성은 하지 않습니다.")
    video = request.app.state.video
    try:
        return ElevenLabsTTS(video.root, settings(video.sessions)).subscription()
    except TTSError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("/video", response_class=HTMLResponse)
def studio(request: Request, draft_id: int | None = None, job_id: int | None = None) -> HTMLResponse:
    video = request.app.state.video
    with request.app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id) if draft_id else None
        job = session.get(RenderJob, job_id) if job_id else None
        if (draft_id and not draft) or (job_id and not job):
            raise HTTPException(404, "대본 또는 영상 작업을 찾지 못했습니다.")
        project = session.get(VideoProject, job.project_id) if job else None
        scenes = (
            list(
                session.scalars(select(Scene).where(Scene.project_id == project.id).order_by(Scene.position))
            )
            if project
            else []
        )
        subtitles = (
            session.scalar(select(SubtitleTrack).where(SubtitleTrack.project_id == project.id))
            if project
            else None
        )
        audio = (
            session.scalar(select(AudioTrack).where(AudioTrack.project_id == project.id)) if project else None
        )
        voices, voice_note = [], ""
        if sys.platform == "win32":
            # Every SAPI voice is listed with its culture; non-Korean ones carry a warning and are
            # never pre-selected. The submitted value stays the voice name the renderer validates.
            try:
                details = WindowsTTS().voice_details()
                korean = [v for v in details if v["culture"].lower().startswith("ko-")]
                others = [v for v in details if v not in korean]
                voices = [{"name": v["name"], "label": f"{v['name']} · {v['culture']}"} for v in korean] + [
                    {"name": v["name"], "label": f"{v['name']} · {v['culture']} (한국어 아님 · 한국어 대본 읽기 품질 미보장)"}
                    for v in others
                ]
            except TTSPolicyError:
                voice_note = POLICY_MESSAGE
            except TTSError:
                voice_note = "Windows 음성 목록을 확인하지 못했습니다. 설치된 음성과 실행 권한을 확인하세요."
        from newsflow.video.supertonic_tts import SupertonicTTS

        voices.extend({"name": voice, "label": f"Supertonic 3 · {voice.split(':')[1]} · 한국어 · 무료 로컬",
                       "engine": "local"} for voice in SupertonicTTS().voices())
        voices.append({"name": "elevenlabs", "label": "ElevenLabs · 외부 API · 설정·동의 필요", "engine": "external"})
        # Reuse the wizard/voice settings instead of silently resetting saved narration to silence.
        preferences = initial_state(session)["values"]
        context_draft = draft or (session.get(ContentDraft, project.draft_id) if project else None)
        production_context = context_for_draft(session, context_draft)
        draft_run = session.get(IntelligenceRun, context_draft.run_id) if context_draft else None
        selected_voice = production_context["initial_voice"] if production_context else preferences["voice"]
        voice_available = selected_voice == "offline-silence" or any(
            item["name"] == selected_voice for item in voices
        )
        preview_job = None
        if draft:
            candidate = session.scalar(select(RenderJob).join(VideoProject).where(
                VideoProject.draft_id == draft.id, RenderJob.status == "success",
            ).order_by(RenderJob.id.desc()).limit(1))
            if candidate and candidate.metadata_json.get("playable"):
                try:
                    if video.output_path(candidate.output_name).is_file():
                        preview_job = candidate
                except VideoError:
                    pass
        return page(
            request,
            "video.html",
            active="video",
            draft=draft,
            preview_job=preview_job,
            job=job,
            job_presentation=video_presentation(job, playable=bool(job.metadata_json.get("playable"))) if job else None,
            project=project,
            scenes=scenes,
            subtitles=subtitles,
            audio=audio,
            voices=voices,
            voice_note=voice_note,
            preferences=preferences,
            production_context=production_context,
            draft_provider=draft_run.provider if draft_run else None,
            selected_voice=selected_voice,
            voice_available=voice_available,
            news_image_articles=[{"article": session.get(NewsArticle, a.get("id", a.get("article_id"))),
                                  "thumbnail": session.get(ArticleThumbnail, a.get("id", a.get("article_id")))}
                                 for a in draft.sources.get("articles", [])] if draft else [],
            image_links=video.news_images.choose(session, draft.sources, len(draft.content["scenes"]))[1] if draft else [],
            assets=video.assets_list(),
            outputs=video.outputs,
            assets_path=video.assets,
            drafts=list(session.scalars(select(ContentDraft).order_by(ContentDraft.id.desc()).limit(100))),
            jobs=list(session.scalars(select(RenderJob).order_by(RenderJob.id.desc()).limit(30))),
        )


@router.post("/video/render")
async def render(
    request: Request,
    draft_id: int = Form(ge=1),
    duration: int = Form(),
    voice: str = Form("offline-silence", max_length=200),
    font_size: int = Form(48),
    subtitle_y: int = Form(1420),
    reviewed: bool = Form(False),
    asset_permission: bool = Form(False),
    external_tts_consent: bool = Form(False),
) -> RedirectResponse:
    form = await request.form()
    try:
        image_ids = [int(value) if value else None for value in form.getlist("image_article_ids")]
        identifier = request.app.state.video.start(
            draft_id,
            duration,
            voice,
            font_size,
            subtitle_y,
            [str(name) for name in form.getlist("images")],
            reviewed,
            asset_permission,
            external_tts_consent=external_tts_consent,
            effects=[str(value) for value in form.getlist("effects")] or None,
            image_article_ids=image_ids or None,
        )
    except RenderBusy:
        raise HTTPException(409, "이미 영상 제작이 실행 중입니다.") from None
    except (VideoError, RenderError, TTSError, ValueError):
        raise HTTPException(
            422, "대본·영상 길이·음성·자막 안전 영역·소재 권한·디스크 공간을 확인하세요."
        ) from None
    return go(f"/video?job_id={identifier}")


@router.get("/api/video/jobs/{job_id}")
def status(request: Request, job_id: int) -> dict:
    with request.app.state.sessions() as session:
        job = session.get(RenderJob, job_id)
        if not job:
            raise HTTPException(404, "영상 작업이 없습니다.")
        return {"job_id": job.id, "status": job.status, "progress": job.progress, "message": job.message}


@router.get("/video/jobs/{job_id}/file")
def media(request: Request, job_id: int, download: bool = False) -> FileResponse:
    from newsflow.db.models import WorkspaceRemoval

    with request.app.state.sessions() as session:
        if session.get(WorkspaceRemoval, f"video:{job_id}"):
            raise HTTPException(404, "휴지 보관한 영상입니다.")
        job = session.get(RenderJob, job_id)
        if not job or job.status != "success" or not job.metadata_json.get("playable"):
            raise HTTPException(404, "검증된 완성 영상이 없습니다.")
        try:
            target = request.app.state.video.output_path(job.output_name)
        except VideoError:
            raise HTTPException(404, "결과 경로를 확인하지 못했습니다.") from None
        if not target.is_file():
            raise HTTPException(404, "결과 파일이 없습니다.")
        return FileResponse(
            target,
            media_type="video/mp4",
            filename=target.name,
            content_disposition_type="attachment" if download else "inline",
        )


@router.get("/video/jobs/{job_id}/thumbnail")
def video_thumbnail(request: Request, job_id: int) -> Response:
    from newsflow.publishing.service import PublishingError, PublishingService
    from newsflow.video.thumbnails import thumbnail

    coordinator = request.app.state.video
    with request.app.state.sessions() as session:
        job = session.get(RenderJob, job_id)
        if job is None:
            raise HTTPException(404, "영상이 없습니다.")
        try:
            target = PublishingService(request.app.state.sessions, coordinator.outputs).media_path(job)
            preview = thumbnail(target, getattr(coordinator.engine, "ffmpeg", None))
        except (PublishingError, OSError):
            raise HTTPException(404, "검증된 영상이 없습니다.") from None
        except RenderError:
            raise HTTPException(503, "미리보기를 준비하지 못했습니다. 영상 재생은 별도로 확인할 수 있습니다.") from None
    return Response(preview, media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.post("/video/news-image")
def link_news_image(request: Request, draft_id: int = Form(ge=1), article_id: int = Form(ge=1),
                    name: str = Form("", max_length=255), rights_basis: str = Form(min_length=3, max_length=400),
                    permission: bool = Form(False)):
    """Associate an existing local asset only. No image/network lookup on this route."""
    if not permission:
        raise HTTPException(422, "영상 사용권을 확인하세요.")
    with request.app.state.sessions() as session:
        draft = session.get(ContentDraft, draft_id)
        article = session.get(NewsArticle, article_id)
        if not draft or not article or article_id not in {a.get("id", a.get("article_id")) for a in draft.sources.get("articles", [])}:
            raise HTTPException(422, "대본과 뉴스 연결을 확인하세요.")
        thumbnail = session.get(ArticleThumbnail, article_id)
        try:
            if name == "__thumbnail__" and thumbnail:
                request.app.state.video.news_images.import_thumbnail(
                    article, thumbnail, request.app.state.news_thumbnails.adapter, rights_basis=rights_basis)
            else:
                request.app.state.video.news_images.remember(
                    article, name, source_url=article.url, rights_basis=rights_basis, origin="collected")
        except Exception:  # noqa: BLE001 -- redact every transport failure; never expose supplier URLs/credentials.
            raise HTTPException(422, "이미지 연결 실패 · 형식·출처·사용권을 확인하세요. 기본 카드를 유지합니다.") from None
    return go(f"/video?draft_id={draft_id}#news-image-links")


@router.get("/video/news-images/articles/{article_id}")
def news_image_preview(request: Request, article_id: int):
    from io import BytesIO

    from PIL import Image
    with request.app.state.sessions() as session:
        article = session.get(NewsArticle, article_id)
        rows = request.app.state.video.news_images.candidates(article) if article else []
    if not rows:
        raise HTTPException(404, "사용권이 확인된 뉴스 이미지가 없습니다.")
    try:
        # This is an already validated local 20MB asset, not an RSS response (2MB).
        with load_image(request.app.state.video.news_images.asset(rows[0]["name"])) as image:
            image.thumbnail((320, 180))
            clean = Image.new("RGB", image.size)
            clean.paste(image)
            output = BytesIO()
            clean.save(output, format="JPEG", quality=82)
            preview = output.getvalue()
    except (OSError, ValueError, RenderError):
        raise HTTPException(404, "이미지를 확인하세요. 기본 카드를 유지합니다.") from None
    return Response(preview, media_type="image/jpeg", headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
