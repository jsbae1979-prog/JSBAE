"""Shared read-only visibility for feed results and their review copies."""
from sqlalchemy import select
from newsflow.db.models import ImagePost, WorkspaceRemoval

def feed_identity(post):
    sources=post.sources if isinstance(post.sources,dict) else {}
    batch=sources.get('feed_batch_id');selection=sources.get('selection')
    rank=selection.get('rank') if isinstance(selection,dict) else None
    return f'feed:{batch}:{rank}' if type(batch) is int and batch>0 and type(rank) is int and rank in (1,2,3) else None

def hidden_items(session):
    removed=set(session.scalars(select(WorkspaceRemoval.key)))
    hidden={key.removeprefix('library:') for key in removed if key.startswith('library:feed:')}
    for post in session.scalars(select(ImagePost)):
        if f'library:post:{post.id}' in removed:
            identity=feed_identity(post)
            if identity:hidden.add(identity)
    return hidden
