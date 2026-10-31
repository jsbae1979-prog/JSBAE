import {useEffect,useRef,useState} from 'react';
import type {Item} from '../contracts';
import type {Controller} from './shared';

export default function LibraryTrash({c,items,title,legacy=false,restore}:{
  c:Controller;items:Item[];title:string;legacy?:boolean;restore:(item:Item)=>React.ReactNode;
}){
  const [selected,setSelected]=useState<string[]>([]),[pending,setPending]=useState<Item[]|null>(null);
  const [hidden,setHidden]=useState<string[]>([]),[busy,setBusy]=useState(false),[message,setMessage]=useState('');
  const sending=useRef(false),dialog=useRef<HTMLDialogElement>(null),cancel=useRef<HTMLButtonElement>(null);
  const id=(x:Item)=>legacy?'archive:'+String(x.key):String(x.id);
  const rows=items.filter(x=>!hidden.includes(id(x)));
  const available=c.view?.libraryPurgeAvailable===true&&c.view.commandsAvailable&&!!c.view.csrfToken;
  useEffect(()=>{const ids=new Set(items.map(id));setSelected(old=>old.filter(x=>ids.has(x)));setHidden(old=>old.filter(x=>ids.has(x)));},[items]);
  useEffect(()=>{if(pending&&dialog.current&&!dialog.current.open){dialog.current.showModal();cancel.current?.focus();}
    else if(!pending&&dialog.current?.open)dialog.current.close();},[pending]);
  function close(){if(!sending.current){setPending(null);setMessage('');}}
  async function purge(){
    if(sending.current||!available||!pending?.length)return;
    const ids=pending.map(id);sending.current=true;setBusy(true);setMessage('');
    try{
      const response=await fetch('/api/studio/library/purge',{method:'POST',credentials:'same-origin',
        body:new URLSearchParams({items:JSON.stringify(ids),confirm:'true',csrf_token:c.view?.csrfToken??''})});
      const result=await response.json().catch(()=>({}));
      if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'삭제 결과를 확인하지 못했습니다. 목록을 새로고침하세요.');
      if(!Array.isArray(result.purged)||result.purged.length!==ids.length||new Set(result.purged).size!==ids.length||!result.purged.every((x:unknown)=>typeof x==='string'&&ids.includes(x)))throw Error('삭제 결과가 불명확합니다. 자동 재요청하지 않습니다.');
      setHidden(old=>[...new Set([...old,...ids])]);setSelected(old=>old.filter(x=>!ids.includes(x)));setPending(null);
      setMessage(`${ids.length}개를 완전 삭제했습니다.`);await c.load();
    }catch(error){setMessage(error instanceof Error?error.message:'삭제 결과를 확인하지 못했습니다. 자동 재요청하지 않습니다.');}
    finally{sending.current=false;setBusy(false);}
  }
  return <details className="mg-advanced mg-library-trash">
    <summary>{title} · {rows.length}개</summary>
    <div className="mg-trash-toolbar" aria-label={title+' 선택'}>
      <strong>선택 {selected.filter(x=>rows.some(r=>id(r)===x)).length}개</strong>
      <button disabled={busy||!rows.length} onClick={()=>setSelected(rows.map(id))}>전체 선택</button>
      <button disabled={busy||!selected.length} onClick={()=>setSelected([])}>선택 해제</button>
      <button disabled={busy||!available||!selected.length} title={!available?'서버 반영 후 사용할 수 있습니다.':undefined}
        onClick={()=>{setMessage('');setPending(rows.filter(x=>selected.includes(id(x))));}}>선택 완전 삭제</button>
    </div>
    {rows.map(x=><div className="mg-trash-row" key={id(x)}>
      <input type="checkbox" aria-label={`${x.title??x.key} 완전 삭제 선택`} checked={selected.includes(id(x))} disabled={busy}
        onChange={e=>setSelected(old=>e.target.checked?[...old,id(x)]:old.filter(k=>k!==id(x)))}/>
      <div><strong>{x.title??x.key}</strong><small>{x.updatedAt??x.created_at}</small></div>
      {x.technicalStatus==='purge_failed'||x.technicalStatus==='purging'?<span>삭제 확인 필요</span>:restore(x)}
    </div>)}
    {!rows.length&&<p className="mg-muted">휴지통이 비어 있습니다.</p>}
    {message&&!pending&&<p role="status">{message}</p>}
    <dialog className="mg-library-delete-dialog" ref={dialog} aria-label="선택 콘텐츠 완전 삭제"
      onCancel={e=>{e.preventDefault();close();}} onClose={()=>{if(!sending.current)setPending(null);}}>
      <h2>선택 콘텐츠 완전 삭제</h2>
      <p>선택한 원본 이미지·영상 파일을 삭제하며 앱에서 복원할 수 없습니다. 생성·비용·승인·게시 이력과 기존 백업은 보존합니다.</p>
      <strong>선택한 항목 {pending?.length??0}개</strong>
      <ul>{pending?.map(x=><li key={id(x)}>{x.title??x.key}</li>)}</ul>
      {message&&<p role="alert" className="mg-alert">{message}</p>}
      <div className="mg-library-dialog-actions"><button ref={cancel} disabled={busy} onClick={close}>취소</button>
        <button className="mg-danger" disabled={busy||!available||!pending?.length} onClick={()=>void purge()}>{busy?'삭제 중…':'완전 삭제'}</button></div>
    </dialog>
  </details>;
}
