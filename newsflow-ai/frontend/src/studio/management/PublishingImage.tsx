import { useEffect, useRef, useState } from "react";
import { safeMedia } from "../contracts";
import "../core/feed-image-gallery.css";
import "./publishing-image.css";

export default function PublishingImage({url,title}:{url:unknown;title:string}) {
  const src=safeMedia(url);
  const [open,setOpen]=useState(false);
  const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
  useEffect(()=>{
    if(open)dialog.current?.showModal();
    else if(dialog.current?.open){dialog.current.close();trigger.current?.focus();}
  },[open]);
  if(!src)return null;
  return <>
    <button ref={trigger} type="button" className="mg-publish-image-open"
      aria-label={`${title} 크게 보기`} aria-haspopup="dialog" onClick={()=>setOpen(true)}>
      <img src={src} alt="콘텐츠 미리보기"/><span>크게 보기</span>
    </button>
    <dialog ref={dialog} className="feed-image-preview" aria-label="게시 이미지 크게 보기"
      onCancel={e=>{e.preventDefault();setOpen(false);}}>
      <header><strong>{title}</strong><button type="button" aria-label="게시 이미지 미리보기 닫기" onClick={()=>setOpen(false)}>×</button></header>
      <div className="feed-image-preview-stage"><img src={src} alt={title}/></div>
      <footer><button type="button" onClick={()=>setOpen(false)}>닫기</button></footer>
    </dialog>
  </>;
}
