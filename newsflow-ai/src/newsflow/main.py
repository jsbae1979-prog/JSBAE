"""Application factory and loopback-only CLI."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from newsflow.gui.social_routes import router as social_router
from newsflow.publishing.analytics import AnalyticsService
from newsflow.publishing.calendar import PublishingCalendar
from newsflow.publishing.extensions import ExtendedPublishingService

from .autopilot.backend import PipelineBackend
from .autopilot.service import AutopilotCoordinator
from .config import Settings
from .db.models import AppSetting, IntelligenceRun, NewsSource, utcnow
from .db.session import make_engine, migrate, session_factory
from .gui.ai_settings_routes import router as ai_settings_router
from .gui.api_settings_routes import router as api_settings_router
from .gui.autopilot_routes import router as autopilot_router
from .gui.character_routes import router as character_router
from .gui.creation_routes import router as creation_router
from .gui.curation_routes import router as curation_router
from .gui.image_post_routes import router as image_post_router
from .gui.instagram_routes import router as instagram_router
from .gui.intelligence_routes import router as intelligence_router
from .gui.news_thumbnail_routes import router as news_thumbnail_router
from .gui.operations_routes import router as operations_router
from .gui.production_routes import router as production_router
from .gui.publishing_routes import router as publishing_router
from .gui.routes import router
from .gui.scheduler_routes import router as scheduler_router
from .gui.serpapi_routes import router as serpapi_router
from .gui.setup_routes import router as setup_router
from .gui.sources_routes import router as sources_router
from .gui.tiktok_routes import router as tiktok_router
from .gui.unified_publishing_routes import router as unified_publishing_router
from .gui.video_ai_routes import router as video_ai_router
from .gui.video_routes import router as video_router
from .gui.voice_routes import router as voice_router
from .gui.youtube_routes import router as youtube_router
from .intelligence.credentials import AIKeyStore, AnthropicKeyStore
from .intelligence.service import IntelligenceService
from .intelligence.settings import external_ready
from .news.collector import Collector
from .news.rss_adapter import PublicRSSAdapter, RSSAdapter
from .news.service import CollectionCoordinator, NewsService
from .news.thumbnails import ThumbnailService
from .oauth.instagram import InstagramConnectionService
from .oauth.lifecycle import expire_production_credentials, recover_production_lifecycle
from .oauth.production_vault import recover_credential_rotations
from .oauth.tiktok import TikTokConnectionService
from .oauth.youtube import YouTubeConnectionService
from .publishing.claude_cards import ClaudeCardService
from .publishing.image_delivery import HTTPSImageDelivery
from .publishing.image_generation import ImageGenerationService
from .publishing.image_posts import ImagePostService
from .publishing.instagram_live import InstagramPublishingService
from .publishing.live import LivePublishingService
from .publishing.unified import UnifiedPublishingService
from .scheduler.service import Scheduler
from .video.ai.contracts import VideoProvider
from .video.ai.keys import VideoAIKeyStore
from .video.ai.service import AIVideoCoordinator
from .video.service import VideoCoordinator


def _recover_intelligence_runs(sessions: sessionmaker[Session], data_dir: Path) -> None:
    """Do not interrupt intelligence owned by another active Autopilot worker."""
    try:
        with FileLock(str(data_dir / "autopilot.lock")).acquire(timeout=0), sessions.begin() as session:
            for run in session.scalars(select(IntelligenceRun).where(
                    IntelligenceRun.status == "running", IntelligenceRun.kind.not_in(["feed_image", "feed_card"]))):
                run.status, run.message, run.finished_at = (
                    "interrupted",
                    "이전 실행이 중단되었습니다. 명시적으로 다시 실행하세요.",
                    utcnow(),
                )
    except Timeout:
        return


def create_app(
    settings: Settings | None = None, adapter: RSSAdapter | None = None, video_provider: VideoProvider | None = None,
    *, automatic_start: bool = False,
) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.data_dir / "newsflow.db")
    migrate(engine)
    sessions = session_factory(engine)
    recover_credential_rotations(sessions)
    recover_production_lifecycle(sessions)
    expire_production_credentials(sessions)
    _recover_intelligence_runs(sessions, settings.data_dir)
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
    video = VideoCoordinator(sessions, settings.data_dir)
    video.recover()
    youtube = YouTubeConnectionService(sessions, settings.data_dir)
    youtube.recover()
    live_publishing = LivePublishingService(sessions, video.outputs, youtube)
    live_publishing.recover()
    tiktok = TikTokConnectionService(sessions, settings.data_dir)
    tiktok.recover()
    instagram = InstagramConnectionService(sessions, settings.data_dir)
    instagram.recover()
    instagram_publishing = InstagramPublishingService(sessions, video.outputs, instagram)
    instagram_publishing.recover()
    social_extensions = {name: ExtendedPublishingService(sessions, video.outputs, name) for name in ("tiktok", "facebook")}
    for extension in social_extensions.values():
        extension.recover()
    unified_publishing = UnifiedPublishingService(sessions, video.outputs, live_publishing, instagram_publishing, extensions=social_extensions)
    unified_publishing.recover()
    publishing_calendar = PublishingCalendar(sessions, unified_publishing)
    publishing_calendar.recover()
    social_analytics = AnalyticsService(sessions)
    ai_keys = AIKeyStore(settings.data_dir)
    api_keys = {"openai": ai_keys, "claude_api": AnthropicKeyStore(settings.data_dir)}
    image_generation = ImageGenerationService(sessions, settings.data_dir, ai_keys)
    claude_cards = ClaudeCardService(sessions, settings.data_dir, api_keys["claude_api"], image_generation)
    claude_cards.recover()
    image_generation.cards = claude_cards
    image_generation.recover()
    image_posts = ImagePostService(sessions, settings.data_dir, instagram,
                                   generation=image_generation, cards=claude_cards,
                                   delivery=HTTPSImageDelivery(sessions, settings.data_dir))
    image_posts.recover()
    autopilot_backend = PipelineBackend(
        sessions, settings.data_dir, coordinator, video,
        intelligence=IntelligenceService(sessions, None, ai_keys, api_key_stores=api_keys),
        ai_gate=lambda: external_ready(sessions, ai_keys),
    )
    autopilot = AutopilotCoordinator(sessions, settings.data_dir, autopilot_backend)
    autopilot.recover()
    scheduler = Scheduler(sessions, settings.data_dir, autopilot)
    # Phase 5D: optional AI video provider. Off by default; only tests/CI inject the Fake provider.
    video_ai = AIVideoCoordinator(sessions, settings.data_dir, video, VideoAIKeyStore(settings.data_dir), video_provider)
    autopilot_backend.ai_video = video_ai
    video_ai.on_complete = autopilot.attach_completed_ai
    if automatic_start:
        video_ai.recover()  # Local recovery only: never resume paid submissions/polling at Windows logon.
    else:
        video_ai.start()
    secret = settings.local_secret().encode()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler.start()
        publishing_calendar.start()
        try:
            yield
        finally:
            youtube.close()
            tiktok.close()
            instagram.close()
            publishing_calendar.close()
            scheduler.close()
            video_ai.close()
            autopilot.close()
            autopilot_backend.close()
            coordinator.close()
            video.close()
            engine.dispose()

    app = FastAPI(title="NewsFlow AI", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.config, app.state.sessions, app.state.coordinator = settings, sessions, coordinator
    from .character.service import CharacterService

    app.state.character = CharacterService(settings.data_dir, sessions, api_keys['claude_api'], video_keys=video_ai.keys)
    app.state.news_thumbnails = ThumbnailService(coordinator.service.collector.adapter)
    app.state.engine = engine
    app.state.video = video
    app.state.youtube = youtube
    app.state.tiktok = tiktok
    app.state.live_publishing = live_publishing
    app.state.instagram = instagram
    app.state.instagram_publishing = instagram_publishing
    app.state.unified_publishing = unified_publishing
    app.state.social_extensions = social_extensions
    app.state.publishing_calendar = publishing_calendar
    app.state.social_analytics = social_analytics
    app.state.video_ai = video_ai
    app.state.scheduler = scheduler
    app.state.autopilot = autopilot
    app.state.autopilot_backend = autopilot_backend
    app.state.ai_keys = ai_keys
    app.state.api_keys = api_keys
    app.state.claude_cards = claude_cards
    app.state.image_generation, app.state.image_posts = image_generation, image_posts
    from .creation.image_studio import ImageStudio
    app.state.image_studio = ImageStudio(sessions, settings.data_dir, image_generation)
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
            encoding = request.headers.get("content-type", "").split(";", 1)[0]
            character_upload = request.url.path in {'/character', '/image-studio/drafts'} and encoding == 'multipart/form-data'
            if encoding != "application/x-www-form-urlencoded" and not character_upload:
                return HTMLResponse("지원하지 않는 요청 형식입니다.", status_code=415)
            # Cache before form parsing so downstream FastAPI receives the same body.
            # Only the local image form accepts bounded base64 raster data.
            # Origin, form encoding, signed CSRF and CSP checks remain unchanged.
            limit = (10 * 1024 * 1024 + 65536 if character_upload else
                     8 * 1024 * 1024 if request.url.path == "/image-posts/create" else 65536)
            chunks, length = [], 0
            async for chunk in request.stream():
                length += len(chunk)
                if length > limit:
                    return HTMLResponse("요청이 너무 큽니다.", status_code=413)
                chunks.append(chunk)
            body = b"".join(chunks)
            request._body = body
            if character_upload:
                try:
                    async with request.form(max_files=1, max_fields=10, max_part_size=10*1024*1024) as form:
                        token = form.get('csrf_token', '')
                except (StarletteHTTPException, ValueError):
                    return HTMLResponse('PNG 파일 1개와 입력 항목을 확인하세요.', status_code=400)
            else:
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

    app.include_router(operations_router)
    app.include_router(scheduler_router)
    app.include_router(setup_router)
    app.include_router(autopilot_router)
    app.include_router(production_router)
    app.include_router(sources_router)
    app.include_router(ai_settings_router)
    app.include_router(api_settings_router)
    app.include_router(voice_router)
    app.include_router(router)
    app.include_router(intelligence_router)
    app.include_router(curation_router)
    app.include_router(image_post_router)
    app.include_router(serpapi_router)
    app.include_router(news_thumbnail_router)
    from newsflow.gui.cleanup_routes import router as cleanup_router

    app.include_router(cleanup_router)
    app.include_router(video_router)
    app.include_router(character_router)
    app.include_router(creation_router)
    app.include_router(video_ai_router)
    app.include_router(publishing_router)
    app.include_router(youtube_router)
    app.include_router(tiktok_router)
    app.include_router(instagram_router)
    app.include_router(unified_publishing_router)
    app.include_router(social_router)
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    return app


def run(*, automatic_data_dir: Path | None = None) -> None:
    import uvicorn

    from .paths import prepare_data_dir
    from .runtime import PortInUseError, reserve_socket, runtime_logger

    logger = None
    try:
        settings = Settings(data_dir=automatic_data_dir, host="127.0.0.1", port=8765) if automatic_data_dir else Settings.from_env()
        prepare_data_dir(settings.data_dir)
        logger = runtime_logger(settings.data_dir)
        with (
            FileLock(str(settings.data_dir / f"server-{settings.port}.lock")).acquire(timeout=0),
            FileLock(str(settings.data_dir / "migration.lock")).acquire(timeout=0),
            reserve_socket(settings.host, settings.port) as listener,
        ):
            app = create_app(settings, automatic_start=automatic_data_dir is not None)
            logger.info("server_start port=%d", settings.port)
            if automatic_data_dir:
                from .operations.autorun import record
                record(automatic_data_dir, "running")
            print(f"GUI 주소: http://{settings.host}:{settings.port} · 종료: Ctrl+C", flush=True)
            # Uvicorn re-raises captured signals after shutdown. Windows' default
            # SIGBREAK terminates before our finally block; treat it like Ctrl+C.
            previous_break = None
            if hasattr(signal, "SIGBREAK"):
                previous_break = signal.signal(signal.SIGBREAK, signal.default_int_handler)
            try:
                uvicorn.Server(
                    uvicorn.Config(
                        app, host=settings.host, port=settings.port, log_level="warning", access_log=False,
                        loop="newsflow.runtime:windows_server_loop" if sys.platform == "win32" else "auto",
                    )
                ).run(sockets=[listener])
            finally:
                if previous_break is not None:
                    signal.signal(signal.SIGBREAK, previous_break)
                app.state.scheduler.close()
                app.state.autopilot.close()
                app.state.autopilot_backend.close()
                app.state.coordinator.close()
                app.state.video.close()
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
