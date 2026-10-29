"""Retired starter-content endpoints; user-owned references remain readable.

The existing local authentication, Origin and CSRF middleware is unchanged.
"""
from fastapi import APIRouter,HTTPException,Request
from fastapi.responses import FileResponse
from newsflow.samples.catalog import SampleError,Samples
router=APIRouter()

def service(request):
    state=request.app.state
    return Samples(state.sessions,state.config.data_dir,state.image_studio)

@router.get('/api/samples')
def catalog(request:Request):
    return {'schemaVersion':1,'sample':False,'removed':True,'assets':[],'warning':''}

@router.get('/api/samples/{identifier}/file')
@router.get('/api/samples/{identifier}/poster')
@router.post('/api/samples/{identifier}/copy')
@router.post('/api/samples/{identifier}/visibility')
def retired(identifier:str):
    raise HTTPException(404,'기본 콘텐츠 제공이 종료되었습니다.')

@router.get('/api/samples/{identifier}/copy-file')
def copied(request:Request,identifier:str,download:bool=False):
    try:
        row,path=service(request).copied_file(identifier)
        return FileResponse(path,media_type=row['mime'],filename='reference'+path.suffix if download else None)
    except (OSError,SampleError):raise HTTPException(404,'보관한 참조 파일을 확인하세요.') from None
