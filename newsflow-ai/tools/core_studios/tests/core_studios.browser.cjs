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
 async function open(name){const names={"images-top3":"images?mode=top3","images":"images","shorts":"shorts?rank=1"};await page.goto(origin+"/studio/"+(names[name]||name));await page.locator(["dashboard","create"].includes(name)?(name==="dashboard"?".hero":".create-page"):["shorts","characters","images","images-top3","news"].includes(name)?".core-panel":".command-catalog").first().waitFor();if(name==="automation")await page.locator(".schedule-table button, .record-row").first().click();if(name==="library")await page.locator(".media-tile").first().click();if(name==="publishing")await page.locator(".record-row").first().click();await settle();const vid=page.locator("video").first();if(await vid.count()){await vid.evaluate(async v=>{if(v.readyState<1)await new Promise((resolve,reject)=>{v.addEventListener("loadedmetadata",resolve,{once:true});v.addEventListener("error",reject,{once:true});});v.pause();if(Math.abs(v.currentTime-1)>.01){const seek=new Promise(r=>v.addEventListener("seeked",r,{once:true}));v.currentTime=1;await seek;}});}await settle();}
 const names=process.env.NF_CORE_PROTECTED_ONLY==="1"?["automation","library","publishing"]:["shorts","characters","images","images-top3","news","dashboard","create","automation","library","publishing","analytics","settings"];
 for(const [width,height] of [[1920,1080],[1366,768]]){await page.setViewportSize({width,height});for(const name of names){await open(name);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),`${name} ${width} overflow`);const file=`${name}-${width}.png`;await page.screenshot({path:path.join(out,file),animations:"disabled",caret:"hide"});result.captures.push({name,width,height,file});check("screen renders without horizontal overflow",{name,width});}}
 if(process.env.NF_CORE_PROTECTED_ONLY==="1"){assert.deepEqual(result.errors,[]);assert.deepEqual(result.externalRequests,[]);await context.close();return;}
 await page.setViewportSize({width:1920,height:1080});await open("shorts");
 assert.equal(await page.locator(".core-news-card").count(),3);assert.equal(await page.locator(".core-character-steps,.stage-rail").count(),0);check("news shorts shows only TOP ranks and no numbered production steps");
 const script=await page.locator(".core-script").boundingBox(),preview=await page.locator(".core-simple-video").boundingBox(),bar=await page.locator(".core-render-bar").boundingBox();assert(script.x+script.width<=preview.x+2);assert(bar.y<1080);check("script and simple portrait preview grouped above accessible render strip");
 await page.locator(".core-news-card").nth(1).click();assert(await page.getByText("선택 기사와 기존 분석을 사용해 대본을 생성하세요。".replace("。",".")).isVisible());await page.getByRole("button",{name:"AI 대본 생성",exact:true}).click();assert.equal(await page.getByRole("dialog").getByLabel("저장된 분석",{exact:true}).inputValue(),"2");assert.equal(await page.getByRole("dialog").getByLabel("선정 순위",{exact:true}).inputValue(),"2");await page.getByRole("button",{name:"닫기",exact:true}).click();check("TOP rank selection binds existing analysis and rank without reanalysis");
 await page.locator(".core-news-card").first().click();const narration=page.getByLabel("장면 1 대본",{exact:true});await narration.fill("합성 수정 대본 · 저장 검증");await page.getByRole("button",{name:"대본 저장",exact:true}).click();await page.getByText("대본을 저장했습니다.",{exact:true}).waitFor();assert.equal(models.shorts.collections.drafts[0].revision,2);check("script edits use original revision-preserving POST");
 revisionConflict=true;await narration.fill("충돌 후 보존할 합성 대본");await page.getByRole("button",{name:"대본 저장",exact:true}).click();await page.getByText(/다른 화면에서 변경됐습니다/).waitFor();assert.equal(await narration.inputValue(),"충돌 후 보존할 합성 대본");await page.reload();await page.getByLabel("장면 1 대본",{exact:true}).waitFor();assert.equal(await page.getByLabel("장면 1 대본",{exact:true}).inputValue(),"충돌 후 보존할 합성 대본");check("revision conflict preserves recoverable text across reload");revisionConflict=false;
 models.shorts.collections.drafts[0].revision++;await page.getByRole("button",{name:"제작실 새로고침",exact:true}).click();await page.getByText(/새 저장 버전이 있습니다/).waitFor();assert.equal(await page.getByLabel("장면 1 대본",{exact:true}).inputValue(),"충돌 후 보존할 합성 대본");await page.getByRole("button",{name:"대본 저장",exact:true}).click();await page.getByText(/다른 화면에서 변경됐습니다/).waitFor();assert.equal(models.shorts.collections.drafts[0].revision,3);check("refresh cannot silently rebase dirty text onto newer server revision");
 await page.locator(".core-advanced summary").click();page.once("dialog",dialog=>dialog.accept());await page.getByRole("button",{name:"최신 저장본 다시 열기",exact:true}).click();await page.getByRole("button",{name:"이전 버전 편집 복구",exact:true}).click();assert.equal(await page.getByLabel("장면 1 대본",{exact:true}).inputValue(),"충돌 후 보존할 합성 대본");check("older edit recovery retains original revision for explicit conflict resolution");
 page.once("dialog",dialog=>dialog.accept());await page.getByRole("button",{name:"최신 저장본 다시 열기",exact:true}).click();await page.getByLabel("장면 1 대본",{exact:true}).fill("최신본에서 다시 편집한 합성 대본");

 await page.getByRole("button",{name:"대본 저장",exact:true}).click();await page.getByText("대본을 저장했습니다.",{exact:true}).waitFor();await page.getByLabel("영상 길이",{exact:true}).selectOption("45");await page.getByRole("button",{name:"영상 제작 · 승인 확인",exact:true}).click();assert.equal(await page.getByRole("dialog").getByLabel("대본",{exact:true}).inputValue(),"1");assert.equal(await page.getByRole("dialog").getByLabel("최종 길이(초)",{exact:true}).inputValue(),"45");assert.equal(await page.getByRole("dialog").getByLabel("내용과 출처를 검토했습니다",{exact:true}).isChecked(),false);await page.getByRole("button",{name:"닫기",exact:true}).click();check("render is not sent before original review and permission modal");
 await open("characters");assert.equal(await page.locator(".core-reference img").evaluate(i=>i.naturalWidth),32);assert.equal(await page.locator(".core-character-steps > div").count(),3);assert.equal(await page.getByRole("button",{name:"장면 생성 · 비용 승인",exact:true}).isDisabled(),true);assert.equal(await page.locator(".core-timeline > button").count(),3);check("character reference, three-step layout, fixed model and state-gated approval preserved");
 models.characters.collections.jobs[0].referenceUrl=null;models.characters.collections.jobs[0].state="submission_unknown";await open("characters");await page.getByText("참조 PNG 없음 · 파일을 등록하세요。".replace("。",".")).waitFor();assert.equal(await page.getByRole("button",{name:"장면 생성 · 비용 승인",exact:true}).isDisabled(),true);check("missing character reference and unknown submission fail closed");
 await open("images");assert.equal(await page.getByRole("tab").count(),2);await page.getByLabel("이미지 프롬프트",{exact:true}).fill("테스트용 합성 하늘 이미지");await page.getByLabel("이미지 품질",{exact:true}).selectOption("high");await page.getByRole("button",{name:"초안 저장 · 참조 첨부",exact:true}).click();assert.equal(await page.getByRole("dialog").getByLabel("이미지 지시문",{exact:true}).inputValue(),"테스트용 합성 하늘 이미지");await page.getByRole("button",{name:"닫기",exact:true}).click();check("independent prompt and model options bind original draft dialog without paid calls");
 await page.getByRole("button",{name:/검증된 Fake 이미지/}).first().click();assert(await page.getByAltText("실제 생성 결과").isVisible());assert(await page.getByRole("button",{name:"견적 · 생성 승인",exact:true}).isDisabled());check("only validated success previews and completed output cannot regenerate implicitly");
 await open("images-top3");assert.equal(await page.locator(".core-feed-results article").count(),3);assert.equal(await page.getByText("이미지 제작 방식",{exact:true}).count(),0);assert.equal(await page.getByRole("button",{name:"TOP 3 생성 · 비용 승인",exact:true}).isDisabled(),true);check("TOP3-only news mode preserves three independent outputs and fail-closed price approval");
 top3.items[1].status="unknown";top3.items[1].mediaUrl=null;await open("images-top3");assert.equal(await page.locator(".core-feed-results img").count(),2);assert(await page.getByRole("button",{name:"TOP 3 생성 · 비용 승인",exact:true}).isDisabled());check("unknown item cannot replay and other success files remain visible");
 await open("news");await page.getByLabel("보관 뉴스 검색",{exact:true}).fill("없는 합성 검색어");await page.getByText("검색 조건에 맞는 보관 기사가 없습니다.",{exact:true}).waitFor();await page.getByLabel("보관 뉴스 검색",{exact:true}).fill("");await page.locator(".core-news-list > button").first().click();assert(await page.getByText("합성 선정 근거",{exact:true}).isVisible());assert.equal(await page.locator(".core-news-center textarea").count(),0);check("news studio searches stored articles and reuses real analysis fields without a video editor");
 production.top3=[];production.selection=null;production.blockedReason="합성: 완료 분석 없음";await open("shorts");assert.equal(await page.locator(".core-news-card").count(),0);assert(await page.getByRole("button",{name:"AI 대본 생성",exact:true}).isDisabled());check("missing TOP3 explicitly blocks script generation without fallback invented news");
 await context.route("**/api/studio/production-context",route=>route.fulfill({status:503,contentType:"application/json",body:'{"detail":"synthetic failure"}'}));await page.goto(origin+"/studio/news");await page.getByRole("alert").waitFor();assert(await page.getByRole("button",{name:"다시 읽기",exact:true}).isVisible());check("read errors do not trigger automatic mutations");
 assert(!result.posts.some(x=>/generate|submit|publish|oauth|step|render/.test(x.path)));check("no generation, OAuth, posting or render submitted by navigation and review");
 assert.deepEqual(result.errors,[]);assert.deepEqual(result.externalRequests,[]);await context.close();
 }finally{if(browser)await browser.close();fs.writeFileSync(path.join(out,"browser-results.json"),JSON.stringify(result,null,2));}
 console.log(JSON.stringify({captures:result.captures.length,checks:result.checks.length,errors:result.errors.length,externalApplicationRequests:result.externalRequests.length,actualAPICalls:0}));
})().catch(e=>{console.error(e);process.exitCode=1;});
