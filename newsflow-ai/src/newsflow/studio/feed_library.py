"""Read-only, per-image library projection; no generation or publishing side effects."""
from sqlalchemy import select
from newsflow.db.models import IntelligenceRun, ImagePost, WorkspaceRemoval
from newsflow.creation.top_three_feeds import KIND
from newsflow.creation.feed_designs import FeedDesigns
from newsflow.publishing.service import PublishingError

from newsflow.creation.feed_visibility import hidden_items

def images(feeds):
    designs=FeedDesigns(feeds)
    with feeds.sessions() as s:
        rows=list(s.scalars(select(IntelligenceRun).where(IntelligenceRun.kind==KIND).order_by(IntelligenceRun.id.desc()).limit(100)))
        hidden=hidden_items(s)
        # A review copy already in the library represents this exact version.
        represented={(p.sources.get('feed_batch_id'),p.sources.get('selection',{}).get('rank'),p.sources.get('feed_design_version',0))
                     for p in s.scalars(select(ImagePost)) if isinstance(p.sources,dict)}
    result=[]
    for row in rows:
        for item in row.result.get('items',[]):
            rank=item.get('rank');identifier=f'feed:{row.id}:{rank}'
            if rank not in (1,2,3) or identifier in hidden:continue
            media=None;version=0;title=item.get('content',{}).get('title','뉴스 이미지')
            try:
                versions=designs.state(row.id,rank)['versions']
                if versions:
                    v=designs.version(row.id,rank,versions[-1]['version'])
                    version=v['version'];title=v['design']['title']
                    media=f'/api/feed-batches/{row.id}/items/{rank}/design-file/{version}'
            except (PublishingError,ValueError,OSError):pass
            if media is None and item.get('status')=='success':
                try:
                    feeds.path(row.id,rank);media=f'/api/feed-batches/{row.id}/items/{rank}/file'
                except (PublishingError,ValueError,OSError):pass
            if not media or (row.id,rank,version) in represented:continue
            result.append({'id':identifier,'title':title,'kind':'image','technicalStatus':'success',
                'updatedAt':row.created_at.isoformat(),'mediaUrl':media,'thumbnailUrl':media,
                'href':f'/studio/images?mode=top3&batch_id={row.id}&rank={rank}',
                'sourceLabel':f'뉴스 이미지 · 작업 #{row.id} · TOP {rank}'+(f' · 편집 버전 {version}' if version else ''),
                'reviewStatus':'review_required','feedBatchId':row.id,'feedRank':rank,'designVersion':version,'purgeable':False})
    return result
