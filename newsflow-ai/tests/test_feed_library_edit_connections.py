"""Synthetic local assets only. All files/DBs are temporary; never call AI."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import pytest
from PIL import Image
from sqlalchemy import select
from newsflow.db.models import IntelligenceRun,WorkspaceRemoval,ImagePost,NewsSource,NewsArticle
from newsflow.studio.feed_library import images
from newsflow.studio.library_visibility import LibraryVisibility,parse_items,LibraryVisibilityError
from newsflow.studio.library_purge import LibraryPurge,PurgeError
from test_photo_feed_editor import feeds,prepared,photo
from test_library_visibility import post

def completed(feeds):
    s,b,state,d=prepared(feeds);raw=photo();result=deepcopy(feeds.get(b).result)
    feeds.root.mkdir(exist_ok=True,parents=True)
    for i in result['items']:
        name=f'feed-{b}-{i["rank"]}-1.jpg';(feeds.root/name).write_bytes(raw)
        i.update(status='success',filename=name,sha256=sha256(raw).hexdigest(),generation_id=999)
    feeds._save(b,result)
    return s,b,state,d

def test_library_individual_images_readonly_latest_saved_and_no_publishing(app,client,feeds):
    s,b,state,d=completed(feeds);before=deepcopy(feeds.get(b).result)
    saved=s.save(b,2,0,'result',{**d,'title':'두 번째 편집 이미지'},export=True)
    rows=images(feeds);assert {r['id'] for r in rows}=={f'feed:{b}:{n}' for n in (1,2,3)}
    second=next(r for r in rows if r['feedRank']==2)
    assert second['title']=='두 번째 편집 이미지' and second['mediaUrl'].endswith('/items/2/design-file/1')
    assert 'rank=2' in second['href']
    assert feeds.get(b).result==before and s.state(b,2)['revision']==saved['revision']
    result=client.get('/api/studio/modules/library').json()
    assert len([p for p in result['projects'] if p['id'].startswith('feed:')])==3
    assert not any(p['id'].startswith('feed:') for p in client.get('/api/studio/modules/publishing').json()['projects'])
    assert all(client.get(r['mediaUrl']).status_code==200 for r in rows)

def test_hide_restore_gallery_library_atomic_preserves_files(app,client,feeds):
    s,b,state,d=completed(feeds);rows=images(feeds);before=deepcopy(feeds.get(b).result)
    originals={p.name:sha256(p.read_bytes()).hexdigest() for p in feeds.root.glob('*.jpg')}
    ids=[f'feed:{b}:1',f'feed:{b}:3'];visibility=LibraryVisibility(feeds.sessions,app.state.character)
    assert post(client,'remove',ids,csrf_token='wrong').status_code==403
    assert post(client,'remove',ids).status_code==200
    assert [r['feedRank'] for r in images(feeds)]==[2]
    assert [r['rank'] for r in feeds.view(b)['items'] if r['libraryHidden']]==[1,3]
    assert all(not r['purgeable'] for r in visibility.listing())
    with feeds.sessions() as session:
        marker=session.get(WorkspaceRemoval,'library:'+ids[0])
        with pytest.raises(PurgeError,match='linked'):LibraryPurge(app.state)._plan(session,ids[0],marker)
    assert post(client,'restore',ids).status_code==200
    assert len(images(feeds))==3 and not any(r['libraryHidden'] for r in feeds.view(b)['items'])
    assert feeds.get(b).result==before
    assert originals=={p.name:sha256(p.read_bytes()).hexdigest() for p in feeds.root.glob('*.jpg')}
    assert post(client,'remove',[ids[0],f'feed:{b}:4']).status_code==422
    assert len(images(feeds))==3

@pytest.mark.parametrize('value',['feed:0:1','feed:1:4','feed:9223372036854775808:1','feed:1:1/file','feed:1:1:1'])
def test_bad_feed_identity(value):
    with pytest.raises(LibraryVisibilityError):parse_items([value])

def test_missing_or_pending_image_not_reported_completed(feeds):
    s,b,state,d=completed(feeds);feeds.path(b,2).unlink()
    result=deepcopy(feeds.get(b).result);result['items'][2]['status']='pending';feeds._save(b,result)
    assert [r['feedRank'] for r in images(feeds)]==[1]

def test_same_background_choices_deduplicate_but_history_preserved(feeds):
    s,b,state,d=prepared(feeds)
    v1=s.save(b,1,state['revision'],state['background'],d,export=True)
    v2=s.save(b,1,v1['revision'],v1['background'],{**d,'accent':'#ffaa33'},export=True)
    assert len(v2['versions'])==2 and len(v2['candidates'])==1
    assert v2['candidates'][0]['id']=='version:2'
    assert {'version:1','version:2'}.issubset(v2['candidates'][0]['aliases'])
    assert s.preview(b,1,v2['revision'],'version:1',d)==s.preview(b,1,v2['revision'],'version:2',d)
    other=BytesIO();Image.new('RGB',(1080,1350),'#a24422').save(other,'PNG')
    v3=s.upload(b,1,v2['revision'],other.getvalue(),'photo','두 번째 이미지')
    assert len(v3['candidates'])==2
    assert s.preview(b,1,v3['revision'],v3['background'],d)!=s.preview(b,1,v3['revision'],'version:2',d)
    assert len(s.state(b,1)['versions'])==2

def test_old_batch_direct_get_readonly(client,feeds,monkeypatch):
    s,b,state,d=completed(feeds);before=deepcopy(feeds.get(b).result)
    monkeypatch.setattr(feeds,'recent',lambda:[])
    assert client.get(f'/api/feed-batches?batch_id={b}').json()['batches'][0]['id']==b
    assert client.get('/api/feed-batches?batch_id=0').status_code==422
    assert feeds.get(b).result==before

def test_review_copy_dedup_and_bidirectional_visibility(app,client,feeds):
    s,b,state,d=completed(feeds)
    with feeds.sessions.begin() as db:
        source=NewsSource(name='Synthetic',url='https://example.com/s',enabled=False);db.add(source);db.flush()
        article=NewsArticle(source_id=source.id,title='합성',publisher='Fixture',url='https://example.com/a',canonical_url='https://example.com/a');db.add(article);db.flush()
        review=ImagePost(article_id=article.id,title='검토본',caption='',sources={'feed_batch_id':b,'selection':{'rank':1}},filename='missing.jpg',sha256='a'*64,ai_disclosure='AI')
        db.add(review);db.flush();pid=review.id
    assert [i['feedRank'] for i in images(feeds)]==[2,3]
    assert post(client,'remove',[f'feed:{b}:1']).status_code==200
    assert f'post:{pid}' not in {p['id'] for p in client.get('/api/studio/modules/library').json()['projects']}
    assert feeds.view(b)['items'][0]['libraryHidden']
    assert post(client,'restore',[f'feed:{b}:1']).status_code==200
    assert f'post:{pid}' in {p['id'] for p in client.get('/api/studio/modules/library').json()['projects']}
    assert post(client,'remove',[f'post:{pid}']).status_code==200
    assert feeds.view(b)['items'][0]['libraryHidden']
    assert post(client,'restore',[f'post:{pid}']).status_code==200
    assert not feeds.view(b)['items'][0]['libraryHidden']
