"""Read-only task cards over existing coordinator, analysis, draft and render records."""

from __future__ import annotations

from sqlalchemy import select

from newsflow.db.models import AudioTrack, ContentDraft, IntelligenceRun, NewsArticle, RenderJob, VideoProject

from .production_context import context_for_run

PROVIDERS = {"offline": "Offline", "openai": "OpenAI API", "claude_code": "Claude Code", "codex": "Codex"}
VOICES = {"offline": "무음", "windows": "Windows SAPI", "supertonic": "Supertonic 3", "elevenlabs": "ElevenLabs"}


def run_label(run: IntelligenceRun | None, planned: str | None = None) -> str:
    if run is None:
        return "아직 실행 전" + (f" · 예정 {PROVIDERS.get(planned, planned)}" if planned else "")
    suffix = {"success": "사용", "running": "진행 중", "failed": "실패", "interrupted": "중단"}.get(run.status, "확인 필요")
    return f"{PROVIDERS.get(run.provider, run.provider)} · {suffix}"


def voice_label(audio: AudioTrack | None, planned: str | None = None) -> str:
    if audio:
        name = VOICES.get(audio.provider, audio.provider)
        return f"{name} · {audio.voice} · {'사용' if audio.status == 'success' else '확인 필요'}"
    return f"아직 생성 전 · 선택 {planned}" if planned else "아직 생성 전"


def task_rows(request, snapshots: list[dict] | None = None) -> list[dict]:
    snapshots = snapshots if snapshots is not None else request.app.state.autopilot.list_jobs(100)
    with request.app.state.sessions() as session:
        drafts = {d.id: d for d in session.scalars(select(ContentDraft).order_by(ContentDraft.id.desc()).limit(100))}
        for draft in session.scalars(select(ContentDraft).where(ContentDraft.id.in_(
                [item["content_draft_id"] for item in snapshots if item.get("content_draft_id")]))):
            drafts[draft.id] = draft
        runs = {r.id: r for r in session.scalars(select(IntelligenceRun).order_by(IntelligenceRun.id.desc()).limit(200))}
        referenced = {draft.run_id for draft in drafts.values()}
        referenced.update(item[key] for item in snapshots for key in ("analysis_run_id", "script_run_id") if item.get(key))
        for run in session.scalars(select(IntelligenceRun).where(IntelligenceRun.id.in_(referenced))):
            runs[run.id] = run
        articles = {a.id: a for a in session.scalars(select(NewsArticle).where(NewsArticle.id.in_(
            [item["article_id"] for item in snapshots if item.get("article_id")])))}
        projects = {p.id: p for p in session.scalars(select(VideoProject).where(VideoProject.draft_id.in_(drafts)))}
        renders = list(session.scalars(select(RenderJob).where(RenderJob.project_id.in_(projects))
                                       .order_by(RenderJob.id.desc())))
        audios = {a.project_id: a for a in session.scalars(select(AudioTrack).where(AudioTrack.project_id.in_(projects)))}
        render_by_id = {r.id: r for r in renders}
        latest_by_draft = {}
        for render in renders:
            project = projects.get(render.project_id)
            if project:
                latest_by_draft.setdefault(project.draft_id, render)
        used_drafts, used_runs, used_renders = set(), set(), set()
        rows = []
        for item in snapshots:
            draft = drafts.get(item.get("content_draft_id"))
            article = articles.get(item.get("article_id"))
            analysis = runs.get(item.get("analysis_run_id"))
            script = runs.get(item.get("script_run_id") or (draft.run_id if draft else None))
            render = render_by_id.get(item.get("render_job_id"))
            used_drafts.add(draft.id if draft else None)
            used_runs.update(r.id for r in (analysis, script) if r)
            used_renders.add(render.id if render else None)
            status = item["status"]
            stage = item["current_stage"]
            if status == "completed":
                label, action = "완료", "완성 영상 보기"
            elif status in {"failed", "interrupted", "cancelled"}:
                label, action = "조치 필요", "멈춘 이유와 복구 방법 확인"
            elif status == "waiting_review":
                label, action = {
                    "select": ("준비 중", "영상으로 만들 뉴스 선택"),
                    "script": ("대본 검토 필요", "대본과 원문 확인 후 제작"),
                    "validate": ("최종 확인 필요", "영상 시청 후 보관"),
                }.get(stage, ("조치 필요", "작업 확인"))
            else:
                label, action = ("영상 제작 중", "제작 진행 확인") if stage == "render" else ("준비 중", "진행 상황 확인")
            provider = run_label(script or analysis, item["ai_mode"])
            if analysis and script and analysis.provider != script.provider:
                provider = f"분석 {run_label(analysis)} / 대본 {run_label(script)}"
            rows.append({
                "id": "auto:" + item["id"], "kind": "auto", "title": draft.content.get("title", "") if draft else
                article.title if article else "제작할 뉴스를 준비하고 있어요", "status": status,
                "status_label": label, "stage": item["stage_label"], "provider": provider,
                "voice": voice_label(audios.get(render.project_id) if render else None, item.get("voice")),
                "next_action": action, "href": f'/autopilot/jobs/{item["id"]}', "duration": item["duration"],
                "progress": item["progress"], "updated_at": item["updated_at"], "completed": status == "completed",
                "task_id": item["id"], "render_job_id": render.id if render else None,
                "draft_id": draft.id if draft else None, "project_id": render.project_id if render else None,
                "workspace_href": f'/?task={item["id"]}#workspace-detail',
                "news_method": ("체험 뉴스 · 로컬" if item["source"] == "sample" else
                                "RSS · 웹 검색 아님" if item.get("acquisition_policy", "rss") == "rss" else
                                "AI 웹 뉴스 조사 · 차단"),
                "analysis_engine": run_label(analysis, item["ai_mode"]),
                "script_engine": run_label(script, item["ai_mode"]),
                "model": item.get("ai_model") or (script or analysis).options.get("model", "")
                if script or analysis or item.get("ai_model") else "",
            })
        for draft in drafts.values():
            if draft.id in used_drafts:
                continue
            run = runs.get(draft.run_id)
            if not run:
                continue
            context = context_for_run(run)
            used_runs.add(run.id)
            if context and context.get("analysis_id"):
                used_runs.add(context["analysis_id"])
            render = latest_by_draft.get(draft.id)
            if render and render.id in used_renders:
                continue
            if render:
                used_renders.add(render.id)
                status = render.status
                label, action = {
                    "running": ("영상 제작 중", "제작 진행 확인"),
                    "success": ("최종 확인 필요", "완성 영상 시청·확인"),
                }.get(status, ("조치 필요", "영상 작업의 오류 확인"))
                stage, href = "음성·자막·MP4 제작", f"/video?job_id={render.id}&draft_id={draft.id}"
            else:
                status, label, action = "waiting_review", "대본 검토 필요", "대본 검토 후 영상 만들기"
                stage, href = "대본 작성 완료", f"/ai?draft_id={draft.id}"
            rows.append({
                "id": f"draft:{draft.id}", "kind": "manual", "title": draft.content.get("title", "저장된 대본"),
                "status": "waiting_review" if status == "success" else status, "status_label": label,
                "stage": stage, "provider": run_label(run),
                "voice": voice_label(audios.get(render.project_id) if render else None,
                                     context.get("initial_voice") if context else None),
                "next_action": action, "href": href, "duration": draft.duration,
                "progress": render.progress if render else None,
                "updated_at": (render.created_at if render else draft.updated_at).isoformat(), "completed": False,
                "task_id": None, "render_job_id": render.id if render else None, "draft_id": draft.id,
                "project_id": render.project_id if render else None,
                "workspace_href": f"/?video={render.id}#workspace-detail" if render and render.status == "success" else href,
            })
        for run in sorted(runs.values(), key=lambda r: r.id, reverse=True):
            context = context_for_run(run)
            if run.kind != "script" or run.id in used_runs or not context or run.status == "success":
                continue
            analysis_id = context.get("analysis_id")
            if not analysis_id or analysis_id in used_runs:
                continue
            used_runs.update((run.id, analysis_id))
            evidence = run.evidence.get("articles", [])
            rows.append({
                "id": f"script:{run.id}", "kind": "manual",
                "title": evidence[0].get("title", "대본 생성") if evidence else "대본 생성",
                "status": "running" if run.status == "running" else "failed",
                "status_label": "준비 중" if run.status == "running" else "조치 필요",
                "stage": "대본 생성", "provider": run_label(run),
                "voice": voice_label(None, context["initial_voice"]),
                "next_action": "대본 생성 진행 확인" if run.status == "running" else "오류·사용량 확인 · 자동 재실행 없음",
                "href": f"/ai?analysis_id={analysis_id}&failed_run_id={run.id}",
                "duration": run.options.get("duration", context["initial_duration"]),
                "progress": None, "updated_at": run.created_at.isoformat(), "completed": False,
                "task_id": None, "render_job_id": None, "draft_id": None, "project_id": None,
                "workspace_href": f"/ai?analysis_id={analysis_id}&failed_run_id={run.id}",
            })
        for run in runs.values():
            context = context_for_run(run)
            # Old records without a production link remain in advanced AI history; do not guess relationships.
            if run.kind != "analysis" or run.id in used_runs or not context:
                continue
            articles_in_run = run.evidence.get("articles", [])
            successful = run.status == "success"
            rows.append({
                "id": f"analysis:{run.id}", "kind": "manual",
                "title": articles_in_run[0].get("title", "기사 분석") if articles_in_run else "기사 분석",
                "status": "waiting_review" if successful else "running" if run.status == "running" else "failed",
                "status_label": "준비 중" if successful or run.status == "running" else "조치 필요",
                "stage": "기사 분석 완료" if successful else "기사 분석", "provider": run_label(run),
                "voice": voice_label(None, context["initial_voice"]),
                "next_action": "분석 확인 후 대본 만들기" if successful else "분석 진행·오류 확인",
                "href": f"/ai?analysis_id={run.id}", "duration": context["initial_duration"], "progress": None,
                "updated_at": run.created_at.isoformat(), "completed": False,
                "task_id": None, "render_job_id": None, "draft_id": None, "project_id": None,
                "workspace_href": f"/ai?analysis_id={run.id}",
            })
        return sorted(rows, key=lambda r: r["updated_at"], reverse=True)[:100]
