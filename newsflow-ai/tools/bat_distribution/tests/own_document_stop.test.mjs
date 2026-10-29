import test from 'node:test';
import assert from 'node:assert/strict';
import {watchOwnDocumentStop,stopNoticePath,stopCloseFallback} from '../../../frontend/src/studio/ownDocumentStop.ts';

const origin='http://127.0.0.1:18780';
function response(data={schemaVersion:1,stopAccepted:true},changes={}) {
  return {status:200,ok:true,url:origin+stopNoticePath,redirected:false,json:async()=>data,...changes};
}
function fake(responses) {
  const controller=new AbortController(),calls=[],timers=[],messages=[];
  const state={closed:false,closeCalls:0,otherTabClosed:false};
  const host={origin,signal:controller.signal,
    fetchNotice:async(path,options)=>{calls.push({path,options});const next=responses.shift();if(next instanceof Error)throw next;return next;},
    closeSelf:()=>{state.closeCalls++;},isClosed:()=>state.closed,
    schedule:(callback,delay)=>timers.push({callback,delay}),notify:message=>messages.push(message)};
  return {host,controller,calls,timers,messages,state};
}
test('explicit authenticated Stop requests only this tab once',async()=>{
  const f=fake([response()]);
  assert.equal(await watchOwnDocumentStop(f.host),'requested');
  assert.equal(f.state.closeCalls,1);assert.equal(f.state.otherTabClosed,false);
  assert.equal(f.calls[0].path,stopNoticePath);
  assert.equal(f.calls[0].options.credentials,'same-origin');
  assert.equal(f.calls[0].options.cache,'no-store');
  assert.equal(f.calls[0].options.redirect,'error');
  assert.deepEqual(f.messages,[]);assert.equal(f.timers.length,1);
});
test('browser refusal gives visible direct-close fallback',async()=>{
  const f=fake([response()]);await watchOwnDocumentStop(f.host);f.timers[0].callback();
  assert.deepEqual(f.messages,[stopCloseFallback]);assert.equal(f.state.closeCalls,1);
});
test('successful close needs no fallback',async()=>{
  const f=fake([response()]);await watchOwnDocumentStop(f.host);f.state.closed=true;f.timers[0].callback();
  assert.deepEqual(f.messages,[]);
});
test('throwing browser close still gives fallback without force close',async()=>{
  const f=fake([response()]);f.host.closeSelf=()=>{throw Error('blocked');};
  assert.equal(await watchOwnDocumentStop(f.host),'requested');f.timers[0].callback();
  assert.deepEqual(f.messages,[stopCloseFallback]);assert.equal(f.state.otherTabClosed,false);
});
for (const [name,value] of [
 ['network failure',Error('offline')],['unauthorized',response(undefined,{status:403,ok:false})],
 ['redirected response',response(undefined,{redirected:true})],
 ['different response URL',response(undefined,{url:origin+'/health'})],
 ['invalid body',response({schemaVersion:1,stopAccepted:'true'})],
 ['unsupported schema',response({schemaVersion:2,stopAccepted:true})],
 ['invalid JSON',response(undefined,{json:async()=>{throw Error('parse');}})],
]) test(`${name} never closes a tab`,async()=>{
  const f=fake([value]);assert.equal(await watchOwnDocumentStop(f.host),'disconnected');
  assert.equal(f.state.closeCalls,0);assert.equal(f.timers.length,0);assert.deepEqual(f.messages,[]);
});
test('ordinary read response cannot close; later explicit accepted response can',async()=>{
  const f=fake([response({schemaVersion:1,stopAccepted:false}),response()]);
  assert.equal(await watchOwnDocumentStop(f.host),'requested');assert.equal(f.calls.length,2);assert.equal(f.state.closeCalls,1);
});
test('cancelled page cannot close on a late response',async()=>{
  const f=fake([response()]);f.host.fetchNotice=async()=>{f.controller.abort();return response();};
  assert.equal(await watchOwnDocumentStop(f.host),'cancelled');assert.equal(f.state.closeCalls,0);
});
