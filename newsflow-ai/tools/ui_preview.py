"""Isolated synthetic UI preview. Never use this launcher with operational data.

Creates a NEW directory only; loopback HTTP, Fake RSS, no credentials, no login or
publishing. Outbound sockets and subprocesses other than local FFmpeg are denied.
This is a development/review tool, not a Linux distribution or production mode.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import socket
import subprocess
import tempfile
from contextvars import ContextVar
from pathlib import Path
from urllib.parse import parse_qs

import uvicorn
from PIL import Image, ImageDraw, ImageFont

from newsflow.config import Settings
from newsflow.db.models import (
    AppSetting,
    AudioTrack,
    AutopilotJob,
    ContentDraft,
    IntelligenceRun,
    NewsArticle,
    NewsSource,
    RenderJob,
    Scene,
    SubtitleTrack,
    VideoProject,
)
from newsflow.gui.routes import templates
from newsflow.intelligence.provider import FakeProvider, Options
from newsflow.main import create_app
from newsflow.news.rss_adapter import FakeRSSAdapter


def install_boundary() -> None:
    for name in list(os.environ):
        if name.startswith("NEWSFLOW_") or name in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY"}:
            os.environ.pop(name, None)
    original_connect, original_popen = socket.socket.connect, subprocess.Popen
    original_resolve = socket.getaddrinfo

    def resolve(host, *args, **options):
        if host not in {None, "127.0.0.1", "::1", "localhost"}:
            raise OSError("UI preview denies external DNS")
        return original_resolve(host, *args, **options)

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1"}:
            raise OSError("UI preview denies outbound network")
        return original_connect(sock, address)

    def popen(args, *values, **options):
        if not isinstance(args, (list, tuple)) or Path(str(args[0])).stem not in {"ffmpeg", "ffprobe"}:
            raise OSError("UI preview denies authentication, voice and other processes")
        if options.get("shell"):
            raise OSError("UI preview denies shell commands")
        return original_popen(args, *values, **options)

    socket.socket.connect = connect
    socket.getaddrinfo = resolve
    subprocess.Popen = popen


def seed(app, root: Path) -> None:
    titles = ["도시를 바꾸는 작은 기술, 우리 일상은 어떻게 달라질까요?", "우주 탐사와 새로운 발견",
              ("문화와 생활을 잇는 오늘의 이야기, 충분히 긴 한글 제목도 읽고 편집할 수 있는지 확인하는 합성 자료입니다. " * 2)[:98]]
    with app.state.sessions.begin() as session:
        session.add(AppSetting(key="video_default_voice", value="offline-silence"))
        source = NewsSource(name="데모 자료", url="https://example.com/demo-rss", enabled=False)
        session.add(source)
        session.flush()
        for index, title in enumerate(titles):
            evidence = {"articles": [{"id": index + 1, "title": title, "summary": "실제 보도가 아닌 화면 검증용 합성 자료입니다.",
                "publisher": "데모 자료", "sources": [{"publisher": "데모 자료", "url": f"https://example.com/demo-{index}"}]}]}
            script = FakeProvider().complete(evidence, 30, Options(model="offline"))
            script["title"] = title
            if index == 2:
                script["summary"] = ("긴 한글 요약을 검토하기 위한 합성 자료입니다. 실제 보도가 아닙니다. " * 9)[:450]
                script["scenes"][0]["narration"] = ("긴 대본의 편집과 줄바꿈만 확인하는 합성 문장입니다. " * 12)[:390]
            session.add(NewsArticle(title=title, url=f"https://example.com/demo-{index}",
                                    canonical_url=f"https://example.com/demo-{index}", source_id=source.id, publisher="데모 자료",
                                    summary=evidence["articles"][0]["summary"], category="it"))
            run = IntelligenceRun(kind="script", provider="offline", status="success", options={"model": "offline"},
                                  evidence=evidence, result=script, message="합성 데모")
            session.add(run)
            session.flush()
            draft = ContentDraft(run_id=run.id, duration=30, content=script, sources=evidence)
            session.add(draft)
            session.flush()
            project = VideoProject(draft_id=draft.id, title=title, duration=30, snapshot=script, sources=evidence)
            session.add(project)
            session.flush()
            name = f"video-{index + 1:032x}.mp4"
            path = app.state.video.outputs / name
            path.parent.mkdir(parents=True, exist_ok=True)
            # A clearly synthetic cover, not news content or a product render-quality change.
            poster = root / f"demo-cover-{index}.png"
            canvas = Image.new("RGB", (1080, 1920), (24, 31, 49))
            draw = ImageDraw.Draw(canvas)
            colors = ["#536cb2", "#8272aa", "#629690"]
            draw.ellipse((100, 500, 1450, 1850), fill=colors[index])
            draw.ellipse((-400, 1100, 900, 2400), fill="#222839")
            draw.rounded_rectangle((80, 120, 480, 200), radius=12, fill="#222839")
            font_path = Path("C:/Windows/Fonts/malgun.ttf") if os.name == "nt" else Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
            font = ImageFont.truetype(str(font_path), 64) if font_path.is_file() else ImageFont.load_default(size=64)
            small = ImageFont.truetype(str(font_path), 32) if font_path.is_file() else ImageFont.load_default(size=32)
            draw.text((105, 135), "UI DEMO / 30s", font=small, fill="#e9e8ff")
            cover_titles = ["도시를 바꾸는\n작은 기술", "우주,\n다음 이야기", "일상에\n문화를 더하다"]
            draw.multiline_text((90, 340), cover_titles[index], font=font, fill="#ffffff", spacing=22)
            draw.text((90, 1720), "합성 자료 · 무음 · 실제 보도 아님", font=small, fill="#ffffff")
            canvas.save(poster)
            # Real decodable media, labelled demo; no article images/downloads/voice.
            subprocess.run(["ffmpeg", "-v", "error", "-loop", "1", "-framerate", "10", "-i", str(poster),
                            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "30", "-c:v", "libx264",
                            "-threads", "2", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-movflags", "+faststart", str(path)], check=True)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            session.add(RenderJob(project_id=project.id, status="success", progress=100, output_name=name,
                                  message="데모 · 무음 검토영상", metadata_json={"playable": True, "sha256": digest}))
            session.add(AudioTrack(project_id=project.id, provider="offline", voice="offline-silence", status="success"))
            session.add(SubtitleTrack(project_id=project.id, font_size=48, position_y=1280, cues=[]))
            for position, scene in enumerate(script["scenes"]):
                session.add(Scene(project_id=project.id, position=position, start_ms=position * 10000,
                                  end_ms=(position + 1) * 10000, narration=scene["narration"], caption=scene["caption"]))
        session.add(AutopilotJob(id="e" * 32, mode="guided", source="sample", duration=30, platform="youtube",
                                status="failed", current_stage="render", progress=70, message="데모 오류 · 음성 준비를 확인해 주세요.",
                                error_code="voice_unavailable"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="New absolute directory, never existing user data")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--empty", action="store_true")
    parser.add_argument("--templates", type=Path, help="Optional read-only baseline templates for before screenshots")
    args = parser.parse_args()
    if (not args.data_dir.is_absolute() or args.data_dir.exists()
            or not args.data_dir.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())):
        parser.error("Use a NEW absolute directory under the system TEMP folder; existing data is never opened.")
    install_boundary()
    app = create_app(Settings(data_dir=args.data_dir, port=args.port), FakeRSSAdapter({}))
    if not args.empty:
        seed(app, args.data_dir)
    if args.templates:
        from jinja2 import FileSystemLoader
        templates.env.loader = FileSystemLoader(str(args.templates))
    templates.env.globals["ui_demo"] = True
    scenario = ContextVar("ui_scenario", default="")
    original_for_video = app.state.unified_publishing.for_video

    def synthetic_outcomes(render_id):
        """Presentation fixtures only, not published jobs or Fake API successes."""
        state = scenario.get()
        if state not in {"partial", "unknown", "failed"}:
            return original_for_video(render_id)
        outcomes = ("complete", "unknown" if state == "unknown" else "failed") if state != "failed" else ("failed", "failed")
        return {"id": 0, "metadata": {}, "accounts": {"youtube": 1, "instagram": 2}, "locked": True,
                "can_execute": False, "checks": [], "targets": [
                    {"platform": platform, "account_label": "데모 계정 · 실제 연결 아님", "status": outcome,
                     "message": "합성 UI 상태입니다. 실제 전송은 0건입니다.", "url": None, "can_continue": False}
                    for platform, outcome in zip(("youtube", "instagram"), outcomes)]}

    app.state.unified_publishing.for_video = synthetic_outcomes

    @app.middleware("http")
    async def deny_live_actions(request, call_next):
        from fastapi.responses import JSONResponse
        safe = ("/ai/drafts/", "/autopilot/quick-start", "/autopilot/jobs/", "/simple-settings", "/production/preferences")
        if request.method == "POST":
            allowed = request.url.path.startswith(safe)
            if request.url.path in {"/ai/analyze", "/ai/generate", "/autopilot/quick-start", "/video/render"}:
                fields = parse_qs((await request.body()).decode("utf-8"), max_num_fields=1000)
                if request.url.path == "/video/render":
                    allowed = fields.get("voice") == ["offline-silence"] and not any(fields.get("images", []))
                else:
                    allowed = (fields.get("source") == ["sample"] if request.url.path == "/autopilot/quick-start"
                               else fields.get("provider") == ["offline"])
            if not allowed:
                return JSONResponse({"detail": "데모에서는 인증·외부 연결·게시를 실행하지 않습니다."}, status_code=403)
        token = scenario.set(request.query_params.get("demo", ""))
        try:
            return await call_next(request)
        finally:
            scenario.reset(token)

    print("DEMO ONLY · synthetic data · external network/authentication/publishing blocked", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
