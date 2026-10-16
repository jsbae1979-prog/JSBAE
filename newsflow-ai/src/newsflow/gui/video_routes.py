"""Video Studio; protected POST execution, same-origin media preview/download."""

from __future__ import annotations

import sys

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select

from newsflow.db.models import AudioTrack, ContentDraft, RenderJob, Scene, SubtitleTrack, VideoProject
from newsflow.video.engine import RenderError
from newsflow.video.service import RenderBusy, VideoError
from newsflow.video.tts import POLICY_MESSAGE, SpeechSettings, TTSError, TTSPolicyError, WindowsTTS

from .routes import go, page

router = APIRouter()


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
        return page(
            request,
            "video.html",
            active="video",
            draft=draft,
            job=job,
            project=project,
            scenes=scenes,
            subtitles=subtitles,
            audio=audio,
            voices=voices,
            voice_note=voice_note,
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
    rate: int = Form(0),
    pause_ms: int = Form(250),
    theme: str = Form('news', max_length=20),
    subtitle_style: str = Form('panel', max_length=20),
) -> RedirectResponse:
    form = await request.form()
    try:
        identifier = request.app.state.video.start(
            draft_id,
            duration,
            voice,
            font_size,
            subtitle_y,
            [str(name) for name in form.getlist("images")],
            reviewed,
            asset_permission,
            speech=SpeechSettings(rate, pause_ms), theme=theme, subtitle_style=subtitle_style,
        )
    except RenderBusy:
        raise HTTPException(409, "이미 영상 제작이 실행 중입니다.") from None
    except (VideoError, RenderError, TTSError):
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
    with request.app.state.sessions() as session:
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
