const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {stripTypeScriptTypes}=require('node:module');
const studio=path.join(__dirname,'../src/studio');
function extract(file,start,end){
  const raw=fs.readFileSync(file,'utf8');
  const first=raw.indexOf(start),last=raw.indexOf(end,first+start.length);
  assert.ok(first>=0&&last>first,'actual source helper must exist');
  return raw.slice(first,last).replace(/^export /gm,'');
}
const source=extract(path.join(studio,'contracts.ts'),'export function safeMedia(','export function itemTitle(')+'\n'+
  extract(path.join(studio,'CommandDialog.tsx'),'export function localCharacterRenderReview(','function choices(')+'\n'+
  extract(path.join(studio,'CommandDialog.tsx'),'function initial(','export async function submitOriginal(');
const compiled=stripTypeScriptTypes(source,{mode:'transform'});
const sandbox={exports:{}};
vm.runInNewContext(compiled+'\nexports.localCharacterRenderReview=localCharacterRenderReview;exports.manualInitial=initial;',sandbox);
const review=sandbox.exports.localCharacterRenderReview;
const id='a'.repeat(32),action={id:'character_act_render'};
const scene=(position,duration)=>({position,state:'downloaded',seconds:3,media:{duration},mediaUrl:`/character/${id}/clips/${position}`});
const view=scenes=>({collections:{jobs:[{id,state:'clips_review',duration:15,scenes}]}});

test('old single file uses actual15.042seconds and never invents five plan files',()=>{
  const result=review(action,{job_id:id},view([scene(1,15.042)]));
  assert.equal(result.clips.length,1);assert.equal(result.clips[0].seconds,15.042);
  assert.equal(result.clips[0].durationBasis,'파일 확인');assert.equal(result.ready,true);
});
test('five actual clips stay five3second files and invalid media cannot be reviewed ready',()=>{
  const rows=Array.from({length:5},(_,i)=>scene(i+1,3));
  let result=review(action,{job_id:id},view(rows));
  assert.equal(result.clips.length,5);assert.equal(result.clips.every(x=>x.seconds===3),true);assert.equal(result.ready,true);
  rows[3].mediaUrl='https://outside.invalid/other.mp4';
  result=review(action,{job_id:id},view(rows));assert.equal(result.ready,false);assert.equal(result.clips[3].mediaUrl,null);
});
test('review remains manual and unrelated paid dialogs have no local-render override',()=>{
  assert.equal(review({id:'character_act_submit'},{job_id:id},view([scene(1,15)])),null);
  const result=review(action,{job_id:'b'.repeat(32)},view([scene(1,15)]));
  assert.equal(result.ready,false);assert.equal(result.clips.length,0);
  const initial=sandbox.exports.manualInitial({...action,fields:[{name:'reviewed',type:'boolean',default:true},{name:'consent',type:'boolean',default:true}]},
    {reviewed:true,consent:true},{catalog:{}});
  assert.equal(initial.reviewed,false);assert.equal(initial.consent,false);
});
