"""Frozen full-video choices, stored alongside existing plans without a migration."""
import json
from copy import deepcopy

from newsflow.autopilot.production_options import freeze_options
from newsflow.db.models import AppSetting, AutopilotJob, IntelligenceRun
from newsflow.easy_setup import preview_preferences, speech_preferences
from newsflow.video.elevenlabs_tts import settings as elevenlabs_settings

from .model_contracts import check_model_contract
from .policy import check_prompt

DEFAULT_MODEL = "pixverse/v6/text-to-video"
COMMON_STYLE = "Consistent navy and blue editorial illustration, soft lighting, restrained motion, no text or logos."


def read_contract(session, plan_id):
    row = session.get(AppSetting, f"ai_plan_contract:{plan_id}")
    return json.loads(row.value) if row else None


def write_contract(session, plan_id, value):
    session.add(AppSetting(key=f"ai_plan_contract:{plan_id}", value=json.dumps(value, ensure_ascii=False)))


def model_ready(model):
    return model is not None and model.confirmed and check_model_contract(
        model.path, model.durations, model.resolution)[0] == "PASS"


def draft_choices(sessions, draft, *, external_consent=False):
    """Prefer the original job snapshot; never silently adopt another voice/model."""
    with sessions() as session:
        run = session.get(IntelligenceRun, draft.run_id)
        ctx = run.options.get("production_context", {}) if run else {}
        job_id = run.options.get("autopilot_job_id") if run else None
        job = session.get(AutopilotJob, job_id) if job_id else None
        choices = (job.stage_results or {}).get("request", {}).get("production_options") if job else None
        choices = choices or ctx.get("production_options")
    if choices:
        snapshot = deepcopy(choices)
        snapshot["video_provider"] = "higgsfield"  # This new plan explicitly chooses full AI video.
        return freeze_options(snapshot, choices.get("voice"))
    voice = ctx.get("initial_voice") if ctx.get("production_options_version") == 1 else None
    voice = voice or preview_preferences(sessions)[0]
    options = {"version": 1, "script_review": ctx.get("script_review", True),
               "video_provider": "higgsfield", "external_tts_consent": external_consent}
    if voice == "elevenlabs":
        options["elevenlabs"] = elevenlabs_settings(sessions)
    return freeze_options(options, voice)


def speech_snapshot(sessions):
    speech = speech_preferences(sessions)
    return {"rate": speech.rate, "pause_ms": speech.pause_ms}


def scene_prompt(title, caption, index):
    # News text is data; reject prohibited reconstruction requests rather than "repairing" them.
    subject = " ".join((title + " / " + caption).split())[:360]
    return check_prompt(f"{COMMON_STYLE} Topic reference: {subject}. Scene {index + 1}: symbolic visual explanation.")


def completed_render(session, draft_id, choices, duration):
    """Read-only bridge back to Autopilot; no synthesis, provider calls or approval changes."""
    from sqlalchemy import select

    from newsflow.db.models import AIVideoPlan, ContentDraft, RenderJob, VideoProject
    draft = session.get(ContentDraft, draft_id) if draft_id else None
    if not draft:
        return None
    plans = session.scalars(select(AIVideoPlan).where(
        AIVideoPlan.draft_id == draft.id, AIVideoPlan.draft_revision == draft.revision,
        AIVideoPlan.duration == duration, AIVideoPlan.status == "composed").order_by(AIVideoPlan.id.desc()))
    for plan in plans:
        contract = read_contract(session, plan.id)
        render = session.get(RenderJob, plan.render_job_id) if plan.render_job_id else None
        project = session.get(VideoProject, render.project_id) if render else None
        if (contract and contract["production"] == choices and project and project.preview_only
                and render.status == "success" and render.metadata_json.get("playable")):
            return render
    return None
