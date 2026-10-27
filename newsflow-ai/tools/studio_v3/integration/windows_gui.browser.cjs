"use strict";
const fs=require("fs"),path=require("path"),assert=require("assert");
const {chromium}=require(path.join(process.env.NF_GUI_RUNTIME,"node_modules","playwright"));
const root=process.env.NF_GUI_ROOT,out=path.join(root,"screenshots"),origin="http://127.0.0.1:18765";
fs.mkdirSync(out,{recursive:true});
const meta=JSON.parse(fs.readFileSync(path.join(root,"ready.json"),"utf8"));
const result={checks:[],failures:[],pageErrors:[],externalRequests:[],captures:[],transport:"real Python ASGI through synthetic file IPC",OS_DPI:"NOT VERIFIED",realPaidCalls:0};
let serial=Promise.resolve(),sequence=0;
function ipc(data){const task=serial.then(async()=>{
 const name=String(++sequence).padStart(6,"0")+".json",file=path.join(root,"requests",name),answer=path.join(root,"responses",name);
 fs.writeFileSync(file+".tmp",JSON.stringify(data));fs.renameSync(file+".tmp",file);
 const deadline=Date.now()+20000;
 while(!fs.existsSync(answer)){assert(Date.now()<deadline,"Python ASGI response timeout");await new Promise(r=>setTimeout(r,15));}
 const value=JSON.parse(fs.readFileSync(answer,"utf8"));fs.unlinkSync(answer);assert(!value.error,value.error);return value;
});serial=task.catch(()=>{});return task;}
const control=action=>ipc({kind:"control",action});
(async()=>{let browser,context;try{
 browser=await chromium.launch({channel:"chrome",headless:true,chromiumSandbox:true,args:["--disable-background-networking","--disable-component-update","--disable-quic",
 "--proxy-server=http://127.0.0.1:18765","--proxy-bypass-list=127.0.0.1","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"]});
 result.browserVersion=browser.version();
 context=await browser.newContext({locale:"ko-KR",serviceWorkers:"block",acceptDownloads:false});
 await context.route("**/*",async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.origin!==origin){result.externalRequests.push(url.origin);return route.abort();}
  const body=req.postDataBuffer()||Buffer.alloc(0);
  const packet={method:req.method(),url:url.pathname+url.search,headers:req.headers(),body:body.toString("base64")};
  if(req.method()==="POST" && url.pathname==="/character" && (req.headers()["content-type"]||"").startsWith("multipart/form-data")){
    // CDP omits uploaded file bytes from multipart postData. Read the selected synthetic DOM File.
    const file=await req.frame().evaluate(async()=>{
      const f=document.querySelector("dialog input[type=file]")?.files?.[0];
      if(!f)return null;return {filename:f.name,type:f.type,bytes:Array.from(new Uint8Array(await f.arrayBuffer()))};
    });
    if(file){
      const bytes=Buffer.from(file.bytes),expected=fs.readFileSync(path.join(root,"reference.png"));
      assert.equal(file.filename,"reference.png");assert(bytes.equals(expected),"Only the selected synthetic PNG is permitted");
      packet.multipartFile={filename:file.filename,type:file.type,body:bytes.toString("base64")};
      result.uploadTransport={CDPcontainsFullFile:body.includes(bytes),DOMfileBytes:bytes.length,syntheticBytesMatch:true};
    }
  }
  const response=await ipc(packet);
  const headers={...response.headers};delete headers["transfer-encoding"];delete headers["content-encoding"];
  return route.fulfill({status:response.status,headers,body:Buffer.from(response.body,"base64")});
 });
 const page=await context.newPage();page.setDefaultTimeout(12000);
 page.on("pageerror",e=>result.pageErrors.push(String(e)));page.on("dialog",d=>d.accept());
 async function open(module){await page.goto(origin+"/studio/"+module);await page.locator(".core-studio").waitFor();await page.evaluate(()=>document.fonts.ready);}
 async function check(name,fn){console.log("GUI_CHECK_START="+name);try{await fn();result.checks.push({name,status:"PASS"});}catch(e){result.checks.push({name,status:"FAIL"});result.failures.push({name,error:String(e)});await page.screenshot({path:path.join(out,"failure-"+result.failures.length+".png"),fullPage:true}).catch(()=>{});await page.keyboard.press("Escape").catch(()=>{});}}
 async function saved(){return control("stats");}
 await page.setViewportSize({width:1920,height:1080});
 await check("news search, source and existing analysis to shorts",async()=>{
  await open("news");await page.getByLabel("보관 뉴스 검색",{exact:true}).fill("도서관");
  assert.equal(await page.locator(".core-news-list button").count()||await page.locator(".core-news-search button").count(),1);
  assert(await page.getByText("테스트 출처",{exact:false}).count()>0);
  assert(await page.getByText(/합성 도서관 운영 안내/).count()>0);
  const before=await saved();assert.equal(before.analysisCount,1);
  await page.getByRole("link",{name:/뉴스 쇼츠 제작실/}).first().click();
  await page.locator(".core-shorts").waitFor();assert(page.url().includes("/studio/shorts"));
  assert.equal((await saved()).analysisCount,1);
 });
 await check("shorts real script save, reopen and Revision conflict",async()=>{
  await open("shorts?draft_id="+meta.draft);
  assert.equal(await page.locator(".core-news-top3 button").count(),3);
  const text=page.getByRole("textbox",{name:"장면 1 대본",exact:true});
  await text.fill("Windows 실제 앱 GUI에서 저장한 합성 대본입니다.");
  await page.getByRole("button",{name:"대본 저장",exact:true}).click();
  await page.getByRole("status").getByText(/대본을 저장/).waitFor();
  assert.equal((await saved()).draft.scenes[0].narration,"Windows 실제 앱 GUI에서 저장한 합성 대본입니다.");
  await page.reload();await text.waitFor();assert.equal(await text.inputValue(),"Windows 실제 앱 GUI에서 저장한 합성 대본입니다.");
  await text.fill("충돌 시 보존할 GUI 합성 대본");await control("conflict");
  await page.getByRole("button",{name:"대본 저장",exact:true}).click();
  await page.getByRole("status").getByText(/다른 편집|다른 화면|다른.*변경|Revision|충돌/).waitFor();
  assert.equal(await text.inputValue(),"충돌 시 보존할 GUI 합성 대본");
 });
 await check("shorts simplified settings and separate production approval",async()=>{
  await open("shorts?draft_id="+meta.draft);
  assert.equal(await page.locator(".core-shorts-steps").count(),0);
  await page.getByRole("button",{name:"영상 제작 · 승인 확인",exact:true}).click();
  const d=page.getByRole("dialog");await d.waitFor();
  for(const box of await d.locator("input[type=checkbox]").all())assert.equal(await box.isChecked(),false);
  await page.keyboard.press("Escape");
 });
 await check("character reference, saved story, storyboard and unknown guard",async()=>{
  await open("characters");
  await page.locator(".core-reference img").waitFor();
  assert.equal(await page.locator(".core-reference img").evaluate(i=>i.naturalWidth),128);
  assert.equal(await page.locator(".core-character .core-timeline button").count(),3);
  assert(await page.getByText(/결과 불명/).count()>0);
  assert(await page.getByRole("button",{name:"장면 생성 · 비용 승인",exact:true}).isDisabled());
 });
 await check("character topic and PNG registration through actual app",async()=>{
  await open("characters");await page.getByLabel("스토리 주제",{exact:true}).fill("Windows GUI 새 합성 주제");
  await page.getByRole("button",{name:"참조 PNG 등록 · 새 작업",exact:true}).click();
  const d=page.getByRole("dialog");await d.waitFor();
  await d.locator("input[type=file]").setInputFiles(path.join(root,"reference.png"));
  const topic=d.getByLabel("이야기 주제",{exact:true});if(await topic.count())await topic.fill("Windows GUI 새 합성 주제");
  await d.getByLabel("이번 작업 한도",{exact:true}).fill("5");await d.getByLabel("하루 한도",{exact:true}).fill("20");
  await d.locator("footer button.primary").click();await d.waitFor({state:"hidden"});
  await page.locator(".core-job-list").getByText("Windows GUI 새 합성 주제",{exact:true}).waitFor();
 });
 let imageId;
 await check("independent image options, actual draft save and reopen",async()=>{
  await open("images");
  await page.getByLabel("이미지 프롬프트",{exact:true}).fill("Windows GUI 합성 도형 이미지");
  await page.getByLabel("이미지 품질",{exact:true}).selectOption("low");
  await page.getByRole("button",{name:"초안 저장 · 참조 첨부",exact:true}).click();
  const d=page.getByRole("dialog");await d.waitFor();await d.locator("footer button.primary").click();await d.waitFor({state:"hidden"});
  await page.getByRole("button",{name:/Windows GUI 합성 도형 이미지/}).first().click();
  const response=await ipc({method:"GET",url:"/api/studio/modules/images",headers:{}});const view=JSON.parse(Buffer.from(response.body,"base64"));
  const row=view.collections.drafts.find(x=>x.prompt==="Windows GUI 합성 도형 이미지");
  assert(row);imageId=row.id;assert.equal(row.selection.quality,"low");
  await open("images?draft_id="+imageId);assert(await page.getByText("Windows GUI 합성 도형 이미지",{exact:false}).count()>0);
 });
 await check("independent Fake generation requires approval, preview and reuse gate",async()=>{
  assert(imageId,"Draft save prerequisite failed");await open("images?draft_id="+imageId);
  await page.getByRole("button",{name:"견적 · 생성 승인",exact:true}).click();
  const d=page.getByRole("dialog");await d.waitFor();
  for(const box of await d.locator("input[type=checkbox]").all()){assert.equal(await box.isChecked(),false);await box.check();}
  await d.locator("footer button.primary").click();await d.waitFor({state:"hidden"});
  await page.locator(".core-image-result img").waitFor();assert(await page.locator(".core-image-result img").evaluate(async i=>{await i.decode();return i.naturalWidth;})>0);
  assert(await page.getByRole("button",{name:"견적 · 생성 승인",exact:true}).isDisabled(),"completed image must not resubmit");
  await page.getByRole("button",{name:"검토 후 재사용",exact:true}).click();await page.getByRole("dialog").waitFor();await page.keyboard.press("Escape");
 });
 await check("TOP3 actual stored analysis, independent Fake outputs and review separation",async()=>{
  await open("images?mode=top3");await page.getByLabel("완료된 TOP 3 분석",{exact:true}).selectOption(String(meta.analysis));await page.getByRole("button",{name:"TOP 3 제작 작업 저장",exact:true}).click();
  await page.locator(".core-feed-results article").first().waitFor();assert.equal(await page.locator(".core-feed-results article").count(),3);
  await page.getByRole("button",{name:"TOP 3 생성 · 비용 승인",exact:true}).click();
  const d=page.getByRole("dialog",{name:"TOP 3 생성 범위 승인"});await d.waitFor();
  assert(await d.getByText("Fake 이미지 검증 · 실제 과금 없음",{exact:true}).isVisible());
  for(const box of await d.locator("input[type=checkbox]").all()){assert.equal(await box.isChecked(),false);await box.check();}
  await d.getByRole("button",{name:"자동 제작 시작",exact:true}).click();
  await page.locator(".core-feed-results img").nth(2).waitFor();
  assert.equal(await page.locator(".core-feed-results img").count(),3);
  for(const img of await page.locator(".core-feed-results img").all()){await img.evaluate(i=>i.decode());assert.deepEqual(await img.evaluate(i=>[i.naturalWidth,i.naturalHeight]),[1080,1350]);}
  assert.equal(await page.getByText("이미지 제작 방식",{exact:true}).count(),0);
  const reviews=page.getByRole("button",{name:"게시용 검토본 저장",exact:true});assert.equal(await reviews.count(),1);for(const button of await reviews.all())assert(await button.isDisabled());
  assert.equal((await saved()).analysisCount,1);
  assert(await page.getByRole("button",{name:"TOP 3 생성 · 비용 승인",exact:true}).isDisabled());
 });
 for(const [width,height] of [[1920,1080],[1366,768]]){
  await page.setViewportSize({width,height});
  for(const [name,url] of [["shorts","shorts?draft_id="+meta.draft],["characters","characters"],["images","images"+(imageId?"?draft_id="+imageId:"")],["images-top3","images?mode=top3"],["news","news"]]){
   await check("viewport "+name+" "+width,async()=>{
    await open(url);
    if(name==="characters")await page.locator(".core-job-list button").filter({hasText:"합성 GUI 캐릭터 주제"}).click();
    await page.evaluate(async()=>{await document.fonts.ready;
     const visible=[...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.width>0&&r.height>0&&r.bottom>0&&r.top<innerHeight;});
     await Promise.all(visible.map(i=>i.decode().catch(()=>{})));});
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2);assert(!overflow,"horizontal overflow");
    const buttons=await page.locator(".core-shorts button,.core-character button,.core-image-grid button,.core-top3 button,.core-news-grid button").evaluateAll(ns=>ns.filter(n=>!n.disabled).map(n=>{const r=n.getBoundingClientRect();return {text:n.textContent.trim().slice(0,45),x:r.x,width:r.width};}));
    const file=name+"-"+width+".png";await page.screenshot({path:path.join(out,file),animations:"disabled",caret:"hide"});
    const capture={screen:name,width,height,file,overflow,buttons};
    result.captures.push(capture);
    if(width===1366 && ["shorts","characters","images"].includes(name)){
      const title={shorts:"영상 제작 · 승인 확인",characters:"참조 PNG 등록 · 새 작업",images:"검토 후 재사용"}[name];
      const action=page.getByRole("button",{name:title,exact:true});
      if(await action.count() && await action.isEnabled()){
        await action.scrollIntoViewIfNeeded();await action.click();
        const dialog=page.getByRole("dialog");await dialog.waitFor();
        const b=await dialog.boundingBox();assert(b && b.x>=0 && b.y>=0 && b.x+b.width<=width+2 && b.y+b.height<=height+2,"approval modal clipped");
        capture.modalBounds=b;
        await page.screenshot({path:path.join(out,name+"-modal-1366.png"),animations:"disabled"});
        await page.keyboard.press("Escape");
      }else capture.modalState="NOT VERIFIED / action unavailable in current state";
    }
   });
  }
 }
 result.backendStats=await saved();
 assert.deepEqual(result.externalRequests,[]);assert.deepEqual(result.pageErrors,[]);
}catch(e){result.failures.push({name:"harness",error:String(e)});}
finally{
 try {
  // Keep ASGI alive until every intercepted request has received its response.
  // Stop real transport before removing routes; no request is replayed.
  if(context){await context.setOffline(true);await context.unrouteAll({behavior:"wait"});await serial;}
  result.requestDrainCompleted=true;
 } catch(e){result.failures.push({name:"cleanup drain",error:String(e)});}
 if(browser)await browser.close();fs.writeFileSync(path.join(root,"STOP"),"stop");result.browserClosed=true;
 result.pass=result.checks.filter(x=>x.status==="PASS").length;result.fail=result.checks.filter(x=>x.status==="FAIL").length+result.failures.filter(x=>!result.checks.some(c=>c.name===x.name)).length;
 result.skip=0;fs.writeFileSync(path.join(root,"gui-results.json"),JSON.stringify(result,null,2));console.log("WINDOWS_GUI_RESULT="+JSON.stringify(result));}
if(result.failures.length)process.exitCode=1;
})();
