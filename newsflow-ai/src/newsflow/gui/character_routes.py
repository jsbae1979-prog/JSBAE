"""Explicit, CSRF-protected stages inside Video Studio. No startup work or publication."""
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from newsflow.character.compose import digest
from newsflow.character.schema import CharacterError, load_character
from newsflow.character.service import SAFE_ERRORS

from .routes import go, page

router=APIRouter()


@router.get('/character',response_class=HTMLResponse)
def studio(request: Request, job_id: str = ''):
    service=request.app.state.character
    try:
        job=service.read(job_id) if job_id else None
        return page(request,'character.html',active='video',character=load_character(),job=job,
                    jobs=service.listing()[:20],error='')
    except CharacterError:
        raise HTTPException(404,'캐릭터 작업을 찾지 못했습니다.') from None


@router.post('/character')
def create(request: Request,reference: Annotated[UploadFile, File()],topic: str=Form(...),
           episode_limit: str=Form(...),day_limit: str=Form(...)):
    try:
        identifier=request.app.state.character.create(topic,episode_limit,day_limit,
                        reference=reference.file.read(10*1024*1024+1))
        return go('/character?job_id='+identifier)
    except (ValueError,OSError,*SAFE_ERRORS):
        return page(request,'character.html',active='video',character=load_character(),job=None,
                    jobs=request.app.state.character.listing()[:20],error='입력과 PNG 원본·제작 한도를 확인하세요.')


@router.post('/character/{job_id}/{action}')
def act(request: Request,job_id: str,action: str,consent: bool=Form(False),reviewed: bool=Form(False),
        quote_hash: str=Form('')):
    service=request.app.state.character
    try:
        if action=='write':
            service.write(job_id,consent=consent)
        elif action=='prepare':
            service.prepare(job_id,consent=consent,script_reviewed=reviewed)
        elif action=='submit':
            service.submit(job_id,consent=consent,quote_hash=quote_hash)
        elif action=='check':
            service.check(job_id,consent=consent)
        elif action=='render':
            service.render(job_id,reviewed=reviewed)
        else:
            raise HTTPException(404)
        return go('/character?job_id='+job_id)
    except (ValueError,OSError,*SAFE_ERRORS) as exc:
        try:
            job=service.read(job_id)
        except CharacterError:
            raise HTTPException(404,'작업을 확인하세요.') from None
        message=str(exc) if isinstance(exc,CharacterError) else '작업을 중단했습니다. 저장된 기록을 확인하세요.'
        return page(request,'character.html',active='video',character=load_character(),job=job,
                    jobs=service.listing()[:20],error=message)


@router.get('/character/{job_id}/file')
def output(request: Request,job_id: str,download: bool=False):
    service=request.app.state.character
    try:
        job=service.read(job_id)
        path=service.folder(job_id)/'final.mp4'
        if job['state']!='completed' or path.is_symlink() or digest(path)!=job['output']['sha256']:
            raise CharacterError()
        return FileResponse(path,media_type='video/mp4',filename='character-short.mp4' if download else None)
    except (CharacterError,OSError):
        raise HTTPException(404,'검증된 완성 영상을 찾지 못했습니다.') from None


@router.get('/character/{job_id}/clips',response_class=HTMLResponse)
def clips(request: Request,job_id: str):
    service=request.app.state.character
    try:
        job=service.read(job_id)
        return page(request,'character_clips.html',active='video',job=job)
    except CharacterError:
        raise HTTPException(404,'작업을 확인하세요.') from None


@router.get('/character/{job_id}/clips/{position}')
def clip(request: Request,job_id: str,position: int):
    service=request.app.state.character
    try:
        job=service.read(job_id)
        scene=next(s for s in job['scenes'] if s['position']==position and s['state']=='downloaded')
        path=service.folder(job_id)/f'scene-{position}.mp4'
        if path.is_symlink() or digest(path)!=scene['sha256']:
            raise CharacterError()
        return FileResponse(path,media_type='video/mp4')
    except (CharacterError,StopIteration,OSError):
        raise HTTPException(404,'저장된 장면을 확인하세요.') from None
