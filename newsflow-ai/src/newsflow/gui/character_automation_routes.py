"""Character profile/topic commands; paid work is explicit, budgeted, and injected in tests."""
from __future__ import annotations
import json
from fastapi import APIRouter, Form, HTTPException, Request
from newsflow.character.schema import CharacterError, clean_topic
from newsflow.intelligence.provider import ProviderError
from newsflow.publishing.service import PublishingError

router = APIRouter()


def registry(request):
    from newsflow.character.registry import CharacterRegistry
    return CharacterRegistry(request.app.state.config.data_dir, request.app.state.image_studio)


def topics(request):
    from newsflow.character.topics import TopicStore
    return TopicStore(request.app.state.config.data_dir)


def authoring(request):
    state = request.app.state
    if getattr(state, 'character_authoring', None) is not None:
        return state.character_authoring
    from newsflow.character.authoring import AuthoringAI
    from newsflow.intelligence.api_settings import APIBudgetService
    return AuthoringAI(keys=state.api_keys, budget=APIBudgetService(state.sessions))


def selected_provider(model):
    from newsflow.intelligence.api_providers import API_MODELS
    values = [provider for provider, models in API_MODELS.items() if model in models]
    if len(values) != 1:
        raise ValueError('model')
    return values[0]


def public_problem():
    # Never echo supplier exceptions, user text, secrets, or local paths.
    return HTTPException(409, '입력·저장 상태·API 승인 한도를 확인하세요. 결과가 불명확하면 자동 재요청하지 않습니다.')


@router.get('/api/studio/characters/profiles')
def profiles_list(request: Request):
    try:
        return {'profiles': registry(request).list()}
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/profiles/save')
def profile_save(request: Request, profile: str = Form(..., max_length=16000),
                 asset: str = Form(..., max_length=80), identifier: str = Form('', max_length=48),
                 revision: int = Form(0)):
    try:
        return registry(request).save(json.loads(profile), asset,
            identifier=identifier or None, expected_revision=revision or None)
    except (ValueError, TypeError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/profiles/{identifier}/delete')
def profile_delete(request: Request, identifier: str, revision: int = Form(...), consent: bool = Form(False)):
    if not consent:
        raise HTTPException(422, '캐릭터 등록 삭제를 확인하세요. 이전 제작물은 보존됩니다.')
    try:
        registry(request).delete(identifier, revision)
        return {'deleted': True, 'historicalJobsPreserved': True}
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/profiles/analyze')
def profile_analyze(request: Request, asset: str = Form(..., max_length=80),
                    model: str = Form(..., max_length=180), request_id: str = Form(..., max_length=64),
                    consent: bool = Form(False)):
    service = None
    try:
        content = request.app.state.image_studio.asset(asset).read_bytes()
        provider = selected_provider(model)
        service = authoring(request)
        return service.analyze(content, provider=provider, model=model,
                               request_id=request_id, consent=consent)
    except (ValueError, OSError, CharacterError, ProviderError, PublishingError) as error:
        from newsflow.character.authoring import analysis_failure_message
        raise HTTPException(409, analysis_failure_message(error, getattr(service, 'last_failure', None))) from None


@router.get('/api/studio/characters/profiles/{identifier}/topics')
def topics_list(request: Request, identifier: str):
    try:
        registry(request).get(identifier)
        return {'topics': topics(request).list(identifier)}
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/profiles/{identifier}/topics/generate')
def topics_generate(request: Request, identifier: str, count: int = Form(10, ge=1, le=50),
                    model: str = Form(..., max_length=180), request_id: str = Form(..., max_length=64),
                    consent: bool = Form(False)):
    try:
        profile = registry(request).get(identifier)
        store = topics(request)
        existing = [row['topic'] for row in store.list(identifier)]
        rows = authoring(request).topics(profile, count, existing, provider=selected_provider(model),
                                        model=model, request_id=request_id, consent=consent)
        store.save_generated(identifier, rows, count)
        return {'topics': store.list(identifier)}
    except (ValueError, OSError, CharacterError, ProviderError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/profiles/{identifier}/topics/manual')
def topic_manual(request: Request, identifier: str, topic: str = Form(..., max_length=60),
                 category: str = Form('', max_length=10)):
    try:
        registry(request).get(identifier)
        return topics(request).add(identifier, clean_topic(topic,60), category=category)
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/profiles/{identifier}/topics/import')
def topics_import(request: Request, identifier: str, content: str = Form(..., max_length=48000)):
    try:
        registry(request).get(identifier)
        topics(request).import_csv(identifier, content)
        return {'topics': topics(request).list(identifier)}
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/profiles/{identifier}/topics/{topic_id}/status')
def topic_status(request: Request, identifier: str, topic_id: str,
                 status: str = Form(..., max_length=16)):
    try:
        registry(request).get(identifier)
        topics(request).update_status(identifier, topic_id, status)
        return {'topics': topics(request).list(identifier)}
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/{job_id}/script')
def script_edit(request: Request, job_id: str, script: str = Form(..., max_length=48000),
                expected_hash: str = Form(..., max_length=64)):
    try:
        request.app.state.character.edit_episode(job_id, json.loads(script), expected_hash)
        return {'id': job_id, 'saved': True, 'approvalInvalidated': True}
    except (ValueError, OSError, CharacterError, ProviderError):
        raise public_problem() from None


def episode_queue(request):
    from newsflow.character.queue import EpisodeQueue
    service = request.app.state.character
    service.authoring = authoring(request)
    return EpisodeQueue(request.app.state.config.data_dir, service, registry(request), topics(request))


@router.get('/api/studio/characters/queues')
def queues_list(request: Request):
    try:
        return {'queues': episode_queue(request).list()}
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.get('/api/studio/characters/queues/{identifier}')
def queue_read(request: Request, identifier: str):
    try:
        return episode_queue(request).get(identifier)
    except (ValueError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/queues/create')
def queue_create(request: Request, character_id: str = Form(..., max_length=48),
                 topic_ids: str = Form(..., max_length=4000), settings: str = Form(..., max_length=16000),
                 episode_limit: str = Form(...), request_id: str = Form(..., max_length=64)):
    try:
        return episode_queue(request).create(character_id, json.loads(topic_ids), json.loads(settings),
                                             episode_limit, request_id)
    except (ValueError, TypeError, OSError, CharacterError, PublishingError):
        raise public_problem() from None


@router.post('/api/studio/characters/queues/{identifier}/scripts')
def queue_scripts(request: Request, identifier: str, consent: bool = Form(False)):
    try:
        return episode_queue(request).run_scripts(identifier, consent=consent)
    except (ValueError, OSError, CharacterError, ProviderError):
        raise public_problem() from None


@router.post('/api/studio/characters/queues/{identifier}/delete')
def queue_delete(request: Request, identifier: str, consent: bool = Form(False)):
    if not consent:
        raise HTTPException(422, '대기열 삭제를 확인하세요. 작업과 영상은 보존됩니다.')
    try:
        return episode_queue(request).delete(identifier, consent=True)
    except CharacterError as error:
        detail = '실행 중인 대기열은 삭제할 수 없습니다.' if error.code == 'busy' else '대기열을 삭제하지 못했습니다.'
        raise HTTPException(409, detail) from None
    except (ValueError, OSError, PublishingError):
        raise HTTPException(409, '대기열을 삭제하지 못했습니다.') from None


@router.post('/api/studio/characters/queues/{identifier}/approve-videos')
def queue_approve(request: Request, identifier: str, approvals: str = Form(..., max_length=16000),
                  max_total_usd: str = Form(...), consent: bool = Form(False)):
    try:
        return episode_queue(request).approve_videos(identifier, json.loads(approvals), max_total_usd, consent=consent)
    except (ValueError, TypeError, OSError, CharacterError, ProviderError):
        raise public_problem() from None


@router.post('/api/studio/characters/queues/{identifier}/advance')
def queue_advance(request: Request, identifier: str, consent: bool = Form(False)):
    try:
        return episode_queue(request).advance_videos(identifier, consent=consent)
    except (ValueError, OSError, CharacterError, ProviderError):
        raise public_problem() from None


@router.post('/api/studio/characters/{job_id}/regeneration/quote')
def regeneration_quote(request: Request, job_id: str, position: int = Form(..., ge=1, le=60), consent: bool = Form(False)):
    try:
        request.app.state.character.prepare_regeneration(job_id, position, consent=consent)
        return {'id':job_id,'state':request.app.state.character.read(job_id)['state']}
    except (ValueError, OSError, CharacterError, ProviderError):
        raise public_problem() from None


@router.post('/api/studio/characters/{job_id}/regeneration/submit')
def regeneration_submit(request: Request, job_id: str, quote_hash: str = Form(..., max_length=64), consent: bool = Form(False)):
    try:
        request.app.state.character.regenerate_scenes(job_id, consent=consent, quote_hash=quote_hash)
        return {'id':job_id,'state':request.app.state.character.read(job_id)['state']}
    except (ValueError, OSError, CharacterError, ProviderError):
        raise public_problem() from None


@router.post('/api/studio/characters/{job_id}/regeneration/cancel')
def regeneration_cancel(request: Request, job_id: str, quote_hash: str = Form(..., max_length=64)):
    try:
        request.app.state.character.cancel_regeneration(job_id, quote_hash=quote_hash)
        return {'id':job_id,'state':request.app.state.character.read(job_id)['state']}
    except (ValueError, OSError, CharacterError):
        raise public_problem() from None
