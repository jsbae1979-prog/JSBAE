import { useEffect, useRef } from "react";
import type { Item } from "../contracts";
import "./feed-image-gallery.css";

export type FeedEntry = { batch: Item; item: Item };
export function completedFeedImages(batches: Item[]): FeedEntry[] {
  return batches.flatMap(batch => (batch.items ?? [])
    .filter((item: Item) => item.status === "success" && item.mediaUrl === `/api/feed-batches/${batch.id}/items/${item.rank}/file`)
    .map((item: Item) => ({ batch, item })));
}
export default function FeedImagePreview({ entries, index, onSelect, onClose }: {
  entries: FeedEntry[]; index: number; onSelect:(entry:FeedEntry)=>void; onClose:()=>void;
}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    const node=dialog.current; node?.showModal();
    return ()=>{node?.close();if(previous?.isConnected)previous.focus();};
  },[]);
  const {batch,item}=entries[index];
  function move(step:number){const next=entries[index+step];if(next)onSelect(next);}
  return <dialog ref={dialog} className="feed-image-preview" aria-label="생성 이미지 크게 보기"
    onCancel={e=>{e.preventDefault();onClose();}}
    onKeyDown={e=>{if(e.key==="ArrowLeft"){e.preventDefault();move(-1);}if(e.key==="ArrowRight"){e.preventDefault();move(1);}}}>
    <header><div><strong>{item.content?.title || "생성 이미지"}</strong><small>작업 #{batch.id} · 1080×1350</small></div>
      <button type="button" aria-label="이미지 미리보기 닫기" onClick={onClose}>×</button></header>
    <div className="feed-image-preview-stage"><img key={`${batch.id}:${item.rank}:${item.sha256}`}
      src={item.mediaUrl} alt={item.content?.title || "생성 이미지"}/></div>
    <footer><button type="button" disabled={index===0} onClick={()=>move(-1)}>이전 이미지</button>
      <span aria-live="polite">{index+1} / {entries.length}</span>
      <button type="button" disabled={index===entries.length-1} onClick={()=>move(1)}>다음 이미지</button>
      <a href={`${item.mediaUrl}?download=true`} download>이미지 저장</a></footer>
  </dialog>;
}
