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
