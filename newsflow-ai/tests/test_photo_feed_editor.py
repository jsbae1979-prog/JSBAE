from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
import pytest
from PIL import Image,ImageDraw
from starlette.testclient import TestClient
from newsflow.creation.feed_designs import FeedDesigns
from newsflow.creation.catalog import DEFAULTS
from newsflow.creation.feed_costs import binding
from newsflow.creation.top_three_feeds import prompt_for
from newsflow.publishing.photo_feed import DEFAULT,render,STYLE,clean_image
from newsflow.publishing.service import PublishingError
from test_top_three_selection import feeds
from bat_distribution.operation import OperatingRequests

def photo():
    im=Image.new('RGB',(1080,1350));d=ImageDraw.Draw(im)
    for y in range(1350):d.line((0,y,1080,y),fill=(12+int(y/100),30+int(y/40),65+int(y/25)))
    d.ellipse((660,140,900,380),fill='#f3dba4')
    d.polygon([(0,780),(280,300),(650,850)],fill='#477987');d.polygon([(280,300),(196,480),(390,486)],fill='#cae6ea')
    d.polygon([(350,820),(790,440),(1080,800)],fill='#294b64')
    d.rectangle((0,830,1080,1350),fill='#173d55')
    for y in range(850,1350,22):d.line((100+(y%80),y,900,y),fill='#2c566c',width=2)
    out=BytesIO();im.save(out,'PNG');return out.getvalue()

def prepared(feeds):
    batch=feeds.create(42,DEFAULTS['image']);service=FeedDesigns(feeds)
    state=service.upload(batch,1,0,photo(),'stock','합성 검증 이미지')
    design={**state['draft'],'title':'새 관측 장비 공개\n산악 지역의 변화 확인','description':'2026년 관측 결과 공개 예정\n추가 검토는 진행 중','source':'합성 과학 뉴스','date':'2026.11.01'}
    return service,batch,state,design

def test_local_edits_preserve_batch_budget_other_ranks_and_exact_preview(feeds):
    service,b,state,d=prepared(feeds);before=deepcopy(feeds.get(b).result);cost=binding(feeds.get(b))
    feeds.generation._generate=lambda *a,**k:pytest.fail('No paid call')
    raw=service.preview(b,1,state['revision'],state['background'],d)
    saved=service.save(b,1,state['revision'],state['background'],d,export=True)
    v=saved['versions'][0];assert service.path(v['filename'],v['sha256']).read_bytes()==raw
    assert feeds.get(b).result==before and binding(feeds.get(b))==cost
    assert service.view(b,2)['revision']==0 and service.view(b,3)['versions']==[]
    reopened=FeedDesigns(feeds).view(b,1);assert reopened['draft']==d
    original=service.path(v['filename'],v['sha256']).read_bytes()
    d2={**d,'accent':'#ffaa44','emphasis':'공개','crop':[.1,0,1,.9]}
    saved2=service.save(b,1,saved['revision'],saved['background'],d2,export=True)
    assert len(saved2['versions'])==2 and service.path(v['filename'],v['sha256']).read_bytes()==original
    assert saved2['versions'][0]['background']['filename']!=saved2['versions'][1]['background']['filename']

@pytest.mark.parametrize('patch,match',[(dict(title='혼합 ABC 2026년 20km 계획 '*20),'글자 수'),(dict(title='한글영문 ABC 123 '*9),'줄'),(dict(source='긴출처 '*51),'출처'),(dict(text_y=.78),'겹칩니다'),(dict(crop=[0,0,0,1]),'자르기'),(dict(accent=12),'강조색')])
def test_overflow_requires_explicit_edit_not_shrink_or_truncate(feeds,patch,match):
    s,b,state,d=prepared(feeds)
    with pytest.raises(PublishingError,match=match):s.preview(b,1,state['revision'],state['background'],{**d,**patch})
    assert not s.state(b,1)['versions']

def test_draft_can_save_long_title_then_repair_without_generation(feeds):
    s,b,state,d=prepared(feeds);d['title']='한글 제목 '*20
    saved=s.save(b,1,state['revision'],state['background'],d)
    assert saved['draft']['title']==d['title']
    with pytest.raises(PublishingError):s.save(b,1,saved['revision'],saved['background'],d,export=True)
    fixed=s.save(b,1,saved['revision'],saved['background'],{**d,'title':'한국어·English 2026\n20km 계획 검토 중'},export=True)
    assert len(fixed['versions'])==1

def test_replacement_resets_credit_and_disclosure_and_old_version_survives(feeds):
    s,b,state,d=prepared(feeds);first=s.save(b,1,state['revision'],state['background'],d,export=True)
    replacement=s.upload(b,1,first['revision'],photo(),'ai','새 AI 이미지')
    assert replacement['draft']['credit']=='새 AI 이미지'
    second=s.save(b,1,replacement['revision'],replacement['background'],replacement['draft'],export=True)
    assert second['versions'][0]['background']['kind']=='stock'
    assert second['versions'][1]['background']['kind']=='ai'

def test_bad_image_paths_and_stale_revision(feeds):
    s,b,state,d=prepared(feeds)
    with pytest.raises(PublishingError):s.upload(b,1,state['revision'],b'not image','photo','credit')
    with pytest.raises(PublishingError):s.save(b,1,0,state['background'],d)
    with pytest.raises(PublishingError):s.preview(b,1,state['revision'],'../../secret',d)
    asset=s.state(b,1)['assets'][0];s.path(asset['filename'],asset['sha256']).unlink()
    with pytest.raises(PublishingError):s.preview(b,1,state['revision'],state['background'],d)

def test_style_prompt_uses_image_only_and_cost_binding_changes_only_new_style(feeds):
    b=feeds.create(42,DEFAULTS['image'],feed_style=STYLE);row=feeds.get(b)
    assert row.options['feed_style']==STYLE
    source=row.evidence['sources'][0];source={**source,'title':'폭력 사건 수사 중'}
    p=prompt_for(source,row.result['items'][0]['content'],b,1,feed_style=STYLE)
    assert 'NO text' in p and 'No human faces' in p and 'plain light header' not in p
    old=binding(row);row.options={k:v for k,v in row.options.items() if k!='feed_style'};assert binding(row)!=old

def test_local_routes_csrf_operating_boundary_and_no_mutating_get(app,feeds):
    s,b,state,d=prepared(feeds)
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1:18779') as c:
        c.get('/studio/images');csrf=c.cookies.get('newsflow_csrf');url=f'/api/feed-batches/{b}/items/1/design'
        assert c.get(url).status_code==200 and s.state(b,1)['revision']==state['revision']
        data={'revision':state['revision'],'action':'preview','background':state['background'],'design':json.dumps(d)}
        assert c.post(url,data=data).status_code==403
        r=c.post(url,data={**data,'csrf_token':csrf});assert r.status_code==200,r.text
        preview=c.get(r.json()['previewUrl']);assert preview.headers['content-type']=='image/jpeg'
        saved=c.post(url,data={**data,'action':'render','csrf_token':csrf});assert saved.status_code==200,saved.text
        v=saved.json()['versions'][0];assert c.get(url+'-file/1').content==preview.content
        assert c.post(url,data={**data,'action':'render','csrf_token':csrf}).status_code==409

def test_no_pii_or_foreign_asset_path_in_view(feeds):
    s,b,state,d=prepared(feeds)
    assert 'path' not in s.view(b,1)['candidates'][0]
    assert not str(feeds.root) in json.dumps(s.view(b,1))


from test_image_selection import selected

def test_design_post_keeps_exact_pixels_and_caption_with_no_generation(app,selected):
    from newsflow.creation.top_three_feeds import TopThreeFeeds
    from newsflow.publishing.image_generation import ImageGenerationService
    generation=ImageGenerationService(app.state.sessions,app.state.config.data_dir,None)
    generation._generate=lambda *a,**k:pytest.fail('No paid API')
    feeds=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,generation)
    b=feeds.create(selected[0],DEFAULTS['image']);s=FeedDesigns(feeds)
    state=s.upload(b,1,0,photo(),'stock','직접 제작한 합성 배경')
    d={**state['draft'],'title':'합성 뉴스 · 검토 중','description':'확정 전 계획을 검토합니다.','source':'Fixture'}
    saved=s.save(b,1,state['revision'],state['background'],d,export=True);v=saved['versions'][0]
    posts=app.state.image_posts
    with pytest.raises(PublishingError):s.review(b,1,1,posts,reviewed=True)
    post=s.review(b,1,1,posts,reviewed=True,image_safety_checked=True)
    assert posts.path(post).read_bytes()==s.path(v['filename'],v['sha256']).read_bytes()
    assert posts.get(post).sources['image_kind']=='stock' and d['caption'] in posts.get(post).caption
    assert s.review(b,1,1,posts,reviewed=True,image_safety_checked=True)==post


def test_status_and_numbers_are_flagged_not_invented():
    source={'title':'새 장비 공개 예정','body':'2026년 계획을 검토 중이다.'}
    warnings=FeedDesigns.copy_warnings({'title':'최초 발견 확정 2030년','description':'시행'},source)
    assert any('검토' in x for x in warnings) and any('2030' in x for x in warnings)


def test_article_background_is_local_rights_bound_and_credit_is_explicit(app,selected):
    from newsflow.creation.top_three_feeds import TopThreeFeeds
    from newsflow.publishing.image_generation import ImageGenerationService
    from newsflow.db.models import NewsArticle
    service=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,ImageGenerationService(app.state.sessions,app.state.config.data_dir,None))
    b=service.create(selected[0],DEFAULTS['image']);designs=FeedDesigns(service)
    assert not designs.view(b,1)['candidates']
    with service.sessions() as session:article=session.get(NewsArticle,selected[1][0])
    service.safe_paths.assets.mkdir(exist_ok=True,parents=True)
    (service.safe_paths.assets/'fixture.png').write_bytes(photo())
    record=service.safe_paths.remember(article,'fixture.png',source_url='https://example.com/fixture.png',rights_basis='Synthetic authored test asset',origin='representative')
    candidate=designs.view(b,1)['candidates'][0]
    assert candidate['id']=='article:'+record['sha256'] and candidate['credit']==''
    state=designs.state(b,1);d={**state['draft'],'title':'뉴스 검토','description':'저장된 내용 확인','credit':'합성 제작자'}
    saved=designs.save(b,1,0,candidate['id'],d,export=True)
    assert saved['versions'][0]['background']['provenance']['sourceUrl']=='https://example.com/fixture.png'
    assert saved['draft']['credit']=='합성 제작자'
    assert not designs.view(b,2)['candidates']


def test_three_photo_backgrounds_and_local_versions_use_only_fake(app,selected):
    from newsflow.creation.top_three_feeds import TopThreeFeeds,LocalFeedPreviewAdapter
    from newsflow.publishing.image_generation import ImageGenerationService
    class Keys:
        def key(self):return 'synthetic-top3-key'
    generation=ImageGenerationService(app.state.sessions,app.state.config.data_dir,Keys(),adapter=LocalFeedPreviewAdapter())
    service=TopThreeFeeds(app.state.sessions,app.state.config.data_dir,generation,simulation=True)
    batch=service.create(selected[0],DEFAULTS['image'],feed_style=STYLE)
    for _ in range(3):service.step(batch,consent=True,reviewed=True)
    row=service.get(batch);assert row.status=='success'
    assert len(generation.adapter.calls)==3
    design=FeedDesigns(service)
    for item in row.result['items']:
        rank=item['rank'];state=design.state(batch,rank)
        assert 'title_header_bottom' not in item
        assert generation.get(item['generation_id']).evidence['source']['plan']['title_layout'] is None
        d={**state['draft'],'title':f'합성 뉴스 {rank}','description':'원문의 검토 상태 유지','credit':'AI 생성'}
        saved=design.save(batch,rank,0,'generated',d,export=True)
        assert Image.open(design.path(saved['versions'][0]['filename'],saved['versions'][0]['sha256'])).size==(1080,1350)
    generation._generate=lambda *a,**k:pytest.fail('No extra generation for editing')
    v=service.view(batch)
    assert all(i['designMediaUrl'] and i['designVersion']==1 for i in v['items'])
    assert len({i['designMediaUrl'] for i in v['items']})==3
    for rank in (1,2,3):
        state=design.state(batch,rank)
        design.preview(batch,rank,state['revision'],'generated',{**state['draft'],'accent':'#ffd700','emphasis':'뉴스'})
    assert service.get(batch).options==row.options and service.get(batch).result==row.result


def test_saved_background_survives_removal_of_temporary_upload(feeds):
    s,b,state,d=prepared(feeds)
    saved=s.save(b,1,state['revision'],state['background'],d,export=True)
    asset=state['assets'][0];s.path(asset['filename'],asset['sha256']).unlink()
    assert saved['background']=='version:1'
    original=s.path(saved['versions'][0]['filename'],saved['versions'][0]['sha256']).read_bytes()
    assert s.preview(b,1,saved['revision'],saved['background'],saved['draft'])==original
    revised=s.save(b,1,saved['revision'],saved['background'],{**saved['draft'],'emphasis':'공개'},export=True)
    assert revised['background']=='version:2'
    assert s.path(saved['versions'][0]['filename'],saved['versions'][0]['sha256']).read_bytes()==original


def test_feed_upload_exact_multipart_route_keeps_origin_csrf_size_and_raster_checks(app,feeds):
    s,b,state,d=prepared(feeds)
    with TestClient(OperatingRequests(app),base_url='http://127.0.0.1:18779') as c:
        c.get('/studio/images');token=c.cookies.get('newsflow_csrf')
        url=f'/api/feed-batches/{b}/items/1/design-upload'
        data={'revision':state['revision'],'kind':'stock','credit':'합성 업로드'}
        files={'image':('test.png',photo(),'image/png')}
        assert c.post(url,data=data,files=files).status_code==403
        data['csrf_token']=token
        assert c.post(url,data=data,files=files,headers={'Origin':'https://other.invalid'}).status_code==403
        assert s.state(b,1)==state or s.state(b,1)['revision']==state['revision']
        assert c.post(url,data=data,files={'image':('bad.png',b'not an image','image/png')}).status_code==422
        oversized={'image':('large.png',b'x'*(20*1024*1024+65536),'image/png')}
        assert c.post(url,data=data,files=oversized).status_code==413
        result=c.post(url,data=data,files=files)
        assert result.status_code==200,result.text
        assert result.json()['draft']['credit']=='합성 업로드'
        assert s.state(b,1)['revision']==state['revision']+1
        assert s.state(b,2)['revision']==0
    with TestClient(app) as c:
        c.get('/studio/images');data['csrf_token']=c.cookies.get('newsflow_csrf')
        for wrong in (f'/api/feed-batches/{b}/items/4/design-upload',f'/api/feed-batches/{b}/items/1/design', '/api/other-upload'):
            assert c.post(wrong,data=data,files=files).status_code==415


def test_photo_pixels_omit_provenance_but_saved_metadata_survives(feeds):
    service,b,state,design=prepared(feeds)
    design={**design,'image_height':1.,'gradient_strength':.3}
    raw=service.preview(b,1,state['revision'],state['background'],design)
    # Long but valid provenance no longer consumes image space or changes pixels.
    changed={**design,'source':'긴 출처 '*39,'credit':'다른 제작자','brand':'다른 브랜드','date':'2026.12.01'}
    assert service.preview(b,1,state['revision'],state['background'],changed)==raw
    assert render(photo(),design,'ai')==render(photo(),design,'stock')
    with Image.open(BytesIO(raw)) as image:
        assert image.size==(1080,1350)
        # The footer is photograph/gradient, not the former solid provenance band.
        assert image.getpixel((500,1330))!=(8,17,29)
    saved=service.save(b,1,state['revision'],state['background'],design,export=True)
    assert saved['draft']==design
    assert saved['versions'][-1]['design']==design
    assert saved['versions'][-1]['background']['credit']==design['credit']
    assert service.path(saved['versions'][-1]['filename'],saved['versions'][-1]['sha256']).read_bytes()==raw
