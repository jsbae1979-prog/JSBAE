"""Independent image studio; all writes retain the application's CSRF boundary."""
from typing import Annotated
from fastapi import APIRouter, Request, Form, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from newsflow.creation.catalog import (IMAGE_MODELS, IMAGE_SIZES, IMAGE_QUALITIES, DEFAULTS,
    SelectionError, read_defaults, save_defaults)
from newsflow.publishing.service import PublishingError
from .routes import page, go

router = APIRouter()


def context(request, identifier=None, error=''):
    service = request.app.state.image_studio
    draft = service.get(identifier) if identifier else None
    return dict(active='image', image_models=IMAGE_MODELS, image_sizes=IMAGE_SIZES,
        image_qualities=IMAGE_QUALITIES, selected=read_defaults(service.sessions, 'image'),
        draft=draft, output=service.output(identifier) if draft else None,
        drafts=service.recent(), assets=service.assets(), error=error,
        key_ready=service.generation.keys.status()['configured'])


@router.get('/image-studio')
def studio(request: Request, draft_id: int | None = None):
    try:
        return page(request, 'image_studio.html', **context(request, draft_id))
    except (PublishingError, SelectionError, OSError, ValueError):
        raise HTTPException(422, '이미지 초안과 저장 설정을 확인하세요.') from None


@router.post('/image-studio/drafts')
def draft(request: Request, prompt: str = Form(...), model: str = Form(...),
          size: str = Form(...), quality: str = Form(...), provider: str = Form('openai'),
          reference: Annotated[UploadFile | None, File()] = None):
    service = request.app.state.image_studio
    try:
        identifier = service.create(prompt, dict(provider=provider, model=model, size=size, quality=quality),
                         reference=reference.file.read(10*1024*1024+1) if reference and reference.filename else b'')
        return go('/image-studio?draft_id=' + str(identifier))
    except (PublishingError, SelectionError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, (PublishingError, SelectionError)) else '입력 이미지를 확인하세요.'
        return page(request, 'image_studio.html', **context(request, error=message))


@router.post('/image-studio/defaults')
def defaults(request: Request, model: str = Form(...), size: str = Form(...),
             quality: str = Form(...), provider: str = Form('openai')):
    try:
        save_defaults(request.app.state.sessions, 'image', dict(provider=provider,model=model,size=size,quality=quality))
    except SelectionError as exc:
        raise HTTPException(422, str(exc)) from None
    return go('/image-studio')


@router.post('/image-studio/{identifier}/generate')
def generate(request: Request, identifier: int, consent: bool = Form(False), reviewed: bool = Form(False)):
    try:
        request.app.state.image_studio.execute(identifier, consent=consent, reviewed=reviewed)
        return go('/image-studio?draft_id=' + str(identifier))
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/image-studio/{identifier}/file')
def image_file(request: Request, identifier: int, download: bool = False):
    try:
        service = request.app.state.image_studio
        run = service.output(identifier)
        if run is None:
            raise PublishingError('이미지 없음')
        path = service.generation.path(run.id)
        service.images.safe(path, service.generation.outputs)
        return FileResponse(path, media_type='image/jpeg', filename='created-image.jpg' if download else None)
    except (PublishingError, SelectionError, OSError, ValueError):
        raise HTTPException(404, '완료된 이미지를 확인하세요.') from None


@router.get('/image-studio/assets/{name}')
def asset(request: Request, name: str):
    try:
        return FileResponse(request.app.state.image_studio.asset(name), media_type='image/png')
    except (PublishingError, ValueError, OSError):
        raise HTTPException(404, '이미지를 확인하세요.') from None


@router.post('/image-studio/{identifier}/reuse')
def reuse(request: Request, identifier: int, reviewed: bool = Form(False), target: str = Form('news')):
    if target not in {'news','character'}:
        raise HTTPException(422, '재사용할 제작 모드를 선택하세요.')
    try:
        name = request.app.state.image_studio.export(identifier, reviewed=reviewed)
    except (PublishingError, SelectionError, ValueError, OSError) as exc:
        raise HTTPException(422, '완성 이미지와 내용·사용권 검토를 확인하세요.') from None
    return go('/character?reference_asset=' + name if target == 'character' else '/video?image_asset=' + name)


@router.get('/api/feed-batches')
def feed_batches(request: Request):
    service = request.app.state.top_three_feeds
    return {"batches": [service.view(row.id) for row in service.recent()], "defaults": service.defaults()}


@router.post('/api/feed-batches/defaults')
def feed_batch_defaults(request: Request, model: str = Form(...), size: str = Form("1024x1280"),
                        quality: str = Form("medium")):
    try:
        return request.app.state.top_three_feeds.save_defaults(dict(provider="openai", model=model, size=size, quality=quality))
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/api/feed-batches')
def feed_batch_create(request: Request, analysis_id: int = Form(ge=1), model: str = Form(...),
                      size: str = Form("1024x1280"), quality: str = Form("medium")):
    try:
        service = request.app.state.top_three_feeds
        identifier = service.create(analysis_id, dict(provider="openai", model=model, size=size, quality=quality))
        return service.view(identifier)
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/api/feed-batches/{identifier}/step')
def feed_batch_step(request: Request, identifier: int, consent: bool = Form(False), reviewed: bool = Form(False)):
    try:
        service = request.app.state.top_three_feeds
        service.step(identifier, consent=consent, reviewed=reviewed)
        return service.view(identifier)
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/api/feed-batches/{identifier}/change')
def feed_batch_change(request: Request, identifier: int, revision: int = Form(ge=1),
                      action: str = Form(...), rank: int | None = Form(None, ge=1, le=3),
                      title: str = Form("", max_length=60), body: str = Form("", max_length=180),
                      hashtags: str = Form("", max_length=200), consent: bool = Form(False),
                      reviewed: bool = Form(False)):
    try:
        service = request.app.state.top_three_feeds
        service.change(identifier, revision, action, rank=rank, title=title, body=body,
                       hashtags=hashtags, consent=consent, reviewed=reviewed)
        return service.view(identifier)
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(409 if "다른 화면" in str(exc) else 422, str(exc)) from None


@router.get('/api/feed-batches/{identifier}/items/{rank}/file')
def feed_batch_file(request: Request, identifier: int, rank: int, download: bool = False):
    try:
        path = request.app.state.top_three_feeds.path(identifier, rank)
        return FileResponse(path, media_type="image/jpeg", filename=path.name if download else None)
    except (PublishingError, SelectionError, ValueError, OSError):
        raise HTTPException(404, "완료한 피드 이미지를 확인하세요.") from None


@router.post('/api/feed-batches/{identifier}/items/{rank}/review')
def feed_batch_review(request: Request, identifier: int, rank: int, reviewed: bool = Form(False),
                      rights: bool = Form(False), sources_confirmed: bool = Form(False),
                      ai_disclosure: str = Form("unreviewed")):
    service = request.app.state.top_three_feeds
    try:
        row = service.get(identifier)
        if row.options["simulation"]:
            raise PublishingError("Fake 산출물은 실제 Instagram 게시 준비에 사용할 수 없습니다.")
        service.path(identifier, rank)
        item = next(i for i in row.result["items"] if i["rank"] == rank)
        source = row.evidence["sources"][rank-1]
        if ai_disclosure != "disclose":
            raise PublishingError("AI 생성 이미지 표시를 검토하세요.")
        # Local reviewed post only. No account/HTTPS upload/container/publish in this endpoint.
        post_id = request.app.state.image_posts.create(source["article_id"], **item["content"],
            reviewed=reviewed, rights=rights, sources_confirmed=sources_confirmed,
            ai_disclosure=ai_disclosure, draft_id=source["draft_id"],
            analysis_id=row.evidence["analysis_id"], rank=rank, generated_id=item["generation_id"])
        return {"postId": post_id, "href": f"/image-posts?post_id={post_id}", "published": False,
                "message": "로컬 검토본 저장 · 계정 선택·이미지 전달·공개 게시 승인은 별도입니다."}
    except (PublishingError, SelectionError, StopIteration) as exc:
        raise HTTPException(422, str(exc) or "완료한 피드 이미지를 선택하세요.") from None
