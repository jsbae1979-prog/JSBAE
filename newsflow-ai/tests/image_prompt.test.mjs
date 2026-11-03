import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
const source=readFileSync(new URL('../frontend/src/studio/core/imagePrompt.ts',import.meta.url),'utf8');
const {imagePrompt}=await import('data:text/javascript;base64,'+Buffer.from(stripTypeScriptTypes(source)).toString('base64'));
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
