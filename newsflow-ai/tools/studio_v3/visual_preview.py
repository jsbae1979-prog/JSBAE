import datetime
import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

R = Path(os.environ["NEWSFLOW_VISUAL_ROOT"]).resolve()
D = Path(__file__).resolve().parents[2] / "frontend/dist"
assert (D / "index.html").is_file()
now = datetime.datetime.now(datetime.UTC).isoformat()
projects = []
for i, (title, kind, status, img) in enumerate(
    [
        ("AI와 일상의 변화 · 합성 뉴스", "news", "success", 2),
        ("느긋한 오후, 캐릭터 이야기 · 합성", "character", "needs_script", 0),
        ("지속 가능한 도시 이야기 · 합성 이미지", "image", "success", 3),
        ("새로운 기술을 만나는 일상 · 합성 이미지", "image", "unknown", 10),
    ]
):
    projects.append(
        {
            "id": f"{kind}:{i + 1}",
            "title": title,
            "kind": kind,
            "technicalStatus": status,
            "contentReviewStatus": "review_required",
            "publishApprovalStatus": "separate_approval_required",
            "updatedAt": now,
            "href": "/create" if kind == "news" else "/character" if kind == "character" else "/image-studio",
            "thumbnailUrl": f"/studio/assets/design-art-{img}.webp",
            "mediaUrl": None,
            "sourceLabel": "설계용 합성 프로젝트 일러스트",
        }
    )
model = {
    "schemaVersion": 1,
    "dataOrigin": "development-fixtures",
    "projects": projects,
    "stats": {"running": 0, "ready": 2, "publishDrafts": 0, "total": 4},
    "today": {"done": 2, "running": 0, "waiting": 1, "failed": 0, "unknown": 1, "total": 4},
    "services": [
        {"id": n, "label": l, "configured": False, "verified": False, "href": "/settings"}
        for n, l in [
            ("openai", "OpenAI"),
            ("claude", "Claude"),
            ("elevenlabs", "ElevenLabs"),
            ("higgsfield", "Higgsfield"),
        ]
    ],
    "upcoming": [],
    "upcomingStatus": "not-connected",
    "activity": [{"title": p["title"], "at": now, "href": p["href"]} for p in projects[:3]],
}


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(D), **kwargs)

    def end_headers(self):
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self';script-src 'self';style-src 'self';img-src 'self';frame-ancestors 'none';base-uri 'none';form-action 'self'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.headers.get("Host") != "127.0.0.1:18765" or self.path.startswith("http"):
            self.send_error(403)
            return
        if self.path == "/api/studio/workspace":
            content = json.dumps(model, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if self.path in ["/studio/", "/studio/dashboard", "/studio/create"]:
            self.path = "/index.html"
        elif self.path.startswith("/studio/assets/"):
            self.path = self.path[7:]
        else:
            self.send_error(404, "Legacy engine not connected in this visual-only preview")
            return
        super().do_GET()

    def do_POST(self):
        self.send_error(405, "Read-only visual preview")


sys.path.insert(0, str(R))
import step13_guard

step13_guard.install()
server = ThreadingHTTPServer(("127.0.0.1", 18765), Handler)
(R / "visual-server-safe.json").write_text(
    json.dumps(
        {
            "pid": os.getpid(),
            "port": 18765,
            "kind": "React visual fixture only",
            "product_engine_started": False,
            "Guard": True,
            "external_calls": 0,
        },
        indent=2,
    )
)
try:
    server.serve_forever()
finally:
    server.server_close()
