"""Shared, read-only selection view over the existing production preference stores."""

from urllib.parse import urlencode

from .production_status import _date, production_context

NEWS_METHODS = {
    "claude_api|ai_web": "Claude API · 웹 뉴스",
    "claude_api|rss": "Claude API + RSS",
    "claude_code|rss": "Claude Code + RSS",
    "codex|rss": "Codex + RSS",
    "offline|rss": "RSS · Offline 대본",
    "openai|ai_web": "OpenAI API · 웹 뉴스",
    "openai|rss": "OpenAI API + RSS",
    "claude_api|hybrid": "Claude API · 웹 뉴스 + RSS 보완",
    "openai|hybrid": "OpenAI API · 웹 뉴스 + RSS 보완",
}


def _light(color, label, detail):
    return {"color": color, "label": label, "detail": detail}


def selection_lights(request, view):
    """Reuse local gates/evidence only. No authentication, synthesis or network checks."""
    from .api_settings_routes import connection_status

    cfg, statuses = view["production_config"], view["provider_statuses"]
    provider, policy = cfg["provider"], cfg["acquisition_policy"]
    if policy != "rss" and provider not in {"openai", "claude_api"}:
        news = _light("red", "웹 검색 미지원", "선택한 AI의 웹 검색은 BLOCKED입니다. 다른 방식으로 자동 전환하지 않습니다.")
    elif provider in {"openai", "claude_api"}:
        gate = (connection_status(request, provider, "analysis") if policy == "rss"
                else view["api_connections"][provider])
        code = gate.get("connection_check", {}).get("code", "not_checked")
        if not gate["key"].get("configured"):
            news = _light("red", "키 미등록", "API Key를 등록해야 합니다. 키 등록과 실제 인증은 별개입니다.")
        elif code in {"key_error", "auth_error", "permission", "model_unavailable", "rate_limit", "unsupported_model"}:
            news = _light("red", "연결·권한 확인 필요", gate["connection_check"]["message"])
        elif gate["ready"] and gate["authentication_verified"]:
            news = _light("green", "분석 조건 확인됨" if policy == "rss" else "검색 조건 확인됨",
                          "현재 모델의 저장된 인증·해당 단계 조건이 충족됐습니다. 단계별 사용 동의는 별도이며 실제 호출 성공을 보장하지 않습니다.")
        else:
            news = _light("yellow", "미확인·승인 확인 필요", " · ".join(gate["reasons"]) or "현재 모델의 실제 연결을 확인하지 않았습니다.")
    elif provider == "offline":
        news = _light("green", "로컬 처리", "외부 AI 연결 없이 RSS 자료로 로컬 대본을 준비합니다.")
    else:
        cached = getattr(request.app.state, "claude_status" if provider == "claude_code" else "codex_status", {})
        state = cached.get("state")
        if state == "ready" and cached.get("ready") and cached.get("authenticated"):
            news = _light("green", "로그인 확인 기록", "저장된 구독 로그인 상태입니다. 실행별 동의·구독 사용량 조건은 유지됩니다.")
        elif statuses[provider]["status_code"] in {"install", "login", "unavailable", "limited"}:
            news = _light("red", "설치·로그인 확인 필요", statuses[provider]["availability"])
        else:
            news = _light("yellow", "연결 미확인", "설치·로그인 확인 기록이 없습니다. 이 화면에서 CLI를 실행하지 않습니다.")
    if policy in {"rss", "hybrid"}:
        rss = view["rss_readiness"]
        if not rss["enabled"]:
            news = _light("red", "RSS 출처 없음", "활성 RSS 출처를 등록하세요. " + news["detail"])
        elif rss["passed"] < rss["enabled"] or rss["failed"]:
            if news["color"] == "green":
                news = _light("yellow", "RSS 확인 필요", "활성 RSS 출처 중 연결 확인이 안 된 항목이 있습니다. " + news["detail"])
        else:
            news["detail"] += " RSS는 마지막 연결 검사 기록이며 현재 수집 성공을 보장하지 않습니다."
    engine = cfg["voice_engine"]
    voice_state = statuses[engine]
    if cfg["voice"] == "offline-silence":
        voice = _light("yellow", "무음 검토용", "음성 없이 제작하는 선택입니다. 음성 연결 성공이 아닙니다.")
    elif not cfg["voice_available"] and engine != "elevenlabs":
        voice = _light("red", "음성 준비 필요", "선택한 음성·모델을 사용할 수 없습니다. 다른 음성으로 자동 전환하지 않습니다.")
    elif engine == "elevenlabs":
        voice = _light("yellow" if voice_state["status_code"] == "check" else "red",
                       "계정·사용 동의 확인 필요" if voice_state["status_code"] == "check" else "음성 설정 필요",
                       voice_state["configuration"] + " · " + voice_state["availability"])
    elif voice_state["status_code"] == "configured":
        voice = _light("green", "로컬 검사 통과 기록", voice_state["evidence"])
    else:
        voice = _light("red" if voice_state["status_code"] in {"unavailable", "install"} else "yellow",
                       "로컬 음성 확인 필요", voice_state["evidence"])
    video_state = statuses["higgsfield" if cfg["video_provider"] == "higgsfield" else "ffmpeg"]
    if cfg["video_provider"] == "higgsfield":
        video = _light("yellow" if video_state["status_code"] == "configured" else "red",
                       "장면별 승인 필요" if video_state["status_code"] == "configured" else "영상 설정 필요",
                       video_state["configuration"] + " · " + video_state["availability"])
    elif video_state["status_code"] == "configured":
        video = _light("green", "로컬 검사 통과 기록", video_state["evidence"])
    else:
        video = _light("red" if video_state["status_code"] in {"install", "unavailable"} else "yellow",
                       "설치·실행 확인 필요", video_state["evidence"])
    for light, saved, scope in ((news, statuses[provider], "기사 분석" if policy == "rss" else "뉴스 검색"),
                                (voice, voice_state, "음성 설치·설정"), (video, video_state, "영상 도구·설정")):
        light["state"] = {"green": "준비됨", "yellow": "미검증", "red": "차단됨"}[light["color"]]
        light["checked_at"] = saved.get("checked_at")
        light["scope"] = scope
    if provider in {"openai", "claude_api"} and "gate" in locals():
        news["checked_at"] = _date(gate.get("connection_check", {}).get("checked_at"))
    news["action_url"] = "/sources" if news["label"] in {"RSS 출처 없음", "RSS 확인 필요"} else "/simple-settings#selected-ai"
    voice["action_url"] = "/video/tts" if engine == "elevenlabs" else "/simple-settings#selected-voice"
    video["action_url"] = "/video-ai-settings" if cfg["video_provider"] == "higgsfield" else "/simple-settings#selected-video"
    if provider in {"openai", "claude_api"}:
        news["scope"] = "인증·모델 조회 기록 / " + news["scope"] + " 실행 조건(로컬)"
    return {"news": news, "voice": voice, "video": video}


def selection_context(request, overview=None):
    view = overview if overview is not None else production_context(request)
    config, statuses = view["production_config"], view["provider_statuses"]
    method = config["provider"] + "|" + config["acquisition_policy"]
    methods = dict(NEWS_METHODS)
    # Preserve a previous unsupported combination visibly; never silently choose RSS.
    if method not in methods:
        methods[method] = config["provider_label"] + " · " + view["acquisition_labels"][config["acquisition_policy"]]
    ai = statuses[config["provider"]]
    voice = statuses[config["voice_engine"]]
    video = statuses["higgsfield" if config["video_provider"] == "higgsfield" else "ffmpeg"]
    query = dict(request.query_params)
    query["selection_saved"] = "true"
    return {
        "lights": selection_lights(request, view),
        "method": method, "methods": methods, "method_label": methods[method],
        "method_short": methods[method].replace(" · 웹 뉴스", "").replace(" · Offline 대본", ""),
        "voice": config["voice"], "voice_label": config["voice_label"], "voices": view["voice_choices"],
        "voice_short": ("Windows" if config["voice_engine"] == "windows" else
                        "Supertonic " + config["voice"].split(":")[-1] if config["voice_engine"] == "supertonic" else
                        "ElevenLabs" if config["voice_engine"] == "elevenlabs" else "무음"),
        "video": config["video_provider"],
        "video_label": "Higgsfield + FFmpeg" if config["video_provider"] == "higgsfield" else "FFmpeg",
        "news_status": ai["authentication"] + " · " + ai["availability"],
        "voice_status": ("무음 검토용 · 실제 음성 없음" if config["voice"] == "offline-silence" else
                         voice["status_label"] + " · " + voice["availability"]),
        "video_status": video["status_label"] + " · " + video["availability"],
        "return_to": request.url.path + "?" + urlencode(query),
        "saved": request.query_params.get("selection_saved") == "true",
    }
