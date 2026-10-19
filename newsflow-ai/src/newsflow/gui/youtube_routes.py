"""Explicit YouTube connection/review/upload actions; GET never calls Google."""

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import select

from newsflow.db.models import PublishDraft, PublishValidation, RenderJob, VideoProject
from newsflow.publishing.service import REAL_BLOCKERS, PublishingError, PublishingService

from .routes import go

router = APIRouter()


def connection_context(request: Request) -> dict:
    service = getattr(request.app.state, "youtube", None)
    return service.status() if service else {"client_configured": False, "storage_supported": False,
                                            "pending": False, "accounts": []}


def publishing_context(request: Request, render_job_id: int | None, *, platform: str = "youtube") -> dict | None:
    if render_job_id is None:
        return None
    with request.app.state.sessions() as session:
        render = session.get(RenderJob, render_job_id)
        project = session.get(VideoProject, render.project_id) if render else None
        if not project:
            return None
        draft = session.scalar(select(PublishDraft).where(
            PublishDraft.render_job_id == render_job_id, PublishDraft.platform == platform,
        ).order_by(PublishDraft.id.desc()).limit(1))
        validation = session.scalar(select(PublishValidation).where(
            PublishValidation.draft_id == draft.id,
        ).order_by(PublishValidation.id.desc()).limit(1)) if draft else None
        local_checks = [item for item in validation.results if item["key"] not in REAL_BLOCKERS] if validation else []
        reviewed = bool(draft and validation and validation.draft_revision == draft.revision
                        and local_checks and all(item["status"] == "pass" for item in local_checks))
        live = getattr(request.app.state, "instagram_publishing" if platform == "instagram" else "live_publishing", None)
        connections = getattr(request.app.state, platform, None)
        results = live.results() if live else []
        return {"render_job_id": render_job_id, "title": project.title, "draft": draft,
                "sources": project.sources, "checks": local_checks, "reviewed": reviewed,
                "accounts": connections.status()["accounts"] if connections else [],
                "results": [item for item in results if item.get("render_job_id") == render_job_id]}


@router.post("/youtube/client")
def save_client(request: Request, client_json: str = Form(max_length=16384)):
    try:
        request.app.state.youtube.save_client(client_json)
    except Exception:  # noqa: BLE001 - client JSON may contain a secret; never reflect exceptions.
        raise HTTPException(422, "Google 데스크톱 앱 OAuth JSON을 확인하세요. Windows 보호 저장소가 필요합니다.") from None
    return go("/simple-settings?saved=youtube-client#youtube")


@router.post("/youtube/connect")
def connect(request: Request, consent: bool = Form(False), account_id: int | None = Form(None, ge=1)):
    if consent is not True:
        raise HTTPException(422, "Google 로그인과 YouTube 채널 확인에 동의해 주세요.")
    try:
        request.app.state.youtube.begin(consent=True, account_id=account_id)
    except Exception:  # noqa: BLE001 - no provider, client or callback data in HTTP errors.
        raise HTTPException(422, "YouTube 연결을 시작하지 못했습니다. 클라이언트 설정과 진행 중인 연결을 확인하세요.") from None
    return go("/simple-settings?saved=youtube-login#youtube")


@router.post("/youtube/connect/{account_id}/cancel")
def cancel(request: Request, account_id: int):
    try:
        request.app.state.youtube.cancel(account_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(422, "연결 취소 상태를 확인하세요.") from None
    return go("/simple-settings#youtube")


@router.post("/youtube/connect/{account_id}/link")
def authorization_link(request: Request, account_id: int):
    try:
        url, remaining = request.app.state.youtube.authorization_link(account_id)
    except Exception:  # noqa: BLE001 - never reflect state or callback data
        raise HTTPException(409, "인증 링크가 만료되었거나 연결 처리가 시작되었습니다. 연결 상태를 새로고침하세요.") from None
    return {"url": url.get_secret_value(), "expires_in": remaining}


@router.post("/youtube/connect/{account_id}/reopen")
def reopen_authorization(request: Request, account_id: int):
    try:
        request.app.state.youtube.reopen_authorization(account_id)
    except Exception:  # noqa: BLE001
        raise HTTPException(409, "인증 창을 열지 못했습니다. 연결 상태를 확인하거나 유효한 링크를 복사해 사용하세요.") from None
    return {"message": "진행 중인 Google 인증 창을 다시 열었습니다."}


@router.post("/youtube/draft")
def save_review(
    request: Request, render_job_id: int = Form(ge=1), title: str = Form(max_length=100),
    description: str = Form("", max_length=5000), hashtags: str = Form("", max_length=2000),
    account_id: int = Form(ge=1), draft_id: int | None = Form(None, ge=1), revision: int = Form(1, ge=1),
    content_reviewed: bool = Form(False), copyright_confirmed: bool = Form(False),
    sources_confirmed: bool = Form(False), ai_disclosure: str = Form("unreviewed", max_length=30),
):
    accounts = connection_context(request)["accounts"]
    if not any(item["id"] == account_id and item["ready"] for item in accounts):
        raise HTTPException(422, "연결된 YouTube 채널을 선택하세요. 설정에서 연결할 수 있습니다.")
    service = PublishingService(request.app.state.sessions, request.app.state.video.outputs)
    inspector = getattr(request.app.state, "publishing_inspector", None)
    if inspector is not None:  # Explicit test dependency; never selected by an environment/UI flag.
        service.inspector = inspector
    fields = {"platform": "youtube", "title": title, "description": description, "hashtags": hashtags,
              "account_id": account_id, "content_reviewed": content_reviewed,
              "copyright_confirmed": copyright_confirmed, "sources_confirmed": sources_confirmed,
              "ai_disclosure": ai_disclosure}
    try:
        if draft_id is None:
            draft_id = service.create(render_job_id=render_job_id, **fields)
        else:
            with request.app.state.sessions() as session:
                draft = session.get(PublishDraft, draft_id)
                if not draft or draft.render_job_id != render_job_id or draft.platform != "youtube":
                    raise PublishingError("선택한 영상과 게시 초안이 일치하지 않습니다.")
            service.edit(draft_id=draft_id, revision=revision, **fields)
        service.validate(draft_id)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go(f"/?video={render_job_id}#youtube-publish")


@router.post("/youtube/publish/{draft_id}")
def publish(
    request: Request, draft_id: int, revision: int = Form(ge=1), privacy: str = Form("private", max_length=10),
    made_for_kids: str = Form("", max_length=3), consent: bool = Form(False), public_consent: bool = Form(False),
):
    if made_for_kids not in {"yes", "no"}:
        raise HTTPException(422, "아동용 영상 여부를 직접 선택하세요.")
    if consent is not True or privacy not in {"private", "unlisted", "public"}:
        raise HTTPException(422, "공개 상태와 이번 영상 업로드 동의를 확인하세요.")
    if privacy != "private" and public_consent is not True:
        raise HTTPException(422, "일부 공개·공개 업로드는 별도 동의가 필요합니다.")
    with request.app.state.sessions() as session:
        draft = session.get(PublishDraft, draft_id)
        if draft is None or draft.platform != "youtube":
            raise HTTPException(404, "YouTube 게시 초안을 찾지 못했습니다.")
        render_job_id = draft.render_job_id
    try:
        request.app.state.live_publishing.execute(
            draft_id, revision, privacy=privacy, made_for_kids=made_for_kids == "yes",
            consent=True, public_consent=public_consent,
        )
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:  # noqa: BLE001 - preserve the service journal, never replay an uncertain upload.
        raise HTTPException(422, "업로드 상태를 확인하지 못했습니다. 작업 기록을 보존했으며 자동 재시도하지 않습니다.") from None
    return go(f"/?video={render_job_id}#youtube-publish")
