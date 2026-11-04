"""Local, explainable recommendation before persistence; never a measured popularity rank."""
from datetime import UTC, timedelta
from .dedup import canonical_url, similar_title
from .ranking import rank
from .recent_filter import check_hours

LIMIT = 30

def recommend(articles, now, hours):
    check_hours(hours)
    now = now.replace(tzinfo=UTC) if now.tzinfo is None else now
    cutoff = now - timedelta(hours=hours)
    groups, old, future = [], 0, 0
    for item in articles:
        date = item.published_at
        if date is not None and date.tzinfo is None: date = date.replace(tzinfo=UTC)
        if date is not None and date < cutoff:
            old += 1; continue
        if date is not None and date > now:
            future += 1; continue
        group = next((g for g in groups if canonical_url(g[0][0].url) == canonical_url(item.url)
                      or similar_title(g[0][0].title, item.title, g[0][1], date)), None)
        if group is None: groups.append([(item,date)])
        else: group.append((item,date))
    scored=[]
    for group in groups:
        # Prefer the most complete representative; no fabricated date/source/summary.
        item,date=max(group,key=lambda r:(bool(r[0].summary.strip()), bool(r[0].publisher.strip()),
                                         r[1] is not None, r[1].timestamp() if r[1] else 0))
        score=rank(item.title,item.summary,date,{r[0].publisher for r in group},now)
        quality=int(bool(item.summary.strip()))+int(bool(item.publisher.strip()))
        scored.append((item,score.total,quality,date.timestamp() if date else 0,score.components))
    scored.sort(key=lambda r:(-r[1],-r[2],-r[3],canonical_url(r[0].url)))
    picked=scored[:LIMIT]
    return [r[0] for r in picked], {
        'policy':'category_recommendation_v1','limit':LIMIT,'candidates':len(articles),
        'eligible':len(groups),'duplicates_removed':sum(len(g)-1 for g in groups),
        'excluded_old':old,'excluded_future':future,'excluded_rank':max(0,len(groups)-LIMIT),
        'selected':len(picked),'unknown_published_at':sum(r[0].published_at is None for r in picked),
        'measured_popularity':False,
        'ranking':[{'url':r[0].url,'score':r[1],'components':r[4]} for r in picked]}
