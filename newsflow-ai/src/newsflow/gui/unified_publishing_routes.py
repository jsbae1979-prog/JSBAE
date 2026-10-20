"""A shared reviewed MP4 and one explicit publish action; platform engines stay separate."""

from fastapi import APIRouter, Form, HTTPException, Request

from newsflow.db.models import RenderJob, VideoProject
from newsflow.publishing.categories import YOUTUBE_CATEGORIES
from newsflow.publishing.service import PublishingError

from .routes import go

router = APIRouter()
TARGETS = {"youtube": ("youtube",), "instagram": ("instagram",), "both": ("youtube", "instagram"), "tiktok": ("tiktok",), "facebook": ("facebook",), "all": ("youtube", "instagram", "tiktok", "facebook")}


def workspace_context(request: Request, render_id: int | None):
    if render_id is None:
        return None
    with request.app.state.sessions() as session:
        render = session.get(RenderJob, render_id)
        project = session.get(VideoProject, render.project_id) if render else None
        if not project:
            return None
        cohort = request.app.state.unified_publishing.for_video(render_id)
        tiktok = next((t for t in cohort["targets"] if t["platform"] == "tiktok"), None) if cohort else None
        prepared = request.app.state.social_extensions["tiktok"].prepared_options(tiktok["draft_id"]) if tiktok else None
        return {"youtube_categories": YOUTUBE_CATEGORIES, "tiktok_options": prepared, "render_id": render_id, "title": project.title, "sources": project.sources,
                "cohort": request.app.state.unified_publishing.for_video(render_id),
                "youtube_accounts": request.app.state.youtube.status()["accounts"],
                "instagram_accounts": request.app.state.instagram.status()["accounts"],
                **{name + "_accounts": service.status()["accounts"] for name, service in request.app.state.social_extensions.items()}}


@router.post("/publishing/unified/review")
def review(
    request: Request, render_job_id: int = Form(ge=1), target: str = Form(max_length=15),
    title: str = Form(max_length=100), description: str = Form("", max_length=5000),
    hashtags: str = Form("", max_length=2000), youtube_account: int | None = Form(None, ge=1),
    instagram_account: int | None = Form(None, ge=1),
    tiktok_account: int | None = Form(None, ge=1), facebook_account: int | None = Form(None, ge=1), content_reviewed: bool = Form(False),
    copyright_confirmed: bool = Form(False), sources_confirmed: bool = Form(False),
    ai_disclosure: str = Form("unreviewed", max_length=30),
    youtube_category_id: str = Form("", max_length=3),
):
    if target not in TARGETS:
        raise HTTPException(422, "게시할 플랫폼을 선택하세요.")
    chosen = {"youtube": youtube_account, "instagram": instagram_account, "tiktok": tiktok_account, "facebook": facebook_account}
    accounts = {}
    for platform in TARGETS[target]:
        identifier = chosen[platform]
        service = request.app.state.social_extensions.get(platform) or getattr(request.app.state, platform)
        ready = service.status()["accounts"]
        if not identifier or not any(row["id"] == identifier and row["ready"] for row in ready):
            raise HTTPException(422, f"{'YouTube' if platform == 'youtube' else 'Instagram'} 계정 연결을 확인하세요. MP4 저장은 계속 사용할 수 있습니다.")
        accounts[platform] = identifier
    try:
        request.app.state.unified_publishing.save_review(
            render_job_id, accounts, title=title, description=description, hashtags=hashtags,
            content_reviewed=content_reviewed, copyright_confirmed=copyright_confirmed,
            sources_confirmed=sources_confirmed, ai_disclosure=ai_disclosure,
            youtube_category_id=youtube_category_id,
        )
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go(f"/?video={render_job_id}&publish_platform=unified#publish-workspace")


@router.post("/publishing/unified/{cohort_id}/execute")
def execute(
    request: Request, cohort_id: int, approval_token: str = Form(pattern=r"^[a-f0-9]{64}$"),
    consent: bool = Form(False), privacy: str = Form("private", max_length=10),
    made_for_kids: str = Form("", max_length=3), youtube_public_consent: bool = Form(False),
    instagram_public_consent: bool = Form(False), facebook_public_consent: bool = Form(False),
    tiktok_privacy: str = Form("", max_length=30), tiktok_music_consent: bool = Form(False),
    tiktok_brand_consent: bool = Form(False), tiktok_branded: bool = Form(False), tiktok_own_brand: bool = Form(False),
    tiktok_allow_comment: bool = Form(False), tiktok_allow_duet: bool = Form(False), tiktok_allow_stitch: bool = Form(False),
):
    if consent is not True or made_for_kids not in {"", "yes", "no"}:
        raise HTTPException(422, "대상 계정·영상·게시 승인 항목을 확인하세요.")
    try:
        result = request.app.state.unified_publishing.execute(
            cohort_id, approval_token=approval_token, consent=True, privacy=privacy,
            made_for_kids={"": None, "yes": True, "no": False}[made_for_kids],
            youtube_public_consent=youtube_public_consent, instagram_public_consent=instagram_public_consent,
            **({"extension_options": {"facebook": {"public_consent": facebook_public_consent}, "tiktok": {
                "privacy": tiktok_privacy, "music_consent": tiktok_music_consent, "brand_consent": tiktok_brand_consent,
                "branded": tiktok_branded, "own_brand": tiktok_own_brand, "allow_comment": tiktok_allow_comment,
                "allow_duet": tiktok_allow_duet, "allow_stitch": tiktok_allow_stitch}}} if any(p in request.app.state.unified_publishing.get(cohort_id)["accounts"] for p in ("tiktok", "facebook")) else {}),
        )
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    except Exception:  # noqa: BLE001 - platform outcomes remain in their durable journals.
        raise HTTPException(422, "게시 결과를 확인하지 못했습니다. 기록을 보존하며 자동 재시도하지 않습니다.") from None
    return go(f"/?video={result['render_job_id']}&publish_platform=unified#publish-workspace")


@router.post("/publishing/unified/{cohort_id}/tiktok-options")
def tiktok_options(request: Request, cohort_id: int, consent: bool = Form(False)):
    try:
        cohort = request.app.state.unified_publishing.get(cohort_id)
        target = next((t for t in cohort["targets"] if t["platform"] == "tiktok"), None)
        if not target:
            raise PublishingError("TikTok 초안을 먼저 검토하세요.")
        request.app.state.social_extensions["tiktok"].prepare_options(target["draft_id"], consent=consent)
    except PublishingError as error:
        raise HTTPException(422, str(error)) from None
    return go(f"/?video={cohort['render_job_id']}&publish_platform=unified#publish-workspace")
