"""Replace visible collections, retain video sources and all historical evidence."""
from sqlalchemy import select

from newsflow.db.models import (
    AutopilotArtifact,
    AutopilotJob,
    ContentDraft,
    NewsArticle,
    NewsListState,
    VideoProject,
)


def used_article_ids(session) -> set[int]:
    identifiers = set(session.scalars(select(NewsListState.article_id).where(NewsListState.used.is_(True))))
    all_sources = list(session.scalars(select(VideoProject.sources)))
    all_sources.extend(session.scalars(select(ContentDraft.sources).join(
        VideoProject, VideoProject.draft_id == ContentDraft.id)))
    for sources in all_sources:
        for article in (sources or {}).get("articles", []):
            identifier = article.get("id", article.get("article_id"))
            if type(identifier) is int:
                identifiers.add(identifier)
    identifiers.update(session.scalars(select(AutopilotJob.article_id).join(
        AutopilotArtifact, AutopilotArtifact.job_id == AutopilotJob.id).where(
        AutopilotJob.article_id.is_not(None), AutopilotArtifact.kind == "render_job_id")))
    return identifiers


def remember_video_sources(session) -> None:
    for identifier in used_article_ids(session):
        if session.get(NewsArticle, identifier) is None:
            continue
        state = session.get(NewsListState, identifier)
        if state is None:
            state = NewsListState(article_id=identifier, hidden=False, used=True)
            session.add(state)
        state.used = True


def replace_collection(session, identifiers: list[int]) -> None:
    # Empty/failed collections must not erase the last useful list.
    if not identifiers:
        return
    remember_video_sources(session)
    keep = set(identifiers)
    for identifier in session.scalars(select(NewsArticle.id)):
        state = session.get(NewsListState, identifier)
        if state is None:
            state = NewsListState(article_id=identifier, hidden=False, used=False)
            session.add(state)
        state.hidden = identifier not in keep


def visible_news():
    return NewsArticle.id.not_in(select(NewsListState.article_id).where(NewsListState.hidden.is_(True)))
