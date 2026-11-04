import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
const source=readFileSync(new URL('../frontend/src/studio/core/imagePrompt.ts',import.meta.url),'utf8');
const {imagePrompt,imageDescription}=await import('data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(source)).toString('base64'));
test('automatic image copy and design use the same request without inventing facts',()=>{
 const output=imagePrompt('파란 바다','실사풍','auto','unused');
 assert.ok(output.startsWith('파란 바다'));
 for(const text of ['짧은 한국어 문구','이미지와 함께 디자인','강조색','근거 없는 사실·수치·인용은 추가하지'])assert.ok(output.includes(text));
 assert.ok(!output.includes('unused'));
});
test('manual copy is preserved verbatim and remains distinct from no-copy',()=>{
 const text='오늘도 나답게\n새로운 하루 2026';
 const output=imagePrompt('꽃','','manual',text);
 assert.ok(output.includes(text));assert.ok(!output.includes('직접 만들고'));
 const none=imagePrompt('꽃','','none',text);
 assert.ok(none.includes('글자나 문구를 넣지 마세요'));assert.ok(!none.includes(text));
});

test('result copy shows user theme, not internal instructions, without changing stored prompt',()=>{
 const prompt=imagePrompt('직장인들의 일상 (반복되고 지친 하루)','3D 애니메이션','auto','');
 const original=prompt;const result=imageDescription(prompt);
 assert.equal(result.title,'직장인들의 일상');
 assert.equal(result.description,'반복되고 지친 하루 · 3D 애니메이션');
 assert.equal(result.request,'직장인들의 일상 (반복되고 지친 하루)');
 assert.equal(prompt,original);
 assert.ok(!JSON.stringify(result).includes('근거 없는 사실'));
});
test('manual and no-copy prompts retain only the user request in result descriptions',()=>{
 for(const mode of ['manual','none']){
  const result=imageDescription(imagePrompt('햇살이 들어오는 카페','실사풍',mode,'좋은 아침'));
  assert.equal(result.request,'햇살이 들어오는 카페');
  assert.equal(result.description,'햇살이 들어오는 카페 · 실사풍');
 }
});
test('historical plain prompts and user-owned wording are preserved',()=>{
 const text='시각 스타일: 실사풍\n문구를 이미지와 조화롭게 디자인하세요.';
 assert.equal(imageDescription(text).request,text);
 assert.equal(imageDescription('기존 프롬프트').title,'기존 프롬프트');
 const long='여행 풍경 '.repeat(90);const result=imageDescription(long);
 assert.ok(result.title.length<=65);assert.ok(result.description.length<=131);
 assert.equal(result.request,long.trim());
});
