"""Application factory and loopback-only CLI."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db.models import AppSetting, NewsSource
from .db.session import make_engine, migrate, session_factory
from .gui.routes import router
from .news.collector import Collector
from .news.rss_adapter import PublicRSSAdapter, RSSAdapter
from .news.service import CollectionCoordinator, NewsService


def create_app(settings: Settings | None = None, adapter: RSSAdapter | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.data_dir / "newsflow.db")
    migrate(engine)
    sessions = session_factory(engine)
    with sessions.begin() as session:
        if not session.get(AppSetting, "request_timeout"):
            session.add(AppSetting(key="request_timeout", value=str(settings.request_timeout)))
        if not session.scalar(select(NewsSource).limit(1)):
            session.add(
                NewsSource(
                    name="Google News · 한국",
                    enabled=False,
                    url="https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",
                )
            )
    coordinator = CollectionCoordinator(
        NewsService(sessions, Collector(adapter or PublicRSSAdapter())), settings.data_dir
    )
    coordinator.recover_interrupted()
    secret = settings.local_secret().encode()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        coordinator.close()
        engine.dispose()

    app = FastAPI(title="NewsFlow AI", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config, app.state.sessions, app.state.coordinator = settings, sessions, coordinator
    app.state.engine = engine
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])

    def valid(token: str) -> bool:
        if not re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{64}", token):
            return False
        nonce, signature = token.split(".", 1)
        return hmac.compare_digest(signature, hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest())

    @app.middleware("http")
    async def security(request: Request, call_next):
        cookie = request.cookies.get("newsflow_csrf", "")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected_origin = str(request.base_url).rstrip("/")
            if (origin and origin != expected_origin) or request.headers.get(
                "sec-fetch-site"
            ) == "cross-site":
                return HTMLResponse("외부 사이트에서 요청할 수 없습니다.", status_code=403)
            if not valid(cookie):
                return HTMLResponse("보안 토큰이 필요합니다.", status_code=403)
            if (
                request.headers.get("content-type", "").split(";", 1)[0]
                != "application/x-www-form-urlencoded"
            ):
                return HTMLResponse("지원하지 않는 요청 형식입니다.", status_code=415)
            # Cache before form parsing so downstream FastAPI receives the same body.
            body = await request.body()
            if len(body) > 65536:
                return HTMLResponse("요청이 너무 큽니다.", status_code=413)
            form = await request.form()
            token = form.get("csrf_token", "")
            if (
                not isinstance(token, str)
                or not valid(cookie)
                or not hmac.compare_digest(cookie.encode(), token.encode())
            ):
                return HTMLResponse(
                    "보안 토큰이 없거나 만료되었습니다. 화면을 새로고침하세요.", status_code=403
                )
        if not valid(cookie):
            nonce = secrets.token_hex(32)
            cookie = nonce + "." + hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()
        request.state.csrf = cookie
        response = await call_next(request)
        response.set_cookie("newsflow_csrf", cookie, httponly=True, samesite="strict", secure=False)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    return app


def run() -> None:
    import uvicorn
    from filelock import FileLock, Timeout

    from .paths import prepare_data_dir
    from .runtime import PortInUseError, reserve_socket, runtime_logger

    logger = None
    try:
        settings = Settings.from_env()
        prepare_data_dir(settings.data_dir)
        logger = runtime_logger(settings.data_dir)
        with (
            FileLock(str(settings.data_dir / f"server-{settings.port}.lock")).acquire(timeout=0),
            FileLock(str(settings.data_dir / "migration.lock")).acquire(timeout=0),
            reserve_socket(settings.host, settings.port) as listener,
        ):
            app = create_app(settings)
            logger.info("server_start port=%d", settings.port)
            print(f"GUI 주소: http://{settings.host}:{settings.port} · 종료: Ctrl+C", flush=True)
            try:
                uvicorn.Server(
                    uvicorn.Config(
                        app, host=settings.host, port=settings.port, log_level="warning", access_log=False
                    )
                ).run(sockets=[listener])
            finally:
                app.state.coordinator.close()
                app.state.engine.dispose()
                logger.info("server_stop")
    except (PortInUseError, Timeout):
        if logger:
            logger.error("server_port_or_instance_conflict")
        print("이미 실행 중이거나 지정 포트를 사용할 수 없습니다. 기존 실행을 종료하세요.", flush=True)
        raise SystemExit(1) from None
    except (ValueError, OSError):
        if logger:
            logger.error("server_configuration_or_path_error")
        print("실행 설정 또는 데이터 폴더 권한을 확인하세요. 비밀값은 출력하지 않습니다.", flush=True)
        raise SystemExit(1) from None
    except Exception:  # noqa: BLE001 -- startup errors must not expose secrets in a traceback
        if logger:
            logger.error("server_startup_or_runtime_error")
        print("서버 실행 오류입니다. 실행 로그와 README를 확인하세요.", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
