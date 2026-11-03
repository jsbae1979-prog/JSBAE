import {useEffect,useState,type ReactNode} from 'react';
import type {Item} from '../contracts';
import ImageResultPreview from './ImageResultPreview';
import {Panel} from './shared';
import PhotoFeedEditor from './PhotoFeedEditor';

export default function CompleteFeedEditor({batch,rank,f,onSelect,csrf,statusPanel}:{batch:Item;rank:number;f:any;onSelect:(n:number)=>void;csrf:string;statusPanel?:ReactNode}){
 const [photoEdit,setPhotoEdit]=useState(false);
 const item=batch.items.find((x:Item)=>x.rank===rank);
 const [title,setTitle]=useState(''),[description,setDescription]=useState(''),[accent,setAccent]=useState('#ffb45c'),[large,setLarge]=useState(false),[version,setVersion]=useState('');
 const [loaded,setLoaded]=useState(''),[failed,setFailed]=useState('');
 useEffect(()=>{setVersion('');setPhotoEdit(false);},[batch.id,rank]);
 useEffect(()=>{const p=item?.creative_plan;setTitle(p?.headline??item?.content?.title??'');setDescription(p?.key_fact??'');setAccent(p?.accent??'#ffb45c');},[batch.id,rank,item?.attempt]);
 if(!item)return null;
 const old=item.history?.slice().reverse().find((x:Item)=>x.status==='success'&&x.filename);
 const history=(item.history??[]).filter((x:Item)=>x.status==='success'&&x.filename&&x.attempt!==item.attempt).slice().reverse();
 const selectedVersion=version?history.find((x:Item)=>String(x.attempt)===version):item;
 const image=selectedVersion?.status==='success'&&(version||item.mediaUrl) ? `/api/feed-batches/${batch.id}/items/${rank}/file?attempt=${selectedVersion.attempt}${selectedVersion.sha256?'&v='+encodeURIComponent(selectedVersion.sha256):''}` : '';
 const versionLabel=version?`이전 버전 ${version}`:`최신 버전 ${item.attempt}`;
 const download=image ? image+(image.includes('?')?'&':'?')+'download=true' : '';

 if(photoEdit)return <PhotoFeedEditor statusPanel={statusPanel} key={`${batch.id}:${rank}`} batch={batch} rank={rank} csrf={csrf} busy={f.busy} local={f.local} onSaved={f.load} resultPicker={<>
  <button onClick={()=>setPhotoEdit(false)}>AI 완성 이미지로 돌아가기</button>
  <p>사용 권한을 확인한 사진을 선택하세요. 얼굴을 AI로 재생성하지 않고 글자·배치만 편집합니다.</p>
  <div className="photo-feed-thumbs">{batch.items.map((x:Item)=><button key={x.rank} aria-pressed={rank===x.rank} disabled={f.busy} onClick={()=>onSelect(x.rank)}>TOP {x.rank}</button>)}</div>
 </>}/>;
 return <><Panel title={`TOP ${rank} · 완성 피드`}>
  <div className="photo-feed-thumbs">{batch.items.map((x:Item)=><button key={x.rank} aria-pressed={rank===x.rank} disabled={f.busy} onClick={()=>onSelect(x.rank)}>TOP {x.rank}{x.mediaUrl&&<img src={`/api/feed-batches/${batch.id}/items/${x.rank}/file?attempt=${x.attempt}${x.sha256?'&v='+encodeURIComponent(x.sha256):''}`} alt="" style={{height:80,objectFit:'contain'}}/>}</button>)}</div>
  {history.length>0&&<label>저장된 버전<select aria-label="저장된 버전" value={version} onChange={e=>setVersion(e.target.value)}><option value="">최신 버전 {item.attempt}</option>{history.map((x:Item)=><option key={x.attempt} value={String(x.attempt)}>이전 버전 {x.attempt}</option>)}</select></label>}
  {image?<div className="complete-feed-preview">
   {loaded!==image&&failed!==image&&<p role="status">{versionLabel} 불러오는 중…</p>}
   {failed===image&&<p role="alert">선택한 이미지를 불러오지 못했습니다. 다른 버전을 선택하거나 화면을 새로고침해 주세요.</p>}
   <button disabled={loaded!==image||failed===image} onClick={()=>setLarge(true)} style={{width:'100%',padding:0}} aria-label="완성 피드 크게 보기">
    <img key={image} src={image} onLoad={()=>{setLoaded(image);setFailed('');}} onError={()=>setFailed(image)} alt={`${item.content.title} · ${versionLabel}`} style={{display:'block',width:'100%',maxHeight:'75vh',objectFit:'contain',visibility:loaded===image&&failed!==image?'visible':'hidden'}}/>
   </button>
  </div>:<p>{old?'수정본 대기 · 이전 원본은 보존돼 있습니다.':'이미지 생성 대기'}</p>}

  {image&&<a href={download} download>이미지 저장</a>}
  {large&&image&&<ImageResultPreview name="완성 피드 확대" item={{title:`${item.content.title} · ${versionLabel}`,mediaUrl:image}} onClose={()=>setLarge(false)}/>}

 </Panel><div className="photo-feed-editor-side">{statusPanel}<Panel title={`TOP ${rank} · 디자인 수정`}>
  <button disabled={f.busy} onClick={()=>setPhotoEdit(true)}>사진 선택·직접 편집 · 무료</button>
  {item.creative_plan?.copy_mode==='rewrite_from_facts'&&<p>아래 문구는 참고 원문입니다. AI가 이미지에 작성한 문구와 다를 수 있습니다.</p>}
  <label>수정할 제목<textarea value={title} maxLength={100} disabled={f.busy} onChange={e=>setTitle(e.target.value)}/></label>
  <label>핵심 설명<textarea value={description} maxLength={180} disabled={f.busy} onChange={e=>setDescription(e.target.value)}/></label>
  <label>강조색<input type="color" value={accent} disabled={f.busy} onChange={e=>setAccent(e.target.value)}/></label>
  <p>완성 이미지의 글자·색상을 AI로 수정합니다. 새 버전으로 저장됩니다.</p>
  <p>설정 한도 {batch.costReview?.settingsLimitUsd ? `US$${batch.costReview.settingsLimitUsd}`:'미설정'} · 이미지 편집 비용 포함</p>
  <button className="primary" disabled={!!version||f.busy||!title.trim()||item.status!=='success'||!batch.canPrepareRegeneration||!batch.costReview?.settingsLimitUsd} onClick={()=>f.runSettings({rank,title,body:description,accent})}>AI 수정 · 설정 예산 사용</button>
  <a href="/studio/settings">사용 한도 설정</a>
 </Panel></div></>;
}
