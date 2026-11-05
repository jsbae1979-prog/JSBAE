"""Local authenticated precision mode. Global LocalAccess/CSRF/Origin policies apply."""
import json
from copy import deepcopy
from newsflow.character.service import fingerprint
from fastapi import APIRouter, Form, HTTPException, Request
from filelock import Timeout
from newsflow.character.precision import PrecisionService
from newsflow.character.schema import CharacterError
from newsflow.publishing.service import PublishingError
from newsflow.character.registry import CharacterRegistry
from newsflow.creation.feed_readiness import FeedReadiness

router=APIRouter()

def service(request):
    from .character_automation_routes import authoring
    state=request.app.state
    images=getattr(state,'precision_image_studio',state.image_studio)
    writer=getattr(state,'precision_authoring',None)
    return PrecisionService(state.config.data_dir,CharacterRegistry(state.config.data_dir,images),
        images,FeedReadiness(state),state.character,writer if writer is not None else authoring(request))

def perform(call):
    try:
        result=call()
        if isinstance(result,dict) and 'common' in result and 'scenes' in result:
            result=deepcopy(result) # Derived UI state must not modify persisted version history.
            from newsflow.character.precision_visual import annotate
            annotate(result)
        return result
    except Timeout: raise HTTPException(409,'이미 처리 중입니다. 현재 결과를 확인하세요.') from None
    except (ValueError,KeyError,TypeError,CharacterError,PublishingError,OSError):
        # Do not surface provider payloads, Pydantic input, local paths or secret values.
        raise HTTPException(422,'입력·예산·현재 장면 상태를 확인하세요. 기존 결과는 보존되며 자동 재요청하지 않습니다.') from None

@router.get('/api/studio/character-precision')
def catalog(request:Request):
    from newsflow.character.editing import load_sfx_map
    from newsflow.creation.catalog import IMAGE_MODELS,IMAGE_QUALITIES,read_defaults
    from newsflow.character.kling import catalog as video_catalog, check as video_choices
    from newsflow.intelligence.api_providers import API_MODELS
    s=service(request)
    def view():
        works=s.listing()
        latest=s.read(works[0]['id']) if works else None
        reusable={key:latest[key] for key in ('selection','video_settings','image_limit','video_limit')} if latest else None
        if reusable:reusable['video_settings']=video_choices(latest['video_settings'])
        return {'works':works,'recent_settings':reusable,'profiles':s.registry.list(),
        'paid_available':request.scope.get('newsflow.precision_paid_available', True),
        'image_models':list(IMAGE_MODELS),'qualities':IMAGE_QUALITIES,
        'image_defaults':{**read_defaults(s.images.sessions,'image'),'size':'864x1536'},
        'sfx_keys':list(load_sfx_map()),
        'script_models':list(API_MODELS['claude_api'])+list(API_MODELS['openai']), 'video':video_catalog(),'standing_limit':s.readiness.standing_limit()}
    return perform(view)

@router.get('/api/studio/character-precision/{identifier}')
def detail(request:Request,identifier:str):
    return perform(lambda:service(request).read(identifier))

@router.post('/api/studio/character-precision/create')
def create(request:Request,payload:str=Form(max_length=20000),request_id:str=Form(max_length=32)):
    def run():
        p=json.loads(payload)
        return service(request).create(p['common'],p['character_ids'],p['outfits'],p['selection'],p['video_settings'],
                                      p['image_limit'],p['video_limit'],request_id)
    return perform(run)

@router.post('/api/studio/character-precision/{identifier}/story')
def story(request:Request,identifier:str,revision:int=Form(ge=1),consent:bool=Form(False)):
    return perform(lambda:service(request).write_story(identifier,revision,consent))

@router.post('/api/studio/character-precision/{identifier}/edit')
def edit(request:Request,identifier:str,revision:int=Form(ge=1),scenario:str=Form(max_length=60000),
         image_limit:str|None=Form(None,max_length=32)):
    return perform(lambda:service(request).edit(identifier,revision,json.loads(scenario),image_limit))

@router.post('/api/studio/character-precision/{identifier}/quote')
def quote(request:Request,identifier:str,revision:int=Form(ge=1),numbers:str=Form(max_length=80),regenerate:bool=Form(False)):
    return perform(lambda:service(request).quote(identifier,revision,json.loads(numbers),regenerate))

@router.post('/api/studio/character-precision/{identifier}/generate')
def generate(request:Request,identifier:str,quote_hash:str=Form(min_length=64,max_length=64),
             consent:bool=Form(False),reference_consent:bool=Form(False)):
    return perform(lambda:service(request).generate(identifier,quote_hash,consent,reference_consent))

@router.post('/api/studio/character-precision/{identifier}/reconcile')
def reconcile(request:Request,identifier:str,revision:int=Form(ge=1)):
    return perform(lambda:service(request).reconcile(identifier,revision))

@router.post('/api/studio/character-precision/{identifier}/confirm')
def confirm(request:Request,identifier:str,revision:int=Form(ge=1),number:int=Form(ge=1,le=12),
            version:int=Form(ge=1),reviewed:bool=Form(False)):
    return perform(lambda:service(request).confirm(identifier,revision,number,version,reviewed))

@router.post('/api/studio/character-precision/{identifier}/handoff')
def handoff(request:Request,identifier:str,revision:int=Form(ge=1)):
    return perform(lambda:service(request).handoff(identifier,revision))

@router.post('/api/studio/character-precision/{identifier}/revise-connection')
def revise_connection(request:Request,identifier:str,revision:int=Form(ge=1),request_id:str=Form(min_length=32,max_length=32)):
    return perform(lambda:service(request).revise_connection(identifier,revision,request_id))
