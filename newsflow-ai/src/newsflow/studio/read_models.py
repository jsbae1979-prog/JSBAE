"""Allowlisted, read-only view models. Commands retain original FastAPI form contracts."""

from datetime import datetime
from hashlib import sha256
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from newsflow.db import models as m
from newsflow.publishing.service import PublishingError

router = APIRouter()
Module = Literal[
    "news",
    "shorts",
    "characters",
    "images",
    "automation",
    "library",
    "publishing",
    "analytics",
    "settings",
    "onboarding",
]
# Explicit column lists: never serialize ORM __dict__, credential references or provider payloads.
SPECS = {
    "news": [
        ("articles", "NewsArticle", "id title url publisher summary category published_at collected_at"),
        ("sources", "NewsSource", "id name url enabled"),
        ("analyses", "IntelligenceRun", "id kind provider status created_at"),
    ],
    "shorts": [
        (
            "drafts",
            "ContentDraft",
            "id run_id duration content sources revision review_status review_notes updated_at",
        ),
        (
            "plans",
            "AIVideoPlan",
            "id draft_id duration status revision currency confirmed_at reviewed_at approved_at render_job_id message",
        ),
        (
            "scenes",
            "AIVideoScene",
            "id plan_id position start_ms end_ms narration caption source material prompt model_path clip_seconds estimated_cost status",
        ),
        ("renders", "RenderJob", "id project_id status progress message created_at"),
    ],
    "images": [
        ("drafts", "IntelligenceRun", "id kind provider status created_at"),
        ("posts", "ImagePost", "id article_id title caption sources ai_disclosure created_at"),
        ("articles", "NewsArticle", "id title publisher category"),
        ("deliveries", "ImagePostDelivery", "id post_id account_id status created_at"),
    ],
    "automation": [
        (
            "schedules",
            "ProductionSchedule",
            "id name kind local_time weekdays once_date status revision next_run_at",
        ),
        ("runs", "ScheduledRun", "id schedule_id status revision message created_at"),
        ("jobs", "AutopilotJob", "id status revision message created_at"),
    ],
    "publishing": [
        (
            "drafts",
            "PublishDraft",
            "id render_job_id platform title description hashtags account_id sources content_reviewed copyright_confirmed sources_confirmed ai_disclosure revision state",
        ),
        ("accounts", "PlatformAccount", "id platform label status account_type api_ready"),
        ("jobs", "PublishJob", "id draft_id status message platform created_at"),
        ("calendar", "PublishSchedule", "id due_at status revision"),
    ],
    "analytics": [
        ("metrics", "SocialMetric", "id platform metric value unit synthetic fetched_at"),
        (
            "usage",
            "AIUsage",
            "id provider model kind status prompt_tokens completion_tokens total_tokens elapsed_ms created_at",
        ),
        (
            "requests",
            "APIRequestReservation",
            "id provider kind model status reserved_usd estimated_usd created_at",
        ),
    ],
    "library": [("removed", "WorkspaceRemoval", "key created_at")],
    "settings": [
        (
            "models",
            "VideoAIModel",
            "id provider path label price_per_second durations resolution confirmed_at",
        ),
        ("sources", "NewsSource", "id name url enabled"),
    ],
    "onboarding": [],
    "characters": [],
}
SETTINGS = {
    "creation_image_defaults",
    "creation_character_defaults",
    "creation_news_video_model",
    "easy_setup",
    "production_selection",
    "production_preferences",
    "ai_provider",
    "ai_model",
    "tts_provider",
    "tts_voice_id",
    "tts_model",
    "voice",
    "duration",
    "require_script_review",
}


def value(v):
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def rows(session, model_name, columns):
    model = getattr(m, model_name)
    query = select(model)
    if model_name == "IntelligenceRun":
        query = query.where(
            model.kind.in_(["analysis", "curation"] if columns.startswith("id kind") else ["image_draft"])
        )
    if model_name == "NewsArticle":
        query = query.outerjoin(m.NewsListState, m.NewsListState.article_id == model.id).where(
            m.NewsListState.hidden.is_not(True)
        )
    order = getattr(model, "id", getattr(model, "key", None))
    if order is not None:
        query = query.order_by(order.desc())
    return [{k: value(getattr(row, k)) for k in columns.split()} for row in session.scalars(query.limit(100))]


def image_rows(state, session):
    outputs = {}
    for row in session.scalars(
        select(m.IntelligenceRun)
        .where(m.IntelligenceRun.kind == "feed_image")
        .order_by(m.IntelligenceRun.id.desc())
    ):
        if row.options.get("style") == "studio" and type(row.options.get("draft_id")) is int:
            outputs.setdefault(row.options["draft_id"], row)
    result = []
    for row in session.scalars(
        select(m.IntelligenceRun)
        .where(m.IntelligenceRun.kind == "image_draft")
        .order_by(m.IntelligenceRun.id.desc())
        .limit(100)
    ):
        output = outputs.get(row.id)
        item = {
            "id": row.id,
            "title": row.result.get("prompt", "이미지 초안"),
            "prompt": row.result.get("prompt", ""),
            "selection": {
                k: v
                for k, v in row.options.get("selection", {}).items()
                if k in {"provider", "model", "size", "quality"}
            },
            "reference": bool(row.options.get("reference")),
            "status": output.status if output else row.status,
            "outputId": output.id if output else None,
            "mediaUrl": None,
        }
        if output is not None and output.status == "success":
            try:
                state.image_generation.path(output.id)
                item["mediaUrl"] = f"/image-studio/{row.id}/file"
            except (OSError, ValueError, PublishingError):
                item["status"] = "missing"
        result.append(item)
    return result


def character_rows(state):
    result = []
    for source in state.character.listing()[:100]:
        job = state.character.read(source["id"])
        item = {
            k: job[k]
            for k in (
                "id",
                "topic",
                "state",
                "created_at",
                "script",
                "selection",
                "quote_total_usd",
                "quote_hash",
                "retry_hash",
                "reported_billed_usd",
                "episode_limit",
                "day_limit",
                "message",
            )
            if k in job
        }
        # Reference and clips use existing validated file routes; do not expose local paths.
        item["scenes"] = [
            {
                k: scene[k]
                for k in ("position", "state", "prompt", "narration", "caption", "seconds", "cost", "message")
                if k in scene
            }
            for scene in job.get("scenes", [])
        ]
        item["story"] = job.get("script")
        item["quote"] = job.get("quote_total_usd")
        item["referenceUrl"] = (
            f"/api/studio/characters/{job['id']}/reference" if job.get("reference_sha256") else None
        )
        for scene in item["scenes"]:
            original = next((x for x in job.get("scenes", []) if x["position"] == scene["position"]), {})
            clip = state.character.folder(job["id"]) / f"scene-{scene['position']}.mp4"
            scene["mediaUrl"] = (
                f"/character/{job['id']}/clips/{scene['position']}"
                if scene.get("state") == "downloaded"
                and not clip.is_symlink()
                and clip.is_file()
                and sha256(clip.read_bytes()).hexdigest() == original.get("sha256")
                else None
            )
        item["mediaUrl"] = None
        if job.get("state") == "completed":
            path = state.character.folder(job["id"]) / "final.mp4"
            if (
                not path.is_symlink()
                and path.is_file()
                and sha256(path.read_bytes()).hexdigest() == job.get("output", {}).get("sha256")
            ):
                item["mediaUrl"] = f"/character/{job['id']}/file"
        result.append(item)
    return result


@router.get("/api/studio/modules/{module}")
def module_view(request: Request, module: Module):
    from newsflow.creation.catalog import (
        API_MODELS,
        IMAGE_MODELS,
        IMAGE_QUALITIES,
        IMAGE_SIZES,
        read_defaults,
    )
    from newsflow.gui.studio_v3 import workspace

    state = request.app.state
    result = {
        "schemaVersion": 1,
        "module": module,
        "dataOrigin": "development-fixtures"
        if getattr(state, "studio_synthetic", False)
        else "local-workspace",
        "csrfToken": getattr(request.state, "csrf", ""),
        "commandsAvailable": True,
        "collections": {},
    }
    with state.sessions() as session:
        for key, name, columns in SPECS[module]:
            result["collections"][key] = rows(session, name, columns)
        if module == "images":
            result["collections"]["drafts"] = image_rows(state, session)
            result["collections"]["selections"] = []
            candidates = session.scalars(
                select(m.IntelligenceRun)
                .where(
                    m.IntelligenceRun.kind == "analysis",
                    m.IntelligenceRun.status == "success",
                    m.IntelligenceRun.evidence["curation_contract"]["top_k"].as_integer() == 3,
                )
                .order_by(m.IntelligenceRun.id.desc())
                .limit(20)
            )
            for row in candidates:
                try:
                    group = state.image_posts.selection(row.id)
                    items = [
                        {
                            k: item[k]
                            for k in (
                                "rank",
                                "score",
                                "title",
                                "body",
                                "article_id",
                                "article_ids",
                                "references",
                                "selection",
                                "origin",
                            )
                        }
                        for item in group["items"]
                    ]
                    result["collections"]["selections"].append(
                        {
                            "id": row.id,
                            "title": f"화제성 평가 #{row.id}",
                            "status": row.status,
                            "ranking": items,
                        }
                    )
                except PublishingError:
                    result["collections"]["selections"].append(
                        {
                            "id": row.id,
                            "title": f"화제성 평가 #{row.id} · 출처 연결 확인 필요",
                            "status": "blocked",
                            "ranking": [],
                        }
                    )
            result["collections"]["cards"] = []
            result["collections"]["generations"] = []
            for run in session.scalars(
                select(m.IntelligenceRun)
                .where(m.IntelligenceRun.kind.in_(["feed_card", "feed_image"]))
                .order_by(m.IntelligenceRun.id.desc())
                .limit(100)
            ):
                if run.kind == "feed_image" and run.options.get("style") == "studio":
                    continue
                source_plan = (
                    run.result.get("plan", {})
                    if run.kind == "feed_card"
                    else run.evidence.get("source", {}).get("plan", {})
                )
                plan = {
                    key: source_plan[key]
                    for key in (
                        "title",
                        "body",
                        "hashtags",
                        "image_prompt",
                        "negative_prompt",
                        "composition",
                        "source_article_ids",
                    )
                    if key in source_plan
                }
                item = {
                    "id": run.id,
                    "title": plan.get("title", "뉴스 이미지 작업 #" + str(run.id)),
                    "status": run.status,
                    "plan": plan,
                    "options": {
                        key: run.options[key]
                        for key in (
                            "article_id",
                            "analysis_id",
                            "rank",
                            "draft_id",
                            "card_id",
                            "purpose",
                            "style",
                        )
                        if key in run.options
                    },
                    "mediaUrl": None,
                }
                if run.kind == "feed_image" and run.status == "success":
                    try:
                        state.image_generation.path(run.id)
                        item["mediaUrl"] = f"/image-posts/backgrounds/{run.id}/file"
                    except (PublishingError, ValueError, OSError):
                        item["status"] = "missing"
                result["collections"]["cards" if run.kind == "feed_card" else "generations"].append(item)
            for post in result["collections"]["posts"]:
                try:
                    state.image_posts.path(post["id"])
                    post["mediaUrl"] = f"/image-posts/{post['id']}/file"
                    post["status"] = "success"
                except (OSError, ValueError, PublishingError, AttributeError):
                    post["mediaUrl"] = None
                    post["status"] = "missing"
        if module in {"shorts", "images", "publishing"}:
            result["collections"]["analyses"] = rows(
                session, "IntelligenceRun", "id kind provider status created_at"
            )
            result["collections"]["articles"] = rows(session, "NewsArticle", "id title publisher category")
            result["collections"]["models"] = rows(
                session,
                "VideoAIModel",
                "id provider path label price_per_second durations resolution confirmed_at",
            )
        if module == "publishing":
            result["collections"]["renders"] = rows(session, "RenderJob", "id status project_id")
            result["collections"]["deliveries"] = rows(
                session, "ImagePostDelivery", "id post_id account_id status created_at"
            )
        if module == "publishing":
            result["collections"]["cohorts"] = []
            for row in session.scalars(
                select(m.PublishEvidence)
                .where(m.PublishEvidence.kind == "unified_review")
                .order_by(m.PublishEvidence.id.desc())
                .limit(50)
            ):
                try:
                    cohort = state.unified_publishing.get(row.id)
                except PublishingError:
                    continue
                result["collections"]["cohorts"].append(
                    {
                        "id": row.id,
                        "title": "게시 검토 #" + str(row.id),
                        "approval_token": cohort["approval_token"],
                        "can_execute": cohort["can_execute"],
                        "reviewed": cohort["reviewed"],
                        "locked": cohort["locked"],
                        "targets": [
                            {
                                k: target[k]
                                for k in ("platform", "status", "draft_id", "can_continue")
                                if k in target
                            }
                            for target in cohort["targets"]
                        ],
                    }
                )
        if module == "shorts":
            for clip in result["collections"]["scenes"]:
                clip["mediaUrl"] = None
                if (
                    clip["source"] == "generated"
                    and hasattr(state, "video_ai")
                    and hasattr(state.video_ai, "clip_path")
                ):
                    from newsflow.video.ai.service import AIVideoError

                    try:
                        state.video_ai.clip_path(clip["id"])
                        clip["mediaUrl"] = f"/video/ai/scenes/{clip['id']}/clip"
                    except (AIVideoError, OSError):
                        pass
            for draft in result["collections"]["drafts"]:
                try:
                    draft["imageLinks"] = (
                        state.video.news_images.choose(
                            session, draft["sources"], len(draft["content"].get("scenes", []))
                        )[1]
                        if hasattr(state.video, "news_images")
                        else []
                    )
                except (AttributeError, TypeError, ValueError, OSError):
                    draft["imageLinks"] = []
                    draft["imageError"] = "장면 이미지 연결을 확인하세요."
        if module == "news":
            # Thumbnail URLs are read from records; no network lookup on page load.
            for article in result["collections"]["articles"]:
                article["thumbnailUrl"] = f"/news/{article['id']}/thumbnail"
        if module in {"settings", "onboarding"}:
            result["settings"] = {
                row.key: row.value
                for row in session.scalars(select(m.AppSetting).where(m.AppSetting.key.in_(SETTINGS)))
            }
    if module == "characters":
        result["collections"]["jobs"] = character_rows(state)
    if module in {"library", "shorts", "publishing", "settings"}:
        work = workspace(request)
        result["projects"] = work["projects"]
        result["services"] = work["services"]
    result["catalog"] = {
        "apiModels": API_MODELS,
        "imageModels": list(IMAGE_MODELS),
        "sizes": IMAGE_SIZES,
        "qualities": IMAGE_QUALITIES,
        "accountVerified": False,
    }
    for mode in ("image", "character"):
        try:
            result["catalog"][mode + "Defaults"] = read_defaults(state.sessions, mode)
        except ValueError as exc:
            result["catalog"][mode + "Error"] = str(exc)
    from newsflow.gui.production_picker import NEWS_METHODS

    result["catalog"]["newsMethods"] = NEWS_METHODS
    from newsflow.intelligence.settings import PROVIDERS, STUDIO_PROVIDERS
    from newsflow.video.elevenlabs_tts import MODELS as TTS_MODELS

    result["catalog"]["legacyProviders"] = PROVIDERS
    result["catalog"]["analysisProviders"] = STUDIO_PROVIDERS
    result["catalog"]["ttsModels"] = list(TTS_MODELS)
    result["catalog"]["referenceAssets"] = (
        state.image_studio.assets() if hasattr(state, "image_studio") else []
    )
    result["catalog"]["assets"] = state.video.assets_list() if hasattr(state.video, "assets_list") else []
    result["catalog"]["voices"] = [{"id": "offline-silence", "label": "무음 검토영상"}]
    with state.sessions() as session:
        voice = session.get(m.AppSetting, "video_default_voice")
        if voice and voice.value != "offline-silence":
            result["catalog"]["voices"].append({"id": voice.value, "label": "저장된 선택 · " + voice.value})
    if module in {"shorts", "settings"}:
        from newsflow.easy_setup import (
            LISTENING_ITEMS,
            LISTENING_VALUES,
            LISTENING_VERDICTS,
            preview_evidence,
        )
        from newsflow.video.elevenlabs_tts import ElevenLabsKeys
        from newsflow.video.elevenlabs_voices import ElevenLabsVoices
        from newsflow.video.tts import TTSError

        catalog = ElevenLabsVoices(state.config.data_dir, ElevenLabsKeys(state.config.data_dir))
        result["catalog"]["elevenVoices"] = []
        result["collections"]["audioSamples"] = []
        for voice in catalog.cached()["voices"]:
            result["catalog"]["elevenVoices"].append({"id": voice["voice_id"], "label": voice["name"]})
            try:
                sample = catalog.sample_path(voice["voice_id"])
                if sample.is_file() and not sample.is_symlink():
                    result["collections"]["audioSamples"].append(
                        {
                            "id": voice["voice_id"],
                            "title": voice["name"],
                            "provider": "elevenlabs",
                            "mediaUrl": f"/video/tts/voices/{voice['voice_id']}/sample",
                        }
                    )
            except TTSError:
                pass
        folder = state.config.data_dir / "voice-preview"
        if folder.is_dir() and not folder.is_symlink():
            for sample in sorted(folder.glob("preview-*.wav"))[-50:]:
                proof = preview_evidence(state.config.data_dir, sample.name)
                if proof:
                    result["collections"]["audioSamples"].append(
                        {
                            "id": sample.name,
                            "title": proof["voice"],
                            "provider": "windows",
                            "voice": proof["voice"],
                            "rate": proof["rate"],
                            "pause_ms": proof["pause_ms"],
                            "mediaUrl": f"/voices/preview/{sample.name}",
                        }
                    )
        from newsflow.easy_setup import listening_summary

        result["listeningSummary"] = listening_summary(state.sessions)
        result["catalog"]["listening"] = {
            "items": LISTENING_ITEMS,
            "values": LISTENING_VALUES,
            "verdicts": LISTENING_VERDICTS,
        }
    if module == "settings":
        from newsflow.operations import evidence

        result["operationsReview"] = evidence.read(state.sessions)
        result["catalog"]["operationsItems"] = evidence.ITEMS
    # Read current non-secret defaults through existing helpers. Never replace a
    # saved configuration with the original Form() defaults merely by opening it.
    from newsflow.easy_setup import preview_preferences, speech_preferences
    from newsflow.intelligence.settings import read_settings as ai_settings
    from newsflow.video.ai.settings import read_settings as video_settings
    from newsflow.video.elevenlabs_tts import settings as tts_settings

    result["formDefaults"] = {}
    from newsflow.intelligence.settings import read_studio_settings

    studio = read_studio_settings(state.sessions)
    result["catalog"]["studioModels"] = studio["models"]
    for action in ("intelligence_analyze", "intelligence_generate", "intelligence_studio_preferences"):
        result["formDefaults"][action] = {"provider": studio["provider"], "model": studio["model"]}

    ai = ai_settings(state.sessions)
    result["formDefaults"]["ai_settings_save_ai_settings"] = {
        key: getattr(ai, key) for key in ("provider", "model", "approved", "monthly_token_limit", "timeout")
    }
    tts = tts_settings(state.sessions)
    result["formDefaults"]["video_save_tts"] = {
        key: tts[key] for key in ("enabled", "voice_id", "model", "job_limit", "monthly_limit", "commercial")
    }
    video = video_settings(state.sessions)
    result["formDefaults"]["video_ai_save_settings"] = {
        key: value(getattr(video, key))
        if key not in {"job_limit", "monthly_limit"}
        else str(getattr(video, key))
        for key in (
            "provider",
            "host",
            "approved",
            "monthly_limit",
            "job_limit",
            "currency",
            "max_active",
            "timeout_minutes",
            "poll_seconds",
        )
    }
    try:
        voice, size, position = preview_preferences(state.sessions)
        speech = speech_preferences(state.sessions)
        result["formDefaults"]["voice_save"] = {
            "voice": voice,
            "rate": str(speech.rate),
            "pause_ms": str(speech.pause_ms),
        }
        result["formDefaults"]["voice_preview"] = dict(result["formDefaults"]["voice_save"])
        result["formDefaults"]["video_render"] = {"voice": voice, "font_size": size, "subtitle_y": position}
    except ValueError:
        pass
    result["policy"] = {
        "automaticRetry": False,
        "providerFallback": False,
        "paidReferenceEdit": False,
        "price": "견적·사용량·청구액은 별도입니다. 확인된 견적이 없으면 금액 미확정입니다.",
    }
    return result


@router.get("/api/studio/characters/{identifier}/reference")
def character_reference(request: Request, identifier: str):
    from newsflow.character.schema import CharacterError

    try:
        service = request.app.state.character
        job = service.read(identifier)
        path = service.folder(identifier) / "reference.png"
        if (
            path.is_symlink()
            or not path.is_file()
            or sha256(path.read_bytes()).hexdigest() != job.get("reference_sha256")
        ):
            raise ValueError
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
    except (OSError, ValueError, CharacterError):
        raise HTTPException(404, "검증된 참조 PNG를 찾지 못했습니다.") from None


@router.get("/api/studio/local-voices")
def local_voices(request: Request):
    # Explicit user action only, same SAPI catalog as the existing voice page.
    from newsflow.easy_setup import voice_choice_catalog
    from newsflow.gui.voice_routes import _voices

    _all, korean, status, _report = _voices()
    return {
        "status": status,
        "voices": [
            {"id": row["name"], "label": row["label"], "available": row["available"]}
            for row in voice_choice_catalog(korean)
        ],
    }


@router.get("/api/studio/system-startup")
def system_startup(request: Request):
    from newsflow.gui.operations_routes import status

    record = status(request)
    return {key: record[key] for key in ("status", "revision", "prepared", "message") if key in record}
