"""Deterministic local shortlist, not an invented popularity score or deletion."""
from .ranking import CATEGORIES

PER_CATEGORY = 30


def shortlist(articles):
    # Existing collection period filtering remains upstream. Latest first, stable ID tie break.
    groups = {key: [] for key in (*CATEGORIES, '미분류')}
    for article in sorted(articles, key=lambda a: (a.published_at.isoformat() if a.published_at else '', a.id), reverse=True):
        groups[article.category if article.category in CATEGORIES else '미분류'].append(article)
    selected = [a for rows in groups.values() for a in rows[:PER_CATEGORY]]
    return selected, {'perCategory': PER_CATEGORY, 'strategy': 'latest_per_category',
        'collectedCount': len(articles), 'candidateCount': len(selected),
        'categories': [{'category': key, 'available': len(rows), 'selected': min(len(rows), PER_CATEGORY)}
                       for key, rows in groups.items() if rows]}
