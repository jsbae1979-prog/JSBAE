'use strict';
const {chromium}=require(process.env.NEWSFLOW_PLAYWRIGHT_PACKAGE);
const fs=require('fs'),path=require('path'),assert=require('assert');
const R=process.env.NEWSFLOW_VISUAL_ROOT;if(!R)throw Error('An approved synthetic output root is required');const phase=process.argv[2]||'before',origin='http://127.0.0.1:18765',out=path.join(R,'polish-'+phase);fs.mkdirSync(out,{recursive:true});
const snapshot={phase,structures:[],images:[],responses:[],captures:[],checks:[],errors:[],external:[],productEngine:false,windowsOSDPI:'NOT VERIFIED'};
(async()=>{let browser;try{
 browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true,chromiumSandbox:true,args:['--proxy-server=http://127.0.0.1:18765','--proxy-bypass-list=127.0.0.1','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--disable-quic','--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--disable-component-update']});
 const ctx=await browser.newContext({viewport:{width:1920,height:1080},locale:'ko-KR',serviceWorkers:'block'});
 const fixture=JSON.parse(fs.readFileSync(path.join(R,'repo/newsflow-ai/tools/studio_v3/fixtures/characters.json'),'utf8'));fixture.collections.jobs[0].referenceUrl='/api/studio/characters/demo-character/reference';fixture.collections.jobs[0].reference_sha256='synthetic-reference-not-an-operating-file';
 await ctx.route('**/*',route=>{const u=new URL(route.request().url());if(u.origin!==origin){snapshot.external.push(u.href);return route.abort();}if(u.pathname==='/api/studio/modules/characters')return route.fulfill({contentType:'application/json',body:JSON.stringify(fixture)});if(u.pathname==='/api/studio/characters/demo-character/reference')return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(R,'preview-media/reference-test.png'))});return route.continue();});
 const page=await ctx.newPage();page.on('pageerror',e=>snapshot.errors.push(String(e)));page.on('response',r=>{if(r.request().resourceType()==='image')snapshot.responses.push({path:new URL(r.url()).pathname,status:r.status()});});
 const imageStats=()=>page.locator('.project-visual img').evaluateAll(imgs=>imgs.map(i=>({src:new URL(i.src).pathname,loading:i.loading,complete:i.complete,naturalWidth:i.naturalWidth,hidden:i.hidden,y:Math.round(i.getBoundingClientRect().top),height:Math.round(i.getBoundingClientRect().height)})));
 async function settle(){await page.evaluate(()=>document.fonts.ready);await page.evaluate(async()=>{const visible=[...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight});await Promise.all(visible.map(i=>i.decode().catch(()=>null)));});await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));}
 for(const [width,height] of [[1920,1080],[1366,768]]){
  await page.setViewportSize({width,height});
  for(const name of ['dashboard','create','shorts','characters','images','library','settings']){
   await page.goto(origin+'/studio/'+name+(name==='shorts'?'?job_id=1&draft_id=1':''));await page.locator(name==='dashboard'?'.hero':name==='create'?'.create-page':'.command-catalog').waitFor();
   if(name==='create')snapshot.images.push({width,stage:'before-decode-wait',values:await imageStats()});
   if(name==='characters')await page.locator('.record-row').first().click();
   await settle();await page.evaluate(()=>window.scrollTo(0,0));
   if(name==='create')snapshot.images.push({width,stage:'after-decode-wait',values:await imageStats()});
   if(['dashboard','create'].includes(name))snapshot.structures.push({screen:name,width,boxes:await page.locator('.sidebar,.hero,.stats,.project-visual,.quick-card,.right-panel,.create-page > header').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return {class:e.className,x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)}}))});
   if(name==='shorts'){
    await page.waitForFunction(()=>document.querySelector('video')?.readyState>=1);
    const v=await page.locator('video').evaluate(async v=>{v.currentTime=1;await new Promise(r=>v.addEventListener('seeked',r,{once:true}));return {width:v.videoWidth,height:v.videoHeight,duration:v.duration};});
    assert.deepEqual([v.width,v.height,Math.round(v.duration)],[1080,1920,30]);snapshot.checks.push({name:'existing vertical synthetic MP4 metadata and decoded frame',viewportWidth:width,...v});
   }
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),name+' overflow');
   await page.screenshot({path:path.join(out,name+'-'+width+'.png'),animations:'disabled'});snapshot.captures.push({name,width,height,scrollY:await page.evaluate(()=>scrollY)});
   if(name==='shorts'&&width===1366){await page.getByRole('textbox',{name:'방송용 내레이션',exact:true}).scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,'shorts-editor-scroll-1366.png'),animations:'disabled'});if(phase==='after'){const tab=await page.locator('.scene-tabs').boundingBox();assert(tab.y>=0&&tab.y<height);snapshot.checks.push({name:'scene controls remain visible during narration editing',viewportWidth:width,top:tab.y});}}
   if(name==='dashboard'&&width===1366){const card=page.locator('.quick-card').first();await card.scrollIntoViewIfNeeded();assert(await card.isVisible());const box=await card.boundingBox();assert(box.y>=0&&box.y<height);snapshot.checks.push({name:'1366 quick creation reachable by normal page scroll',y:box.y});}
   if(name==='images'){await page.getByRole('tab',{name:'뉴스 이미지 게시물',exact:true}).click();await settle();await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:path.join(out,'images-news-'+width+'.png'),animations:'disabled'});snapshot.captures.push({name:'images-news',width,height,scrollY:await page.evaluate(()=>scrollY)});}
   if(name==='characters'&&phase==='after'){const ref=page.locator('.character-reference-panel');assert(await ref.isVisible());assert((await ref.boundingBox()).y+100<height);assert.equal(await ref.locator('img').evaluate(i=>i.naturalWidth),32);snapshot.checks.push({name:'saved synthetic reference PNG visible in first viewport',width});}
   if(name==='settings'&&phase==='after'){for(const label of ['OpenAI · Claude 키 설정','ElevenLabs 키 설정','Higgsfield 키 설정']){assert.equal(await page.getByRole('button',{name:label,exact:true}).count(),1);await page.getByRole('button',{name:label,exact:true}).click();const dialog=page.getByRole('dialog');await dialog.waitFor();assert(await dialog.locator('input[type=password]').count()>=1);for(const input of await dialog.locator('input[type=password]').all())assert.equal(await input.inputValue(),'');await page.keyboard.press('Escape');}snapshot.checks.push({name:'distinct credential settings labels',width});}
   if(name==='library'&&phase==='after'){assert.equal(await page.locator('.media-tile-art img[src*="design-art-"]').count(),0);snapshot.checks.push({name:'decorative duration images omitted from library',width});}
  }
 }
 if(phase==='after'){await page.setViewportSize({width:1366,height:768});fixture.collections.jobs[0].referenceUrl=null;await page.goto(origin+'/studio/characters');await page.locator('.record-row').first().click();await settle();await page.evaluate(()=>window.scrollTo(0,0));assert.equal(await page.locator('.character-reference-panel img').count(),0);assert(await page.locator('.character-reference-panel').getByText('미리보기 없음',{exact:true}).isVisible());await page.screenshot({path:path.join(out,'characters-no-reference-1366.png'),animations:'disabled'});snapshot.checks.push({name:'missing reference PNG has explicit empty state'});}
 // Reproduce a real image HTTP error without changing a fixture on disk.
 await page.setViewportSize({width:1920,height:1080});
 await page.route('**/studio/assets/design-art-2.webp',route=>route.fulfill({status:404,body:''}));
 await page.goto(origin+'/studio/create');await page.locator('.projects .project').first().waitFor();await page.locator('.project-visual').first().scrollIntoViewIfNeeded();await settle();
 snapshot.failedImage=await page.locator('.project-visual').first().evaluate(e=>({text:e.textContent,hiddenImages:e.querySelectorAll('img[hidden]').length,images:e.querySelectorAll('img').length}));
 if(phase==='after')assert(snapshot.failedImage.text.includes('미리보기 없음'));
 await page.screenshot({path:path.join(out,'create-http404-1920.png'),animations:'disabled'});
 assert.deepEqual(snapshot.errors,[]);assert.deepEqual(snapshot.external,[]);
 await ctx.close();
 fs.writeFileSync(path.join(R,'polish-'+phase+'-safe.json'),JSON.stringify(snapshot,null,2));console.log(JSON.stringify({phase,captures:snapshot.captures.length,checks:snapshot.checks.length,errors:0,externalPageRequests:0,failedImage:snapshot.failedImage}));
}finally{if(browser)await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
