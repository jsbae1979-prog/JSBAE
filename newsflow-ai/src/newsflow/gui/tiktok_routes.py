"""Explicit account preparation/actions. Default production gate cannot be enabled by a form."""
import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from newsflow.oauth.tiktok_protocol import TikTokError

from .routes import go


class SecretSafeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def redacted(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default errors include the rejected input, possibly a client secret.
                raise HTTPException(422, "TikTok 입력 형식과 필수 항목을 확인하세요.") from None
        return redacted


router = APIRouter(route_class=SecretSafeRoute)


@router.post("/tiktok/client")
def save_client(request: Request, client_key: str = Form(max_length=128),
                client_secret: str = Form(max_length=256), port: int = Form(0, ge=0, le=65535)):
    try:
        request.app.state.tiktok.save_client(json.dumps({"client_key": client_key, "client_secret": client_secret, "port": port}))
    except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
        raise HTTPException(422, "TikTok Desktop 앱 설정과 Windows 보호 저장소를 확인하세요.") from None
    return go("/publishing/platforms#tiktok")


@router.post("/tiktok/connect")
def connect(request: Request, consent: bool = Form(False), account_id: int | None = Form(None, ge=1)):
    try:
        request.app.state.tiktok.begin(consent=consent, account_id=account_id)
    except TikTokError as error:
        raise HTTPException(403 if error.code == "blocked" else 422, str(error)) from None
    except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
        raise HTTPException(422, "TikTok 연결을 시작하지 못했습니다. 설정을 확인하세요.") from None
    return go("/publishing/platforms#tiktok")


@router.post("/tiktok/accounts/{account_id}/{action}")
def action(request: Request, account_id: int, action: str, consent: bool = Form(False)):
    if action not in {"cancel", "refresh", "revoke"}:
        raise HTTPException(404, "지원하지 않는 계정 작업입니다.")
    if consent is not True:
        raise HTTPException(422, "이번 계정 작업에 동의해 주세요.")
    try:
        service = request.app.state.tiktok
        if action == "cancel":
            service.cancel(account_id)
        else:
            getattr(service, action)(account_id, consent=True)
    except TikTokError as error:
        raise HTTPException(403 if error.code == "blocked" else 422, str(error)) from None
    except Exception:  # noqa: BLE001 - redact credentials and provider diagnostics
        raise HTTPException(422, "계정 작업 결과를 확인하지 못했습니다. 자동 재시도하지 않습니다.") from None
    return go("/publishing/platforms#tiktok")
