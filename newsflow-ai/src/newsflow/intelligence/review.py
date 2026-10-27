"""Producer notes are separate from broadcast copy; legacy content is never rewritten."""

def scene_findings(content):
    findings = []
    for index, scene in enumerate(content.get("scenes", []), 1):
        notes = list(scene.get("review_notes", []))
        text = scene.get("narration", "")
        if (text.startswith("제공된 요약에는") and ("구체적인 배경이 없어" in text or "자료가 부족" in text)
                and "원문 확인" in text):
            notes.append("기존 내레이션에 제작자용 안내가 섞여 있습니다. 방송 문장과 분리해 직접 수정하세요. 원문은 자동 변경하지 않았습니다.")
        if notes:
            findings.append({"scene": index, "notes": notes})
    return findings
