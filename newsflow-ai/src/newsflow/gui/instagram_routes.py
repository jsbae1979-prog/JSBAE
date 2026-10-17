"""Explicit Instagram actions; opening a page cannot log in, poll or publish."""

from fastapi import APIRouter, Form, HTTPException, Request

from newsflow.db.models import PublishDraft, PublishJob
from newsflow.publishing.service import PublishingError, PublishingService

from .routes import go

router = APIRouter()


def connection_context(request: Request) -> dict:
    service = getattr(request.app.state, "instagram", None)
    return service.status() if service else {
        "configured": False, "connection_supported": False, "accounts": [],
        "blocked_reason": "auth_relay_required", "message": "공식 HTTPS 로그인 연결 준비가 필요합니다.",
    }


@router.post("/instagram/connect")
def connect(request: Request, consent: bool = Form(False)):
    if consent is not True:
        raise HTTPException(422, "Meta 로그인·게시 계정 확인에 동의해 주세요.")
    status = connection_context(request)
    if not status["connection_supported"]:
        raise HTTPException(422, "BLOCKED · 공식 HTTPS 로그인 연결이 준비되지 않았습니다. 토큰을 직접 입력하지 마세요.")
    try:
        request.app.state.instagram.begin(consent=True)
    except Exception:  # noqa: BLE001 - OAuth failures can include credentials.
        raise HTTPException(422, "Instagram 계정 연결을 완료하지 못했습니다. 자동으로 다시 요청하지 않습니다.") from None
    return go("/simple-settings?saved=instagram#instagram")


@router.post("/instagram/draft")
def save_review(
    request: Request, render_job_id: int = Form(ge=1), title: str = Form(max_length=100),
    description: str = Form("", max_length=5000), hashtags: str = Form("", max_length=2000),
    account_id: int = Form(ge=1), draft_id: int | None = Form(None, ge=1), revision: int = Form(1, ge=1),
    content_reviewed: bool = Form(False), copyright_confirmed: bool = Form(False),
    sources_confirmed: bool = Form(False), ai_disclosure: str = Form("unreviewed", max_length=30),
):
    if not any(row["id"] == account_id and row["ready"] for row in connection_context(request)["accounts"]):
        raise HTTPException(422, "게시 권한을 확인한 Instagram 프로 계정을 선택하세요.")
    service = PublishingService(request.app.state.sessions, request.app.state.video.outputs,
                                getattr(request.app.state, "publishing_inspector", None))
    fields = {"platform": "instagram", "title": title, "description": description, "hashtags": hashtags,
              "account_id": account_id, "content_reviewed": content_reviewed,
              "copyright_confirmed": copyright_confirmed, "sources_confirmed": sources_confirmed,
              "ai_disclosure": ai_disclosure}
    try:
        if draft_id is None:
            draft_id = service.create(render_job_id=render_job_id, **fields)
        else:
            with request.app.state.sessions() as session:
                draft = session.get(PublishDraft, draft_id)
                if not draft or draft.platform != "instagram" or draft.render_job_id != render_job_id:
                    raise PublishingError("선택한 영상과 Instagram 검토 기록이 일치하지 않습니다.")
            service.edit(draft_id=draft_id, revision=revision, **fields)
        service.validate(draft_id)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go(f"/?video={render_job_id}&publish_platform=instagram#instagram-publish")


def _redirect(request: Request, *, draft_id: int | None = None, job_id: int | None = None):
    with request.app.state.sessions() as session:
        if job_id is not None:
            job = session.get(PublishJob, job_id)
            if not job or job.platform != "instagram":
                raise HTTPException(404, "Instagram 게시 작업이 없습니다.")
            draft_id = job.draft_id
        draft = session.get(PublishDraft, draft_id)
        if not draft or draft.platform != "instagram":
            raise HTTPException(404, "Instagram 게시 초안이 없습니다.")
        return f"/?video={draft.render_job_id}&publish_platform=instagram#instagram-publish"


def _execute(request: Request, method: str, identifier: int, **options):
    try:
        return getattr(request.app.state.instagram_publishing, method)(identifier, **options)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:  # noqa: BLE001 - provider raw responses and token material never reach the browser.
        raise HTTPException(422, "Instagram 처리 상태를 확인하지 못했습니다. 기록을 보존하며 자동 재시도하지 않습니다.") from None


@router.post("/instagram/prepare/{draft_id}")
def prepare(request: Request, draft_id: int, revision: int = Form(ge=1), consent: bool = Form(False)):
    target = _redirect(request, draft_id=draft_id)
    if consent is not True:
        raise HTTPException(422, "선택한 영상과 설명을 Meta에 전송하는 데 동의해 주세요.")
    _execute(request, "prepare", draft_id, revision=revision, consent=True)
    return go(target)


@router.post("/instagram/check/{job_id}")
def check(request: Request, job_id: int, consent: bool = Form(False)):
    target = _redirect(request, job_id=job_id)
    if consent is not True:
        raise HTTPException(422, "Meta 영상 처리 상태 조회에 동의해 주세요.")
    _execute(request, "check", job_id, consent=True)
    return go(target)


@router.post("/instagram/publish/{job_id}")
def publish(
    request: Request, job_id: int, account_id: int = Form(ge=1), media_sha256: str = Form(pattern=r"^[a-f0-9]{64}$"),
    consent: bool = Form(False), public_consent: bool = Form(False),
):
    target = _redirect(request, job_id=job_id)
    if consent is not True or public_consent is not True:
        raise HTTPException(422, "선택한 계정·영상의 Instagram 공개 게시를 직접 승인해 주세요.")
    _execute(request, "publish", job_id, account_id=account_id, media_sha256=media_sha256,
             consent=True, public_consent=True)
    return go(target)
