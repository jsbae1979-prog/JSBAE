import {useEffect,useRef,useState} from "react";
import type {FeedEntry} from "./FeedImagePreview";
import {Thumbnail} from "../Thumbnail";

export default function FeedImageHistory({entries,busy,csrf,onOpen,onRemoved,kind="feed"}:{kind?:"feed"|"image";entries:FeedEntry[];busy:boolean;csrf:string;onOpen:(entry:FeedEntry)=>void;onRemoved:()=>Promise<void>}) {
  const [selected,setSelected]=useState<string[]>([]),[pending,setPending]=useState<FeedEntry[]|null>(null);
  const [sending,setSending]=useState(false),[message,setMessage]=useState("");
  const flight=useRef(false),dialog=useRef<HTMLDialogElement>(null);
  const id=({batch,item}:FeedEntry)=>kind==="image"?`image:${batch.id}`:`feed:${batch.id}:${item.rank}`;
  const [hidden,setHidden]=useState<string[]>([]);
  const visible=entries.filter(x=>!hidden.includes(id(x)));
  useEffect(()=>{if(pending)dialog.current?.showModal();else dialog.current?.close();},[pending]);
  useEffect(()=>{const ids=new Set(entries.map(id));setSelected(old=>old.filter(x=>ids.has(x)));setHidden(old=>old.filter(x=>ids.has(x)));},[entries,kind]);
  async function remove(){
    if(flight.current||!pending?.length||!csrf)return;
    flight.current=true;setSending(true);setMessage("");const ids=pending.map(id);
    try {
      const r=await fetch('/api/studio/library/remove',{method:'POST',credentials:'same-origin',body:new URLSearchParams({items:JSON.stringify(ids),confirm:'true',csrf_token:csrf})});
      const data=await r.json();
      if(!r.ok||!Array.isArray(data.removed)||data.removed.length!==ids.length||new Set(data.removed).size!==ids.length||!data.removed.every((x:string)=>ids.includes(x)))throw Error();
      setHidden(old=>[...new Set([...old,...ids])]);setSelected(old=>old.filter(x=>!ids.includes(x)));setPending(null);
      setMessage(`${ids.length}개를 휴지통으로 옮겼습니다. 라이브러리에서 복원할 수 있습니다.`);
      try { await onRemoved(); }
      catch { setMessage(`${ids.length}개를 휴지통으로 옮겼습니다. 목록 새로고침만 실패했습니다. 새로고침해 확인하세요.`); }
    }catch {setMessage('삭제 결과를 확인하지 못했습니다. 목록을 새로고침해 확인하세요.');}
    finally {flight.current=false;setSending(false);}
  }
  return <>
    <div className="feed-history-actions"><span>선택 {selected.filter(x=>visible.some(v=>id(v)===x)).length}개</span>
      <button disabled={busy||sending||!visible.length} onClick={()=>setSelected(visible.slice(0,100).map(id))}>전체 선택</button>
      <button disabled={sending||!selected.length} onClick={()=>setSelected([])}>선택 해제</button>
      <button disabled={busy||sending||!csrf||!selected.length} onClick={()=>setPending(visible.filter(x=>selected.includes(id(x))))}>선택 삭제</button></div>
    <div className="feed-image-history">{visible.map(entry=><div className={`feed-history-entry${selected.includes(id(entry))?' is-selected':''}`} key={id(entry)}>
      <button className="feed-image-history-card" disabled={busy||sending} onClick={()=>onOpen(entry)}>
        <Thumbnail src={entry.item.mediaUrl} alt={entry.item.content?.title}/><strong>{entry.item.content?.title}</strong>
        <small>작업 #{entry.batch.id}{kind==="feed"?` · TOP ${entry.item.rank}`:""}</small></button>
      <label className="feed-history-select" title="이미지 선택">
        <input type="checkbox" aria-label={`작업 ${entry.batch.id}${kind==="feed"?` TOP ${entry.item.rank}`:""} 선택`} checked={selected.includes(id(entry))} disabled={busy||sending||!selected.includes(id(entry))&&selected.length>=100}
          onChange={e=>setSelected(old=>e.target.checked?[...old,id(entry)]:old.filter(x=>x!==id(entry)))}/>
      </label></div>)}</div>
    {!visible.length&&<p>표시할 최근 이미지가 없습니다. 삭제한 이미지는 <a href="/studio/library">라이브러리 휴지통</a>에서 복원할 수 있습니다.</p>}
    {message&&<p role="status">{message}</p>}
    <dialog className="top3-dialog" ref={dialog} aria-label="최근 생성 이미지 삭제" onCancel={e=>{e.preventDefault();if(!flight.current)setPending(null);}}>
      <h2>선택 이미지 삭제</h2><p>최근 목록과 라이브러리에서 숨기고 휴지통으로 옮깁니다. 원본·편집 버전·제작 기록은 보존됩니다.</p>
      <ul>{pending?.map(x=><li key={id(x)}>{x.item.content?.title}</li>)}</ul>
      {message&&<p role="status">{message}</p>}
      <button disabled={sending} onClick={()=>setPending(null)}>취소</button><button disabled={sending} onClick={()=>void remove()}>{sending?'처리 중…':'휴지통으로 이동'}</button>
    </dialog>
  </>;
}
