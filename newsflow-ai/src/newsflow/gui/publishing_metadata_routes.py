"""Authenticated local copy editing and explicit AI suggestions; never SNS execution."""
import json
from fastapi import APIRouter, Form, HTTPException, Request
from filelock import Timeout
from pydantic import ValidationError
from newsflow.db.models import IntelligenceRun
from newsflow.publishing.posting_copy import PostingCopy,Copy,digest
from newsflow.publishing.service import PublishingError

router=APIRouter()

def service(request):
    state=request.app.state
    current=getattr(state,'posting_copy',None)
    if current is None:
        current=PostingCopy(state);state.posting_copy=current
    return current

def safe(call):
    try:return call()
    except PublishingError as e:raise HTTPException(409,str(e)) from None
    except Timeout:raise HTTPException(409,'다른 게시 문구 작업이 진행 중입니다.') from None
    except (ValueError,TypeError,ValidationError):raise HTTPException(422,'제목 100자·설명 1500자·해시태그 15개 이내로 확인하세요.') from None

@router.get('/api/studio/publishing/copy')
def read(request:Request, project_id:str):
    return safe(lambda:service(request).view(project_id))

@router.post('/api/studio/publishing/copy/save')
def save(request:Request,project_id:str=Form(max_length=65),source_hash:str=Form(min_length=64,max_length=64),
         revision:int=Form(ge=0),copy_payload:str=Form(alias="copy",max_length=12000)):
    return safe(lambda:service(request).save(project_id,source_hash,revision,json.loads(copy_payload)))

@router.post('/api/studio/publishing/copy/review')
def review(request:Request,project_id:str=Form(max_length=65),source_hash:str=Form(min_length=64,max_length=64),
           revision:int=Form(ge=0),copy_payload:str=Form(alias="copy",max_length=12000),provider:str=Form(max_length=20),
           request_id:str=Form(min_length=32,max_length=32),consent:bool=Form(False)):
    return safe(lambda:service(request).review(project_id,source_hash,revision,json.loads(copy_payload),provider,request_id,consent))

@router.post('/api/studio/publishing/copy/apply')
def apply(request:Request,project_id:str=Form(max_length=65),source_hash:str=Form(min_length=64,max_length=64),
          revision:int=Form(ge=0),review_id:int=Form(ge=1)):
    def perform():
        svc=service(request)
        with svc.sessions() as s:
            row=s.get(IntelligenceRun,review_id)
            if (not row or row.kind!='posting_copy_review' or row.status!='success'
                or row.options.get('project_id')!=project_id or row.evidence.get('sourceHash')!=source_hash
                or row.options.get('revision')!=revision):
                raise PublishingError('현재 콘텐츠의 검토 제안을 다시 확인하세요.')
            value={k:row.result[k] for k in ('title','description','hashtags')}
        return svc.save(project_id,source_hash,revision,value)
    return safe(perform)


@router.post('/api/studio/publishing/copy/validate')
def validate(request:Request,project_id:str=Form(max_length=65),source_hash:str=Form(min_length=64,max_length=64),
             copy_payload:str=Form(alias="copy",max_length=12000)):
    def perform():
        if digest(service(request).source(project_id))!=source_hash:
            raise PublishingError('콘텐츠가 변경됐습니다. 다시 선택하세요.')
        Copy.model_validate(json.loads(copy_payload))
        return {'valid':True,'published':False,'approval':False}
    return safe(perform)


@router.post('/api/studio/publishing/copy/prepare')
def prepare(request:Request,project_id:str=Form(max_length=65),source_hash:str=Form(min_length=64,max_length=64),
            revision:int=Form(ge=0),copy_payload:str=Form(alias="copy",max_length=12000),
            preparation:str=Form(max_length=1000)):
    return safe(lambda:service(request).save(project_id,source_hash,revision,json.loads(copy_payload),
                                            preparation=json.loads(preparation)))
