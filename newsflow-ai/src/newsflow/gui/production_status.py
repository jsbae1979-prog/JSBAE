"""Read-only production composition and evidence; never authenticates or sends a request."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select

from newsflow.autopilot.samples import SAMPLE_URL
from newsflow.db.models import (
    AppSetting,
    AudioTrack,
    IntelligenceRun,
    NewsSource,
    NewsSourceCheck,
    RenderJob,
    VideoAIUsage,
)
from newsflow.easy_setup import initial_state, voice_choice_catalog
from newsflow.intelligence.api_providers import API_MODELS
from newsflow.intelligence.capabilities import provider_capabilities
from newsflow.intelligence.settings import external_ready, read_settings, read_studio_settings
from newsflow.video.ai.settings import readiness as video_readiness
from newsflow.video.elevenlabs_tts import ElevenLabsKeys
from newsflow.video.elevenlabs_tts import settings as elevenlabs_settings
from newsflow.video.engine import FFmpegAdapter, RenderError
from newsflow.video.voice_engines import provider_name

from .api_settings_routes import connection_status
from .production_context import ACQUISITION_LABELS, CATEGORY_LABELS, PERIOD_LABELS, acquisition_preferences

PROVIDER_LABELS = {"offline": "Offline", "claude_code": "Claude Code", "codex": "Codex", "openai": "OpenAI API",
                   "claude_api": "Claude API · API Key",
                   "supertonic": "Supertonic 3", "windows": "Windows SAPI", "elevenlabs": "ElevenLabs",
                   "higgsfield": "Higgsfield", "ffmpeg": "FFmpeg", "rss": "RSS"}
STATUS_LABELS = {"ready": "사용 준비 완료", "configured": "설정 확인됨", "setup": "설정 필요",
                 "install": "설치 필요", "login": "로그인 필요", "check": "연결 확인 필요",
                 "limited": "사용 제한", "unavailable": "사용 불가", "review": "사용자 검토 필요"}


def _date(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _status(provider, code, configuration, availability, *, authentication="해당 없음", checked_at=None,
            cost="외부 API 비용 없음", evidence="실제 호출 미검증", action="#connections"):
    return {"provider": provider, "provider_label": PROVIDER_LABELS[provider], "status_code": code,
            "status_label": STATUS_LABELS[code], "configuration": configuration, "authentication": authentication,
            "availability": availability, "checked_at": _date(checked_at), "last_success_at": None,
            "evidence": evidence, "cost_notice": cost, "action_url": action}


def _cli_status(provider, cached):
    from newsflow.intelligence.claude_code import CONNECTION_MESSAGES
    from newsflow.intelligence.codex import MESSAGES

    state = cached.get("state", "unchecked")
    codes = {"not_installed": "install", "login_required": "login", "login_started": "login",
             "login_running": "login", "login_cancelled": "login", "manual_login": "login",
             "usage_blocked": "limited", "approval_required": "limited", "busy": "limited",
             "isolation_blocked": "unavailable", "version_check": "unavailable", "version_unsupported": "unavailable",
             "failed": "unavailable", "check_failed": "unavailable", "auth_error": "unavailable",
             "login_failed": "unavailable", "timeout": "check"}
    code = "configured" if state == "ready" and cached.get("ready") else codes.get(state, "check")
    message = (MESSAGES if provider == "codex" else CONNECTION_MESSAGES).get(
        state, "CLI 상태·지원 버전을 다시 확인하세요. 확인되지 않은 상태에서는 실행하지 않습니다.")
    authentication = "구독 로그인 확인됨" if cached.get("authenticated") else "로그인 확인 필요"
    if state == "approval_required":
        authentication = "다른 인증 방식 확인됨 · API 과금 자동 전환 차단"
    elif state == "auth_error":
        authentication = "인증 확인 실패"
    return _status(provider, code,
                   "CLI 설치 확인됨" if cached.get("installed") else "CLI 설치 확인 필요",
                   message + " · RSS 분석·대본 통합 제작 지원 · 실행별 외부 전송·계정 사용량 동의 필요",
                   authentication=authentication,
                   checked_at=cached.get("checked_at"), cost="본인 구독 사용량·한도 적용 · 무료·무제한 아님",
                   evidence="설치·인증 검사와 실제 생성 성공은 별개입니다."
                   + (" Claude Code 일반 배포 약관 적합성 NOT VERIFIED." if provider == "claude_code" else ""),
                   action="#selected-ai")


def production_context(request) -> dict:
    """Existing configuration is canonical; observations never rewrite or prove current credentials."""
    sessions = request.app.state.sessions
    studio = read_studio_settings(sessions)
    acquisition = acquisition_preferences(sessions)
    checks = getattr(request.app.state, "production_checks", {})
    with sessions() as session:
        values = initial_state(session)["values"]
        if session.get(AppSetting, "autopilot_source") is None:
            values["source"] = "feeds"  # new-user display only; never rewrite a saved sample selection
        sources = list(session.scalars(select(NewsSource).where(NewsSource.enabled, NewsSource.url != SAMPLE_URL)))
        rss_checks = list(session.scalars(select(NewsSourceCheck).where(
            NewsSourceCheck.source_id.in_([item.id for item in sources]))))
        successful = list(session.scalars(select(IntelligenceRun).where(
            IntelligenceRun.status == "success", IntelligenceRun.kind.not_in(["feed_image", "feed_card"])
        ).order_by(IntelligenceRun.id.desc()).limit(100)))
        renders = session.execute(select(RenderJob, AudioTrack).join(
            AudioTrack, AudioTrack.project_id == RenderJob.project_id).where(
                RenderJob.status == "success", AudioTrack.status == "success"
            ).order_by(RenderJob.id.desc()).limit(100)).all()
        video_success = session.scalar(select(VideoAIUsage.updated_at).where(
            VideoAIUsage.provider == "higgsfield", VideoAIUsage.status == "completed"
        ).order_by(VideoAIUsage.updated_at.desc()).limit(1))
        ai_check = session.get(AppSetting, "ai_last_check")
        try:
            ai_check = json.loads(ai_check.value) if ai_check else {}
        except (ValueError, TypeError):
            ai_check = {}
        if not isinstance(ai_check, dict):
            ai_check = {}

    catalog = voice_choice_catalog()
    selected = next((item for item in catalog if item["name"] == values["voice"]), None)
    if selected is None:
        selected = {"name": values["voice"], "label": "저장한 음성 · 현재 확인 불가", "engine": provider_name(values["voice"]),
                    "available": False}
        catalog.append(selected)
    ai_gate = external_ready(sessions, request.app.state.ai_keys)
    video_gate = video_readiness(sessions, request.app.state.video_ai.keys, reported=True)
    statuses = {
        "offline": _status("offline", "ready", "내장 기본 대본", "외부 전송 없이 분석·대본 생성", evidence="출처·대본의 사람 검토 필요"),
        "claude_code": _cli_status("claude_code", getattr(request.app.state, "claude_status", {})),
        "codex": _cli_status("codex", getattr(request.app.state, "codex_status", {})),
    }
    statuses["codex"]["availability"] += " · RSS 자료만 사용 · 웹 검색 BLOCKED"
    latest_rss = max((item.checked_at for item in rss_checks), default=None)
    statuses["rss"] = _status("rss", "configured" if sources else "setup",
        f"활성 출처 {len(sources)}개 · 마지막 검사 통과 {sum(item.status == 'pass' for item in rss_checks)}개",
        "시작할 때 기존 RSS 정책으로 수집 · 최근 검사 결과가 현재 연결을 보장하지 않음",
        checked_at=latest_rss, evidence="기사 출처·발행 시각·사실 확인은 별도 검토", action="#advanced")
    statuses["openai"] = _status("openai", "configured" if ai_gate["ready"] else "setup",
        "키 등록됨" if ai_gate["key"]["configured"] else "API 키 필요",
        "저장된 승인·로컬 토큰 한도 통과" if ai_gate["ready"] else " ".join(ai_gate["reasons"]),
        authentication="모델 조회 성공 기록 있음" if ai_check.get("ok") is True else "실제 API 인증 확인 필요",
        checked_at=ai_check.get("checked_at"), cost=f"유료 API · 로컬 잔여 한도 {ai_gate['remaining_tokens']} 토큰",
        evidence="키 파일 존재·설정 통과는 현재 API 인증 성공이 아닙니다.", action="#selected-ai")
    api_connections = {name: connection_status(request, name) for name in ("openai", "claude_api")}
    for name in ("openai", "claude_api"):
        api = api_connections[name]
        inference = connection_status(request, name, "analysis")
        statuses[name] = _status(name, "configured" if api["key"]["configured"] else "setup",
            "API 키 등록됨" if api["key"]["configured"] else "API Key 미등록",
            " ".join(inference["reasons"]) if not inference["ready"] else "분석·대본 실행 조건 확인됨",
            authentication="실제 인증 확인 기록 있음" if api["authentication_verified"] else "실제 연결 미확인",
            cost="별도 API 과금 · 월 예산·보고 사용량 확인 · 로컬 집계는 공급사 청구액과 다름",
            evidence="설정 완료와 실제 검색·분석·대본 성공은 별개입니다.", action="#selected-ai")
    for name in ("offline", "claude_code", "codex", "openai", "claude_api"):
        statuses[name]["capabilities"] = provider_capabilities(name)

    for name in ("windows", "supertonic"):
        available = any(item["engine"] == name and item["available"] for item in catalog)
        checked = checks.get(name, {})
        code = "configured" if checked.get("ok") else "unavailable" if checked else "check" if available else "install"
        statuses[name] = _status(name, code,
            "선택 가능한 로컬 음성 있음" if available else "로컬 음성·모델 설치 확인 필요",
            "음성 생성은 로컬에서 실행하며 사용할 수 없으면 중단합니다.", checked_at=checked.get("checked_at"),
            evidence="설치·무결성 검사 기록 있음 · 실제 생성·사람 청취는 별도" if checked.get("ok") else
            "최근 로컬 검사 실패 · 설치와 모델을 확인하세요." if checked else
            "목록 표시는 실제 생성 성공이나 모델 전체 무결성 검증이 아닙니다.", action="#selected-voice")
    el = elevenlabs_settings(sessions)
    key = ElevenLabsKeys(request.app.state.video.root).status()
    elevenlabs_key = key
    el_ready = key["configured"] and el["enabled"] and bool(el["voice_id"])
    statuses["elevenlabs"] = _status("elevenlabs", "check" if el_ready else "setup",
        "API Key 등록됨" if key["configured"] else "API Key 미등록",
        ("음성 선택·사용 설정 확인 필요 · " if not el_ready else "") + "영상 제작마다 외부 전송 동의 필요 · 공급사 한도 확인 실패 시 호출 차단",
        authentication="공급사 계정 상태 미확인", cost="무료 플랜 비상업용 · 공급사 한도와 로컬 한도 별도",
        evidence="계정 조회·음성 생성을 자동 실행하지 않습니다.", action="#selected-voice")
    statuses["higgsfield"] = _status("higgsfield", "configured" if video_gate["ready"] else "setup",
        "모델 규격·키·승인 준비 · 실제 계정 미검증" if video_gate["ready"] else " ".join(video_gate["reasons"]),
        "전체 장면 계획·생성 승인·관계 검토 후 합성",
        authentication="실제 API 동작 미검증", cost="유료 장면 생성 · 작업별 명시적 승인 · 사용량·청구액 미확인",
        action="#selected-video")
    binary_exists = True
    try:
        for name in ("ffmpeg", "ffprobe"):
            FFmpegAdapter.executable(name, getattr(request.app.state.video.engine, name, None))
    except (RenderError, OSError):
        binary_exists = False
    ffmpeg_check = checks.get("ffmpeg", {})
    code = ("install" if not binary_exists else "configured" if ffmpeg_check.get("ok")
            else "unavailable" if ffmpeg_check else "check")
    statuses["ffmpeg"] = _status("ffmpeg", code,
        "FFmpeg·ffprobe 경로 있음" if binary_exists else "FFmpeg·ffprobe 설치 또는 경로 필요",
        "기본 장면·자막·음성 합성과 최종 MP4 제작", checked_at=ffmpeg_check.get("checked_at"),
        evidence="최근 로컬 버전 검사 기록 있음" if ffmpeg_check.get("ok") else
        "최근 로컬 버전 검사 실패" if ffmpeg_check else "파일 존재 확인만 수행 · 실행 확인 필요",
        action="#selected-video")

    for name, status in statuses.items():
        if name in {"offline", "claude_code", "codex", "openai", "claude_api"}:
            match = next((row for row in successful if row.provider == name and row.kind in {"search", "analysis", "script"}), None)
            status["last_success_at"] = match.finished_at if match else None
        elif name in {"windows", "supertonic", "elevenlabs", "ffmpeg"}:
            match = next((job for job, audio in renders if job.metadata_json.get("playable")
                          and (name == "ffmpeg" or audio.provider == name)), None)
            status["last_success_at"] = match.finished_at if match else None
        elif name == "higgsfield":
            status["last_success_at"] = video_success
        if status["last_success_at"]:
            status["evidence"] += " · 이전 성공 이력은 현재 요청 성공이나 사람 품질 평가를 보장하지 않습니다."

    config = {**values, **acquisition, "duration": int(values["duration"]), "provider": studio["provider"],
              "provider_label": PROVIDER_LABELS[studio["provider"]], "model": studio["model"], "models": studio["models"],
              "voice_label": selected["label"], "voice_available": selected["available"],
              "voice_engine": provider_name(values["voice"]), "video_provider": video_gate["provider"],
              "video_label": "Higgsfield · 별도 장면 승인 필요" if video_gate["provider"] == "higgsfield" else "FFmpeg 기본 장면"}
    actual_ai = "offline" if values["source"] == "sample" else studio["provider"]
    mapping = [("collect", "① 뉴스 수집", "rss"), ("analysis", "② 기사 분석", actual_ai),
               ("script", "③ 대본 생성", actual_ai), ("voice", "④ 한국어 음성", provider_name(values["voice"])),
               ("scene", "⑤ 영상 장면 생성", "higgsfield" if video_gate["provider"] == "higgsfield" else "ffmpeg"),
               ("compose", "⑥ 자막·최종 MP4", "ffmpeg")]
    stages = [{**statuses[provider], "key": key, "label": label} for key, label, provider in mapping]
    for stage in stages[1:3]:
        match = next((row for row in successful if row.provider == actual_ai and row.kind == stage["key"]), None)
        stage["last_success_at"] = match.finished_at if match else None
        if values["source"] == "sample":
            stage["availability"] = (
                f"체험 뉴스는 Offline으로 연습 · 등록 뉴스용 {PROVIDER_LABELS[studio['provider']]} 선택은 보존"
            )
    if values["source"] == "sample":
        stages[0].update(provider_label="체험 뉴스 · 로컬", status_code="ready", status_label="사용 준비 완료",
                         configuration="내장 합성 뉴스", availability="외부 뉴스 수집 없이 연습 자료 사용",
                         checked_at=None, last_success_at=None, evidence="실제 보도로 게시하면 안 되는 체험 자료")
    elif acquisition["acquisition_policy"] != "rss":
        stages[0].update(provider_label=ACQUISITION_LABELS[acquisition["acquisition_policy"]],
                         status_code="unavailable", status_label="웹 뉴스 조사 BLOCKED",
                         availability="실제 검색·출처 확인 경로가 승인·검증되지 않아 실행하지 않습니다. RSS 자동 전환 없음.",
                         last_success_at=None, evidence="AI 연결 성공과 실제 웹 검색 성공은 별개입니다.")
        if actual_ai in api_connections:
            api = api_connections[actual_ai]
            stages[0].update(provider=actual_ai,
                provider_label=PROVIDER_LABELS[actual_ai] + (" + RSS 보완" if acquisition["acquisition_policy"] == "hybrid" else ""),
                configuration="공식 API 검색 구현됨 · " + statuses[actual_ai]["configuration"],
                authentication=statuses[actual_ai]["authentication"], cost_notice=statuses[actual_ai]["cost_notice"],
                status_code="configured" if api["ready"] else "unavailable",
                status_label="실행 조건 확인됨" if api["ready"] else "웹 뉴스 조사 BLOCKED",
                availability=" ".join(api["reasons"]) if not api["ready"] else "검색 → 같은 API 분석·대본 → 사용자 검토",
                evidence="도구 검색 증거와 AI 요약을 구분합니다. 원문 전체 사실 검증을 뜻하지 않습니다.")
    if values["voice"] == "offline-silence":
        stages[3].update(provider_label="Offline 무음", configuration="무음 검토영상 선택됨",
                         availability="실제 음성 없이 자막 검토영상 제작", last_success_at=None,
                         evidence="음성 생성 성공이나 사람 청취를 의미하지 않습니다.")
    stages.append({**_status("offline", "review", "검토 기록과 기존 게시 대기함 유지", "사용자 직접 확인 · 실제 SNS 게시 차단",
                             evidence="사람의 대본·최종 영상·출처·권리 확인", action="#advanced"),
                   "key": "review", "label": "⑦ 검토·게시 준비", "provider_label": "사용자 검토"})
    unchecked = {"state": "unchecked", "ready": False, "version": None, "checked_at": None,
                 "message": "아직 연결을 확인하지 않았습니다. 아래 확인 버튼을 눌러 주세요."}
    return {"production_config": config, "pipeline_stages": stages, "provider_statuses": statuses,
            "rss_readiness": {"enabled": len(sources), "passed": sum(item.status == "pass" for item in rss_checks),
                              "failed": sum(item.status != "pass" for item in rss_checks)},
            "api_connections": api_connections, "legacy_api_settings": read_settings(sessions),
            "elevenlabs_config": el, "video_ai_budget": video_gate,
            "acquisition_labels": ACQUISITION_LABELS, "category_labels": CATEGORY_LABELS, "period_labels": PERIOD_LABELS,
            "voice_choices": catalog, "studio_defaults": studio, "elevenlabs_key": elevenlabs_key,
            "model_choices": {name: [{"value": model, "label": model} for model in models]
                              for name, models in {**API_MODELS, "offline": ("offline",),
                                                   "claude_code": ("sonnet", "opus", "haiku"),
                                                   "codex": ("default",)}.items()},
            "claude_status": getattr(request.app.state, "claude_status", unchecked),
            "codex_status": getattr(request.app.state, "codex_status", unchecked)}
