import { useEffect, useRef, useState } from 'react';
import type { Item } from '../contracts';

type Props={project:Item; form:Item; setForm:(fn:(old:Item)=>Item)=>void; csrf:string; targets?:string[]};
export default function PostingCopyReview({project,form,setForm,csrf,targets=[]}:Props){
  const [state,setState]=useState<Item|null>(null),[provider,setProvider]=useState('claude_api');
  const [message,setMessage]=useState(''),[busy,setBusy]=useState(false),[confirm,setConfirm]=useState(false);
  const [suggestion,setSuggestion]=useState<Item|null>(null);
  const [reviewed,setReviewed]=useState(false);
  useEffect(()=>setReviewed(false),[JSON.stringify(targets),form.title,form.description,form.hashtags]);
  const lock=useRef(false),alive=useRef(true),dialog=useRef<HTMLDialogElement>(null);
  const fields=()=>({title:form.title??project.title??'',description:form.description??'',hashtags:String(form.hashtags??'').split(/\s+/).filter(Boolean)});
  const fingerprint=JSON.stringify(fields());
  const currentFingerprint=useRef(fingerprint);currentFingerprint.current=fingerprint;
  useEffect(()=>{const loadingFingerprint=currentFingerprint.current;alive.current=true;fetch('/api/studio/publishing/copy?project_id='+encodeURIComponent(project.id),{credentials:'same-origin',cache:'no-store'})
    .then(async r=>{const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'게시 문구를 읽지 못했습니다.');return d;})
    .then(d=>{if(!alive.current)return;setState(d);if(d.copy && currentFingerprint.current===loadingFingerprint)setForm(old=>({...old,...d.copy,hashtags:d.copy.hashtags.join(' ')}));})
    .catch(()=>{if(alive.current)setMessage('게시 문구를 불러오지 못했습니다. 새로고침해 주세요.');});
    return()=>{alive.current=false};},[project.id]);
  useEffect(()=>{if(confirm)dialog.current?.showModal();else dialog.current?.close();},[confirm]);
  async function post(action:string,extra:Item){
    if(!state)throw Error('콘텐츠를 다시 선택하세요.');
    const body=new URLSearchParams({csrf_token:csrf,project_id:project.id,source_hash:state.sourceHash,revision:String(state.revision),...extra});
    const r=await fetch('/api/studio/publishing/copy/'+action,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded'},body});
    const d=await r.json().catch(()=>null);
    if(!r.ok)throw Error(typeof d?.detail==='string'?d.detail:'요청을 완료하지 못했습니다. 자동으로 다시 요청하지 않습니다.');return d;
  }
  async function run(action:'save'|'review'|'apply'|'validate'|'prepare'){
    if(lock.current||!state)return;lock.current=true;setBusy(true);setMessage('');setConfirm(false);
    const before=fingerprint;
    try{
      const result=await post(action,action==='prepare'?{copy:before,preparation:JSON.stringify({platforms:targets,content_reviewed:reviewed,rights_reviewed:reviewed,sources_reviewed:reviewed})}:action==='review'?{provider,consent:'true',request_id:crypto.randomUUID().replaceAll('-',''),copy:before}:action==='apply'?{review_id:String(suggestion?.id)}:{copy:before});
      if(!alive.current)return;
      if(action==='validate'){setMessage('제목·설명·해시태그 형식을 확인했습니다. 게시 승인과는 별도입니다.');}
      else if(action==='review'){setSuggestion({...result,formFingerprint:before});setMessage('수정안을 확인한 뒤 적용해 주세요.');}
      else{setState(old=>({...old,...result}));
        if(currentFingerprint.current===before){setForm(old=>({...old,...result.copy,hashtags:result.copy.hashtags.join(' ')}));setMessage(action==='prepare'?'플랫폼별 게시 준비를 저장했습니다. 실제 게시는 실행하지 않았습니다.':'게시 문구를 저장했습니다.');}
        else setMessage('요청한 문구를 저장했습니다. 이후 입력한 변경 내용은 아직 저장하지 않았습니다.');
        setSuggestion(null);}
    }catch(e){if(alive.current)setMessage(e instanceof Error?e.message:'저장 실패');}
    finally{lock.current=false;if(alive.current)setBusy(false);}
  }
  const savedFields=state?.copy?JSON.stringify({title:state.copy.title,description:state.copy.description,hashtags:state.copy.hashtags}):'';
  const preparedTargets=[...(state?.preparation?.platforms??[])].sort().join(',');
  const selected=state?.providers.find((x:Item)=>x.id===provider);
  return <section className="mg-copy-review" aria-label="게시 문구 검토">
    <div className="mg-actions">
      <button disabled={busy||!state} onClick={()=>void run('save')}>게시 문구 저장</button>
      <button disabled={busy||!state} onClick={()=>void run('validate')}>문구 형식 검사</button>
      <button disabled={busy||!state} onClick={()=>{setMessage('');setConfirm(true)}}>AI 제목·설명·해시태그 검토</button>
    </div>
    {project.kind!=="news"&&<div className="mg-copy-preparation">
      <label className="mg-inline"><input type="checkbox" checked={reviewed} disabled={busy}
        onChange={e=>setReviewed(e.target.checked)}/>콘텐츠·권리·출처 검토 완료</label>
      <button disabled={busy||!state||!reviewed||!targets.length} onClick={()=>void run('prepare')}>선택 플랫폼 게시 준비 저장</button>
      {!targets.length&&<p className="mg-muted">오른쪽에서 게시 플랫폼을 선택하세요.</p>}
      {state?.preparation&&<p role="status">{state.preparationCurrent&&savedFields===fingerprint&&preparedTargets===[...targets].sort().join(',')?'저장된 준비':'내용 변경 · 재검토 필요'} · {state.preparation.platforms.join(', ')} · 미게시</p>}
    </div>}
    {busy&&<p role="status">{suggestion?'게시 문구 처리 중…':'요청 처리 중…'}</p>}
    {message&&<p role="status">{message}</p>}
    {suggestion&&<div className="mg-copy-suggestion"><strong>AI 수정안</strong>
      <p>{suggestion.suggestion.title}</p><p className="mg-copy-description">{suggestion.suggestion.description}</p><p>{suggestion.suggestion.hashtags.join(' ')}</p>
      {suggestion.suggestion.notes.map((s:string,i:number)=><p key={i} className="mg-muted">{s}</p>)}
      <button disabled={busy||fingerprint!==suggestion.formFingerprint} onClick={()=>void run('apply')}>수정안 적용·저장</button>
      <button disabled={busy} onClick={()=>setSuggestion(null)}>현재 문구 유지</button>
      {fingerprint!==suggestion.formFingerprint&&<p>입력 내용이 변경되었습니다. 기존 제안은 적용하지 않습니다.</p>}
    </div>}
    <dialog ref={dialog} aria-label="AI 게시 문구 검토" className="mg-copy-dialog" onCancel={()=>setConfirm(false)}>
      <h2>AI 게시 문구 검토</h2><p>{project.title}</p>
      <label>검토 AI<select aria-label="게시 문구 검토 AI" value={provider} onChange={e=>setProvider(e.target.value)}>
        {(state?.providers??[]).map((p:Item)=><option key={p.id} value={p.id}>{p.id==='claude_api'?'Claude':'OpenAI'} · {p.model}</option>)}
      </select></label>
      <p>이번 요청 상한 US${selected?.limitUsd??'미설정'}. 저장된 주제·대본과 입력한 문구만 전송합니다.</p>
      <p className="mg-muted">영상·이미지 파일은 전송하지 않습니다. 수정안 확인 후 적용하며 실제 게시는 하지 않습니다.</p>
      {!selected?.ready&&<p>설정에서 API 연결·모델·사용 한도를 확인하세요.</p>}
      <div className="mg-actions"><button onClick={()=>setConfirm(false)}>취소</button><button disabled={busy||!selected?.ready} onClick={()=>void run('review')}>검토 요청 · 유료</button></div>
    </dialog>
  </section>
}
