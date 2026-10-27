"""Local sample endpoints under the unchanged Origin/CSRF middleware."""
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse

from newsflow.samples.catalog import SampleError, Samples

router = APIRouter()


def service(request):
    state = request.app.state
    return Samples(state.sessions, state.config.data_dir, state.image_studio)


@router.get('/api/samples')
def catalog(request: Request):
    try:
        return service(request).listing()
    except (OSError, ValueError):
        return {'schemaVersion': 1, 'sample': True, 'assets': [], 'warning': '샘플 표시를 준비하지 못했습니다. 내 작업은 보존됩니다.'}


@router.get('/api/samples/{identifier}/file')
def file(request: Request, identifier: str):
    try:
        s = service(request)
        row = s.get(identifier)
        return FileResponse(s.checked(row), media_type=row['mime'])
    except (OSError, SampleError):
        raise HTTPException(404, '샘플 파일을 확인하세요.') from None


@router.get('/api/samples/{identifier}/poster')
def poster(request: Request, identifier: str):
    try:
        s = service(request)
        row = s.get(identifier)
        return FileResponse(s.checked(row, poster=True), media_type='image/jpeg')
    except (OSError, SampleError, KeyError):
        raise HTTPException(404, '샘플 포스터를 확인하세요.') from None


@router.get('/api/samples/{identifier}/copy-file')
def copied(request: Request, identifier: str, download: bool = False):
    try:
        row, path = service(request).copied_file(identifier)
        return FileResponse(path, media_type=row['mime'], filename='sample-reference'+path.suffix if download else None)
    except (OSError, SampleError):
        raise HTTPException(404, '복사한 샘플 참조 파일을 확인하세요.') from None


@router.post('/api/samples/{identifier}/copy')
def copy(request: Request, identifier: str, use: bool = Form(False)):
    try:
        return service(request).copy(identifier, use)
    except (OSError, ValueError):
        raise HTTPException(409, '샘플 복사를 완료하지 못했습니다. 기존 파일은 덮어쓰지 않습니다.') from None


@router.post('/api/samples/{identifier}/visibility')
def visibility(request: Request, identifier: str, hidden: bool = Form(...)):
    try:
        service(request).hide(identifier, hidden)
        return {'saved': True}
    except (OSError, ValueError):
        raise HTTPException(409, '샘플 표시 설정을 저장하지 못했습니다.') from None
