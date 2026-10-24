"""Editable local suggestions from the rendered script, never an AI/API call or approval."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .service import PublishingError, reject_secrets


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def suggest_metadata(title: str, snapshot: dict, sources: dict) -> dict:
    """Copy facts verbatim; reserve caption room for title, tags and platform AI labels.

    URLs are included whole or omitted with a visible notice. Full provenance remains
    in the video record. Existing saved posting drafts always take precedence in the UI.
    """
    empty = {"title": "", "description": "", "hashtags": "", "source_block": "", "notice": "대본과 출처를 확인한 뒤 게시 문구를 작성하세요."}
    summary = snapshot.get("summary", "") if isinstance(snapshot, dict) else ""
    if not isinstance(title, str) or not isinstance(summary, str):
        return empty
    try:
        reject_secrets((title, summary, sources))
    except PublishingError:
        return {**empty, "notice": "민감정보로 보이는 내용이 있어 자동 작성을 중단했습니다. 게시 문구와 출처를 확인하세요."}
    if not 1 <= len(title) <= 100 or len(summary) > 500:
        return empty
    if any(ord(c) < 32 and c not in "\n\t" for c in title + summary):
        return empty
    # Use only words already in the title, without inventing topical claims or trends.
    tags = []
    for word in re.findall(r"[^\W_]+", title, re.UNICODE):
        if 2 <= len(word) <= 20 and any(c.isalpha() for c in word) and word.casefold() not in {t.casefold() for t in tags}:
            tags.append(word)
        if len(tags) == 4:
            break
    hashtags = " ".join("#" + tag for tag in tags)
    budget = min(1800, 2100 - _units(title) - _units(hashtags) - 2)
    description = "대본 기반 초안 · 게시 전 사실·출처 확인 필요"
    if summary.strip():
        description += "\n\n" + summary.strip()
    urls, included, omitted = [], [], 0
    articles = sources.get("articles", []) if isinstance(sources, dict) else []
    for article in articles if isinstance(articles, list) else []:
        if not isinstance(article, dict):
            continue
        entries = article.get("sources", [])
        for source in entries if isinstance(entries, list) else []:
            url = source.get("url") if isinstance(source, dict) else None
            if not isinstance(url, str) or url in urls:
                continue
            try:
                parsed = urlsplit(url)
                safe = parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password
            except ValueError:
                safe = False
            if not safe or any(c.isspace() or ord(c) < 32 for c in url):
                omitted += 1
                continue
            urls.append(url)
            addition = ("\n\n출처:\n" if not included else "\n") + url
            if _units(description + addition) > budget:
                omitted += 1
                continue
            description += addition
            included.append(url)
    notice = "영상에 사용한 대본으로 제목·설명·해시태그를 채웠습니다. 수정 후 검토해 주세요."
    if omitted:
        notice += f" 출처 링크 {omitted}개는 형식·길이 때문에 넣지 못했습니다. ‘영상의 출처 보기’에서 확인하세요."
    return {"title": title, "description": description, "hashtags": hashtags, "notice": notice,
            "source_block": "출처:\n" + "\n".join(included) if included else ""}
