"use strict";
// Synthetic React-only verification. No Python app, providers, credentials or operating profile.
const fs=require("fs"),path=require("path"),assert=require("assert"),crypto=require("crypto");
const {chromium}=require(process.env.NF_UI_PLAYWRIGHT_ENTRY);
const project=process.env.NF_UI_PROJECT,dist=process.env.NF_UI_DIST,out=process.env.NF_UI_OUTPUT,media=process.env.NF_UI_MEDIA_ROOT;
const major=false;
const phase=process.env.NF_UI_PHASE||"after",origin="http://127.0.0.1:18765";
for(const x of [project,dist,out,media])assert(path.isAbsolute(x));fs.mkdirSync(out,{recursive:true});
const models=Object.fromEntries(fs.readdirSync(path.join(project,"tools/studio_v3/fixtures")).filter(n=>n.endsWith(".json")).map(n=>[n.slice(0,-5),JSON.parse(fs.readFileSync(path.join(project,"tools/studio_v3/fixtures",n),"utf8"))]));
for(const m of Object.values(models)){if(m.projects?.[0])m.projects[0].mediaUrl="/video/jobs/1/file";}
models.characters.collections.jobs[0].referenceUrl="/api/studio/characters/demo-character/reference";
models.publishing.collections.accounts=[{id:11,platform:"instagram",label:"합성 Instagram A",status:"registered",api_ready:false},{id:12,platform:"instagram",label:"합성 Instagram B",status:"registered",api_ready:false},{id:13,platform:"youtube",label:"합성 YouTube",status:"registered",api_ready:false}];
models.images.collections.drafts.push({id:9,title:"검증된 Fake 이미지",prompt:"합성 결과 이미지",selection:models.images.catalog.imageDefaults,status:"success",outputId:9,mediaUrl:"/image-studio/9/file"});
models.images.collections.posts.push({id:7,title:"뉴스 카드 · 합성",plan:{title:"뉴스 카드 · 합성",body:"저장된 합성 뉴스 요약",hashtags:["#합성자료"]},status:"review_required",mediaUrl:"/image-posts/7/file"});
const top3={id:1,analysisId:2,revision:1,simulation:true,paused:false,canGenerate:false,selection:models.images.catalog.imageDefaults,price:"Fake 검증 · 실제 과금 없음",publishApproval:"실제 게시 차단",items:models.images.collections.articles.map((a,i)=>({rank:i+1,status:"success",mediaUrl:`/api/feed-batches/1/items/${i+1}/file`,content:{title:a.title,body:a.summary,hashtags:"#합성자료"},source:{origin:"저장된 합성 분석",references:[{publisher:a.publisher}],title:a.title,body:a.summary},caption:a.summary,prompt:"합성 이미지 지시문",attempt:1,history:[]}))};
const production={schemaVersion:1,collection:{id:1,createdAt:"2026-10-26T08:00:00Z"},selection:{id:2,provider:"claude_api",model:"claude-sonnet-4-6",createdAt:"2026-10-26T09:00:00Z",overview:"합성 뉴스 TOP 3 분석",stale:false},blockedReason:null,top3:models.images.collections.articles.map((a,i)=>({rank:i+1,articleId:a.id,articleIds:[a.id],title:a.title,summary:a.summary,reason:"합성 선정 근거",category:a.category,thumbnailUrl:`/news/${a.id}/thumbnail`,references:[{url:a.url,publisher:a.publisher}],draftId:i===0?1:null,draftRevision:i===0?1:null,body:a.summary,origin:"합성 검증"}))};
let revisionConflict=false;
models.characters.collections.jobs[0].scenes=[{position:1,state:"downloaded",seconds:10},{position:2,state:"failed",seconds:10},{position:3,state:"unknown",seconds:10}];
models.characters.collections.jobs[0].state="submission_unknown";
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
    const d=models.shorts.collections.drafts[0];if(revisionConflict||Number(form.get("revision"))!==d.revision)return json({detail:"다른 화면에서 변경됐습니다. 편집 내용을 유지하세요."},409);
    d.content=JSON.parse(form.get("content"));d.revision++;return json({saved:true});
   }
   if(u.pathname==="/image-studio/drafts"){models.images.collections.drafts.push({id:99,title:form.get("prompt"),prompt:form.get("prompt"),selection:Object.fromEntries(["model","size","quality","provider"].map(k=>[k,form.get(k)])),status:"saved",outputId:null,mediaUrl:null});return json({saved:true});}
   if(u.pathname==="/schedules"){models.automation.collections.schedules.push({id:"fixture-new",name:form.get("name"),kind:form.get("kind"),local_time:form.get("local_time"),status:"paused",revision:1});return json({saved:true});}
   return json({detail:"Synthetic boundary: real generation, OAuth and publishing are blocked."},403);
  }
  if(u.pathname==="/api/studio/production-context")return json(production);
  if(/^\/news\/\d+\/thumbnail$/.test(u.pathname))return route.fulfill({contentType:"image/png",body:png});
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
 await page.setViewportSize({width:1920,height:1080});await page.goto(origin+"/studio/characters");await page.locator(".core-timeline .core-state").first().waitFor();await settle();
 const expected=["클립 저장","실패 · 확인 필요","결과 불명 · 재요청 금지"],actual=await page.locator(".core-timeline .core-state").allTextContents();
 result.characterSceneContract={input:["downloaded","failed","unknown"],actual,expected,verdict:JSON.stringify(actual)===JSON.stringify(expected)?"PASS":"FAIL",evidenceKind:"actual rebuilt React + synthetic DTO matching real Python API shape; not a live full-app browser connection"};
 await page.screenshot({path:path.join(out,"character-scene-state.png"),fullPage:true,animations:"disabled",caret:"hide"});
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.externalRequests,[]);assert.equal(result.posts.length,0);
 assert.deepEqual(actual,expected,"Character storyboard must show the API's scene.state, not silently label failed/unknown clips pending");
 await context.close();
 }finally{if(browser)await browser.close();fs.writeFileSync(path.join(out,"browser-results.json"),JSON.stringify(result,null,2));}
})().catch(e=>{console.error(e);process.exitCode=1;});
