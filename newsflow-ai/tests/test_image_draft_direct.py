import json
from test_top_three_selection import feeds
from newsflow.creation.catalog import DEFAULTS
from test_standalone_image_access import standalone
from test_feed_budget import budget_setup

def test_json_draft_without_reference_preserves_security_and_no_generation(standalone):
    x=standalone;c=x.client
    data={**DEFAULTS['image'],'prompt':'짧은 한국어 문구와 멋진 바다 이미지','csrf_token':c.cookies.get('newsflow_csrf')}
    headers={'Accept':'application/json','Origin':str(c.base_url).rstrip('/')}
    r=c.post('/image-studio/drafts',data=data,headers=headers)
    assert r.status_code==200 and r.headers['cache-control']=='no-store'
    identifier=r.json()['draft_id'];assert identifier!=x.draft
    draft=x.studio.get(identifier);assert draft.result['prompt']==data['prompt']
    assert not draft.options.get('reference') and not x.calls
    for change in ({'csrf_token':'bad'},{'csrf_token':''}):
        assert c.post('/image-studio/drafts',data={**data,**change},headers=headers).status_code==403
    assert c.post('/image-studio/drafts',data=data,headers={**headers,'Origin':'https://other.invalid'}).status_code==403
    assert c.post('/image-studio/drafts',data={**data,'model':'invalid'},headers=headers).status_code==422
    assert not x.calls

def test_image_gallery_removal_restore_keeps_output_and_other_draft(standalone):
    x=standalone;c=x.client;assert x.post().status_code==303
    output=x.studio.output(x.draft);path=x.owner.generation.path(output.id);before=path.read_bytes()
    other=x.studio.create('다른 합성 이미지',DEFAULTS['image'])
    url='/api/studio/modules/images'
    ids=lambda:{row['id'] for row in c.get(url).json()['collections']['drafts']}
    assert {x.draft,other}<=ids()
    data={'items':json.dumps([f'image:{x.draft}']),'confirm':'true','csrf_token':c.cookies.get('newsflow_csrf')}
    headers={'Origin':str(c.base_url).rstrip('/')}
    assert c.post('/api/studio/library/remove',data=data,headers=headers).status_code==200
    assert x.draft not in ids() and other in ids()
    assert path.read_bytes()==before and x.studio.output(x.draft).id==output.id
    assert c.post('/api/studio/library/restore',data=data,headers=headers).status_code==200
    assert {x.draft,other}<=ids() and path.read_bytes()==before and len(x.calls)==1
