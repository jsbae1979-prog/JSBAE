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
        ("metrics", "SocialMetric", "id job_id account_id platform metric value unit period_start period_end synthetic fetched_at"),
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
    if model_name == "WorkspaceRemoval":
        query = query.where(~model.key.startswith("library:"))
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
    from newsflow.character.visibility import read_visibility
    from newsflow.character.service import quote_settings_editable
    visibility = read_visibility(state.character.sessions)
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
                "automation_version",
                "character_id",
                "script_hash",
                "script",
                "selection",
                "studio_selection",
                "duration",
                "model",
                "claude_model",
                "quote_total_usd",
                "quote_hash",
                "retry_hash",
                "regeneration_hash",
                "reported_billed_usd",
                "reused_story",
                "submit_diagnostics",
                "episode_limit",
                "day_limit",
                "message",
            )
            if k in job
        }
        from newsflow.character.story_response import public_failure
        item['scriptFailure']=public_failure(job.get('script_failure'))
        item['scriptRetryAllowed']=(job.get('state')=='script_failed' and job.get('response_received') is True
                                    and 0<job.get('script_attempts',0)<3)
        item['scriptResponseSaved']=bool(job.get('script_responses'))
        item['quoteSettingsEditable']=quote_settings_editable(job)
        if job.get('prompt_validation_error'):
            item['message'] = '대본 저장됨 · 영상 지시문 길이를 줄여주세요'
        item.update(visibility.get(job['id'], {'trashed': False, 'recentHidden': False}))
        # Reference and clips use existing validated file routes; do not expose local paths.
        item["scenes"] = [
            {
                k: scene[k]
                for k in ("position", "state", "prompt", "narration", "caption", "seconds", "cost", "message")
                if k in scene
            }
            for scene in job.get("scenes", [])
        ]
        item["reviewWarnings"] = [job["character"]["style_warn"]] if job.get("character",{}).get("style_warn") else []
        item["story"] = job.get("script")
        if job.get("automation_version") == 1:
            item["characterProfile"] = job.get("character", {})
        if job.get("regeneration"):
            item["regeneration"] = {k: job["regeneration"][k] for k in
                ("position", "affected", "quote_total_usd", "exposure_usd", "total_after_usd", "at") if k in job["regeneration"]}
        if job.get('automation_version') == 1 and job.get('script'):
            from newsflow.character.episode_story import EpisodeScript
            from newsflow.character.editing import total_playback_seconds, load_edit_presets, load_sfx_map, edit_timeline
            parsed = EpisodeScript.model_validate(job['script'])
            item['playback_seconds'] = total_playback_seconds(parsed, load_edit_presets())
            item['editTimeline'] = edit_timeline(parsed, job['duration'])
            item['sfx_keys'] = list(load_sfx_map())
            item['characterProfile'] = job.get('character', {})
        item["quote"] = job.get("quote_total_usd")
        item["referenceUrl"] = (
            f"/api/studio/characters/{job['id']}/reference" if job.get("reference_sha256") else None
        )
        story = job.get("script")
        story_scenes = story.get("scenes") if isinstance(story, dict) else None
        if not isinstance(story_scenes, list):
            story_scenes = []
        if job.get("state") == "retry_quoted" and job.get("retry"):
            item["retryQuote"] = {
                k: job["retry"][k] for k in ("position", "quote_usd", "at") if k in job["retry"]
            }
        for scene in item["scenes"]:
            position = scene["position"]
            if isinstance(position, int) and 1 <= position <= len(story_scenes):
                planned = story_scenes[position - 1]
                for field in ("caption", "action", "seconds"):
                    if isinstance(planned, dict) and field not in scene and field in planned:
                        scene[field] = planned[field]
            original = next((x for x in job.get("scenes", []) if x["position"] == scene["position"]), {})
            if "cost" not in scene and "quote_usd" in original:
                scene["cost"] = original["quote_usd"]
            from newsflow.character.status_diagnostics import public_diagnostic, private_inputs
            details = public_diagnostic(original.get('status_diagnostics'), private_inputs(job))
            if details is not None:
                scene['status_diagnostics'] = details
            import re
            filename = original.get("file", f"scene-{scene['position']}.mp4")
            if not isinstance(filename,str) or not re.fullmatch(rf"scene-{scene['position']}(?:-t[0-9]+)?\.mp4",filename):
                filename = "blocked-missing-clip.mp4"
            clip = state.character.folder(job["id"]) / filename
            scene["mediaUrl"] = (
                f"/character/{job['id']}/clips/{scene['position']}"
                if scene.get("state") == "downloaded"
                and not clip.is_symlink()
                and clip.is_file()
                and sha256(clip.read_bytes()).hexdigest() == original.get("sha256")
                else None
            )
            media = original.get("media")
            if scene["mediaUrl"] and isinstance(media, dict):
                projected = {}
                duration = media.get("duration")
                if type(duration) in (int, float) and 0 < duration <= 86400:
                    projected["duration"] = duration
                for dimension in ("width", "height"):
                    value = media.get(dimension)
                    if type(value) is int and 0 < value <= 32768:
                        projected[dimension] = value
                if type(media.get("has_audio")) is bool:
                    projected["has_audio"] = media["has_audio"]
                if projected:
                    scene["media"] = projected
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
        if module == "automation":
            # Explicit non-secret saved options, so editing never resets them.
            for item in result["collections"]["schedules"]:
                schedule = session.get(m.ProductionSchedule, item["id"])
                item.update({key: schedule.options[key] for key in ("source", "duration", "platform", "voice") if key in schedule.options})
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
            # Only source-supplied metadata earns an image request. Reading the
            # model never fetches an image or substitutes generated artwork.
            article_ids = [article["id"] for article in result["collections"]["articles"]]
            with_previews = set(session.scalars(select(m.ArticleThumbnail.article_id).where(
                m.ArticleThumbnail.article_id.in_(article_ids))))
            for article in result["collections"]["articles"]:
                article["thumbnailUrl"] = (f"/news/{article['id']}/thumbnail"
                                           if article["id"] in with_previews else None)
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
        if module == "library":
            from newsflow.samples.catalog import Samples
            from newsflow.studio.library_visibility import LibraryVisibility
            result["collections"]["ownedReferences"] = Samples(
                state.sessions,state.config.data_dir,state.image_studio).owned_references()
            removed = LibraryVisibility(state.sessions, state.character).listing()
            hidden = {item["id"] for item in removed}
            result["projects"] = [item for item in result["projects"] if item["id"] not in hidden]
            result["collections"]["ownedReferences"] = [
                item for item in result["collections"]["ownedReferences"] if item["id"] not in hidden]
            result["collections"]["libraryRemoved"] = removed
            result["libraryRemovalAvailable"] = True
    result["catalog"] = {
        "apiModels": API_MODELS,
        "imageModels": list(IMAGE_MODELS),
        "sizes": IMAGE_SIZES,
        "qualities": IMAGE_QUALITIES,
        "accountVerified": False,
    }
    if module == "characters":
        from newsflow.character.kling import catalog as character_catalog
        result["catalog"]["characterStudio"] = character_catalog()
        result["catalog"]["characterStudio"]["manualExecutionEnabled"] = bool(
            getattr(state.character, "_manual_character_execution_enabled",
                    not getattr(state.character, "_operating_quote_only", False)))
        live_trial = getattr(state.character, "_approved_character_trial", None)
        if live_trial is not None and not getattr(state.character, "_operating_quote_only", False):
            result["catalog"]["characterStudio"]["liveTrial"] = {
                "enabled": True, "duration": 15, "totalLimitUsd": live_trial.policy["total_limit_usd"],
                "sound": live_trial.policy["sound"],
                "reuseStory": bool(live_trial.policy.get("reuse_source_job_id")),
                "expiresAt": live_trial.policy["expires_at"],
            }
        from newsflow.character.kling import DEFAULTS, as_generation, validate as validate_character
        from newsflow.video_models.catalog import reconcile
        for completed in state.character.listing():
            if completed['state']=='completed' and completed.get('studio_selection'):
                try:
                    saved={k:completed['studio_selection'][k] for k in DEFAULTS}
                    adjusted,notes=reconcile(as_generation(saved))
                    saved.update(video_model=adjusted.model_id,aspect_ratio=adjusted.aspect_ratio,
                        native_resolution=adjusted.resolution,clip_seconds=adjusted.duration,
                        sound='on' if adjusted.audio else 'off',style=DEFAULTS['style'])
                    saved['aspect_ratio']=DEFAULTS['aspect_ratio']
                    if completed.get('automation_version') != 1:
                        saved['duration']=saved['clip_seconds']*min(5,60//saved['clip_seconds'])
                    result["catalog"]["characterStudio"]["defaults"] = validate_character(saved)
                    result["catalog"]["characterStudio"]["restoredNotes"] = notes
                except (ValueError,KeyError,TypeError):
                    result["catalog"]["characterStudio"]["restoredNotes"] = {'model':'마지막 성공 설정을 재사용할 수 없어 카탈로그 기본값을 표시합니다. 저장 작업은 변경하지 않습니다.'}
                break
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
    result["catalog"]["myCharacters"] = (
        state.image_studio.characters() if hasattr(state, "image_studio") else []
    )
    if module == "characters":
        from newsflow.character.registry import CharacterRegistry
        result['catalog']['characterProfiles'] = CharacterRegistry(state.config.data_dir, state.image_studio).list()
        result['catalog']['characterAIProviders'] = []
        for provider, label in (('claude_api', 'Claude API'), ('openai', 'OpenAI API')):
            store = getattr(state, 'api_keys', {}).get(provider)
            configured = bool(store is not None and store.status().get('configured'))
            result['catalog']['characterAIProviders'].append({'id': provider, 'label': label,
                'models': list(API_MODELS.get(provider, ())), 'configured': configured})
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
        import platform
        result["catalog"]["storage"] = {"dataDirectory": str(state.config.data_dir), "python": platform.python_version()}
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
        key: getattr(ai, key) for key in ("provider", "model", "approved", "request_token_limit", "timeout")
    }
    from newsflow.intelligence.api_settings import read_api_settings
    result["catalog"]["apiSettingsDefaults"] = {}
    for provider in ("openai", "claude_api"):
        current = read_api_settings(state.sessions, provider)
        result["catalog"]["apiSettingsDefaults"][provider] = {
            "provider": provider, "model": current.model, "approved": current.approved,
            "search_enabled": current.search_enabled, "search_approved": current.search_approved,
            "request_limit_usd": str(current.request_limit_usd),
            "input_price_per_1m": str(current.input_price_per_1m or ""),
            "output_price_per_1m": str(current.output_price_per_1m or ""),
            "search_price_per_1k": str(current.search_price_per_1k or ""),
            "request_token_limit": ai.request_token_limit, "timeout": ai.timeout}
    tts = tts_settings(state.sessions)
    result["formDefaults"]["video_save_tts"] = {
        key: tts[key] for key in ("enabled", "voice_id", "model", "job_limit", "commercial")
    }
    video = video_settings(state.sessions)
    result["formDefaults"]["video_ai_save_settings"] = {
        key: value(getattr(video, key))
        if key != "job_limit"
        else str(getattr(video, key))
        for key in (
            "provider",
            "host",
            "approved",
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



@router.get("/api/studio/production-context")
def core_production_context(request: Request):
    """Reuse saved TOP3/analysis/script associations; never invoke a provider."""
    from .core_context import production_context
    with request.app.state.sessions() as session:
        return production_context(session)
