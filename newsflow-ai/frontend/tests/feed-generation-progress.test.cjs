const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {stripTypeScriptTypes}=require('node:module');
const filename=path.resolve(__dirname,'../src/studio/core/FeedGenerationProgress.tsx');
const source=fs.readFileSync(filename,'utf8');
const helper=source.slice(source.indexOf('export function feedProgress'),source.indexOf('export default function')).replace('export function','function');
const sandbox={exports:{}};vm.runInNewContext(stripTypeScriptTypes(helper,{mode:'transform'})+'\nexports.feedProgress=feedProgress;',sandbox);
const {feedProgress}=sandbox.exports;
const batch=(statuses,ranks=[1,2,3])=>({items:statuses.map((status,i)=>({rank:ranks[i],status}))});
test('first request shows current item and zero completion',()=>{
 const b=batch(['pending','pending','pending']),p=feedProgress(b,true,1);assert.equal(p.title,'TOP 1 이미지 생성 중');assert.equal(p.percent,0);

});
test('sequential completion and current item update',()=>{for(const [statuses,rank,count,percent] of [[['success','pending','pending'],2,1,33],[['success','success','pending'],3,2,66]]){const p=feedProgress(batch(statuses),true,rank);assert.equal(p.completed,count);assert.equal(p.percent,percent);assert.equal(p.current,rank);}});
test('all successful results show100%',()=>{const p=feedProgress(batch(['success','success','success']),false,null);assert.equal(p.finished,true);assert.equal(p.percent,100);assert.equal(p.title,'이미지 생성 완료');});
test('failure or unknown never show completed',()=>{let p=feedProgress(batch(['success','failed','pending']),false,null);assert.equal(p.percent,33);assert.match(p.title,/중단/);for(const status of ['unknown','running','missing']){p=feedProgress(batch(['success',status,'pending']),false,null);assert.equal(p.finished,false);assert.match(p.title,/결과 확인 필요/);}});
test('saving costs is not image generation',()=>{const p=feedProgress(batch(['pending','pending','pending']),true,null);assert.equal(p.current,null);assert.equal(p.title,'이미지 생성 대기');});
test('pause waits for current response',()=>{const p=feedProgress(batch(['success','pending','pending']),true,2,true);assert.match(p.title,/중단 대기 · TOP 2/);assert.equal(p.percent,33);assert.equal(feedProgress({...batch(['success','pending','pending']),paused:true},false,null).title,'생성 일시 중단');});
test('selected single news and empty list',()=>{const p=feedProgress(batch(['pending'],[3]),true,3);assert.equal(p.title,'TOP 3 이미지 생성 중');assert.equal(p.total,1);assert.equal(feedProgress(batch(['success'],[3]),false,null).percent,100);const empty=feedProgress(batch([]),false,null);assert.equal(empty.percent,0);assert.equal(empty.finished,false);});
test('transport errors remain visible and stale current rank is not busy',()=>{assert.equal(feedProgress(batch(['pending','pending','pending']),false,null,false,'서버 응답 확인 필요').title,'서버 응답 확인 필요');assert.equal(feedProgress(batch(['success','success','success']),true,3).current,null);});


