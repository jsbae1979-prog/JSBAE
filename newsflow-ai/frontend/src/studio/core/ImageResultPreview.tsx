import { useEffect, useRef } from "react";
import { safeMedia, type Item } from "../contracts";
import "./feed-image-gallery.css";
export default function ImageResultPreview({item,onClose,name="AI 이미지 크게 보기"}:{item:Item;onClose:()=>void;name?:string}) {
  const dialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null; const node=dialog.current;node?.showModal();
    return ()=>{node?.close();if(previous?.isConnected)previous.focus();};},[]);
  const src=safeMedia(item.mediaUrl);
  return <dialog ref={dialog} className="feed-image-preview" aria-label={name}
    onCancel={e=>{e.preventDefault();onClose();}}>
    <header><strong>{item.title || "생성 이미지"}</strong><button type="button" onClick={onClose} aria-label="확대 이미지 닫기">×</button></header>
    <div className="feed-image-preview-stage">{src && <img src={src} alt={item.title || "생성 이미지"}/>}</div>
    <footer>{src && <a href={`${src}${src.includes('?')?'&':'?'}download=true`} download>이미지 저장</a>}</footer>
  </dialog>;
}
