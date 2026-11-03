import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';


const source=fs.readFileSync(new URL('../frontend/src/studio/TopThreeFeeds.tsx',import.meta.url),'utf8');
const body=source.slice(source.indexOf('  async function runSettings('),source.indexOf('  const [regenerate, setRegenerate]'));
assert.ok(body.includes('async function runSettings('));
const script=body.replace('edit?:Item','edit').replaceAll('(x:Item)','(x)');
function fixture({limit='3',failure=false,approved=true}={}){
 const calls=[];let state={id:7,revision:1,paused:false,costReview:{settingsLimitUsd:limit},items:[1,2,3].map(rank=>({rank,status:'pending'})),canGenerate:true};
 const ctx={batch:structuredClone(state),busy:false,ready:true,stop:{current:false},setStopRequested(){},setRunningRank(){},setMessage(){},show(){},local:fn=>fn(),post:async(path,data)=>{
  calls.push({path,data});
  if(path.endsWith('cost-review'))state.costReview.approved=approved;
  if(path.endsWith('/change')){state.items=[{rank:data.rank,status:'pending'}];state.revision++;}
  if(path.endsWith('/step')){state.items.find(x=>x.status==='pending').status=failure?'unknown':'success';state.revision++;}
  return structuredClone(state);
 }};
 vm.createContext(ctx);vm.runInContext(script,ctx);
 return {ctx,calls};
}
test('opening the UI or missing saved budget never submits',async()=>{
 const {ctx,calls}=fixture({limit:null});assert.equal(calls.length,0);await ctx.runSettings();assert.equal(calls.length,0);
});
test('explicit generation uses one settings check then each pending image once',async()=>{
 const {ctx,calls}=fixture();await ctx.runSettings();assert.equal(calls.length,4);
 assert.ok(calls[0].path.endsWith('cost-review'));
 assert.equal(calls.filter(x=>x.path.endsWith('/step')).length,3);
 assert.ok(calls.slice(1).every(x=>x.data.consent===true&&x.data.reviewed===true));
 assert.ok(!calls.some(x=>'limit' in x.data));
});
test('unknown outcome stops the sequence without replay',async()=>{
 const {ctx,calls}=fixture({failure:true});await ctx.runSettings();assert.equal(calls.filter(x=>x.path.endsWith('/step')).length,1);
});
test('rejected budget cannot be overridden by the one-click UI',async()=>{
 const {ctx,calls}=fixture({approved:false});await assert.rejects(ctx.runSettings());assert.equal(calls.length,1);
});
test('explicit design edit freezes exactly one rank before its budget check',async()=>{
 const {ctx,calls}=fixture();await ctx.runSettings({rank:2,title:'수정 제목',body:'핵심 설명',accent:'#aa9922'});
 assert.equal(calls.length,3);assert.equal(calls[0].data.action,'design_edit');assert.equal(calls[0].data.rank,2);
 assert.equal(calls[1].path,'/api/feed-batches/7/cost-review');assert.equal(calls[2].path,'/api/feed-batches/7/step');
});
