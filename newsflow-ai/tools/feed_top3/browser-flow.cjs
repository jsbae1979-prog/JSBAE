"use strict";
// Synthetic React interaction proof only. Python service contracts run separately in Windows Actions.
const fs=require('fs'),path=require('path'),assert=require('assert'),crypto=require('crypto');
const R=process.env.NEWSFLOW_VISUAL_ROOT;if(!R)throw Error('Dedicated synthetic output root required');
const {chromium}=require(process.env.NEWSFLOW_PLAYWRIGHT_PACKAGE);
const origin='http://127.0.0.1:18765',out=path.join(R,'top3-validation'),ev=path.join(out,'ci-evidence');
const template=JSON.parse(fs.readFileSync(path.join(ev,'fake-batch.json'),'utf8'));
const fixture=JSON.parse(fs.readFileSync(path.join(R,'repo/newsflow-ai/tools/studio_v3/fixtures/images.json'),'utf8'));
fixture.collections.selections=[{id:template.analysisId,title:'합성 TOP 3 분석 · 검증 전용',status:'success',ranking:template.items.map(x=>({...x.source,selection:{analysis_id:template.analysisId,rank:x.rank,draft_id:x.source.draft_id}}))}];
let defaults={provider:'openai',model:template.selection.model,size:'1024x1280',quality:'medium'},batch=null,calls=0;
const checks=[],shots=[],errors=[],external=[],requests=[];
const clone=x=>JSON.parse(JSON.stringify(x));
function fresh(options){let b=clone(template);b.id=900;b.selection={...b.selection,...options};b.revision=1;b.paused=false;b.status='saved';b.items.forEach(x=>{x.status='pending';x.generation_id=null;x.mediaUrl=null;x.history=[];x.attempt=1;});return b;}
(async()=>{let browser;try{
 browser=await chromium.launch({executablePath:process.env.NEWSFLOW_TEST_BROWSER_EXECUTABLE,headless:true,chromiumSandbox:true,args:['--proxy-server=http://127.0.0.1:18765','--proxy-bypass-list=127.0.0.1','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1','--disable-quic','--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--disable-component-update']});
 const ctx=await browser.newContext({viewport:{width:1366,height:768},locale:'ko-KR',serviceWorkers:'block'});
 await ctx.route('**/*',async route=>{
  const req=route.request(),u=new URL(req.url());if(u.origin!==origin){external.push(u.origin);return route.abort();}
  const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  if(u.pathname==='/api/studio/modules/images')return json(fixture);
  if(!u.pathname.startsWith('/api/feed-batches'))return route.continue();
  if(req.method()==='GET'&&u.pathname==='/api/feed-batches')return json({batches:batch?[batch]:[],defaults});
  if(req.method()==='GET'&&u.pathname.endsWith('/file')){
   const rank=u.pathname.split('/').at(-2);return route.fulfill({status:200,contentType:'image/jpeg',body:fs.readFileSync(path.join(ev,`fake-top${rank}.jpg`))});
  }
  const data=Object.fromEntries(new URLSearchParams(req.postData()??''));assert.equal(data.csrf_token,fixture.csrfToken);requests.push({path:u.pathname,method:req.method()});
  if(u.pathname.endsWith('/defaults')){defaults={provider:'openai',model:data.model,size:data.size,quality:data.quality};return json(defaults);}
  if(u.pathname==='/api/feed-batches'){if(!batch)batch=fresh({provider:'openai',model:data.model,size:data.size,quality:data.quality});return json(batch);}
  if(u.pathname.endsWith('/step')){
   assert.equal(data.consent,'true');assert.equal(data.reviewed,'true');assert(batch.canGenerate&&!batch.paused);
   const item=batch.items.find(x=>x.status==='pending');if(item){calls++;await new Promise(r=>setTimeout(r,500));item.status='success';item.generation_id=100+calls;item.mediaUrl=`/api/feed-batches/900/items/${item.rank}/file`;batch.revision++;batch.status=batch.items.every(x=>x.status==='success')?'success':'partial';}
   return json(batch);
  }
  if(u.pathname.endsWith('/change')){
   assert.equal(Number(data.revision),batch.revision);
   if(data.action==='pause'||data.action==='resume')batch.paused=data.action==='pause';
   if(data.action==='edit'){const x=batch.items.find(x=>x.rank===Number(data.rank));assert.equal(x.status,'pending');x.content={title:data.title,body:data.body,hashtags:data.hashtags};}
   if(data.action==='regenerate'){const x=batch.items.find(x=>x.rank===Number(data.rank));assert.equal(data.consent,'true');assert.equal(data.reviewed,'true');x.history.push({status:x.status});x.status='pending';x.mediaUrl=null;x.attempt++;}
   batch.revision++;return json(batch);
  }
  return json({detail:'Unapproved synthetic operation'},403);
 });
 const page=await ctx.newPage();page.on('pageerror',e=>errors.push(String(e)));
 async function openAuto(){await page.goto(origin+'/studio/images');await page.getByRole('tab',{name:'뉴스 TOP 3 자동 제작',exact:true}).click();await page.locator('.top3-workflow[aria-busy=false]').waitFor();}
 await page.goto(origin+'/studio/images');await page.getByRole('textbox',{name:'이미지 지시문',exact:true}).waitFor({state:'visible'});await page.getByRole('tab',{name:'뉴스 이미지 게시물',exact:true}).click();await page.getByRole('heading',{name:'뉴스 기반 이미지',exact:true}).waitFor();checks.push('Original independent/manual news image workflows retained');
 await openAuto();await page.getByLabel('TOP 3 분석 결과',{exact:true}).selectOption(String(template.analysisId));assert.equal(await page.locator('.top3-selection li').count(),3);
 await page.getByLabel('TOP 3 품질',{exact:true}).selectOption('high');await page.getByRole('button',{name:'자동 제작 기본값 저장',exact:true}).click();await page.getByRole('status').filter({hasText:'자동 제작 기본값을 저장'}).waitFor();
 await page.getByRole('button',{name:'TOP 3 제작 작업 저장',exact:true}).click();await page.locator('.top3-result').first().waitFor();assert.equal(batch.selection.quality,'high');checks.push('Select stored analysis, preserve rank/source and freeze model/quality');
 await page.getByRole('button',{name:'검토 후 자동 제작',exact:true}).click();let d=page.getByRole('dialog',{name:'TOP 3 생성 범위 승인',exact:true});assert.equal(await d.locator('input:checked').count(),0);assert(await d.getByRole('button',{name:'자동 제작 시작',exact:true}).isDisabled());await page.keyboard.press('Escape');assert.equal(calls,0);checks.push('Unchecked generation consent and Escape do not generate');
 await page.locator('.top3-result').nth(1).getByRole('button',{name:'문구 수정',exact:true}).click();await page.getByLabel('TOP 3 수정 요약',{exact:true}).fill('검토한 합성 버스 안내입니다.');await page.getByRole('button',{name:'문구 저장',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});assert.equal(batch.items[1].content.body,'검토한 합성 버스 안내입니다.');checks.push('Individual editable short feed copy persists');
 async function approve(){await page.getByRole('button',{name:batch.paused?'검토 후 재개':'검토 후 자동 제작',exact:true}).click();d=page.getByRole('dialog',{name:'TOP 3 생성 범위 승인',exact:true});await d.locator('input[type=checkbox]').nth(0).check();await d.locator('input[type=checkbox]').nth(1).check();await d.getByRole('button',{name:'자동 제작 시작',exact:true}).click();}
 await approve();await page.getByText('TOP 1 이미지 생성 중 · 현재 요청은 다시 보내지 마세요.',{exact:true}).waitFor();await page.getByRole('button',{name:'현재 항목 후 중지',exact:true}).click();await page.getByRole('button',{name:'검토 후 재개',exact:true}).waitFor({state:'visible'});await page.waitForFunction(()=>document.querySelectorAll('.top3-result img').length===1);assert.equal(calls,1);assert(batch.paused);checks.push('Pause after current item preserves first result and remaining pending');
 await openAuto();assert.equal(await page.getByLabel('TOP 3 품질',{exact:true}).inputValue(),'high');await approve();await page.waitForFunction(()=>document.querySelectorAll('.top3-result img').length===3);assert.equal(calls,3);assert.equal(await page.locator('.top3-result').count(),3);checks.push('Reload/resume finishes only pending images; three independent results');
 for(const img of await page.locator('.top3-result img').all()){await img.scrollIntoViewIfNeeded();await img.evaluate(x=>x.decode());const size=await img.evaluate(x=>[x.naturalWidth,x.naturalHeight]);assert.deepEqual(size,[1080,1350]);}
 assert.equal(await page.getByRole('button',{name:'게시용 검토',exact:true}).count(),3);assert(await page.getByRole('button',{name:'게시용 검토',exact:true}).first().isDisabled());checks.push('Fake outputs cannot become real Instagram publication input');
 for(const [w,h] of [[1920,1080],[1366,768],[390,844]]){await page.setViewportSize({width:w,height:h});await page.evaluate(()=>window.scrollTo(0,0));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),'overflow '+w);await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));await page.screenshot({path:path.join(out,`top3-${w}.png`),fullPage:false,animations:'disabled'});await page.locator('.top3-results').evaluate(x=>x.scrollIntoView({block:'start'}));await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));await page.screenshot({path:path.join(out,`top3-results-${w}.png`),fullPage:false,animations:'disabled'});shots.push({width:w,height:h,horizontalOverflow:false,topAndResultsCaptured:true});}
 await page.setViewportSize({width:1366,height:768});await page.locator('.top3-result').nth(1).getByRole('button',{name:'개별 재생성 준비',exact:true}).click();d=page.getByRole('dialog',{name:'TOP 3 생성 범위 승인',exact:true});assert.equal(await d.locator('input:checked').count(),0);await d.locator('input[type=checkbox]').nth(0).check();await d.locator('input[type=checkbox]').nth(1).check();await d.getByRole('button',{name:'1회 재생성 준비',exact:true}).click();await page.locator('.top3-result').nth(1).getByRole('button',{name:'문구 수정',exact:true}).waitFor();assert.equal(calls,3);assert.equal(batch.items[1].history.length,1);await approve();await page.waitForFunction(()=>document.querySelectorAll('.top3-result img').length===3);assert.equal(calls,4);checks.push('Explicit single-item regeneration keeps prior result history and other ranks');
 batch.items[1].status='unknown';batch.items[1].mediaUrl=null;await page.getByRole('button',{name:'TOP 3 상태 새로고침',exact:true}).click();await page.getByText('결과 불명 · 재요청 금지',{exact:true}).waitFor();assert(await page.getByRole('button',{name:'검토 후 자동 제작',exact:true}).isDisabled());assert(await page.locator('.top3-result').nth(1).getByRole('button',{name:'개별 재생성 준비',exact:true}).isDisabled());checks.push('Unknown request blocks automatic restart and individual regeneration');
 batch.simulation=false;batch.canGenerate=false;batch.price='공식 견적 미확정 · 유료 실행 차단';batch.items[1].status='pending';await page.getByRole('button',{name:'TOP 3 상태 새로고침',exact:true}).click();await page.getByText('공식 견적 미확정 · 유료 실행 차단',{exact:true}).waitFor();assert(await page.getByRole('button',{name:'검토 후 자동 제작',exact:true}).isDisabled());checks.push('Unquoted paid batch remains blocked');
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
 fs.writeFileSync(path.join(out,'browser-safe.json'),JSON.stringify({checks,shots,jsErrors:errors,externalPageRequests:external,realProviderCalls:0,syntheticStepRequests:calls,engine:'React synthetic API simulation; actual Python form integration separate Windows CI',windowsDPI:'NOT VERIFIED'},null,2));console.log(JSON.stringify({checks:checks.length,captures:shots.length,jsErrors:errors.length,externalPageRequests:external.length}));await ctx.close();
 }finally{if(browser)await browser.close();}})().catch(e=>{console.error(e);process.exitCode=1});
