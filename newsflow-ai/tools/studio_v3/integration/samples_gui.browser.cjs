"use strict";
const fs=require("fs"),path=require("path"),assert=require("assert"),crypto=require("crypto");
const {chromium}=require(path.join(process.env.NF_GUI_RUNTIME,"node_modules","playwright"));
const root=process.env.NF_GUI_ROOT,out=path.join(root,"screenshots"),origin="http://127.0.0.1:18765";
fs.mkdirSync(out,{recursive:true});
const result={checks:[],failures:[],pageErrors:[],externalRequests:[],captures:[],videos:[],transport:"real Python ASGI through synthetic file IPC",realPaidCalls:0,OS_DPI:"NOT VERIFIED"};
let serial=Promise.resolve(),sequence=0;
function ipc(data){const task=serial.then(async()=>{
 const name=String(++sequence).padStart(6,"0")+".json",file=path.join(root,"requests",name),answer=path.join(root,"responses",name);
 fs.writeFileSync(file+".tmp",JSON.stringify(data));fs.renameSync(file+".tmp",file);
 const deadline=Date.now()+20000;
 while(!fs.existsSync(answer)){assert(Date.now()<deadline,"Python ASGI response timeout");await new Promise(r=>setTimeout(r,15));}
 const value=JSON.parse(fs.readFileSync(answer,"utf8"));fs.unlinkSync(answer);assert(!value.error,value.error);return value;
});serial=task.catch(()=>{});return task;}
(async()=>{let browser;try{
 browser=await chromium.launch({channel:"chrome",headless:true,chromiumSandbox:true,args:["--disable-background-networking","--disable-component-update","--disable-quic","--proxy-server=http://127.0.0.1:18765","--proxy-bypass-list=127.0.0.1","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1"]});
 result.browserVersion=browser.version();
 const context=await browser.newContext({locale:"ko-KR",serviceWorkers:"block",acceptDownloads:false});
 await context.route("**/*",async route=>{
  const req=route.request(),url=new URL(req.url());
  if(url.origin!==origin){result.externalRequests.push(url.origin);return route.abort();}
  const response=await ipc({method:req.method(),url:url.pathname+url.search,headers:req.headers(),body:(req.postDataBuffer()||Buffer.alloc(0)).toString("base64")});
  const headers={...response.headers};delete headers["transfer-encoding"];delete headers["content-encoding"];
  await route.fulfill({status:response.status,headers,body:Buffer.from(response.body,"base64")});
 });
 const page=await context.newPage();page.setDefaultTimeout(12000);page.on("pageerror",e=>result.pageErrors.push(String(e)));
 async function open(s){await page.goto(origin+"/studio/"+s);await page.locator(".sample-gallery").waitFor();await page.locator(".sample-cards article").first().waitFor();}
 const card=id=>page.locator(`[data-sample-id="${id}"]`);
 async function check(name,fn){try{await fn();result.checks.push({name,status:"PASS"});}catch(e){result.checks.push({name,status:"FAIL"});result.failures.push({name,error:String(e)});await page.screenshot({path:path.join(out,"failure-"+result.failures.length+".png"),fullPage:true}).catch(()=>{});await page.keyboard.press("Escape").catch(()=>{});}}
 async function api(url){const r=await ipc({method:"GET",url,headers:{}});assert.equal(r.status,200);return JSON.parse(Buffer.from(r.body,"base64"));}
 await page.setViewportSize({width:1920,height:1080});
 await check("first run shows three independent samples without history insertion",async()=>{
  await open("images");assert.equal(await page.locator(".sample-cards article").count(),3);
  assert.equal((await api("/api/studio/modules/images")).collections.drafts.length,0);
  await card("standalone-city").getByRole("button",{name:/미리보기$/}).click();
  const img=page.locator("dialog.sample-dialog img");await img.waitFor();assert.deepEqual(await img.evaluate(async i=>{await i.decode();return [i.naturalWidth,i.naturalHeight]}),[720,1080]);
  await page.getByRole("dialog").getByRole("button",{name:"닫기",exact:true}).click();
 });
 await check("copy is repeatable and creates a real private reference download",async()=>{
  for(let i=0;i<2;i++){await card("standalone-city").getByRole("button",{name:"내 작업으로 복사",exact:true}).click();await card("standalone-city").getByRole("link",{name:"내 참조 파일 다운로드"}).waitFor();await page.getByRole("status").getByText(/샘플 참조 파일/).waitFor();}
  const list=await api("/api/samples"),row=list.assets.find(x=>x.id==="standalone-city");
  const raw=await ipc({method:"GET",url:row.copyUrl,headers:{}});assert.equal(crypto.createHash("sha256").update(Buffer.from(raw.body,"base64")).digest("hex"),row.sha256);
 });
 await check("hide persists across reload and can be restored",async()=>{
  await card("standalone-city").getByRole("button",{name:"샘플 숨기기",exact:true}).click();await card("standalone-city").waitFor({state:"hidden"});
  await open("images");assert.equal(await page.locator(".sample-cards article").count(),2);
  await page.getByRole("button",{name:"숨긴 샘플 관리",exact:true}).click();await card("standalone-city").getByRole("button",{name:"샘플 다시 표시",exact:true}).click();
  await card("standalone-city").getByRole("button",{name:"샘플 숨기기",exact:true}).waitFor();
 });
 await check("sample prompt starts an explicit saved draft without paid generation",async()=>{
  await card("standalone-city").getByRole("button",{name:"프롬프트로 새 작업",exact:true}).click();
  const expected=(await api("/api/samples")).assets.find(x=>x.id==="standalone-city").promptExample;
  await page.waitForFunction(v=>document.querySelector('[aria-label="이미지 프롬프트"]')?.value===v,expected);
  await page.getByRole("button",{name:"초안 저장 · 참조 첨부",exact:true}).click();const d=page.getByRole("dialog");await d.waitFor();await d.locator("footer button.primary").click();await d.waitFor({state:"hidden"});
  const drafts=(await api("/api/studio/modules/images")).collections.drafts;assert.equal(drafts.length,1);assert.equal(drafts[0].status,"saved");assert.equal(drafts[0].mediaUrl,null);
 });
 await check("sample character selection attaches PNG to a new local character draft",async()=>{
  await open("characters");assert.equal(await page.locator(".sample-cards article").count(),5);
  await card("character-cat").getByRole("button",{name:"참조 PNG로 선택",exact:true}).click();
  await page.locator('.core-reference img[src="/api/samples/character-cat/file"]').waitFor();
  assert.equal((await api("/api/studio/modules/characters")).collections.jobs.length,0);
  await page.getByLabel("스토리 주제",{exact:true}).fill("샘플 고양이 연습 주제");await page.getByRole("button",{name:"이 주제로 작업 저장",exact:true}).click();
  const d=page.getByRole("dialog");await d.waitFor();assert((await d.getByLabel("저장한 참조 소재",{exact:true}).inputValue()).startsWith("studio-"));
  await d.getByLabel("이번 작업 한도",{exact:true}).fill("5");await d.getByLabel("하루 한도",{exact:true}).fill("20");await d.locator("footer button.primary").click();await d.waitFor({state:"hidden"});
  assert.equal((await api("/api/studio/modules/characters")).collections.jobs.length,1);
 });
 for(const [id,screen] of [["news-short","shorts"],["character-short-robot","characters"],["character-short-cat","characters"]]){
  await check("actual MP4 playback "+id,async()=>{
   await open(screen);await card(id).getByRole("button",{name:/미리보기$/}).click();const v=page.getByRole("dialog").locator("video");await v.waitFor();
   const meta=await v.evaluate(async video=>{if(video.readyState<1)await new Promise((ok,no)=>{video.addEventListener("loadedmetadata",ok,{once:true});video.addEventListener("error",()=>no(Error("video metadata error")),{once:true})});return {width:video.videoWidth,height:video.videoHeight,duration:video.duration};});
   assert.deepEqual(meta,{width:720,height:1280,duration:12});await v.evaluate(async video=>{video.muted=true;await video.play();});await page.waitForFunction(()=>document.querySelector("dialog video")?.currentTime>.2);
   await v.evaluate(video=>{video.currentTime=6;});await page.waitForFunction(()=>{const v=document.querySelector("dialog video");return v?.currentTime>6.1 && v.readyState>=2;});
   result.videos.push({id,...meta,played:true,seeked:true,audio:false});await page.screenshot({path:path.join(out,id+"-playing.png")});await page.getByRole("dialog").getByRole("button",{name:"닫기",exact:true}).click();
  });
 }
 await check("TOP3 examples are separate from real analysis and generation results",async()=>{
  await open("images?mode=top3");assert.equal(await page.locator(".sample-cards article").count(),3);
  assert.equal((await api("/api/studio/production-context")).top3.length,0);
  assert.equal(await page.getByText("이미지 제작 방식",{exact:true}).count(),0);
 });
 await check("library all, my copies and samples remain distinct",async()=>{
  await open("library");assert.equal(await page.locator(".sample-cards article").count(),12);
  const scopes=page.getByLabel("라이브러리 콘텐츠 구분",{exact:true});await scopes.getByRole("button",{name:"내 콘텐츠",exact:true}).click();
  assert(await page.locator(".sample-cards article").count()>=2);assert(await page.locator(".sample-cards article").count()<12);
  await scopes.getByRole("button",{name:"샘플 콘텐츠",exact:true}).click();assert.equal(await page.locator(".sample-cards article").count(),12);assert.equal(await page.locator(".approved-library-grid").count(),0);
 });
 await check("offline page reload and catalog require no outside requests",async()=>{
  await context.setOffline(true);await open("images");assert.equal(await page.locator(".sample-cards article").count(),3);await context.setOffline(false);
 });
 for(const [width,height] of [[1920,1080],[1366,768]]){
  await page.setViewportSize({width,height});
  for(const [screen,url] of [["images","images"],["top3","images?mode=top3"],["characters","characters"],["shorts","shorts"],["library","library"]]){
   await check(`samples viewport ${screen} ${width}`,async()=>{
    await open(url);await page.evaluate(()=>document.fonts.ready);assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)));
    const file=`${screen}-${width}.png`;await page.screenshot({path:path.join(out,file),animations:"disabled",caret:"hide"});result.captures.push({screen,width,height,file,overflow:false});
   });
  }
 }
 assert.deepEqual(result.externalRequests,[]);assert.deepEqual(result.pageErrors,[]);
}catch(e){result.failures.push({name:"harness",error:String(e)});}
finally{if(browser)await browser.close();fs.writeFileSync(path.join(root,"STOP"),"stop");result.browserClosed=true;result.pass=result.checks.filter(x=>x.status==="PASS").length;result.fail=result.checks.filter(x=>x.status==="FAIL").length+result.failures.filter(x=>x.name==="harness").length;result.skip=0;fs.writeFileSync(path.join(root,"gui-results.json"),JSON.stringify(result,null,2));console.log("SAMPLE_GUI_RESULT="+JSON.stringify(result));}
if(result.failures.length)process.exitCode=1;
})();
