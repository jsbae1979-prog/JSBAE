from copy import deepcopy
from pathlib import Path
from hashlib import sha256
from PIL import Image,ImageDraw,ImageFont
from io import BytesIO
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_photo_feed_editor import feeds,prepared,photo
from newsflow.publishing.feed_titles import render_title
from newsflow.video.engine import font_path

def test_photo_feed_editor_local_browser(app,feeds,browser,tmp_path):
    s,b,state,d=prepared(feeds)
    # Keep demonstration copy grounded in its synthetic source, never real operating data.
    from newsflow.db.models import IntelligenceRun
    from newsflow.creation.top_three_feeds import digest
    with feeds.sessions.begin() as session:
        row=session.get(IntelligenceRun,b);e=deepcopy(row.evidence)
        e['sources'][0]['title']='새 관측 장비 공개: 산악 지역 변화 확인'
        e['sources'][0]['body']='2026년 관측 결과 공개 예정이며 추가 검토는 진행 중입니다.'
        row.evidence=e;row.options={**row.options,'source_hash':digest(e)}
    # Synthetic old-layout reference, not an operating image or an actual news photograph.
    old=Image.new('RGB',(1080,1350),'#f7f9fc');old.paste(Image.open(BytesIO(photo())).resize((1080,850)),(0,500))
    draw=ImageDraw.Draw(old);font=ImageFont.truetype(str(font_path()),38)
    draw.multiline_text((50,60),'합성 과학 뉴스 : 새로운 관측 장비를 공개하고\n산악 지역 변화를 살펴보는 연구 계획\n\n연구진은 관측 결과를 공개할 예정입니다.\n추가 검토가 진행 중이며 확정되지 않았습니다.\n자세한 기사 요약이 상단을 차지하는 구성입니다.\n\n#뉴스요약 #과학 #세계',font=font,fill='#162035',spacing=15)
    out=BytesIO();old.save(out,'JPEG');raw=out.getvalue();feeds.root.mkdir(exist_ok=True,parents=True)
    r=deepcopy(feeds.get(b).result)
    for item in r['items']:
        name=f'feed-{b}-{item["rank"]}-1.jpg';(feeds.root/name).write_bytes(raw)
        item.update(status='success',filename=name,sha256=sha256(raw).hexdigest(),generation_id=999,title_header_bottom=260)
    feeds._save(b,r)
    saved=s.save(b,1,state['revision'],state['background'],d,export=True)
    evidence=tmp_path/'evidence';evidence.mkdir();(evidence/'before.jpg').write_bytes(raw)
    v=saved['versions'][0];(evidence/'after.jpg').write_bytes(s.path(v['filename'],v['sha256']).read_bytes())
    with local_server(app) as origin:
        ctx=browser.new_context(viewport={'width':1920,'height':1080});ctx.route('**/*',lambda r:r.continue_() if r.request.url.startswith(origin+'/') else r.abort())
        def module(route):
            data=route.fetch().json()
            data['collections']['selections']=[{'id':42,'status':'success','title':'합성 TOP 3 분석','ranking':[
                {'rank':n,'title':f'합성 뉴스 {n}','body':f'합성 요약 {n}','article_ids':[n]} for n in (1,2,3)]}]
            route.fulfill(json=data)
        ctx.route('**/api/studio/modules/images',module)
        ctx.route('**/news/*/thumbnail',lambda route:route.fulfill(content_type='image/png',body=photo()))
        p=ctx.new_page();errors=[];requests=[];p.on('pageerror',lambda e:errors.append(str(e)));p.on('request',lambda r:requests.append((r.method,r.url)))
        p.goto(origin+'/studio/images?mode=top3');expect(p.get_by_label('피드 제목',exact=True)).to_have_value(d['title'])
        expect(p.locator('.photo-feed-canvas img')).to_be_visible()
        p.get_by_label('핵심 설명',exact=True).fill('2026년 관측 결과 공개 예정\n추가 검토 진행 중')
        expect(p.get_by_role('status').filter(has_text='미리보기 반영됨')).to_be_visible()
        p.get_by_role('button',name='새 버전으로 저장',exact=True).click();expect(p.get_by_role('status').filter(has_text='새 버전 저장 완료')).to_be_visible()
        p.reload();expect(p.get_by_label('핵심 설명',exact=True)).to_have_value('2026년 관측 결과 공개 예정\n추가 검토 진행 중')
        p.get_by_role('button',name='선택 이미지 크게 보기',exact=True).click();expect(p.get_by_role('dialog')).to_be_visible();p.get_by_role('button',name='닫기',exact=True).click()
        for width,height in [(1920,1080),(1366,768)]:
            p.set_viewport_size({'width':width,'height':height});assert p.evaluate('document.documentElement.scrollWidth<=innerWidth')
            p.screenshot(path=str(evidence/f'editor-{width}.png'),full_page=True)
        p.get_by_role('button',name='TOP 2 결과 선택',exact=True).click();expect(p.get_by_label('피드 제목',exact=True)).to_have_value('합성 뉴스 2')
        p.get_by_role('button',name='TOP 1 결과 선택',exact=True).click();expect(p.get_by_label('피드 제목',exact=True)).to_have_value(d['title'])
        assert p.locator('.photo-feed-thumbs img').first.get_attribute('src').endswith('/design-file/2')
        assert p.locator('.photo-feed-canvas img').evaluate('(img)=>img.complete && img.naturalWidth===1080')
        assert not errors
        writes=[url for method,url in requests if method=='POST']
        assert writes and all(url.endswith('/design') for url in writes),writes
        ctx.close()
