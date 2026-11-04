import {useEffect,useRef,useState} from 'react';
import {characterCommand,CharacterModal} from './CharacterAutomation';
import type {Controller} from './shared';
import type {Item} from '../contracts';
import './character-precision.css';

const base='/api/studio/character-precision';
const blank={title:'',topic:'',relationships:'',genre:'대사 없는 코미디',world:'',background:'',props:'',
  style:'3D animation',ratio:'9:16',scene_count:5,duration:26,prohibitions:''};
const stateName:Record<string,string>={needs_story:'스토리 작성',writing:'스토리 생성 중',story_failed:'스토리 확인 필요',
  images:'장면 이미지 검토',generating:'이미지 생성 중',video_ready:'영상 제작 준비',pending:'생성 전',
  review:'검토 대기',confirmed:'이미지 확정',unknown:'결과 미확인 · 재전송 안 함',failed:'실패',success:'완료',requesting:'요청 중'};

export default function CharacterPrecision({c}:{c:Controller}) {
  const [catalog,setCatalog]=useState<Item|null>(null),[work,setWork]=useState<Item|null>(null);
  const [common,setCommon]=useState(blank),[cast,setCast]=useState<string[]>([]),[outfits,setOutfits]=useState<Record<string,string>>({});
  const [image,setImage]=useState<Item>({}),[video,setVideo]=useState<Item>({});
  const [imageLimit,setImageLimit]=useState(''),[videoLimit,setVideoLimit]=useState('');
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[consent,setConsent]=useState(false);
  const [picked,setPicked]=useState<number[]>([]),[versions,setVersions]=useState<Record<number,number>>({});
  const [review,setReview]=useState<number|null>(null),[editing,setEditing]=useState<Item|null>(null);
  const [large,setLarge]=useState<string|null>(null);
  const sending=useRef(false),createId=useRef(crypto.randomUUID().replaceAll('-',''));
  async function get(path:string) {const r=await fetch(path,{credentials:'same-origin'});if(!r.ok)throw Error('저장된 자료를 불러오지 못했습니다.');return r.json();}
  useEffect(()=>{let live=true;get(base).then(async d=>{
    if(!live)return;setCatalog(d);setImage(d.image_defaults);setVideo(d.video.defaults);setImageLimit(d.standing_limit??'');
    const id=new URLSearchParams(location.search).get('precision');
    if(id&&/^[a-f0-9]{32}$/.test(id)){const w=await get(`${base}/${id}`);if(live)setWork(w);}
  }).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
  useEffect(()=>{if(!busy||!work?.id)return;let live=true;
    const timer=setInterval(()=>get(`${base}/${work.id}`).then(w=>{if(live)setWork(w);}).catch(()=>{}),2000);
    return()=>{live=false;clearInterval(timer);};},[busy,work?.id]);
  async function act(kind:string,values:Record<string,string>={}) {
    if(sending.current)return;sending.current=true;setBusy(kind);setError('');
    try {const path=kind==='create'?`${base}/create`:`${base}/${work?.id}/${kind}`;
      const w=await characterCommand(path,c.view?.csrfToken??'',{revision:String(work?.revision??1),...values});
      setWork(w);setConsent(false);setPicked([]);setVersions({});setEditing(null);setReview(null);
      const url=new URL(location.href);url.searchParams.set('precision',w.id);history.replaceState(null,'',url);
    } catch(e){setError(e instanceof Error?e.message:'처리 결과를 확인하세요.');
      if(work?.id)try{setWork(await get(`${base}/${work.id}`));}catch{/* keep the last visible journal */}
    } finally{setBusy('');sending.current=false;}
  }
  function create(){void act('create',{request_id:createId.current,payload:JSON.stringify({common,character_ids:cast,
    outfits:Object.fromEntries(cast.map(id=>[id,outfits[id]??''])),selection:image,video_settings:video,image_limit:imageLimit,video_limit:videoLimit})});}
  const rows:Item[]=work?.scenes??[], profiles:Item[]=catalog?.profiles??[];
  const locked=!!busy||!!work?.video_job_id||['writing','generating'].includes(work?.state);
  const completed=rows.filter(s=>s.versions.some((v:Item)=>v.state==='success')).length;
  const quote=work?.quote;
  return <section className="character-precision" aria-label="정밀 제작">
    <header><h2>정밀 제작 — 장면 이미지 먼저 만들기</h2><p>캐릭터 → 스토리 → 이미지 검토 → 영상 → 합성</p></header>
    {error&&<p role="alert" className="precision-error">{error}</p>}
    <div className="precision-toolbar"><label>저장한 작품 <select disabled={!!busy} value={work?.id??''} onChange={async e=>{
      if(!e.target.value){setWork(null);createId.current=crypto.randomUUID().replaceAll('-','');return;}
      try{setWork(await get(`${base}/${e.target.value}`));setVersions({});setPicked([]);}catch{setError('작품을 확인하세요.');}}}>
      <option value="">새 작품</option>{(catalog?.works??[]).map((w:Item)=><option key={w.id} value={w.id}>{w.title}</option>)}
      {work&&!(catalog?.works??[]).some((w:Item)=>w.id===work.id)&&<option value={work.id}>{work.common.title}</option>}
    </select></label><button disabled={!!busy} onClick={()=>{setWork(null);setVersions({});setPicked([]);setError('');
      createId.current=crypto.randomUUID().replaceAll('-','');const u=new URL(location.href);u.searchParams.delete('precision');history.replaceState(null,'',u);}}>새 작품</button></div>
    {!work&&catalog&&<div className="precision-setup">
      <section><h3>① 캐릭터 선택</h3><p>기존 캐릭터 등록에서 대표 이미지와 특징을 저장한 뒤 선택하세요.</p>
        {profiles.map(p=><div className="precision-person" key={p.id}><label className="precision-check">
          <input type="checkbox" disabled={!!busy} checked={cast.includes(p.id)} onChange={e=>setCast(e.target.checked?[...cast,p.id]:cast.filter(id=>id!==p.id))}/>
          <img src={p.url} alt={p.name_ko}/><b>{p.name_ko}</b><small>이미지 버전 {p.revision}</small></label>
          {cast.includes(p.id)&&<label>의상·액세서리<input value={outfits[p.id]??''} maxLength={300}
            onChange={e=>setOutfits({...outfits,[p.id]:e.target.value})}/></label>}</div>)}
      </section><section><h3>② 작품·스토리 설정</h3>
        {([['title','작품명'],['topic','스토리 주제'],['relationships','캐릭터 관계'],['style','그림 스타일']] as const).map(([key,label])=>
          <label key={key}>{label}<input value={common[key]} onChange={e=>setCommon({...common,[key]:e.target.value})}/></label>)}
        <div className="precision-pair"><label>총 길이(초)<input type="number" min={15} max={60} value={common.duration} onChange={e=>setCommon({...common,duration:+e.target.value})}/></label>
          <label>장면 수<input type="number" min={2} max={12} value={common.scene_count} onChange={e=>setCommon({...common,scene_count:+e.target.value})}/></label></div>
        <details><summary>배경·소품·전문가 설정</summary>
          {([['genre','장르'],['world','세계관'],['background','공통 배경'],['props','공통 소품'],['prohibitions','공통 금지 조건']] as const).map(([key,label])=>
            <label key={key}>{label}<input value={common[key]} onChange={e=>setCommon({...common,[key]:e.target.value})}/></label>)}
          <label>스토리 AI 모델<select value={video.script_model??''} onChange={e=>setVideo({...video,script_model:e.target.value})}>
            {(catalog.script_models??[video.script_model]).map((m:string)=><option key={m}>{m}</option>)}</select></label>
          <label>이미지 모델<select value={image.model??''} onChange={e=>setImage({...image,model:e.target.value})}>{catalog.image_models.map((m:string)=><option key={m}>{m}</option>)}</select></label>
          <label>이미지 화질<select value={image.quality??''} onChange={e=>setImage({...image,quality:e.target.value})}>
            {Object.entries(catalog.qualities).map(([key,label])=><option key={key} value={key}>{String(label)}</option>)}</select></label>
          <p>이미지 비율 9:16</p>
          <label>영상 모델<select value={video.video_model??''} onChange={e=>{
            const m=catalog.video.modelsDetailed.find((m:Item)=>m.id===e.target.value);
            setVideo({...video,video_model:m.id,native_resolution:m.default_resolution,clip_seconds:m.duration_values[0]});}}>
            {Object.entries(catalog.video.models).map(([key,label])=><option key={key} value={key}>{String(label)}</option>)}</select></label>
          <label>영상 생성 화질<select value={video.native_resolution??''} onChange={e=>setVideo({...video,native_resolution:e.target.value})}>{(catalog.video.modelsDetailed.find((m:Item)=>m.id===video.video_model)?.resolutions??[]).map((key:string)=><option key={key}>{key}</option>)}</select></label>
          <label>환경음<select value={video.sound??'on'} onChange={e=>setVideo({...video,sound:e.target.value})}><option value="on">켜기</option><option value="off">끄기</option></select></label>
        </details><div className="precision-pair"><label>이미지 작업 예산(USD)<input type="number" min="0.01" step="0.01" value={imageLimit} onChange={e=>setImageLimit(e.target.value)}/></label>
          <label>스토리·영상 예산(USD)<input type="number" min="0.01" step="0.01" value={videoLimit} onChange={e=>setVideoLimit(e.target.value)}/></label></div>
        <button className="primary" disabled={!!busy||!cast.length||!imageLimit||!videoLimit} onClick={create}>작품 저장 · 무료</button>
      </section></div>}
    {work&&<><div className="precision-progress" role="status" aria-live="polite"><strong>{work.common.title} · {stateName[work.state]??work.state}</strong>
      <span>{completed}/{rows.length||work.common.scene_count}장 완료 · {rows.filter(s=>s.confirmed).length}장 확정</span>
      {busy&&<span className="precision-running">처리 중 · 결과를 확인하고 있습니다</span>}
      {!busy&&(['writing','generating'].includes(work.state)||rows.some(s=>s.versions.some((v:Item)=>['requesting','unknown'].includes(v.state))))&&<button onClick={()=>void act('reconcile')}>저장된 결과 확인 · 무료</button>}
      <progress value={completed} max={rows.length||work.common.scene_count}/></div>
      {!work.scenario&&<section><h3>② 스토리 작성</h3><p>{work.common.topic} · {work.common.duration}초 · {work.common.scene_count}장면</p>
        <label className="precision-check"><input type="checkbox" checked={consent} disabled={locked} onChange={e=>setConsent(e.target.checked)}/>선택한 AI로 유료 스토리 생성에 동의합니다.</label>
        <button disabled={locked||!consent||work.story_attempts.length>0} onClick={()=>void act('story',{consent:'true'})}>스토리 자동 생성하기</button>
        <button disabled={locked} onClick={()=>setEditing({scenario:{scenes:Array.from({length:work.common.scene_count},(_,i)=>({no:i+1,
          characters:[Object.keys(work.cast)[0]],description:'',location:'',pose:'',emotion:'',camera:'',props:'',continuity:'',caption:'',
          seconds:Math.floor(work.common.duration/work.common.scene_count)+(i<work.common.duration%work.common.scene_count?1:0),motion:'',motion_camera:'',sound:''}))}})}>직접 작성</button>
        {work.state==='story_failed'&&<p>보관된 응답을 검토하세요. 추가 AI 요청 없이 수정할 수 있습니다.</p>}
        {work.story_attempts.at(-1)?.candidate&&<button onClick={()=>setEditing({scenario:work.story_attempts.at(-1).candidate})}>보관된 스토리 편집</button>}
      </section>}
      {rows.length>0&&<section><h3>③ 장면 이미지 제작</h3>
        <div className="precision-toolbar"><button disabled={locked} onClick={()=>setEditing({scenario:structuredClone(work.scenario)})}>장면 수정</button>
          <button disabled={locked||!rows.some(s=>!s.versions.length)} onClick={()=>void act('quote',{numbers:JSON.stringify(rows.filter(s=>!s.versions.length).map(s=>s.plan.no))})}>전체 미생성 장면 예산 확인</button>
          <button disabled={locked||!picked.length} onClick={()=>void act('quote',{numbers:JSON.stringify(picked),regenerate:'true'})}>선택 장면 재생성 예산</button></div>
        <div className="precision-scenes">{rows.map(s=>{const n=s.plan.no,v=s.versions.find((v:Item)=>v.version===(versions[n]??s.selected));return <article key={n}>
          <label className="precision-check"><input type="checkbox" disabled={locked} checked={picked.includes(n)} onChange={e=>setPicked(e.target.checked?[...picked,n]:picked.filter(x=>x!==n))}/><b>장면 {n} · {s.plan.seconds}초</b></label>
          <p>{s.plan.description}</p><small>{s.plan.characters.map((id:string)=>work.cast[id].name_ko).join(' · ')}</small>
          {v?.asset?<button className="precision-image" onClick={()=>setLarge(`/image-studio/assets/${v.asset}`)}><img src={`/image-studio/assets/${v.asset}`} alt={`장면 ${n}`}/></button>:<div className="precision-empty">{stateName[s.state]??s.state}</div>}
          <strong>{stateName[s.state]??s.state}</strong>
          <select aria-label={`장면 ${n} 이미지 버전`} value={versions[n]??s.selected??''} onChange={e=>setVersions({...versions,[n]:+e.target.value})}>
            <option value="">버전 선택</option>{s.versions.map((v:Item)=><option key={v.version} value={v.version}>버전 {v.version} · {stateName[v.state]??v.state}</option>)}</select>
          <details><summary>이미지 프롬프트</summary><p className="precision-prompt">{s.prompt}</p></details>
          <button disabled={locked||!v?.asset} onClick={()=>setReview(n)}>이 이미지 검토·확정</button>
        </article>;})}</div>
      </section>}
      {quote&&<section className="precision-budget"><h3>{quote.numbers.length}장 이미지 생성</h3>
        <p>예상 US${quote.estimated_usd} · 예산 예약 US${quote.reserve_usd}</p><small>참조 이미지 비용을 포함한 앱 추정값입니다. 실제 청구액과 다를 수 있습니다. 영상 비용은 별도입니다.</small>
        <label className="precision-check"><input type="checkbox" disabled={locked} checked={consent} onChange={e=>setConsent(e.target.checked)}/>선택한 캐릭터 참조 이미지 전송과 표시된 이미지 생성 비용에 동의합니다.</label>
        <button className="primary" disabled={locked||!consent} onClick={()=>void act('generate',{quote_hash:quote.hash,consent:'true',reference_consent:'true'})}>승인한 장면 이미지 생성</button></section>}
      <button className="primary" disabled={!!busy||!rows.length||rows.some(s=>!s.confirmed)} onClick={()=>void act('handoff')}>④ 영상 제작으로 이동 준비 · 무료</button>
      {work.video_job_id&&<a className="button" href={`/studio/characters?job_id=${work.video_job_id}`}>영상 견적·제작·최종 합성 열기</a>}
    </>}
    {review!==null&&<CharacterModal title={`장면 ${review} 이미지 검토`} busy={!!busy} onClose={()=>setReview(null)} footer={<button className="primary" disabled={!!busy}
      onClick={()=>{const s=rows.find(s=>s.plan.no===review)!;void act('confirm',{number:String(review),version:String(versions[review]??s.selected),reviewed:'true'});}}>검토 완료 · 이미지 확정</button>}>
      <p>캐릭터 외형·얼굴과 색상·의상·소품·인원·배경·구도와 표정·장면 내용이 맞는지 확인하세요.</p>
      <p>이 버전만 영상에 사용합니다. 이전 이미지는 보존합니다.</p></CharacterModal>}
    {editing&&<CharacterModal title="장면 내용 수정" busy={!!busy} onClose={()=>setEditing(null)} footer={<button className="primary" disabled={!!busy} onClick={()=>void act('edit',{scenario:JSON.stringify(editing.scenario)})}>장면 저장 · 무료</button>}>
      <div className="precision-editor">{(editing.scenario.scenes??[]).map((s:Item,i:number)=>{
        const set=(key:string,value:unknown)=>setEditing({scenario:{...editing.scenario,scenes:editing.scenario.scenes.map((r:Item,j:number)=>j===i?{...r,[key]:value}:r)}});
        return <fieldset key={s.no}><legend>장면 {s.no}</legend><div className="precision-pair">
          {Object.values(work!.cast).map((p:unknown)=>{const person=p as Item;return <label className="precision-check" key={person.id}><input type="checkbox" checked={s.characters.includes(person.id)}
            onChange={e=>set('characters',e.target.checked?[...s.characters,person.id]:s.characters.filter((id:string)=>id!==person.id))}/>{person.name_ko}</label>;})}
          {Object.entries({description:'장면 설명',location:'장소',pose:'행동·자세',emotion:'표정·감정',camera:'이미지 구도',props:'소품·위치',continuity:'이어질 요소',caption:'별도 자막',motion:'영상 동작 · 영어',motion_camera:'영상 카메라 · 영어',sound:'환경음'}).map(([key,label])=>
            <label key={key}>{label}<textarea value={s[key]??''} onChange={e=>set(key,e.target.value)}/></label>)}
          <label>로컬 효과음<select value={s.sfx?.[0]?.key??''} onChange={e=>set('sfx',e.target.value?[{at:'end',key:e.target.value}]:[])}><option value="">없음</option>{(catalog?.sfx_keys??[]).map((key:string)=><option key={key}>{key}</option>)}</select></label>
          <label>길이(초)<input type="number" min={3} max={15} value={s.seconds} onChange={e=>set('seconds',+e.target.value)}/></label>
        </div></fieldset>;})}</div></CharacterModal>}
    {large&&<CharacterModal title="장면 이미지" onClose={()=>setLarge(null)}><img className="precision-large" src={large} alt="장면 확대"/></CharacterModal>}
  </section>;
}
