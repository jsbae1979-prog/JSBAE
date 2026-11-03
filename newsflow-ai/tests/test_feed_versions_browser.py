"""Real browser rendering with isolated files and intercepted local batch responses."""
import os,json
from copy import deepcopy
from pathlib import Path
from hashlib import sha256
from io import BytesIO
from urllib.parse import urlsplit,parse_qs
import pytest
from PIL import Image
from playwright.sync_api import expect
from test_model_picker_browser import browser
from test_cloud_workspace_flow import local_server
from test_feed_connections_browser import context

@pytest.fixture(autouse=True)
def dist(monkeypatch):monkeypatch.setattr('newsflow.studio.resources.studio_dist_root',lambda:Path(os.environ['EDITORIAL_TEST_DIST']))

def test_versions_preview_download_fullscreen_and_right_status(app,browser,tmp_path):
    files={}
    for n,color in [(1,'orange'),(2,'blue'),(3,'green')]:
        out=BytesIO();Image.new('RGB',(1080,1350),color).save(out,'JPEG');files[n]=out.getvalue()
    def version(n):return {'attempt':n,'status':'success','filename':f'feed-103-1-{n}.jpg','sha256':sha256(files[n]).hexdigest()}
    item={**version(2),'rank':1,'mediaUrl':'/api/feed-batches/103/items/1/file','content':{'title':'합성 피드 제목'},'history':[version(1)]}
    batch={'id':103,'analysisId':42,'feedStyle':'ai_design_v1','items':[item], 'selection':{},'plannedImages':1,'revision':2,'costReview':{'settingsLimitUsd':'1'}}
    before=deepcopy(batch)
    with local_server(app) as origin:
        c=context(browser,origin);p=c.new_page();posts=[];errors=[];requested=[]
        p.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
        p.on('pageerror',lambda e:errors.append(str(e)))
        p.route(origin+'/api/feed-batches?*',lambda r:r.fulfill(json={'batches':[batch],'defaults':{}}))
        p.route(origin+'/api/feed-batches',lambda r:r.fulfill(json={'batches':[batch],'defaults':{}}))
        def image(route):
            q=parse_qs(urlsplit(route.request.url).query);n=int(q.get('attempt',['2'])[0]);requested.append(n)
            route.fulfill(body=files[n],content_type='image/jpeg',headers={'Cache-Control':'no-store'})
        p.route(origin+'/api/feed-batches/103/items/1/file*',image)
        p.goto(origin+'/studio/images?mode=top3&batch_id=103&rank=1')
        select=p.get_by_label('저장된 버전',exact=True);img=p.locator('.complete-feed-preview img')
        expect(img).to_be_visible();assert '?attempt=2&v=' in img.get_attribute('src')
        latest=img.get_attribute('src');assert img.evaluate('(i)=>{let c=document.createElement("canvas");c.width=c.height=1;let x=c.getContext("2d");x.drawImage(i,0,0,1,1);return x.getImageData(0,0,1,1).data[2]>200}')
        select.select_option('1');expect(img).to_have_attribute('src',f'/api/feed-batches/103/items/1/file?attempt=1&v={sha256(files[1]).hexdigest()}')
        expect(img).to_be_visible();old=img.get_attribute('src');assert img.evaluate('(i)=>{let c=document.createElement("canvas");c.width=c.height=1;let x=c.getContext("2d");x.drawImage(i,0,0,1,1);return x.getImageData(0,0,1,1).data[0]>200}')
        preview=p.get_by_role('button',name='완성 피드 크게 보기',exact=True)
        for width,height in [(1366,768),(900,600),(390,650)]:
            p.set_viewport_size({'width':width,'height':height});preview.click()
            modal=p.get_by_role('dialog',name='완성 피드 확대');expect(modal.get_by_role('img')).to_be_visible()
            expect(modal.get_by_role('img')).to_have_attribute('src',old)
            assert modal.get_by_role('link',name='이미지 저장').get_attribute('href')==old+'&download=true'
            assert modal.evaluate('(d)=>d.scrollWidth<=d.clientWidth+1&&d.scrollHeight<=d.clientHeight+1')
            box=modal.bounding_box();assert box['x']>=0 and box['y']>=0 and box['x']+box['width']<=width+1 and box['y']+box['height']<=height+1
            p.screenshot(path=str(tmp_path/f'full-image-{width}.png'))
            p.keyboard.press('Escape');expect(modal).not_to_be_visible()
        p.set_viewport_size({'width':1600,'height':900})
        select.select_option('');expect(img).to_have_attribute('src',latest);expect(img).to_be_visible()
        side=p.locator('.photo-feed-editor-side');expect(side).to_contain_text('작업 #103 · 제작 상태')
        expect(p.locator('.core-top3-left')).not_to_contain_text('제작 상태')
        assert side.bounding_box()['x']>img.bounding_box()['x']+img.bounding_box()['width']-1
        p.screenshot(path=str(tmp_path/'right-status-and-version.png'),full_page=True)
        assert batch==before and not posts and not errors and {1,2}.issubset(set(requested))
        # Newest generation has a new URL even when the media endpoint remains the same.
        item.update(**version(3),history=[version(1),version(2)]);p.reload();expect(img).to_be_visible()
        assert '?attempt=3&v=' in img.get_attribute('src') and img.get_attribute('src')!=latest
        c.unroute_all(behavior='wait');c.close()
