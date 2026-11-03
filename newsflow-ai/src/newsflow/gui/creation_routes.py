"""Independent image studio; all writes retain the application's CSRF boundary."""
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from newsflow.creation.catalog import (
    IMAGE_MODELS,
    IMAGE_QUALITIES,
    IMAGE_SIZES,
    SelectionError,
    read_defaults,
    save_defaults,
)
from newsflow.publishing.service import PublishingError

from .routes import go, page

router = APIRouter()


def context(request, identifier=None, error=''):
    service = request.app.state.image_studio
    draft = service.get(identifier) if identifier else None
    return {'active': 'image', 'image_models': IMAGE_MODELS, 'image_sizes': IMAGE_SIZES,
        'image_qualities': IMAGE_QUALITIES, 'selected': read_defaults(service.sessions, 'image'),
        'draft': draft, 'output': service.output(identifier) if draft else None,
        'drafts': service.recent(), 'assets': service.assets(), 'error': error,
        'key_ready': service.generation.keys.status()['configured']}


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
        identifier = service.create(prompt, {'provider': provider, 'model': model, 'size': size, 'quality': quality},
                         reference=reference.file.read(10*1024*1024+1) if reference and reference.filename else b'')
        return go('/image-studio?draft_id=' + str(identifier))
    except (PublishingError, SelectionError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, (PublishingError, SelectionError)) else '입력 이미지를 확인하세요.'
        return page(request, 'image_studio.html', **context(request, error=message))


@router.post('/image-studio/defaults')
def defaults(request: Request, model: str = Form(...), size: str = Form(...),
             quality: str = Form(...), provider: str = Form('openai')):
    try:
        save_defaults(request.app.state.sessions, 'image', {'provider': provider,'model': model,'size': size,'quality': quality})
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
    except (PublishingError, SelectionError, ValueError, OSError):
        raise HTTPException(422, '완성 이미지와 내용·사용권 검토를 확인하세요.') from None
    return go('/character?reference_asset=' + name if target == 'character' else '/video?image_asset=' + name)


@router.get('/api/feed-batches')
def feed_batches(request: Request, batch_id: int | None = None):
    service = request.app.state.top_three_feeds
    rows=service.recent()
    if batch_id is not None and not any(row.id==batch_id for row in rows):
        if not 1<=batch_id<=9223372036854775807:raise HTTPException(422,'작업 번호를 확인하세요.')
        try:rows.insert(0,service.get(batch_id))
        except PublishingError:raise HTTPException(404,'선택한 작업을 확인하세요.') from None
    return {"batches": [service.view(row.id) for row in rows], "defaults": service.defaults()}


@router.post('/api/feed-batches/defaults')
def feed_batch_defaults(request: Request, model: str = Form(...), size: str = Form("1024x1280"),
                        quality: str = Form("medium")):
    try:
        return request.app.state.top_three_feeds.save_defaults({'provider': "openai", 'model': model, 'size': size, 'quality': quality})
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/api/feed-batches')
def feed_batch_create(request: Request, analysis_id: int = Form(ge=1), model: str = Form(...),
                      size: str = Form("1024x1280"), quality: str = Form("medium"),
                      rank: int | None = Form(None, ge=1, le=3), feed_style: str = Form("legacy")):
    try:
        service = request.app.state.top_three_feeds
        identifier = service.create(analysis_id, {'provider': "openai", 'model': model, 'size': size, 'quality': quality}, rank=rank, feed_style=feed_style)
        return service.view(identifier)
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.get('/api/feed-batches/{identifier}/cost-review')
def feed_cost_status(request: Request, identifier: int):
    try:
        return request.app.state.top_three_feeds.view(identifier)
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.post('/api/feed-batches/{identifier}/cost-review')
def feed_cost_review(request: Request, identifier: int, revision: int = Form(ge=1),
                     limit: str | None = Form(None,max_length=20), quote_hash: str = Form('',max_length=64),
                     consent: bool = Form(False)):
    try:
        service=request.app.state.top_three_feeds
        service.cost_review(identifier,revision,limit=limit,quote_hash=quote_hash,consent=consent)
        return service.view(identifier)
    except (PublishingError,SelectionError) as exc:
        raise HTTPException(409 if '다른 화면' in str(exc) else 422,str(exc)) from None


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
                      title: str = Form("", max_length=100), body: str = Form("", max_length=180),
                      hashtags: str = Form("", max_length=200), accent: str = Form("#ffb45c", max_length=7), consent: bool = Form(False),
                      reviewed: bool = Form(False)):
    try:
        service = request.app.state.top_three_feeds
        service.change(identifier, revision, action, rank=rank, title=title, body=body,
                       hashtags=hashtags, accent=accent, consent=consent, reviewed=reviewed)
        return service.view(identifier)
    except (PublishingError, SelectionError) as exc:
        raise HTTPException(409 if "다른 화면" in str(exc) else 422, str(exc)) from None


@router.get('/api/feed-batches/{identifier}/items/{rank}/file')
def feed_batch_file(request: Request, identifier: int, rank: int, download: bool = False, attempt: int | None = None):
    try:
        path = request.app.state.top_three_feeds.path(identifier, rank, attempt=attempt)
        return FileResponse(path, media_type="image/jpeg", filename=path.name if download else None, headers={"Cache-Control": "no-store"})
    except (PublishingError, SelectionError, ValueError, OSError):
        raise HTTPException(404, "완료한 피드 이미지를 확인하세요.") from None


@router.post('/api/feed-batches/{identifier}/items/{rank}/review')
def feed_batch_review(request: Request, identifier: int, rank: int, reviewed: bool = Form(False),
                      rights: bool = Form(False), sources_confirmed: bool = Form(False), image_safety_checked: bool = Form(False),
                      ai_disclosure: str = Form("unreviewed")):
    service = request.app.state.top_three_feeds
    try:
        # Local reviewed post only; no upload, account query or publish in this endpoint.
        post_id = service.review(identifier, rank, request.app.state.image_posts,
            reviewed=reviewed, rights=rights, sources_confirmed=sources_confirmed, ai_disclosure=ai_disclosure, image_safety_checked=image_safety_checked)
        return {"postId": post_id, "href": f"/image-posts?post_id={post_id}", "published": False,
                "message": "로컬 검토본 저장 · 계정 선택·이미지 전달·공개 게시 승인은 별도입니다."}
    except (PublishingError, SelectionError, StopIteration) as exc:
        raise HTTPException(422, str(exc) or "완료한 피드 이미지를 선택하세요.") from None


# Local-only photo feed editing. Existing application Origin/CSRF middleware applies.
@router.get('/api/feed-batches/{identifier}/items/{rank}/design')
def feed_design_view(request: Request, identifier: int, rank: int):
    from newsflow.creation.feed_designs import FeedDesigns
    try: return FeedDesigns(request.app.state.top_three_feeds).view(identifier, rank)
    except (PublishingError, ValueError, OSError): raise HTTPException(422, '편집 이미지 연결을 확인하세요.') from None


@router.post('/api/feed-batches/{identifier}/items/{rank}/design')
def feed_design_save(request: Request, identifier: int, rank: int, revision: int = Form(ge=0),
                     action: str = Form(...), background: str = Form(...), design: str = Form(..., max_length=8000)):
    import json
    from newsflow.creation.feed_designs import FeedDesigns
    try:
        service=FeedDesigns(request.app.state.top_three_feeds); value=json.loads(design)
        if action=='caption':
            from newsflow.creation.feed_growth import compose_caption
            service.checked(identifier,rank,revision)
            return {'caption':compose_caption(value), 'paid':False}
        if action=='preview':
            from hashlib import sha256
            raw=service.preview(identifier,rank,revision,background,value);digest=sha256(raw).hexdigest()
            folder=service.feeds.safe_paths.safe(service.root/'previews',service.root);folder.mkdir(parents=True,exist_ok=True)
            path=folder/f'{identifier}-{rank}-{digest}.jpg'
            if not path.exists():
                with path.open('xb') as stream:stream.write(raw)
            return {'previewUrl':f'/api/feed-batches/{identifier}/items/{rank}/design-preview/{digest}'}
        if action not in {'draft','render'}:raise PublishingError('편집 동작을 확인하세요.')
        return service.save(identifier,rank,revision,background,value,export=action=='render')
    except (PublishingError,ValueError,OSError) as exc:
        raise HTTPException(409 if '다른 화면' in str(exc) else 422,str(exc) if isinstance(exc,PublishingError) else '편집 입력·이미지를 확인하세요.') from None


@router.post('/api/feed-batches/{identifier}/items/{rank}/design-upload')
def feed_design_upload(request: Request, identifier: int, rank: int, revision: int = Form(ge=0),
                       kind: str = Form(...), credit: str = Form(...,max_length=160), image: UploadFile = File(...)):
    from newsflow.creation.feed_designs import FeedDesigns
    try:return FeedDesigns(request.app.state.top_three_feeds).upload(identifier,rank,revision,image.file.read(20*1024*1024+1),kind,credit)
    except (PublishingError,ValueError,OSError) as exc:
        raise HTTPException(422,str(exc) if isinstance(exc,PublishingError) else '업로드 이미지를 확인하세요.') from None


@router.get('/api/feed-batches/{identifier}/items/{rank}/design-file/{version}')
def feed_design_file(request: Request, identifier: int, rank: int, version: int, download: bool=False):
    from newsflow.creation.feed_designs import FeedDesigns
    try:
        service=FeedDesigns(request.app.state.top_three_feeds);v=service.version(identifier,rank,version)
        return FileResponse(service.path(v['filename'],v['sha256']),media_type='image/jpeg',filename=f'news-{rank}-v{version}.jpg' if download else None,headers={'Cache-Control':'no-store'})
    except (PublishingError,ValueError,OSError):raise HTTPException(404,'저장된 편집 이미지를 확인하세요.') from None


@router.post('/api/feed-batches/{identifier}/items/{rank}/design-review')
def feed_design_review(request: Request, identifier: int, rank: int, version: int = Form(ge=1), reviewed: bool = Form(False), image_safety_checked: bool = Form(False)):
    from newsflow.creation.feed_designs import FeedDesigns
    try:
        post=FeedDesigns(request.app.state.top_three_feeds).review(identifier,rank,version,request.app.state.image_posts,reviewed=reviewed,image_safety_checked=image_safety_checked)
        return {'postId':post,'published':False}
    except (PublishingError,ValueError,OSError) as exc:raise HTTPException(422,str(exc) if isinstance(exc,PublishingError) else '저장된 버전을 확인하세요.') from None


@router.get('/api/feed-batches/{identifier}/items/{rank}/design-preview/{digest}')
def feed_design_preview_file(request: Request, identifier: int, rank: int, digest: str):
    import re
    from hashlib import sha256
    from newsflow.creation.feed_designs import FeedDesigns
    try:
        if not re.fullmatch(r'[a-f0-9]{64}',digest):raise ValueError()
        service=FeedDesigns(request.app.state.top_three_feeds);service.source(identifier,rank)
        path=service.feeds.safe_paths.safe(service.root/'previews'/f'{identifier}-{rank}-{digest}.jpg',service.root)
        if sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError()
        return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'no-store'})
    except (PublishingError,ValueError,OSError):raise HTTPException(404,'미리보기 이미지를 확인하세요.') from None


@router.get('/api/feed-batches/{identifier}/items/{rank}/design-performance')
def feed_performance_view(request: Request, identifier: int, rank: int):
    from newsflow.creation.feed_designs import FeedDesigns
    from newsflow.creation.feed_growth import FeedPerformance
    try:
        return FeedPerformance(FeedDesigns(request.app.state.top_three_feeds)).view(identifier,rank)
    except (PublishingError, ValueError, OSError):
        raise HTTPException(422, '선택 뉴스의 성과 기록을 확인하세요.') from None


@router.post('/api/feed-batches/{identifier}/items/{rank}/design-performance')
def feed_performance_save(request: Request, identifier: int, rank: int,
                          revision: int = Form(ge=0), metrics: str = Form(...,max_length=3000)):
    import json
    from newsflow.creation.feed_designs import FeedDesigns
    from newsflow.creation.feed_growth import FeedPerformance
    try:
        return FeedPerformance(FeedDesigns(request.app.state.top_three_feeds)).save(identifier,rank,revision,json.loads(metrics))
    except (PublishingError, ValueError, OSError) as exc:
        raise HTTPException(422,str(exc) if isinstance(exc,PublishingError) else '성과 입력 형식을 확인하세요.') from None
