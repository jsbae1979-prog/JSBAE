"""Current news workspace only; original articles and saved work stay intact.

A new collection hides the previous round before contacting any feed. Freshly
received IDs are revealed, including duplicates received again in this round.
Physical cleanup remains the existing successful-collection lifecycle policy.
"""
from sqlalchemy import select
from newsflow.db.models import NewsArticle, NewsListState
from .lifecycle import remember_video_sources

def begin_collection(session):
    remember_video_sources(session)
    session.flush()  # Session factories disable autoflush; preserve newly remembered used flags.
    for identifier in session.scalars(select(NewsArticle.id)):
        state=session.get(NewsListState,identifier)
        if state is None:
            state=NewsListState(article_id=identifier,hidden=True,used=False)
            session.add(state)
        state.hidden=True
    session.flush()

def reveal_current(session,identifiers):
    for identifier in dict.fromkeys(identifiers):
        state=session.get(NewsListState,identifier)
        if state is None:
            state=NewsListState(article_id=identifier,hidden=False,used=False)
            session.add(state)
        state.hidden=False
    session.flush()
