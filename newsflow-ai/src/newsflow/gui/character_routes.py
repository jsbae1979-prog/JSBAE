"""Explicit, CSRF-protected stages inside Video Studio. No startup work or publication."""
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from newsflow.character.compose import digest
from newsflow.character.schema import CharacterError, load_character
from newsflow.character.service import SAFE_ERRORS
from newsflow.creation.catalog import API_MODELS, SelectionError, read_defaults, save_defaults
from newsflow.publishing.service import PublishingError

from .routes import go, page


def choices(request, reference_asset=''):
    service = request.app.state.image_studio
    assets = service.assets()
    if reference_asset and reference_asset not in assets:
        raise HTTPException(422, '저장한 참조 이미지를 확인하세요.')
    return {'chosen': read_defaults(request.app.state.sessions, 'character'),
                'script_models': API_MODELS['claude_api'], 'reference_assets': assets,
                'reference_asset': reference_asset}


router=APIRouter()


@router.get('/api/studio/video-models')
def video_models():
    from newsflow.character.kling import catalog
    return catalog()


@router.post('/api/studio/characters/library')
def save_character_reference(request: Request, reference: Annotated[UploadFile, File()],
                             save_to_library: bool=Form(False), name: str=Form('',max_length=255)):
    if not save_to_library:
        raise HTTPException(422, '내 캐릭터 저장을 선택하세요.')
    if reference.content_type not in {'image/png', 'image/jpeg'}:
        raise HTTPException(422, 'PNG/JPG, 최대 10MB 이미지를 선택하세요.')
    try:
        raw = reference.file.read(10*1024*1024+1)
        return request.app.state.image_studio.save_character(raw, name or reference.filename)
    except (PublishingError, ValueError):
        raise HTTPException(422, '이미지 형식·크기 또는 저장한 캐릭터 정보를 확인하세요.') from None
    except OSError:
        raise HTTPException(409, '캐릭터를 저장하지 못했습니다. 저장 공간과 파일 접근 권한을 확인하세요.') from None


@router.post('/api/studio/characters/auto-story')
def auto_story(request: Request, job_id: str=Form(...), consent: bool=Form(False)):
    service=request.app.state.character
    try:
        service.consent(consent)
        job=service.read(job_id)
        if not job.get('studio_selection'): raise CharacterError('blocked')
        if job['state']=='needs_script':
            service.write(job_id,consent=True)
        elif job['state']!='script_review':
            raise CharacterError('blocked')
        return {'id':job_id,'state':service.read(job_id)['state']}
    except (ValueError,OSError,*SAFE_ERRORS):
        return JSONResponse({'id':job_id,'error':'스토리 요청을 중단했습니다. 작업 이력을 확인하세요. 자동 재요청하지 않습니다.'},status_code=409)


@router.post('/api/studio/characters/{job_id}/recover-story')
def recover_story(request: Request,job_id:str,consent:bool=Form(False)):
    try:
        request.app.state.character.recover_story_response(job_id,consent=consent)
        return {'id':job_id,'state':'script_review','additionalProviderCalls':0}
    except (ValueError,OSError,*SAFE_ERRORS):
        raise HTTPException(409,'보관 응답을 복구하지 못했습니다. 기존 실패 기록은 보존됩니다.') from None


@router.post('/api/studio/characters/{job_id}/settings')
def studio_settings(request: Request,job_id:str,settings:str=Form(...),
                    episode_limit:str=Form(...),day_limit:str=Form('')):
    import json
    try:
        from newsflow.character.kling import field_errors
        parsed=json.loads(settings)
        invalid=field_errors(parsed)
        if invalid:return JSONResponse({'error':'모델 지원 설정을 확인하세요.','fields':invalid},status_code=422)
        request.app.state.character.update_studio_settings(job_id,parsed,episode_limit,day_limit)
        state=request.app.state.character.read(job_id)['state']
        if state not in {'quoted','script_review'}:raise CharacterError('blocked')
        return {'id':job_id,'saved':True,'state':state,'quoteRetained':state=='quoted'}
    except (ValueError,OSError,*SAFE_ERRORS):
        raise HTTPException(409,'견적 전 스토리 검토 단계에서만 영상 설정을 저장할 수 있습니다.') from None


@router.post('/api/studio/characters/{job_id}/reuse-story')
def reuse_story(request: Request,job_id: str,settings: str=Form(...,max_length=16000),
                episode_limit: str=Form(...),day_limit: str=Form(''),request_id: str=Form(...),
                dialogues: str=Form('[]',max_length=8000),consent: bool=Form(False),
                reference: Annotated[UploadFile | None, File()]=None,
                reference_job: str=Form('',max_length=32),
                reference_asset: str=Form('',max_length=80)):
    import json
    try:
        parsed=json.loads(settings)
        spoken=json.loads(dialogues)
        from newsflow.character.kling import field_errors
        invalid=field_errors(parsed)
        if invalid:return JSONResponse({'error':'모델 지원 설정을 확인하세요.','fields':invalid},status_code=422)
        service=request.app.state.character
        sources=int(bool(reference and reference.filename))+int(bool(reference_job))+int(bool(reference_asset))
        if sources>1:
            raise ValueError('Select one reference')
        raw=reference.file.read(10*1024*1024+1) if reference and reference.filename else None
        if reference_asset:
            raw=request.app.state.image_studio.asset(reference_asset).read_bytes()
        identifier,created=service.reuse_story(job_id,parsed,episode_limit,day_limit,
                              request_id=request_id,dialogues=spoken,reference=raw,
                              reference_job=reference_job,consent=consent)
        job=service.read(identifier)
        return {'id':identifier,'created':created,'state':job['state'],'source_id':job_id,
                'reusedStory':True,'additionalClaudeCalls':0,
                'dialogueSource':job['reused_story']['dialogue_source']}
    except (OSError,*SAFE_ERRORS):
        return JSONResponse({'error':'복사를 중단했습니다. 원본 작업과 작업 이력을 확인하세요. 자동 재요청하지 않습니다.'},status_code=409)
    except (ValueError,TypeError,PublishingError):
        return JSONResponse({'error':'저장 스토리·참조 이미지·영상 설정을 확인하세요.'},status_code=422)


@router.post('/api/studio/characters/{job_id}/visibility')
def character_visibility(request: Request, job_id: str, scope: str=Form(...), hidden: bool=Form(...)):
    from newsflow.character.visibility import set_visibility
    try:
        return set_visibility(request.app.state.character,job_id,scope,hidden)
    except (OSError,*SAFE_ERRORS):
        raise HTTPException(409,'처리 중인 작업이나 원본 상태를 확인하세요. 원본 파일은 변경하지 않았습니다.') from None
    except (ValueError,TypeError):
        raise HTTPException(422,'작업과 목록 구분·숨김 값을 확인하세요.') from None


@router.get('/character',response_class=HTMLResponse)
def studio(request: Request, job_id: str = '', reference_asset: str = ''):
    service=request.app.state.character
    try:
        job=service.read(job_id) if job_id else None
        return page(request,'character.html',active='video',character=load_character(),job=job,
                    jobs=service.listing()[:20],error='',**choices(request, reference_asset))
    except CharacterError:
        raise HTTPException(404,'캐릭터 작업을 찾지 못했습니다.') from None


@router.post('/character')
def create(request: Request, reference: Annotated[UploadFile | None, File()] = None, topic: str=Form(...),
           episode_limit: str=Form(...),day_limit: str=Form(''), script_model: str=Form(''),
           video_model: str=Form(''), reference_asset: str=Form(''), reference_job: str=Form(''),
           studio_settings: str=Form(''), request_id: str=Form('')):
    if studio_settings:
        import json
        try:
            service=request.app.state.character
            from newsflow.character.kling import field_errors
            parsed=json.loads(studio_settings)
            invalid=field_errors(parsed)
            if invalid:return JSONResponse({'error':'모델 지원 설정을 확인하세요.','fields':invalid},status_code=422)
            sources=int(bool(reference and reference.filename))+int(bool(reference_asset))+int(bool(reference_job))
            if sources!=1: raise CharacterError('reference')
            raw=reference.file.read(10*1024*1024+1) if reference and reference.filename else b''
            if reference_asset: raw=request.app.state.image_studio.asset(reference_asset).read_bytes()
            if reference_job:
                source=service.read(reference_job)
                path=service.folder(reference_job)/'reference.png'
                if digest(path)!=source.get('reference_sha256'): raise CharacterError('reference')
                raw=path.read_bytes()
            identifier,created=service.create_studio(topic,episode_limit,day_limit,reference=raw,
                          settings=parsed,request_id=request_id)
            return JSONResponse({'id':identifier,'created':created,'state':service.read(identifier)['state']})
        except (ValueError,OSError,*SAFE_ERRORS):
            return JSONResponse({'error':'참조 이미지와 새 작업 설정을 확인하세요.'},status_code=422)
    try:
        selected = read_defaults(request.app.state.sessions, 'character')
        if script_model:
            selected['script_model'] = script_model
        if video_model:
            selected['video_model'] = video_model
        raw = reference.file.read(10*1024*1024+1) if reference and reference.filename else b''
        if reference_asset:
            if raw:
                raise ValueError('Select one reference')
            raw = request.app.state.image_studio.asset(reference_asset).read_bytes()
        if not raw:
            raise ValueError('Reference required')
        identifier=request.app.state.character.create(topic,episode_limit,day_limit,
                        reference=raw, selection=selected)
        return go('/character?job_id='+identifier)
    except (ValueError,OSError,*SAFE_ERRORS):
        return page(request,'character.html',active='video',character=load_character(),job=None,
                    jobs=request.app.state.character.listing()[:20],error='입력과 PNG 원본·제작 한도를 확인하세요.',**choices(request))


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
        elif action=='retry-quote':
            service.prepare_retry(job_id,consent=consent)
        elif action=='retry-scene':
            service.retry_scene(job_id,consent=consent,quote_hash=quote_hash)
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
        from newsflow.character.story_response import public_failure
        diagnosed=public_failure(job.get('script_failure'))
        if diagnosed:message=diagnosed['message']
        return page(request,'character.html',active='video',character=load_character(),job=job,
                    jobs=service.listing()[:20],error=message,**choices(request))


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


@router.post('/character-defaults')
def character_defaults(request: Request, script_model: str=Form(...), video_model: str=Form(...)):
    selected = read_defaults(request.app.state.sessions, 'character')
    selected.update(script_model=script_model, video_model=video_model)
    try:
        save_defaults(request.app.state.sessions, 'character', selected)
    except SelectionError as exc:
        raise HTTPException(422, str(exc)) from None
    return go('/character')
