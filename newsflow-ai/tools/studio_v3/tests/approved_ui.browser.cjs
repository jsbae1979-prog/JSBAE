"use strict";
// Synthetic React-only verification. No Python app, providers, credentials or operating profile.
const fs=require("fs"),path=require("path"),assert=require("assert"),crypto=require("crypto");
const {chromium}=require(process.env.NF_UI_PLAYWRIGHT_ENTRY);
const project=process.env.NF_UI_PROJECT,dist=process.env.NF_UI_DIST,out=process.env.NF_UI_OUTPUT,media=process.env.NF_UI_MEDIA_ROOT;
const phase=process.env.NF_UI_PHASE||"after",origin="http://127.0.0.1:18765";
for(const x of [project,dist,out,media])assert(path.isAbsolute(x));fs.mkdirSync(out,{recursive:true});
const models=Object.fromEntries(fs.readdirSync(path.join(project,"tools/studio_v3/fixtures")).filter(n=>n.endsWith(".json")).map(n=>[n.slice(0,-5),JSON.parse(fs.readFileSync(path.join(project,"tools/studio_v3/fixtures",n),"utf8"))]));
for(const m of Object.values(models)){if(m.projects?.[0])m.projects[0].mediaUrl="/video/jobs/1/file";}
models.characters.collections.jobs[0].referenceUrl="/api/studio/characters/demo-character/reference";
models.publishing.collections.accounts=[{id:11,platform:"instagram",label:"합성 Instagram A",status:"registered",api_ready:false},{id:12,platform:"instagram",label:"합성 Instagram B",status:"registered",api_ready:false},{id:13,platform:"youtube",label:"합성 YouTube",status:"registered",api_ready:false}];
models.images.collections.drafts.push({id:9,title:"검증된 Fake 이미지",prompt:"합성 결과 이미지",selection:models.images.catalog.imageDefaults,status:"success",outputId:9,mediaUrl:"/image-studio/9/file"});
models.images.collections.posts.push({id:7,title:"뉴스 카드 · 합성",plan:{title:"뉴스 카드 · 합성",body:"저장된 합성 뉴스 요약",hashtags:["#합성자료"]},status:"review_required",mediaUrl:"/image-posts/7/file"});
const top3={id:1,analysisId:2,revision:1,simulation:true,paused:false,canGenerate:false,selection:models.images.catalog.imageDefaults,price:"Fake 검증 · 실제 과금 없음",publishApproval:"실제 게시 차단",items:models.images.collections.articles.map((a,i)=>({rank:i+1,status:"success",mediaUrl:`/api/feed-batches/1/items/${i+1}/file`,content:{title:a.title,body:a.summary,hashtags:"#합성자료"},source:{origin:"저장된 합성 분석",references:[{publisher:a.publisher}],title:a.title,body:a.summary},caption:a.summary,prompt:"합성 이미지 지시문",attempt:1,history:[]}))};
const png=fs.readFileSync(path.join(media,"reference-test.png")),mp4=fs.readFileSync(path.join(media,"synthetic.mp4")),jpg=fs.readFileSync(process.env.NF_UI_FEED_IMAGE);
const result={phase,captures:[],checks:[],errors:[],externalRequests:[],posts:[],networkMode:"Playwright routes fulfill all application requests; pinned Node/Chrome boundary preserved; browser background egress NOT VERIFIED",WindowsOSDPI:"NOT VERIFIED",realAPICalls:0,productAppStarted:false};
const check=(name,details={})=>result.checks.push({name,...details});
function mime(f){return ({".js":"application/javascript",".css":"text/css",".png":"image/png",".webp":"image/webp",".ttf":"font/ttf",".html":"text/html",".svg":"image/svg+xml"})[path.extname(f)]||"application/octet-stream";}
(async()=>{let browser;try{
 if(process.env.NF_UI_JOB_READY){for(let i=0;!fs.existsSync(process.env.NF_UI_JOB_READY);i++){assert(i<1000,"Owned test job not assigned");await new Promise(r=>setTimeout(r,10));}}
 browser=await chromium.launch({executablePath:process.env.NF_UI_CHROME,headless:true,chromiumSandbox:true,args:["--proxy-server=http://127.0.0.1:18765","--proxy-bypass-list=127.0.0.1","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1","--disable-quic","--force-webrtc-ip-handling-policy=disable_non_proxied_udp","--disable-component-update"]});
 const context=await browser.newContext({locale:"ko-KR",serviceWorkers:"block",acceptDownloads:false});
 await context.route("**/*",async route=>{
  const req=route.request(),u=new URL(req.url());if(u.origin!==origin){result.externalRequests.push(crypto.createHash("sha256").update(u.href).digest("hex"));return route.abort();}
  const json=(d,status=200)=>route.fulfill({status,contentType:"application/json",body:JSON.stringify(d)});
  if(req.method()==="POST"){
   const form=new URLSearchParams(req.postData()||"");
   const type=req.headers()["content-type"]||"";
   if(type.startsWith("multipart/form-data")){
    assert((req.postDataBuffer()?.length||0)<65536,"Bounded synthetic form");
    for(const key of [...form.keys()])form.delete(key);
    const boundary=/boundary=(?:"([^"]+)"|([^;]+))/.exec(type);assert(boundary,"Multipart boundary required");
    for(const chunk of req.postData().split("--"+(boundary[1]||boundary[2]))){const m=/name="([a-z_]+)"(?:;[^\r\n]*)?\r\n(?:[^\r\n]+\r\n)*\r\n([\s\S]*?)\r\n$/.exec(chunk);if(m&&!chunk.includes("filename="))form.set(m[1],m[2]);}
   }
   result.posts.push({path:u.pathname,keys:[...form.keys()],synthetic:true});
   if(form.get("csrf_token")!=="studio-synthetic-local-only")return json({detail:"CSRF rejected"},403);
   if(u.pathname==="/ai/drafts/1"){
    const d=models.shorts.collections.drafts[0];if(Number(form.get("revision"))!==d.revision)return json({detail:"다른 화면에서 변경됐습니다. 편집 내용을 유지하세요."},409);
    d.content=JSON.parse(form.get("content"));d.revision++;return json({saved:true});
   }
   if(u.pathname==="/image-studio/drafts"){models.images.collections.drafts.push({id:99,title:form.get("prompt"),prompt:form.get("prompt"),selection:Object.fromEntries(["model","size","quality","provider"].map(k=>[k,form.get(k)])),status:"saved",outputId:null,mediaUrl:null});return json({saved:true});}
   if(u.pathname==="/schedules"){models.automation.collections.schedules.push({id:"fixture-new",name:form.get("name"),kind:form.get("kind"),local_time:form.get("local_time"),status:"paused",revision:1});return json({saved:true});}
   return json({detail:"Synthetic boundary: real generation, OAuth and publishing are blocked."},403);
  }
  if(u.pathname==="/api/studio/workspace")return json(models.workspace);
  if(u.pathname.startsWith("/api/studio/modules/"))return json(models[u.pathname.split("/").pop()]||{detail:"Unknown fixture"});
  if(u.pathname==="/api/feed-batches")return json({batches:[top3],defaults:models.images.catalog.imageDefaults});
  if(u.pathname==="/api/studio/characters/demo-character/reference")return route.fulfill({contentType:"image/png",body:png});
  if(/^\/(image-studio|image-posts)\/(9|7)\/file$/.test(u.pathname)||/^\/api\/feed-batches\/1\/items\/[123]\/file$/.test(u.pathname))return route.fulfill({contentType:"image/jpeg",body:jpg});
  if(u.pathname==="/video/jobs/1/file"){
   const range=/bytes=(\d+)-(\d*)/.exec(req.headers().range||"");const start=range?Number(range[1]):0,end=Math.min(range?.[2]?Number(range[2]):mp4.length-1,mp4.length-1);
   return route.fulfill({status:range?206:200,contentType:"video/mp4",headers:{"Accept-Ranges":"bytes",...(range?{"Content-Range":`bytes ${start}-${end}/${mp4.length}`}:{})},body:mp4.subarray(start,end+1)});
  }
  if(u.pathname.startsWith("/studio/assets/")){
   const name=u.pathname.split("/").pop();if(!/^[a-zA-Z0-9_.-]+$/.test(name))return route.abort();const f=path.join(dist,"assets",name);if(!fs.existsSync(f))return route.fulfill({status:404,body:"missing test asset"});return route.fulfill({contentType:mime(f),body:fs.readFileSync(f)});
  }
  if(u.pathname.startsWith("/studio/"))return route.fulfill({contentType:"text/html",headers:{"Content-Security-Policy":"default-src 'self';script-src 'self';style-src 'self';img-src 'self';frame-ancestors 'none';base-uri 'none';form-action 'self'"},body:fs.readFileSync(path.join(dist,"index.html"))});
  return route.fulfill({status:404,body:"Synthetic route not implemented"});
 });
 const page=await context.newPage();page.on("pageerror",e=>result.errors.push(String(e)));await page.clock.setFixedTime(new Date("2026-10-27T00:00:00Z"));
 async function settle(){await page.evaluate(()=>document.fonts.ready);await page.evaluate(async()=>{await Promise.all([...document.images].filter(i=>{const r=i.getBoundingClientRect();return r.bottom>0&&r.top<innerHeight}).map(i=>i.decode().catch(()=>null)));await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));});}
 async function open(name){
  const paths={"images-news":"images?mode=news","images-top3":"images","shorts":"shorts?job_id=1&draft_id=1","characters":"characters?job_id=demo-character","images":"images?draft_id=9"};
  await page.goto(origin+"/studio/"+(paths[name]||name));await page.locator(["dashboard","create"].includes(name)?(name==="dashboard"?".hero":".create-page"):".command-catalog").waitFor();
  if(name==="images-top3"){await page.getByRole("tab",{name:"뉴스 TOP 3 자동 제작",exact:true}).click();await page.locator(".top3-results img").first().waitFor();}
  if(name==="images-news"){await page.getByRole("button",{name:/뉴스 카드 · 합성/}).first().click();}
  if(name==="news"){await page.locator(".news-card>button").first().click();}
  if(name==="library"){await page.locator(".media-tile").first().click();}
  if(name==="automation"){await page.locator(".record-row").first().click();}
  if(name==="publishing"){await page.locator(".record-row").first().click();}
  await settle();
  const vid=page.locator("video").first();if(await vid.count()){const metadata=await vid.evaluate(async v=>{if(v.readyState<1)await new Promise(r=>v.addEventListener("loadedmetadata",r,{once:true}));v.pause();if(Math.abs(v.currentTime-1)>.01){const seek=new Promise(r=>v.addEventListener("seeked",r,{once:true}));v.currentTime=1;await seek;}return {width:v.videoWidth,height:v.videoHeight,seconds:v.duration};});assert.deepEqual([metadata.width,metadata.height,Math.round(metadata.seconds)],[1080,1920,30]);}
  await page.evaluate(()=>scrollTo(0,0));await settle();
 }
 const names=phase==="baseline"?["dashboard","create"]:["dashboard","create","shorts","characters","images","images-news","images-top3","news","automation","library","publishing","analytics","settings"];
 for(const [width,height] of [[1920,1080],[1366,768]]){
  await page.setViewportSize({width,height});for(const name of names){await open(name);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),`${name} ${width}: horizontal overflow`);const filename=`${name}-${width}.png`;await page.screenshot({path:path.join(out,filename),animations:"disabled",caret:"hide"});result.captures.push({name,width,height,file:filename});check("screen renders without overflow",{name,width});}
 }
 if(phase!=="baseline"){
  await page.setViewportSize({width:1366,height:768});
  await open("shorts");const narration=page.getByRole("textbox",{name:"방송용 내레이션",exact:true});await narration.fill("수정한 합성 내레이션");await page.getByRole("button",{name:"대본 저장",exact:true}).click();await page.getByText("저장된 내용",{exact:true}).waitFor();await page.reload();await narration.waitFor();assert.equal(await narration.inputValue(),"수정한 합성 내레이션");check("script save and reload through unchanged revision contract");
  const d=models.shorts.collections.drafts[0];d.revision++;await narration.fill("충돌 시 유지할 합성 편집");await page.getByRole("button",{name:"대본 저장",exact:true}).click();await page.getByRole("status").getByText(/다른 화면에서 변경/).waitFor();assert.equal(await narration.inputValue(),"충돌 시 유지할 합성 편집");check("revision conflict preserves typed script");
  await open("characters");assert.equal(await page.locator(".character-reference-panel img").evaluate(i=>i.naturalWidth),32);assert.equal(await page.locator(".character-storyboard .timeline button").count(),3);check("reference PNG and three real fixture storyboard scenes");
  const submitName=JSON.parse(fs.readFileSync(path.join(project,"frontend/src/legacy-actions.json"),"utf8")).find(x=>x.id==="character_act_submit").label;const submit=page.getByRole("button",{name:submitName,exact:true}).first();assert(await submit.isDisabled());check("character state guard retained");await page.getByLabel("새 캐릭터 이야기 주제",{exact:true}).fill("새 합성 이야기 주제");await page.getByRole("button",{name:"이 주제로 새 작업 초안",exact:true}).click();let topicDialog=page.getByRole("dialog");await topicDialog.waitFor();assert.equal(await topicDialog.getByLabel("이야기 주제",{exact:true}).inputValue(),"새 합성 이야기 주제");await page.keyboard.press("Escape");check("new character topic enters existing draft form without changing saved job");
  await open("images");await page.getByLabel("독립 이미지 품질",{exact:true}).selectOption("high");await page.getByRole("textbox",{name:"이미지 지시문",exact:true}).fill("합성 새 이미지 초안");await page.getByRole("button",{name:"이미지 초안 저장",exact:true}).first().click();let dialog=page.getByRole("dialog");await dialog.waitFor();assert.equal(await dialog.getByLabel("품질",{exact:true}).inputValue(),"high");await dialog.getByRole("button",{name:"이미지 초안 저장",exact:true}).click();await page.getByRole("button",{name:/합성 새 이미지 초안/}).waitFor();check("image options propagate into existing draft save form");
  await page.getByRole("button",{name:/결과 불명 · 合成|결과 불명 · 합성 사례/}).first().click();assert.equal(await page.locator(".image-canvas img").count(),0);check("unknown image has no success preview");
  await page.getByRole("tab",{name:"뉴스 TOP 3 자동 제작",exact:true}).click();await page.locator(".top3-results img").first().waitFor();assert.equal(await page.locator(".top3-result").count(),3);assert.equal(await page.getByRole("button",{name:"게시용 검토",exact:true}).count(),3);for(const b of await page.getByRole("button",{name:"게시용 검토",exact:true}).all())assert(await b.isDisabled());check("three ranked independent feeds and Fake publishing blocked");
  await open("automation");await page.getByRole("button",{name:"제작 예약 저장",exact:true}).first().click();let scheduleDialog=page.getByRole("dialog");await scheduleDialog.waitFor();await scheduleDialog.getByLabel("이름",{exact:true}).fill("합성 신규 예약");await scheduleDialog.getByLabel("예약 종류",{exact:true}).selectOption("daily");await scheduleDialog.getByLabel("실행 시각",{exact:true}).fill("09:30");await scheduleDialog.getByRole("button",{name:"제작 예약 저장",exact:true}).click();await page.getByRole("button",{name:/합성 신규 예약/}).waitFor();assert.equal(models.automation.collections.schedules.at(-1).status,"paused");check("schedule save remains paused and separate from activation");
  await open("settings");assert.equal(await page.locator(".approved-settings-tabs [role=tab]").count(),7);await page.getByRole("tab",{name:"AI 모델 · API 키",exact:true}).click();for(const name of ["OpenAI · Claude 키 설정","ElevenLabs 키 설정","Higgsfield 키 설정"]){await page.getByRole("button",{name,exact:true}).first().click();dialog=page.getByRole("dialog");await dialog.waitFor();for(const input of await dialog.locator("input[type=password]").all())assert.equal(await input.inputValue(),"");await page.keyboard.press("Escape");}check("settings seven tabs and blank per-provider credential dialogs");
  await page.getByRole("tab",{name:"플랫폼 계정",exact:true}).click();assert.equal(await page.locator(".platform-instagram li").count(),2);assert(await page.locator(".platform-tiktok").getByText("실전송 차단",{exact:true}).isVisible());check("multiple Instagram metadata accounts and blocked TikTok/Facebook");
  await open("analytics");await page.getByRole("button",{name:"Instagram Reels · 피드",exact:true}).click();await page.getByLabel("성과 계정 필터",{exact:true}).selectOption("12");assert.equal(await page.locator(".analytics-metrics .metric-grid>div").count(),0);assert(await page.getByText("실제 청구액",{exact:true}).isVisible());check("account selection never assigns unlinked metrics or invents billings");
  await open("publishing");assert(await page.getByText("확인 필요",{exact:false}).count()>0);assert.equal(result.posts.filter(x=>/execute|submit|publish|generate|oauth|check/.test(x.path)).length,0);check("content review separate from actual execution");
  const violations=await page.evaluate(()=>[...document.styleSheets].flatMap(sheet=>{try{const out=[];function visit(rules){for(const rule of rules){if(rule.selectorText&&rule.selectorText.includes("approved-")&&rule.selectorText.split(",").some(s=>!s.trim().startsWith(".approved-studio")))out.push(rule.selectorText);if(rule.cssRules)visit(rule.cssRules);}}visit(sheet.cssRules);return out;}catch{return [];}}));assert.deepEqual(violations,[]);check("all new CSS selectors are workspace scoped");
 }
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.externalRequests,[]);
 await context.close();
}finally{if(browser)await browser.close();fs.writeFileSync(path.join(out,"browser-results.json"),JSON.stringify(result,null,2));}
 console.log(JSON.stringify({phase,captures:result.captures.length,checks:result.checks.length,errors:result.errors.length,externalApplicationRequests:result.externalRequests.length,actualAPICalls:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
