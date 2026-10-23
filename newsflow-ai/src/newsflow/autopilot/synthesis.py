"""Conservative selection from the already captured analysis; no search or AI request."""

from datetime import datetime
from difflib import SequenceMatcher

POLICY = "similar_articles_v1"
CLAIM_KIND = "synthesis_article"
MAX_ARTICLES = 5


def choose_articles(evidence: dict, anchor: int) -> list[int]:
    articles = {a["id"]: a for a in evidence.get("articles", [])}
    if anchor not in articles:
        raise ValueError("Missing anchor")
    primary = articles[anchor]
    # Reuse the existing title-similarity groups; recheck direct similarity to the
    # chosen anchor so a chain of loosely related articles cannot broaden the topic.
    group = next((g for g in evidence.get("groups", []) if anchor in g), [anchor])
    chosen = [anchor]
    for identifier in group:
        if identifier in chosen or identifier not in articles:
            continue
        article = articles[identifier]
        if SequenceMatcher(None, primary["title"], article["title"]).ratio() < 0.65:
            continue
        categories = {a.get("category") for a in (primary, article)} - {None, "", "미분류"}
        if len(categories) > 1:
            continue
        if primary.get("published_at") and article.get("published_at"):
            try:
                gap = datetime.fromisoformat(primary["published_at"]) - datetime.fromisoformat(article["published_at"])
                if abs(gap.total_seconds()) > 48 * 3600:
                    continue
            except (ValueError, TypeError):
                continue
        chosen.append(identifier)
        if len(chosen) == MAX_ARTICLES:
            break
    return chosen
