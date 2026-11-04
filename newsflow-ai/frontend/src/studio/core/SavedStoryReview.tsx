import {useEffect, useRef, useState} from 'react';
import {CharacterModal, characterCommand} from './CharacterAutomation';
import type {Item} from '../contracts';

export function SavedStoryReview({jobId,csrf,onClose,onRecovered}:{jobId:string;csrf:string;onClose:()=>void;onRecovered:()=>Promise<unknown>}) {
  const [timing,setTiming]=useState<Item|null>(null);
  const [value,setValue]=useState<Item|null>(null),[raw,setRaw]=useState(''),[hash,setHash]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [rawInvalid,setRawInvalid]=useState(false);const sending=useRef(false);
  useEffect(()=>{let active=true;setValue(null);setTiming(null);setRawInvalid(false);setHash('');setError('');
    fetch(`/api/studio/characters/${jobId}/story-response`,{credentials:'same-origin'})
      .then(async response=>{if(!response.ok)throw Error('보관된 응답을 불러오지 못했습니다.');return response.json();})
      .then(data=>{if(active){setValue(data.candidate);setRaw(JSON.stringify(data.candidate,null,2));setHash(data.expected_hash);setTiming(data.timing??null);}})
      .catch(()=>{if(active)setError('보관된 응답을 불러오지 못했습니다. 추가 AI 요청은 하지 않았습니다.');});
    return()=>{active=false;};},[jobId]);
  function edit(index:number,key:string,text:string|number|null){
    if(!value)return;const next=structuredClone(value);next.scenes[index][key]=text;
    if(key==='speed'){next.scenes[index].fast_intensity=text==='fast'?'weak':null;}
    setValue(next);setRaw(JSON.stringify(next,null,2));setError('');
  }
  async function recover(){if(sending.current||!hash)return;sending.current=true;setBusy(true);setError('');
    try{const script=JSON.parse(raw);await characterCommand(`/api/studio/characters/${jobId}/recover-story`,csrf,
      {consent:'true',script:JSON.stringify(script),expected_hash:hash});await onRecovered();onClose();}
    catch{setError('아직 검증을 통과하지 못했습니다. 글자 수·장면 연결·길이를 확인하세요. 추가 AI 요청은 하지 않았습니다.');}
    finally{setBusy(false);sending.current=false;}
  }
  const scenes=Array.isArray(value?.scenes)?value.scenes.slice(0,60):[];
  const duration=(scene:Item)=>{
    if(!timing||typeof scene?.seconds!=='number')return NaN;
    const factor=scene.speed==='fast'?timing.fast[scene.fast_intensity]:1;
    const hold=scene.freeze_end==='none'||!scene.freeze_end?0:timing.freeze[scene.freeze_end];
    return scene.seconds/factor+hold;
  };
  const total=scenes.reduce((sum:number,scene:Item)=>sum+duration(scene),0);
  return <CharacterModal title="보관된 스토리 검토" busy={busy} onClose={onClose} footer={<>
    <button type="button" disabled={busy} onClick={onClose}>닫기</button>
    <button type="button" className="primary" disabled={busy||!hash||rawInvalid} onClick={()=>void recover()}>편집본 검증·복구 · 추가 비용 없음</button>
  </>}>
    <p>원본 응답을 보존한 채 편집합니다. 모든 검증을 통과해야 견적을 확인할 수 있습니다.</p>
    {timing&&<div className="core-saved-selection" role="status">
      <strong>목표 {timing.targetSeconds}초 · 편집 후 {Number.isFinite(total)?total.toFixed(2)+'초':'확인 필요'}</strong>
      <p>허용 길이 {timing.minimumSeconds}~{timing.maximumSeconds}초 · 장면 {timing.sceneRange.join('~')}개</p>
      <small>원본을 보존합니다. 속도·정지 효과는 직접 바꾼 뒤 검증하며 자동으로 늘리지 않습니다.</small>
    </div>}
    {!value&&!error&&<p role="status">보관된 응답을 불러오는 중…</p>}
    {scenes.map((scene:Item,index:number)=>scene && typeof scene==='object' ? <section key={index}>
      <h3>장면 {index+1} {Number.isFinite(duration(scene))&&<small>· 편집 후 {duration(scene).toFixed(2)}초</small>}</h3>
      {timing&&<div className="core-two-fields">
        <label>원본 클립 길이<select aria-label={`장면 ${index+1} 길이`} disabled={busy||rawInvalid} value={scene.seconds??''}
          onChange={e=>edit(index,'seconds',Number(e.target.value))}>
          {!timing.allowedClipSeconds.includes(scene.seconds)&&<option value={scene.seconds??''}>지원 길이 선택</option>}
          {timing.allowedClipSeconds.map((n:number)=><option key={n} value={n}>{n}초</option>)}
        </select></label>
        <label>재생 속도<select aria-label={`장면 ${index+1} 속도`} disabled={busy||rawInvalid} value={scene.speed??'normal'} onChange={e=>edit(index,'speed',e.target.value)}>
          <option value="normal">기본</option><option value="fast">빠르게</option>
        </select></label>
        {scene.speed==='fast'&&<label>속도 강도<select disabled={busy||rawInvalid} value={scene.fast_intensity??'weak'} onChange={e=>edit(index,'fast_intensity',e.target.value)}>
          {Object.entries(timing.fast).map(([key,n])=><option key={key} value={key}>{key==='weak'?'약하게':key==='medium'?'보통':'강하게'} · {String(n)}배</option>)}
        </select></label>}
        <label>마지막 정지<select aria-label={`장면 ${index+1} 정지`} disabled={busy||rawInvalid} value={scene.freeze_end??'none'} onChange={e=>edit(index,'freeze_end',e.target.value)}>
          <option value="none">없음</option>{Object.entries(timing.freeze).map(([key,n])=><option key={key} value={key}>{String(n)}초</option>)}
        </select></label>
      </div>}
      {(['action','camera'] as const).map(key=>{const text=typeof scene?.[key]==='string'?scene[key]:'';
        const limit=key==='action'?300:120;const count=Array.from(text).length;
        return <label key={key}>{key==='action'?'행동 · 영어':'카메라 · 영어'} · {count}/{limit}
          <textarea aria-label={`장면 ${index+1} ${key==='action'?'행동':'카메라'}`} value={text} disabled={busy||rawInvalid}
            aria-invalid={count>limit} onChange={event=>edit(index,key,event.target.value)}/>
        </label>;})}
    </section> : <p key={index}>장면 {index+1}은 전체 항목 편집에서 확인하세요.</p>)}
    {value&&<details><summary>원문·전체 항목 편집</summary>
      <textarea aria-label="보관된 스토리 전체 편집" value={raw} disabled={busy} maxLength={48000}
        onChange={event=>{setRaw(event.target.value);setError('');try{const next=JSON.parse(event.target.value);if(!next||typeof next!=='object'||Array.isArray(next))throw Error();setValue(next);setRawInvalid(false);}catch{setRawInvalid(true);}}} rows={12}/>
    </details>}
    {error&&<p role="alert">{error}</p>}
  </CharacterModal>;
}
