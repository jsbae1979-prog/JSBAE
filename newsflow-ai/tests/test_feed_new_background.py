from copy import deepcopy
from types import SimpleNamespace
from test_photo_feed_editor import feeds, prepared, photo
from newsflow.creation.feed_designs import FeedDesigns

def test_new_background_is_proposed_without_overwriting_old_versions(feeds,tmp_path):
    designs,b,state,design=prepared(feeds)
    saved=designs.save(b,1,state['revision'],state['background'],design,export=True)
    old=deepcopy(designs.state(b,1));old_file=designs.path(old['versions'][0]['filename'],old['versions'][0]['sha256']).read_bytes()
    new=tmp_path/'new.png';new.write_bytes(photo())
    # Distinct new media, independent of the frozen version and no network transport.
    from PIL import Image
    Image.new('RGB',(1080,1350),'orange').save(new)
    feeds.generation=SimpleNamespace(path=lambda *a,**kw:new)
    row=feeds.get(b);result=deepcopy(row.result)
    result['items'][0].update(status='success',generation_id=202,attempt=2)
    feeds._save(b,result)
    view=designs.view(b,1)
    assert view['newGeneratedBackground']=='generated'
    assert designs.state(b,1)==old and designs.path(old['versions'][0]['filename'],old['versions'][0]['sha256']).read_bytes()==old_file
    chosen=designs.save(b,1,old['revision'],'generated',design,export=True)
    assert len(chosen['versions'])==2 and chosen['newGeneratedBackground'] is None
    assert chosen['versions'][0]==old['versions'][0]
