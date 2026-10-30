import {useEffect, useRef, useState} from 'react';
import {CharacterModal, characterCommand} from './CharacterAutomation';
import type {Item} from '../contracts';

export function SavedStoryReview({jobId,csrf,onClose,onRecovered}:{jobId:string;csrf:string;onClose:()=>void;onRecovered:()=>Promise<unknown>}) {
  const [value,setValue]=useState<Item|null>(null),[raw,setRaw]=useState(''),[hash,setHash]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const [rawInvalid,setRawInvalid]=useState(false);const sending=useRef(false);
  useEffect(()=>{let active=true;setValue(null);setHash('');setError('');
    fetch(`/api/studio/characters/${jobId}/story-response`,{credentials:'same-origin'})
      .then(async response=>{if(!response.ok)throw Error('보관된 응답을 불러오지 못했습니다.');return response.json();})
      .then(data=>{if(active){setValue(data.candidate);setRaw(JSON.stringify(data.candidate,null,2));setHash(data.expected_hash);}})
      .catch(()=>{if(active)setError('보관된 응답을 불러오지 못했습니다. 추가 AI 요청은 하지 않았습니다.');});
    return()=>{active=false;};},[jobId]);
  function edit(index:number,key:string,text:string){
    if(!value)return;const next=structuredClone(value);next.scenes[index][key]=text;
    setValue(next);setRaw(JSON.stringify(next,null,2));setError('');
  }
  async function recover(){if(sending.current||!hash)return;sending.current=true;setBusy(true);setError('');
    try{const script=JSON.parse(raw);await characterCommand(`/api/studio/characters/${jobId}/recover-story`,csrf,
      {consent:'true',script:JSON.stringify(script),expected_hash:hash});await onRecovered();onClose();}
    catch{setError('아직 검증을 통과하지 못했습니다. 글자 수·장면 연결·길이를 확인하세요. 추가 AI 요청은 하지 않았습니다.');}
    finally{setBusy(false);sending.current=false;}
  }
  const scenes=Array.isArray(value?.scenes)?value.scenes.slice(0,60):[];
  return <CharacterModal title="보관된 스토리 검토" busy={busy} onClose={onClose} footer={<>
    <button type="button" disabled={busy} onClick={onClose}>닫기</button>
    <button type="button" className="primary" disabled={busy||!hash} onClick={()=>void recover()}>편집본 검증·복구 · 추가 비용 없음</button>
  </>}>
    <p>원본 응답을 보존한 채 편집합니다. 모든 검증을 통과해야 견적을 확인할 수 있습니다.</p>
    {!value&&!error&&<p role="status">보관된 응답을 불러오는 중…</p>}
    {scenes.map((scene:Item,index:number)=>scene && typeof scene==='object' ? <section key={index}>
      <h3>장면 {index+1}</h3>
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
