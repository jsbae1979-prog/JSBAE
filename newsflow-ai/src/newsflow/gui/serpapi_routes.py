"""SerpApi key registration is independent from collection and AI use approval."""
from fastapi import APIRouter, Form, HTTPException, Request
from filelock import FileLock, Timeout

from newsflow.intelligence.credentials import CredentialError
from newsflow.news.curator import Curator
from newsflow.news.serpapi import SerpApiError, SerpApiKeys
from newsflow.news.serpapi_settings import context, save
from newsflow.news.service import CollectionBusy

from .routes import go

router = APIRouter()


def keys(request):
    return getattr(request.app.state, "serpapi_keys", None) or SerpApiKeys(request.app.state.config.data_dir)


def connection_context(request):
    return context(request.app.state.sessions, keys(request))


@router.post("/serpapi/settings")
def settings(request: Request, api_key: str = Form(""), approved: bool = Form(False)):
    try:
        with FileLock(str(request.app.state.coordinator.lock_path)).acquire(timeout=0):
            save(request.app.state.sessions, keys(request), key=api_key, approved=approved)
    except (CredentialError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    except Timeout:
        raise HTTPException(409, "자료 수집 중입니다. 완료 후 키 설정을 저장하세요.") from None
    return go("/simple-settings?saved=serpapi#serpapi")


@router.post("/news/curation/serpapi")
def collect(request: Request, request_token: str = Form(max_length=32), consent: bool = Form(False),
            collection_policy: str = Form("korea_v1", max_length=30), maximum_requests: int = Form(1)):
    from newsflow.news.global_collection import GLOBAL_POLICY, plan_context

    expected = plan_context()["maximum_requests"] if collection_policy == GLOBAL_POLICY else 1
    if maximum_requests != expected:
        raise HTTPException(422, "예상 조회 횟수가 변경됐습니다. 수집 범위와 동의를 다시 확인해 주세요.")
    try:
        Curator(request.app.state.coordinator).serpapi(keys(request), request_token, consent=consent,
                                                     adapter=getattr(request.app.state, "serpapi_adapter", None),
                                                     policy=collection_policy)
    except (ValueError, SerpApiError) as exc:
        raise HTTPException(422, str(exc)) from None
    except CollectionBusy:
        raise HTTPException(409, "다른 뉴스 수집이 진행 중입니다.") from None
    return go("/news#curation")
