import {useEffect,useState} from 'react';
import type {Item} from '../contracts';
import {FeedDialog} from '../TopThreeFeeds';
import {Panel} from './shared';

export default function CompleteFeedEditor({batch,rank,f,onSelect}:{batch:Item;rank:number;f:any;onSelect:(n:number)=>void}){
 const item=batch.items.find((x:Item)=>x.rank===rank);
 const [title,setTitle]=useState(''),[description,setDescription]=useState(''),[accent,setAccent]=useState('#ffb45c'),[large,setLarge]=useState(false),[version,setVersion]=useState('');
 useEffect(()=>{setVersion('');const p=item?.creative_plan;setTitle(p?.headline??item?.content?.title??'');setDescription(p?.key_fact??'');setAccent(p?.accent??'#ffb45c');},[batch.id,rank,item?.attempt]);
 if(!item)return null;
 const old=item.history?.slice().reverse().find((x:Item)=>x.status==='success'&&x.filename);
 const history=(item.history??[]).filter((x:Item)=>x.status==='success');
 const image=version ? `/api/feed-batches/${batch.id}/items/${rank}/file?attempt=${version}` : item.mediaUrl;
 const download=image ? image+(image.includes('?')?'&':'?')+'download=true' : '';

 return <><Panel title={`TOP ${rank} · 완성 피드`}>
  <div className="photo-feed-thumbs">{batch.items.map((x:Item)=><button key={x.rank} aria-pressed={rank===x.rank} disabled={f.busy} onClick={()=>onSelect(x.rank)}>TOP {x.rank}{x.mediaUrl&&<img src={x.mediaUrl} alt="" style={{height:80,objectFit:'contain'}}/>}</button>)}</div>
  {history.length>0&&<label>저장된 버전<select value={version} onChange={e=>setVersion(e.target.value)}><option value="">최신 버전</option>{history.map((x:Item)=><option key={x.attempt} value={String(x.attempt)}>이전 버전 {x.attempt}</option>)}</select></label>}
  {image?<button onClick={()=>setLarge(true)} style={{width:'100%',padding:0}} aria-label="완성 피드 크게 보기"><img src={image} alt={item.content.title} style={{display:'block',width:'100%',maxHeight:'75vh',objectFit:'contain'}}/></button>:<p>{old?'수정본 대기 · 이전 원본은 보존돼 있습니다.':'이미지 생성 대기'}</p>}
  {image&&<a href={download} download>이미지 저장</a>}
  {large&&image&&<FeedDialog name="완성 피드 확대" onClose={()=>setLarge(false)}><button onClick={()=>setLarge(false)}>닫기</button><img src={image} alt={title} style={{maxHeight:'85vh',maxWidth:'90vw',objectFit:'contain'}}/></FeedDialog>}
 </Panel><Panel title={`TOP ${rank} · 디자인 수정`}>
  <label>제목<textarea value={title} maxLength={100} disabled={f.busy} onChange={e=>setTitle(e.target.value)}/></label>
  <label>핵심 설명<textarea value={description} maxLength={180} disabled={f.busy} onChange={e=>setDescription(e.target.value)}/></label>
  <label>강조색<input type="color" value={accent} disabled={f.busy} onChange={e=>setAccent(e.target.value)}/></label>
  <p>완성 이미지의 글자·색상을 AI로 수정합니다. 새 버전으로 저장됩니다.</p>
  <p>설정 한도 {batch.costReview?.settingsLimitUsd ? `US$${batch.costReview.settingsLimitUsd}`:'미설정'} · 이미지 편집 비용 포함</p>
  <button className="primary" disabled={!!version||f.busy||!title.trim()||item.status!=='success'||!batch.canPrepareRegeneration||!batch.costReview?.settingsLimitUsd} onClick={()=>f.runSettings({rank,title,body:description,accent})}>AI 수정 · 설정 예산 사용</button>
  <a href="/studio/settings">사용 한도 설정</a>
 </Panel></>;
}
