import {useEffect,useRef,useState} from 'react';
import {characterCommand,CharacterModal} from './CharacterAutomation';
import type {Controller} from './shared';
import type {Item} from '../contracts';
import './character-precision.css';

const base='/api/studio/character-precision';
const blank={title:'',topic:'',relationships:'',genre:'대사 없는 코미디',world:'',background:'',props:'',
  style:'3D animation',ratio:'9:16',scene_count:5,duration:20,prohibitions:''};
const stateName:Record<string,string>={needs_story:'스토리 작성',writing:'스토리 생성 중',story_failed:'스토리 확인 필요',
  images:'장면 이미지 검토',generating:'이미지 생성 중',video_ready:'영상 제작 준비',pending:'생성 전',
  review:'검토 대기',confirmed:'이미지 확정',unknown:'결과 미확인 · 재전송 안 함',failed:'실패',success:'완료',requesting:'요청 중'};

export default function CharacterPrecision({c}:{c:Controller}) {
  const [catalog,setCatalog]=useState<Item|null>(null),[work,setWork]=useState<Item|null>(null);
  const [common,setCommon]=useState(blank),[cast,setCast]=useState<string[]>([]),[outfits,setOutfits]=useState<Record<string,string>>({});
  const [image,setImage]=useState<Item>({}),[video,setVideo]=useState<Item>({});
  const [imageLimit,setImageLimit]=useState(''),[videoLimit,setVideoLimit]=useState('');
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[approval,setApproval]=useState<'story'|'images'|null>(null);
  const [picked,setPicked]=useState<number[]>([]),[versions,setVersions]=useState<Record<number,number>>({});
  const [budgetOpen,setBudgetOpen]=useState(false),[editing,setEditing]=useState<Item|null>(null);
  const reviewArea=useRef<HTMLElement|null>(null);
  const [large,setLarge]=useState<string|null>(null),[scene,setScene]=useState(1);
  const styleEdited=useRef(false),worldEdited=useRef(false);
  const sending=useRef(false),createId=useRef(crypto.randomUUID().replaceAll('-',''));
  async function get(path:string) {const r=await fetch(path,{credentials:'same-origin'});if(!r.ok)throw Error('저장된 자료를 불러오지 못했습니다.');return r.json();}
  useEffect(()=>{let live=true;get(base).then(async d=>{
    if(!live)return;setCatalog(d);setImage(d.recent_settings?.selection??d.image_defaults);
    setVideo(d.recent_settings?.video_settings??d.video.defaults);
    const standing=Number(d.standing_limit),previous=Number(d.recent_settings?.image_limit);
    setImageLimit(standing>0?String(previous>0?Math.min(standing,previous):standing):'');
    setVideoLimit(d.recent_settings?.video_limit??'');
    setBudgetOpen(!(standing>0&&Number(d.recent_settings?.video_limit)>0));
    setCommon(v=>({...v,duration:d.video.character?.target_duration?.default??d.video.defaults.duration??20}));
    const id=new URLSearchParams(location.search).get('precision');
    if(id&&/^[a-f0-9]{32}$/.test(id)){const w=await get(`${base}/${id}`);if(live)setWork(w);}
  }).catch(e=>{if(live)setError(e.message);});return()=>{live=false;};},[]);
  useEffect(()=>{if(!busy||!work?.id)return;let live=true;
    const timer=setInterval(()=>get(`${base}/${work.id}`).then(w=>{if(live)setWork(w);}).catch(()=>{}),2000);
    return()=>{live=false;clearInterval(timer);};},[busy,work?.id]);
  function remember(w:Item){
    setWork(w);setCatalog(d=>d?{...d,works:[{id:w.id,title:w.common.title},...(d.works??[]).filter((item:Item)=>item.id!==w.id)]}:d);
    const url=new URL(location.href);url.searchParams.set('precision',w.id);url.searchParams.delete('job_id');history.replaceState(null,'',url);
  }
  function creationValues(){return {request_id:createId.current,payload:JSON.stringify({
    common:{...common,title:Array.from(common.topic.trim()).slice(0,100).join('')},character_ids:cast,
    outfits:Object.fromEntries(cast.map(id=>[id,outfits[id]??'참조 이미지의 의상·액세서리 유지'])),
    selection:image,video_settings:video,image_limit:imageLimit,video_limit:videoLimit})};}
  function manual(w:Item){setEditing({scenario:{scenes:Array.from({length:w.common.scene_count},(_,i)=>({no:i+1,
    characters:[Object.keys(w.cast)[0]],description:'',location:'',pose:'',emotion:'',camera:'',props:'',continuity:'',caption:'',
    seconds:Math.floor(w.common.duration/w.common.scene_count)+(i<w.common.duration%w.common.scene_count?1:0),motion:'',motion_camera:'',sound:''}))}});}
  async function act(kind:string,values:Record<string,string>={}) {
    if(sending.current)return;sending.current=true;setBusy(kind);setError('');
    let target=work;
    try {
      // Free draft persistence precedes one explicitly approved story call. No automatic replay.
      if(!target&&(kind==='story'||kind==='manual')){
        target=await characterCommand(`${base}/create`,c.view?.csrfToken??'',creationValues());remember(target!);
      }
      if(!target)throw Error('작품을 먼저 선택하세요.');
      if(kind==='manual'){manual(target);return;}
      const w=await characterCommand(`${base}/${target.id}/${kind}`,c.view?.csrfToken??'',{revision:String(target.revision),...values});
      remember(w);setApproval(kind==='quote'?'images':null);setPicked([]);setVersions({});setEditing(null);
      if(kind==='confirm'){
        const pending=w.scenes.filter((row:Item)=>!row.confirmed);
        const next=pending.find((row:Item)=>row.plan.no>Number(values.number))??pending[0];
        if(next)setScene(next.plan.no);
      }
      if(kind==='handoff'&&w.video_job_id)location.assign(`/studio/characters?job_id=${w.video_job_id}`);
    } catch(e){setApproval(null);setError(e instanceof Error?e.message:'처리 결과를 확인하세요.');
      if(target?.id)try{remember(await get(`${base}/${target.id}`));}catch{/* keep the last visible journal */}
    } finally{setBusy('');sending.current=false;}
  }
  const rows:Item[]=work?.scenes??[], profiles:Item[]=catalog?.profiles??[];
  const locked=!!busy||!!work?.video_job_id||['writing','generating'].includes(work?.state);
  const completed=rows.filter(s=>s.versions.some((v:Item)=>v.state==='success')).length;
  useEffect(()=>{if(completed>0)reviewArea.current?.scrollIntoView({block:'start'});},[work?.id,completed>0]);
  const quote=work?.quote;
  const missing=rows.filter(s=>!s.versions.length);
  const allConfirmed=!!rows.length&&rows.every(s=>s.confirmed);
  const canCreate=!busy&&cast.length>0&&cast.length<=4&&!!common.topic.trim()&&Number(imageLimit)>0&&Number(videoLimit)>0;
  const selected=rows.find(s=>s.plan.no===scene)??rows[0];
  const current=selected?.versions.find((v:Item)=>v.version===(versions[selected.plan.no]??selected.selected));
  function selectCharacter(p:Item,checked:boolean){
    setCast(checked?[...cast,p.id]:cast.filter(id=>id!==p.id));
    if(checked&&!cast.length)setCommon(v=>({...v,
      style:styleEdited.current?v.style:p.style_lock||v.style,
      world:worldEdited.current?v.world:p.comedy_formula?.world||''}));
  }

  function clearSelection(){setVersions({});setPicked([]);setScene(1);setApproval(null);setEditing(null);setLarge(null);setError('');}
  function newWork(){clearSelection();setWork(null);createId.current=crypto.randomUUID().replaceAll('-','');
    const u=new URL(location.href);u.searchParams.set('precision','');u.searchParams.delete('job_id');history.replaceState(null,'',u);}
  return <section className="character-precision" aria-label="정밀 제작">
    <header className="precision-steps" aria-label="정밀 제작 흐름">
      {['캐릭터 선택','스토리 생성','영상 제작'].map((title,i)=><div key={title}><b>{i+1}</b><strong>{title}</strong></div>)}
    </header>
    {error&&<p role="alert" className="precision-error">{error}</p>}
    <div className="precision-toolbar"><label>저장한 작품 <select disabled={!!busy} value={work?.id??''} onChange={async e=>{
      if(!e.target.value){newWork();return;}
      try{const w=await get(`${base}/${e.target.value}`);clearSelection();setWork(w);
        const u=new URL(location.href);u.searchParams.set('precision',w.id);u.searchParams.delete('job_id');history.replaceState(null,'',u);
      }catch{setError('작품을 확인하세요.');}}}>
      <option value="">새 작품</option>{(catalog?.works??[]).map((w:Item)=><option key={w.id} value={w.id}>{w.title}</option>)}
      {work&&!(catalog?.works??[]).some((w:Item)=>w.id===work.id)&&<option value={work.id}>{work.common.title}</option>}
    </select></label><button disabled={!!busy} onClick={newWork}>새 작품</button></div>
    {!work&&catalog&&<div className="precision-setup">
      <section><h3>1. 캐릭터 선택</h3><p>저장된 이미지와 특징을 그대로 사용합니다.</p>
        {profiles.map(p=><div className="precision-person" key={p.id}><label className="precision-check">
          <input type="checkbox" disabled={!!busy} checked={cast.includes(p.id)} onChange={e=>selectCharacter(p,e.target.checked)}/>
          <img src={p.url} alt={p.name_ko}/><b>{p.name_ko}</b></label>
          {cast.includes(p.id)&&<details><summary>특징 수정</summary><small>이미지 버전 {p.revision}</small><p>{p.personality}</p><p>{p.appearance}</p>
            <label>의상·액세서리<input value={outfits[p.id]??'참조 이미지의 의상·액세서리 유지'} maxLength={300}
            onChange={e=>setOutfits({...outfits,[p.id]:e.target.value})}/></label></details>}</div>)}
      </section><section><h3>2. 스토리 생성</h3>
        <label>스토리 주제<input maxLength={150} value={common.topic} onChange={e=>setCommon({...common,topic:e.target.value})}/></label>
        <p className="precision-hint">{video.script_model}</p>
        <button className="primary" disabled={!canCreate} onClick={()=>setApproval('story')}>스토리 만들기</button>
        <details><summary>직접 작성·상세 설정</summary><button disabled={!canCreate} onClick={()=>void act('manual')}>직접 작성</button>
        <label>스토리 AI 모델<select value={video.script_model??''} onChange={e=>setVideo({...video,script_model:e.target.value})}>
          {(catalog.script_models??[video.script_model]).map((m:string)=><option key={m}>{m}</option>)}</select></label>

          <label>캐릭터 관계<input maxLength={300} value={common.relationships} onChange={e=>setCommon({...common,relationships:e.target.value})}/></label>
          <label>그림 스타일<input maxLength={600} value={common.style} onChange={e=>{styleEdited.current=true;setCommon({...common,style:e.target.value});}}/></label>
          {([['genre','장르'],['world','세계관'],['background','공통 배경'],['props','공통 소품'],['prohibitions','공통 금지 조건']] as const).map(([key,label])=>
            <label key={key}>{label}<input maxLength={key==='genre'?80:300} value={common[key]} onChange={e=>{if(key==='world')worldEdited.current=true;setCommon({...common,[key]:e.target.value});}}/></label>)}
        </details>

      </section><section><h3>3. 영상 제작</h3>
        <div className="precision-pair"><label>총 길이(초)<input type="number" min={15} max={60} value={common.duration} onChange={e=>setCommon({...common,duration:+e.target.value})}/></label>
          <label>장면 수<input type="number" min={2} max={12} value={common.scene_count} onChange={e=>setCommon({...common,scene_count:+e.target.value})}/></label></div>
          <label>영상 모델<select value={video.video_model??''} onChange={e=>{
            const m=catalog.video.modelsDetailed.find((m:Item)=>m.id===e.target.value);
            setVideo({...video,video_model:m.id,native_resolution:m.default_resolution,clip_seconds:m.duration_values[0]});}}>
            {Object.entries(catalog.video.models).map(([key,label])=><option key={key} value={key}>{String(label)}</option>)}</select></label>
        <details><summary>화질·이미지 모델·소리</summary>
          <label>이미지 모델<select value={image.model??''} onChange={e=>setImage({...image,model:e.target.value})}>{catalog.image_models.map((m:string)=><option key={m}>{m}</option>)}</select></label>
          <label>이미지 화질<select value={image.quality??''} onChange={e=>setImage({...image,quality:e.target.value})}>
            {Object.entries(catalog.qualities).map(([key,label])=><option key={key} value={key}>{String(label)}</option>)}</select></label>
          <p>이미지 비율 9:16</p>
          <label>영상 생성 화질<select value={video.native_resolution??''} onChange={e=>setVideo({...video,native_resolution:e.target.value})}>{(catalog.video.modelsDetailed.find((m:Item)=>m.id===video.video_model)?.resolutions??[]).map((key:string)=><option key={key}>{key}</option>)}</select></label>
          <label>환경음<select value={video.sound??'on'} onChange={e=>setVideo({...video,sound:e.target.value})}><option value="on">켜기</option><option value="off">끄기</option></select></label>
        </details><details className="precision-budget-settings" open={budgetOpen} onToggle={e=>setBudgetOpen(e.currentTarget.open)}><summary>작업 예산 (USD){(!imageLimit||!videoLimit)&&' · 설정 필요'}</summary><div className="precision-pair"><label>이미지 작업 예산(USD)<input type="number" min="0.01" step="0.01" value={imageLimit} onChange={e=>setImageLimit(e.target.value)}/></label>
          <label>스토리·영상 예산(USD)<input type="number" min="0.01" step="0.01" value={videoLimit} onChange={e=>setVideoLimit(e.target.value)}/></label></div></details>
        <p className="precision-hint">{catalog.recent_settings?'최근 작품의 모델·예산 사용':'모델·예산을 설정한 뒤 스토리를 만드세요.'}</p>
      </section></div>}
    {work&&<><details className="precision-work-context" key={`${work.id}:${completed>0}`} open={completed===0}><summary>캐릭터·스토리·설정 보기</summary><div className="precision-setup precision-saved">
      <section><h3>1. 캐릭터 선택</h3>{Object.values(work.cast).map((p:unknown)=>{const person=p as Item;return <div className="precision-person precision-snapshot" key={person.id}>
        <img src={`/image-studio/assets/${person.asset}`} alt={person.name_ko}/><div><strong>{person.name_ko}</strong><details><summary>캐릭터 특징</summary><p>{person.personality}</p></details></div></div>;})}</section>
      <section><h3>2. 스토리 생성</h3><p>{work.common.topic}</p>
        {work.scenario&&<button disabled={locked} onClick={()=>setEditing({scenario:structuredClone(work.scenario)})}>스토리 검토·수정</button>}
      {!work.scenario&&<div className="precision-story-controls">
        <button className="primary" disabled={locked||work.story_attempts.length>0} onClick={()=>setApproval('story')}>스토리 만들기</button>
        <details><summary>직접 작성·복구</summary><button disabled={locked} onClick={()=>manual(work)}>직접 작성</button>
        {work.state==='story_failed'&&<p>보관된 응답을 검토하세요. 추가 AI 요청 없이 수정할 수 있습니다.</p>}
        {work.story_attempts.at(-1)?.candidate&&<button onClick={()=>setEditing({scenario:work.story_attempts.at(-1).candidate})}>보관된 스토리 편집</button>}</details>
      </div>}
      </section>
      <section><h3>3. 영상 제작</h3><p>{work.common.duration}초 · {work.common.scene_count}장면</p>
        <p>{catalog?.video.models[work.video_settings.video_model]??work.video_settings.video_model}</p>
        {work.video_job_id?<><p className="precision-hint">확정한 이미지로 영상 제작을 이어갑니다.</p></>:
          allConfirmed?<p className="precision-hint">장면 검토 아래에서 영상 제작으로 이동하세요.</p>:
          missing.length?<button className="primary" disabled={locked} onClick={()=>void act('quote',{numbers:JSON.stringify(missing.map(s=>s.plan.no))})}>장면 이미지 만들기</button>:
          <p className="precision-hint">{rows.length?'아래에서 장면 이미지를 확인하세요.':'스토리를 먼저 만들어 주세요.'}</p>}
        <details><summary>저장된 모델·예산</summary><p>이미지 {work.selection.model} · {work.selection.quality}</p>
          <p>이미지 US${work.image_limit} / 스토리·영상 US${work.video_limit}</p></details>
      </section>
      </div></details><div className="precision-progress" role="status" aria-live="polite"><strong>{work.common.title} · {stateName[work.state]??work.state}</strong>
      <span>{completed}/{rows.length||work.common.scene_count}장 완료 · {rows.filter(s=>s.confirmed).length}장 확정</span>
      {busy&&<span className="precision-running">처리 중 · 결과를 확인하고 있습니다</span>}
      {!busy&&(['writing','generating'].includes(work.state)||rows.some(s=>s.versions.some((v:Item)=>['requesting','unknown'].includes(v.state))))&&<button onClick={()=>void act('reconcile')}>저장된 결과 확인 · 무료</button>}
      <progress value={completed} max={rows.length||work.common.scene_count}/></div>
      {rows.length>0&&<section ref={reviewArea} className="precision-review-area"><div className="precision-review-heading"><h3>장면 이미지 검토</h3>
        {allConfirmed&&!work.video_job_id&&<button className="primary" disabled={locked} onClick={()=>void act('handoff')}>영상 제작으로 이동</button>}
        {work.video_job_id&&<a className="button primary" href={`/studio/characters?job_id=${work.video_job_id}`}>영상 제작 열기</a>}</div>
        <details className="precision-batch"><summary>여러 장면 다시 만들기</summary>
          {rows.map(s=><label className="precision-check" key={s.plan.no}><input type="checkbox" disabled={locked} checked={picked.includes(s.plan.no)} onChange={e=>setPicked(e.target.checked?[...picked,s.plan.no]:picked.filter(x=>x!==s.plan.no))}/>장면 {s.plan.no}</label>)}
          <button disabled={locked||!picked.length} onClick={()=>void act('quote',{numbers:JSON.stringify(picked),regenerate:'true'})}>선택 장면 다시 만들기</button>
        </details>
        <div className="precision-review-layout">
          <div className="precision-scenes" role="group" aria-label="장면 선택">{rows.map(s=>{const n=s.plan.no,v=s.versions.find((v:Item)=>v.version===(versions[n]??s.selected));return <article key={n}>
            <button className="precision-scene-choice" aria-pressed={selected?.plan.no===n} onClick={()=>setScene(n)}>
              {v?.asset?<img src={`/image-studio/assets/${v.asset}`} alt=""/>:<span className="precision-thumb-empty">{n}</span>}
              <span><b>장면 {n} · {s.plan.seconds}초</b><small>{stateName[s.state]??s.state}</small></span>
            </button>

          </article>;})}</div>
          {selected&&<div className="precision-selected">
            <div>{current?.asset?<button className="precision-image" onClick={()=>setLarge(`/image-studio/assets/${current.asset}`)}><img src={`/image-studio/assets/${current.asset}`} alt={`장면 ${selected.plan.no}`}/></button>:<div className="precision-empty">{stateName[selected.state]??selected.state}</div>}</div>
            <div className="precision-scene-detail"><h4>장면 {selected.plan.no} · {selected.plan.seconds}초</h4><p>{selected.plan.description}</p>
              <p>{selected.plan.characters.map((id:string)=>work.cast[id].name_ko).join(' · ')}</p>
              <p className="precision-hint">캐릭터·의상·배경·장면 연결을 확인한 뒤 확정하세요.</p>
              <div className="precision-scene-actions">
                <button disabled={locked||selected.versions.some((v:Item)=>['requesting','unknown'].includes(v.state))} onClick={()=>void act('quote',{numbers:JSON.stringify([selected.plan.no]),regenerate:'true'})}>다시 만들기</button>
                <button className={!allConfirmed?'primary':''} disabled={locked||!current?.asset||selected.confirmed?.version===current.version}
                  onClick={e=>{if(e.detail>1)return;void act('confirm',{number:String(selected.plan.no),version:String(current.version),reviewed:'true'});}}>
                  {current&&selected.confirmed?.version===current.version?'사용 중인 이미지':rows.some(s=>s.plan.no!==selected.plan.no&&!s.confirmed)?'확정하고 다음 장면':'이미지 확정'}</button>
              </div>
              <details><summary>버전·프롬프트 더보기</summary>
              <label>이미지 버전<select aria-label={`장면 ${selected.plan.no} 이미지 버전`} value={versions[selected.plan.no]??selected.selected??''} onChange={e=>setVersions({...versions,[selected.plan.no]:+e.target.value})}>
                <option value="">버전 선택</option>{selected.versions.map((v:Item)=><option key={v.version} value={v.version}>버전 {v.version} · {stateName[v.state]??v.state}</option>)}</select></label>
              <p className="precision-prompt">{selected.prompt}</p>
              <button disabled={locked} onClick={()=>setEditing({scenario:structuredClone(work.scenario),number:selected.plan.no})}>장면 내용 수정</button></details>
            </div>
          </div>}
        </div>
      </section>}
    </>}
    {approval==='story'&&<CharacterModal title="스토리 만들기" busy={!!busy} onClose={()=>setApproval(null)} footer={<button className="primary" disabled={!!busy||(!work&&!canCreate)} onClick={()=>void act('story',{consent:'true'})}>유료 스토리 생성 승인</button>}>
      <p>{work?.common.topic??common.topic}</p><p>{work?.video_settings.script_model??video.script_model}</p>
      <p>스토리·영상 작업 한도 US${work?.video_limit??videoLimit}</p><p>캐릭터 특징과 주제를 AI에 전송합니다. 참조 이미지는 보내지 않습니다.</p>
    </CharacterModal>}
    {approval==='images'&&quote&&<CharacterModal title="장면 이미지 만들기" busy={!!busy} onClose={()=>setApproval(null)} footer={<button className="primary" disabled={locked} onClick={()=>void act('generate',{quote_hash:quote.hash,consent:'true',reference_consent:'true'})}>참조 이미지 전송·생성 승인</button>}>
      <p>장면 {quote.numbers.join(', ')} · {work?.selection.model}</p>
      <p>예상 US${quote.estimated_usd} · 예산 예약 US${quote.reserve_usd}</p>
      <p>선택한 캐릭터 참조 이미지를 전송합니다. 실제 청구액과 다를 수 있으며 영상 비용은 별도입니다.</p>
    </CharacterModal>}
    {editing&&<CharacterModal title="장면 내용 수정" busy={!!busy} onClose={()=>setEditing(null)} footer={<button className="primary" disabled={!!busy} onClick={()=>void act('edit',{scenario:JSON.stringify(editing.scenario)})}>장면 저장 · 무료</button>}>
      <label>편집할 장면<select value={editing.number??editing.scenario.scenes[0]?.no} onChange={e=>setEditing({...editing,number:Number(e.target.value)})}>
        {editing.scenario.scenes.map((s:Item)=><option key={s.no} value={s.no}>장면 {s.no}</option>)}</select></label>
      <div className="precision-editor">{(editing.scenario.scenes??[]).map((s:Item,i:number)=>{
        if(s.no!==(editing.number??editing.scenario.scenes[0]?.no))return null;
        const set=(key:string,value:unknown)=>setEditing({...editing,scenario:{...editing.scenario,scenes:editing.scenario.scenes.map((r:Item,j:number)=>j===i?{...r,[key]:value}:r)}});
        return <fieldset key={s.no}><legend>장면 {s.no}</legend><div className="precision-pair">
          {Object.values(work!.cast).map((p:unknown)=>{const person=p as Item;return <label className="precision-check" key={person.id}><input type="checkbox" checked={s.characters.includes(person.id)}
            onChange={e=>set('characters',e.target.checked?[...s.characters,person.id]:s.characters.filter((id:string)=>id!==person.id))}/>{person.name_ko}</label>;})}
          {Object.entries({description:'장면 설명',location:'장소',pose:'행동·자세',emotion:'표정·감정'}).map(([key,label])=>
            <label key={key}>{label}<textarea value={s[key]??''} onChange={e=>set(key,e.target.value)}/></label>)}
          <label>길이(초)<input type="number" min={3} max={15} value={s.seconds} onChange={e=>set('seconds',+e.target.value)}/></label>
        </div><details className="precision-editor-advanced"><summary>구도·연결·자막·소리 자세히</summary><div className="precision-pair">
          {Object.entries({camera:'이미지 구도',props:'소품·위치',continuity:'이어질 요소',caption:'별도 자막',motion:'영상 동작 · 영어',motion_camera:'영상 카메라 · 영어',sound:'환경음'}).map(([key,label])=>
            <label key={key}>{label}<textarea value={s[key]??''} onChange={e=>set(key,e.target.value)}/></label>)}
          <label>로컬 효과음<select value={s.sfx?.[0]?.key??''} onChange={e=>set('sfx',e.target.value?[{at:'end',key:e.target.value}]:[])}><option value="">없음</option>{(catalog?.sfx_keys??[]).map((key:string)=><option key={key}>{key}</option>)}</select></label>
        </div></details></fieldset>;})}</div></CharacterModal>}
    {large&&<CharacterModal title="장면 이미지" onClose={()=>setLarge(null)}><img className="precision-large" src={large} alt="장면 확대"/></CharacterModal>}
  </section>;
}
