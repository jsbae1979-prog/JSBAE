const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {stripTypeScriptTypes}=require('node:module');
const text=fs.readFileSync(path.join(__dirname,'../src/studio/contracts.ts'),'utf8');
const start=text.indexOf('export function safeMedia('),end=text.indexOf('export function itemTitle(',start);
assert.ok(start>=0&&end>start);
const source=stripTypeScriptTypes(text.slice(start,end).replace(/^export /gm,''),{mode:'transform'});
const box={};vm.runInNewContext(source+';this.safe=safeMedia;this.reference=characterReferenceThumbnail;',box);
const id='a'.repeat(32),url=`/api/studio/characters/${id}/reference`;
test('exact character reference endpoint is accepted for card fallback',()=>{
  assert.equal(box.safe(url),url);assert.equal(box.reference({kind:'character',id:'character:'+id}),url);
});
test('reference fallback never trusts arbitrary fields, other kinds or malformed identifiers',()=>{
  for(const row of [{kind:'image',id:'character:'+id},{kind:'character',id},{kind:'character',id:'character:../secret'},
    {kind:'character',id:'character:'+id+'?x'}, {kind:'character',id:'character:'+id.toUpperCase()},
    {kind:'character',id:'character:'+id+'/../b'}]) assert.equal(box.reference(row),null);
  assert.equal(box.reference({kind:'character',id:'character:'+id,referenceUrl:'https://outside.invalid/x'}),url);
});
test('external traversal encoded query and wrong reference paths are rejected',()=>{
  for(const value of ['https://outside.invalid'+url,'//outside.invalid'+url,url+'?download=true',url+'#x',
    url+'/../key',url.replace(id,'..'),url.replace(id,'%2e%2e'),url.replace('/reference','/reference.png'),
    url.replace(id,id.slice(1)),url.replace(id,id+'a'),url.replace('/api/','/api%2f'),url.replaceAll('/','\\'),null,{}])
    assert.equal(box.safe(value),null);
});
