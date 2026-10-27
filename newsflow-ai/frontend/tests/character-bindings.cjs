"use strict";
// Synthetic React only. No product engine, provider keys, or actual generation.
const fs = require("fs"), path = require("path"), assert = require("assert/strict");
const { chromium } = require(process.env.NEWSFLOW_PLAYWRIGHT_PACKAGE);
const output = path.resolve(process.env.NEWSFLOW_CHARACTER_BINDINGS_OUTPUT);
const fixtureRoot = path.resolve(process.env.NEWSFLOW_CHARACTER_FIXTURES);
const base = "http://127.0.0.1:18765";
const result = { checks: [], pageErrors: [], externalPageRequests: [], submitted: [], productEngine: false, realProviderCalls: 0, completeOSNetworkIsolation: "NOT VERIFIED" };
const character = JSON.parse(fs.readFileSync(path.join(fixtureRoot, "characters.json"), "utf8"));
const sceneData = () => [1,2,3].map(position => ({ position, state: "downloaded", seconds: 10, caption: `합성 자막 ${position}`, action: `Synthetic action ${position}`, cost: "0.20", mediaUrl: null }));
const oldHash = "1".repeat(64), newHash = "2".repeat(64);
const make = (hex, state, title) => {
 const id = hex.repeat(32), scenes = sceneData().map(x=>({...x,mediaUrl:`/character/${id}/clips/${x.position}`}));
 return { id, topic:title, state, scenes, story:{title, plan:{situation:"합성 검증 전용"}, scenes: scenes.map(({seconds,caption,action})=>({seconds,caption,action}))}, selection:{script_provider:"claude_api",script_model:"claude-sonnet-4-6",video_provider:"higgsfield",video_model:"bytedance/seedance-2.0/reference-to-video",resolution:"720p",aspect_ratio:"9:16"}, referenceUrl:null, quote:"0.60", quote_hash:oldHash, mediaUrl:null };
};
const clips=make("a","clips_review","클립 검토 합성 작업");
const completed=make("b","completed","완성 영상 합성 작업");completed.mediaUrl=`/character/${completed.id}/file`;
const retry=make("c","retry_quoted","재시도 견적 합성 작업");retry.retry_hash=newHash;retry.retryQuote={position:2,quote_usd:"0.25",at:"2026-10-27T00:00:00+00:00"};retry.scenes[1].state="failed";retry.scenes[1].mediaUrl=null;
const unknown=make("d","submission_unknown","결과 불명 합성 작업");unknown.retry_hash=newHash;
const missing=make("e","completed","누락 클립 합성 작업");missing.mediaUrl=`/character/${missing.id}/file`;missing.scenes[0].mediaUrl=null;
const prequote=make("f","script_review","견적 전 합성 작업");prequote.scenes=[];
const noHash=make("9","retry_quoted","승인값 없는 합성 작업");noHash.retryQuote={...retry.retryQuote};
character.collections.jobs=[clips,completed,retry,unknown,missing,prequote,noHash];
const snapshot = JSON.stringify(character.collections.jobs.map(x=>({id:x.id,selection:x.selection})));
let browser, context, page;
const record = async (name, operation) => { const detail = await operation(); result.checks.push({name,status:"PASS",detail}); console.log("PASS "+name); };
const select = async job => { await page.locator(".record-row").filter({hasText:job.topic}).click(); await page.locator(".story-copy h3").filter({hasText:job.topic}).waitFor(); };
const retryButton = () => page.locator(".command-catalog").getByRole("button",{name:/새 승인으로 실패 장면 요청/});
async function openRetry(){ if(await page.locator(".command-catalog").getAttribute("open")===null) await page.locator(".command-catalog summary").click(); await retryButton().click(); const d=page.getByRole("dialog"); await d.waitFor(); return d; }
(async()=>{try{
 fs.mkdirSync(output,{recursive:true});
 browser=await chromium.launchPersistentContext(path.join(output,"chrome-profile"),{executablePath:process.env.NEWSFLOW_TEST_CHROME||"C:/Program Files/Google/Chrome/Application/chrome.exe",headless:true,chromiumSandbox:true,viewport:{width:1366,height:768},locale:"ko-KR",serviceWorkers:"block",reducedMotion:"reduce",args:["--proxy-server=http://127.0.0.1:18765","--proxy-bypass-list=127.0.0.1","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1","--disable-quic","--force-webrtc-ip-handling-policy=disable_non_proxied_udp","--disable-component-update"]});
 context=browser;
 await context.route("**/*",async route=>{
  const request=route.request(),url=new URL(request.url());
  if(url.origin!==base){result.externalPageRequests.push(url.origin);return route.abort();}
  if(url.pathname==="/api/studio/modules/characters") return route.fulfill({json:character});
  if(request.method()==="POST"){
   if(url.pathname===`/character/${retry.id}/retry-scene`){
    const fields=Object.fromEntries(new URLSearchParams(request.postData()));
    result.submitted.push({path:url.pathname,quote_hash:fields.quote_hash,consent:fields.consent,reviewed:fields.reviewed,csrfPresent:!!fields.csrf_token});
    return route.fulfill({json:{saved:true,synthetic:true}});
   }
   throw Error("Unexpected synthetic POST: "+url.pathname);
  }
  if(/^\/character\/[a-f0-9]{32}\/(?:clips\/[123]|file)$/.test(url.pathname)){
   const body=fs.readFileSync(process.env.NEWSFLOW_SYNTHETIC_MP4); return route.fulfill({contentType:"video/mp4",body});
  }
  return route.continue();
 });
 page=await context.newPage();page.on("pageerror",e=>result.pageErrors.push(e.message));
 await page.goto(base+"/studio/characters");await page.locator(".command-catalog").waitFor();
 await record("Quoted scene descriptions, timing and labels 1..3 survive React projection",async()=>{
  await select(clips);const buttons=page.locator(".timeline button");assert.equal(await buttons.count(),3);
  assert.deepEqual(await buttons.locator(":scope > span:first-child").allTextContents(),["장면 1","장면 2","장면 3"]);
  for(let i=0;i<3;i++){assert.ok((await buttons.nth(i).textContent()).includes(`Synthetic action ${i+1}`));assert.ok((await buttons.nth(i).textContent()).includes("10초"));}
 });
 await record("Selected character scene drives the local validated clip URL",async()=>{
  await page.locator(".timeline button").nth(1).click();assert.equal(await page.locator("video").getAttribute("src"),`/character/${clips.id}/clips/2`);
  await page.waitForFunction(()=>document.querySelector("video")?.readyState>=1);
  return await page.locator("video").evaluate(v=>({width:v.videoWidth,height:v.videoHeight}));
 });
 await record("Completed output remains default and can be reopened after clip selection",async()=>{
  await select(completed);assert.equal(await page.locator("video").getAttribute("src"),completed.mediaUrl);
  await page.locator(".timeline button").nth(2).click();assert.equal(await page.locator("video").getAttribute("src"),`/character/${completed.id}/clips/3`);
  await page.getByRole("button",{name:"완성 영상 보기",exact:true}).click();assert.equal(await page.locator("video").getAttribute("src"),completed.mediaUrl);
 });
 await record("Missing selected clip never falls through to an unrelated final preview",async()=>{
  await select(missing);await page.locator(".timeline button").first().click();assert.equal(await page.locator("video").count(),0);
 });
 await record("Selecting another job resets the previous clip selection",async()=>{
  await select(clips);await page.locator(".timeline button").nth(2).click();await select(completed);assert.equal(await page.locator("video").getAttribute("src"),completed.mediaUrl);
 });
 await record("Story before quotation keeps labels 1..3 without changing stored positions",async()=>{
  await select(prequote);assert.deepEqual(await page.locator(".timeline button > span:first-child").allTextContents(),["장면 1","장면 2","장면 3"]);
 });
 await record("Retry dialog shows fresh official scene quote and approvals stay unchecked",async()=>{
  await select(retry);const d=await openRetry();assert.ok((await d.textContent()).includes("재시도 대상 장면 2 · 공식 견적 USD 0.25"));assert.equal(await d.locator("input[type=checkbox]:checked").count(),0);
  assert.equal(await d.getByRole("button",{name:"새 승인으로 실패 장면 요청",exact:true}).isDisabled(),true);
  await d.getByRole("button",{name:"취소",exact:true}).click();assert.equal(result.submitted.length,0);
 });
 await record("Explicit Fake retry posts retry_hash rather than initial quote_hash",async()=>{
  const d=await openRetry();const checkboxes=d.locator("input[type=checkbox]");for(let i=0;i<await checkboxes.count();i++)await checkboxes.nth(i).check();
  await d.getByRole("button",{name:"새 승인으로 실패 장면 요청",exact:true}).click();await d.waitFor({state:"hidden"});
  assert.equal(result.submitted.length,1);assert.equal(result.submitted[0].quote_hash,newHash);assert.notEqual(result.submitted[0].quote_hash,oldHash);assert.equal(result.submitted[0].csrfPresent,true);
 });
 await record("Unknown outcome and missing retry approval stay blocked",async()=>{
  await select(unknown);assert.equal(await retryButton().isDisabled(),true);await select(noHash);assert.equal(await retryButton().isDisabled(),true);assert.equal(result.submitted.length,1);
 });
 await record("Existing job model snapshots stay unchanged after React interactions",async()=>{
  assert.equal(JSON.stringify(character.collections.jobs.map(x=>({id:x.id,selection:x.selection}))),snapshot);
 });
 await select(clips);
 for(const [width,height] of [[1366,768],[1920,1080]]){
  await page.setViewportSize({width,height});await page.evaluate(()=>document.fonts.ready);
  await page.evaluate(()=>window.scrollTo(0,0));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),true);
  await page.screenshot({path:path.join(output,`characters-fixed-${width}.png`),animations:"disabled",fullPage:true});
 }
 assert.deepEqual(result.pageErrors,[]);assert.deepEqual(result.externalPageRequests,[]);
 result.PASS=result.checks.length;result.FAIL=0;result.ERROR=0;
} catch(error){result.ERROR=1;result.error=String(error.stack||error);console.error(result.error);process.exitCode=1;}
finally {if(browser)await browser.close();result.browserClosed=true;fs.writeFileSync(path.join(output,"browser-results-safe.json"),JSON.stringify(result,null,2));}})();

