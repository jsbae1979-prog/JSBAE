const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../src/studio/core/CharacterStudio.tsx'),'utf8');
const body=source.slice(source.indexOf('  async function saveSettings()'),source.indexOf('  async function recoverStory()'));
function harness(job,pending=false,ok=true){
 const calls=[];const context={job,pendingReferenceCopy:pending,settings:job?.studio_selection,per:'5',FormData,URLSearchParams,
 c:{view:{csrfToken:'synthetic-csrf'},load:async()=>calls.push('load')},
 fetch:async(url,options)=>{calls.push({url,options});return {ok,json:async()=>({quoteRetained:false})}}};
 vm.runInNewContext(body+';this.run=saveSettings;',context);return {run:context.run,calls};
}
for(const state of ['script_review','quoted'])test('precision '+state+' never rewrites confirmed settings',async()=>{
 const job={id:'a'.repeat(32),precisionWorkId:'a'.repeat(32),state,studio_selection:{duration:20}};
 const before=JSON.stringify(job),h=harness(job);assert.equal(await h.run(),state==='quoted');assert.deepEqual(h.calls,[]);assert.equal(JSON.stringify(job),before);
});
test('fast mode still saves with CSRF and same-origin credentials',async()=>{
 const h=harness({id:'b'.repeat(32),state:'script_review',studio_selection:{duration:20}});
 assert.equal(await h.run(),false);assert.equal(h.calls.length,2);const request=h.calls[0];
 assert.match(request.url,/\/settings$/);assert.equal(request.options.credentials,'same-origin');assert.equal(request.options.body.get('csrf_token'),'synthetic-csrf');
});
test('failed fast save still stops before quote',async()=>{
 const h=harness({id:'b'.repeat(32),state:'script_review',studio_selection:{}},false,false);
 await assert.rejects(h.run(),/견적은 요청하지 않았습니다/);assert.equal(h.calls.length,1);
});
test('pending reference does not save or generate',async()=>{
 const h=harness({precisionWorkId:'a',studio_selection:{}},true);assert.equal(await h.run(),false);assert.deepEqual(h.calls,[]);
});
