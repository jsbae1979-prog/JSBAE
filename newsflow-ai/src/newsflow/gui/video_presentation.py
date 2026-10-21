"""Read-only video status shared by the library and job detail. No retries."""

def video_presentation(job, *, playable=False):
    status = job.status
    state = {
        "queued": ("제작 대기", "준비 순서를 기다립니다."),
        "running": ("영상 제작 중", "현재 작업의 진행 상태를 확인하세요."),
        "failed": ("제작 실패", "원인 확인 필요 · 저장된 오류 기록을 확인하세요."),
        "unknown": ("결과 불명", "기록을 보존하며 자동 재전송하지 않습니다."),
        "interrupted": ("제작 중단", "중단된 작업입니다. 설정과 승인부터 확인하세요."),
        "success": ("영상 생성 완료 · 검토 필요" if playable else "영상 파일 확인 필요",
                    "게시 전 영상·음성·출처를 직접 확인하세요." if playable else "파일 보존 상태를 확인하세요."),
        "simulated": ("모의 결과", "실제 재생 영상이 아닙니다."),
    }.get(status, ("상태 확인 필요", "저장된 작업 기록을 확인하세요."))
    stage = (job.metadata_json or {}).get("failure_stage")
    stages = {"voice": ("음성 생성", "선택한 음성·연결·사용 조건을 확인하세요.", "/simple-settings#selected-voice"),
              "audio": ("음성 길이", "대본 분량과 실제 음성 길이를 확인하세요.", "/ai"),
              "audio_review": ("음성 분량 검토", "대본 분량을 수정한 뒤 직접 제작을 승인하세요.", "/ai"),
              "subtitle": ("자막 배치", "자막 길이와 안전 영역을 확인하세요.", "/video"),
              "font": ("한국어 글꼴", "설치된 한국어 글꼴을 확인하세요.", "/simple-settings#selected-video"),
              "dependency": ("영상 도구", "FFmpeg·ffprobe 경로를 확인하세요.", "/simple-settings#selected-video"),
              "validation": ("완성 파일 검사", "코덱·해상도·길이 검사 기록을 확인하세요.", "/video"),
              "disk": ("저장 공간", "남은 디스크 공간을 확인하세요.", "/video")}
    # Legacy stage is recognized only from the application's own fixed prefix.
    if not stage and status == "failed" and (job.message or "").startswith("음성 생성 실패."):
        stage = "voice"
    known = stages.get(stage) if status == "failed" else None
    return {"label": state[0], "message": known[1] if known else state[1],
            "stage": known[0] if known else "원인 확인 필요" if status == "failed" else "",
            "action": known[2] if known else "/simple-settings#quality",
            "active": status in {"running", "queued"}}
