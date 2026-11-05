import {useEffect,useRef,useState} from 'react';
import {characterCommand,CharacterModal} from './CharacterAutomation';
import type {Controller} from './shared';
import type {Item} from '../contracts';
import './character-precision.css';
import PrecisionActivity from './PrecisionActivity';
import {timingIssue,sceneErrors,basicSceneFields,advancedSceneFields,connectionSceneFields,editableScenario} from './precisionValidation';

const base='/api/studio/character-precision';
const blank={title:'',topic:'',relationships:'',genre:'대사 없는 코미디',world:'',background:'',props:'',
  style:'3D animation',ratio:'9:16',scene_count:5,duration:20,prohibitions:''};
const stateName:Record<string,string>={needs_story:'스토리 작성',writing:'스토리 생성 중',story_failed:'스토리 확인 필요',
  connection_review:'장면 연결 검토',images:'장면 이미지 검토',generating:'이미지 생성 중',video_ready:'영상 제작 준비',pending:'생성 전',
  review:'검토 대기',confirmed:'이미지 확정',unknown:'결과 미확인 · 재전송 안 함',failed:'실패',success:'완료',requesting:'요청 중'};

export default function CharacterPrecision({c}:{c:Controller}) {
  const [catalog,setCatalog]=useState<Item|null>(null),[work,setWork]=useState<Item|null>(null);
  const [common,setCommon]=useState(blank),[cast,setCast]=useState<string[]>([]),[outfits,setOutfits]=useState<Record<string,string>>({});
  const [image,setImage]=useState<Item>({}),[video,setVideo]=useState<Item>({});
  const [imageLimit,setImageLimit]=useState(''),[videoLimit,setVideoLimit]=useState('');
  const [savedImageLimit,setSavedImageLimit]=useState('');
  useEffect(()=>{setSavedImageLimit(String(work?.image_limit??''));},[work?.id,work?.revision]);
  const [busy,setBusy]=useState(''),[error,setError]=useState(''),[approval,setApproval]=useState<'story'|'images'|null>(null);
  const [picked,setPicked]=useState<number[]>([]),[versions,setVersions]=useState<Record<number,number>>({});
  const [budgetOpen,setBudgetOpen]=useState(false),[editing,setEditing]=useState<Item|null>(null);
  const reviewArea=useRef<HTMLElement|null>(null),editorInitial=useRef('');
  const [editorError,setEditorError]=useState(''),[fieldErrors,setFieldErrors]=useState<Record<string,string>>({});
  const [pollError,setPollError]=useState('');
  const [requestStarted,setRequestStarted]=useState(0);
  const selectionEpoch=useRef(0);
  const [loadingWork,setLoadingWork]=useState<string|null>(null),[editorNotice,setEditorNotice]=useState('');
  function openEditor(draft:Item,source=work){
    if(!source)return;
    const prepared=editableScenario(draft.scenario,source.common.scene_count);
    if(!prepared){setError('보관된 장면 수가 설정과 다릅니다. 원문은 보존돼 있으며 직접 작성으로 수정할 수 있습니다.');return;}
    editorInitial.current=JSON.stringify(prepared.scenario);setEditorError('');setFieldErrors({});
    setEditorNotice(prepared.recovered?'보관된 응답에 빠진 항목이 있습니다. 빈 항목을 채운 뒤 저장하세요. 원문은 그대로 보존합니다.':'');
    setEditing({...draft,scenario:prepared.scenario});
  }
  function closeEditor(){
    if(editing&&JSON.stringify(editing.scenario)!==editorInitial.current&&!window.confirm('저장하지 않은 수정 내용이 있습니다. 버리고 닫을까요?'))return;
    setEditing(null);setEditorError('');setFieldErrors({});
  }
  useEffect(()=>{
    if(!editing||JSON.stringify(editing.scenario)===editorInitial.current)return;
    const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue='';};
    window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);
  },[editing]);
  const [large,setLarge]=useState<string|null>(null),[scene,setScene]=useState(1);
  const styleEdited=useRef(false),worldEdited=useRef(false);
  const sending=useRef(false),createId=useRef(crypto.randomUUID().replaceAll('-',''));
  async function get(path:string) {const r=await fetch(path,{credentials:'same-origin'});if(!r.ok)throw Error('저장된 자료를 불러오지 못했습니다.');return r.json();}
  useEffect(()=>{let live=true;const epoch=selectionEpoch.current;const initialId=new URLSearchParams(location.search).get('precision');get(base).then(async d=>{
    if(!live)return;setCatalog(d);setImage(d.recent_settings?.selection??d.image_defaults);
    setVideo(d.recent_settings?.video_settings??d.video.defaults);
    const standing=Number(d.standing_limit),previous=Number(d.recent_settings?.image_limit);
    setImageLimit(standing>0?String(previous>0?Math.min(standing,previous):standing):'');
    setVideoLimit(d.recent_settings?.video_limit??'');
    setBudgetOpen(!(standing>0&&Number(d.recent_settings?.video_limit)>0));
    setCommon(v=>({...v,duration:d.video.character?.target_duration?.default??d.video.defaults.duration??20}));
    if(epoch===selectionEpoch.current&&initialId&&/^[a-f0-9]{32}$/.test(initialId))await loadWork(initialId);
  }).catch(e=>{if(live)setError(e.message);});return()=>{live=false;selectionEpoch.current++;};},[]);
  useEffect(()=>{
    if(loadingWork!==null||!work?.id||!(busy||['writing','generating'].includes(work.state)))return;
    const id=work.id;let live=true,inFlight=false;
    const poll=async()=>{
      if(inFlight)return;inFlight=true;
      try{const next=await get(`${base}/${id}`);
        if(live){setPollError('');setWork(previous=>previous&&previous.id===id&&next.revision>=previous.revision&&
          (next.updated_at??'')>=(previous.updated_at??'')?next:previous);}
      }catch{if(live)setPollError('진행 상태를 확인하지 못했습니다. 연결되면 다시 확인합니다. 생성 요청은 반복하지 않습니다.');}
      finally{inFlight=false;}
    };
    const timer=setInterval(()=>void poll(),2000);
    return()=>{live=false;clearInterval(timer);};
  },[busy,work?.id,work?.state,loadingWork]);
  function remember(w:Item){
    setWork(w);setCatalog(d=>d?{...d,works:[{id:w.id,title:w.common.title},...(d.works??[]).filter((item:Item)=>item.id!==w.id)]}:d);
    const url=new URL(location.href);url.searchParams.set('precision',w.id);url.searchParams.delete('job_id');history.replaceState(null,'',url);
  }
  function creationValues(){return {request_id:createId.current,payload:JSON.stringify({
    common:{...common,title:Array.from(common.topic.trim()).slice(0,100).join('')},character_ids:cast,
    outfits:Object.fromEntries(cast.map(id=>[id,outfits[id]??'참조 이미지의 의상·액세서리 유지'])),
    selection:image,video_settings:video,image_limit:imageLimit,video_limit:videoLimit})};}
  function manual(w:Item){openEditor({scenario:{scenes:Array.from({length:w.common.scene_count},(_,i)=>({no:i+1,
    characters:[Object.keys(w.cast)[0]],description:'',location:'',pose:'',emotion:'',camera:'',props:'',continuity:'',connection:i?'continue':'cut',set_id:'',environment:'',start_state:'',end_state:'',transition_reason:'',caption:'',
    seconds:Math.floor(w.common.duration/w.common.scene_count)+(i<w.common.duration%w.common.scene_count?1:0),motion:'',motion_camera:'',sound:''}))}},w);}
  async function act(kind:string,values:Record<string,string>={}) {
    if(sending.current||loadingWork!==null)return;
    if(kind==='edit'&&editing&&work){
      const issues=sceneErrors(editing.scenario,work,sceneSeconds(work.video_settings.video_model));
      setFieldErrors(issues);setEditorError('');
      if(Object.keys(issues).length){
        const first=Object.keys(issues).find(key=>!key.startsWith('_'));
        if(first)setEditing({...editing,number:Number(first.split('.')[0])});
        setEditorError(issues._scenes??issues._total??'표시된 입력 항목을 확인하세요.');return;
      }
    }
    sending.current=true;setRequestStarted(Date.now());setBusy(kind);setError('');setPollError('');
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
      if(kind==='revise-connection')openEditor({scenario:structuredClone(w.scenario)},w);
      if(kind==='confirm'){
        const pending=w.scenes.filter((row:Item)=>!row.confirmed);
        const next=pending.find((row:Item)=>row.plan.no>Number(values.number))??pending[0];
        if(next)setScene(next.plan.no);
      }
      if(kind==='handoff'&&w.video_job_id)location.assign(`/studio/characters?job_id=${w.video_job_id}`);
    } catch(e){setApproval(null);const message=e instanceof Error?e.message:'처리 결과를 확인하세요.';
      if(kind==='edit')setEditorError(message);else setError(message);
      if(target?.id)try{remember(await get(`${base}/${target.id}`));}catch{/* keep the last visible journal */}
    } finally{setBusy('');sending.current=false;}
  }
  const rows:Item[]=work?.scenes??[], profiles:Item[]=catalog?.profiles??[];
  const paidAvailable=catalog?.paid_available!==false;
  const locked=loadingWork!==null||!!busy||!!work?.video_job_id||['writing','generating'].includes(work?.state);
  const completed=rows.filter(s=>s.versions.some((v:Item)=>v.state==='success')).length;
  useEffect(()=>{if(completed>0)reviewArea.current?.scrollIntoView({block:'start'});},[work?.id,completed>0]);
  const lastStory=work?.story_attempts?.at(-1);
  const storyActive=busy==='story'||work?.state==='writing';
  const imageActive=busy==='generate'||work?.state==='generating';
  const storyFailed=work?.state==='story_failed';
  const imageStart=work?.events?.filter((e:Item)=>e.kind==='image_approval').at(-1)?.at;
  const activityStart=(storyActive?lastStory?.at:imageActive?imageStart:null);
  const activity=<PrecisionActivity active={storyActive||imageActive} phase={storyActive||storyFailed?'story':'images'}
    started={activityStart?Date.parse(activityStart):requestStarted} completed={completed} total={work?.common.scene_count??common.scene_count}
    failed={storyFailed} unknown={lastStory?.state==='unknown'} candidate={!!lastStory?.candidate} connectionIssue={pollError}/>;
  const quote=work?.quote;
  const missing=rows.filter(s=>!s.versions.length&&s.image_ready!==false);
  const validConfirmed=(s:Item)=>!!s.confirmed&&s.confirmed_valid!==false;
  const needsAnchorReview=rows.some(s=>s.image_ready===false);
  const allConfirmed=!!rows.length&&rows.every(validConfirmed);
  function sceneSeconds(model:string):number[]{return catalog?.video.modelsDetailed.find((m:Item)=>m.id===model)?.duration_values??[];}
  const timingError=catalog?timingIssue(common.duration,common.scene_count,sceneSeconds(video.video_model)):'';
  const canCreate=loadingWork===null&&!timingError&&!busy&&cast.length>0&&cast.length<=4&&!!common.topic.trim()&&Number(imageLimit)>0&&Number(videoLimit)>0;
  const selected=rows.find(s=>s.plan.no===scene)??rows[0];
  const current=selected?.versions.find((v:Item)=>v.version===(versions[selected.plan.no]??selected.selected));
  const staleImage=!!current&&current.matches_current_plan!==true;
  function selectCharacter(p:Item,checked:boolean){
    setCast(checked?[...cast,p.id]:cast.filter(id=>id!==p.id));
    if(checked&&!cast.length)setCommon(v=>({...v,
      style:styleEdited.current?v.style:p.style_lock||v.style,
      world:worldEdited.current?v.world:p.comedy_formula?.world||''}));
  }

  function clearSelection(){setVersions({});setPicked([]);setScene(1);setApproval(null);setEditing(null);setLarge(null);setError('');setEditorError('');setFieldErrors({});setPollError('');}
  function newWork(){selectionEpoch.current++;setLoadingWork(null);clearSelection();setWork(null);createId.current=crypto.randomUUID().replaceAll('-','');
    const u=new URL(location.href);u.searchParams.set('precision','');u.searchParams.delete('job_id');history.replaceState(null,'',u);}
  async function loadWork(id:string){
    const epoch=++selectionEpoch.current;setLoadingWork(id);clearSelection();
    try{
      const next=await get(`${base}/${id}`);
      if(epoch!==selectionEpoch.current)return;
      setWork(next);
      const url=new URL(location.href);url.searchParams.set('precision',next.id);url.searchParams.delete('job_id');history.replaceState(null,'',url);
    }catch{if(epoch===selectionEpoch.current)setError('작품을 불러오지 못했습니다. 다시 선택해 주세요.');}
    finally{if(epoch===selectionEpoch.current)setLoadingWork(null);}
  }
  return <section className="character-precision" aria-label="정밀 제작">
    <header className="precision-steps" aria-label="정밀 제작 흐름">
      {['캐릭터 선택','스토리 생성','영상 제작'].map((title,i)=><div key={title}><b>{i+1}</b><strong>{title}</strong></div>)}
    </header>
    {error&&<p role="alert" className="precision-error">{error}</p>}
    {catalog&&!paidAvailable&&<p role="status" className="precision-hint">정밀 제작의 AI 연결 준비 중 · 작품 편집과 검토는 사용할 수 있습니다.</p>}
    <div className="precision-toolbar"><label>저장한 작품 <select disabled={!!busy} value={loadingWork??work?.id??''} onChange={e=>{
      if(!e.target.value){newWork();return;}void loadWork(e.target.value);}}>
      <option value="">새 작품</option>{(catalog?.works??[]).map((w:Item)=><option key={w.id} value={w.id}>{w.title}</option>)}
      {work&&!(catalog?.works??[]).some((w:Item)=>w.id===work.id)&&<option value={work.id}>{work.common.title}</option>}
    </select></label><button disabled={!!busy} onClick={newWork}>새 작품</button></div>
    {loadingWork!==null&&<p role="status">선택한 작품을 불러오는 중입니다.</p>}
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
        <button className="primary" disabled={!paidAvailable||!canCreate} onClick={()=>setApproval('story')}>스토리 만들기</button>
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
          <label>장면 수<input aria-invalid={!!timingError} aria-describedby={timingError?"precision-timing-error":undefined} type="number" min={2} max={12} value={common.scene_count} onChange={e=>setCommon({...common,scene_count:+e.target.value})}/></label></div>
          <>{timingError&&<p id="precision-timing-error" role="alert" className="precision-error">{timingError}</p>}</><label>영상 모델<select value={video.video_model??''} onChange={e=>{
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
        {work.scenario&&<button disabled={locked} onClick={()=>openEditor({scenario:structuredClone(work.scenario)})}>스토리 검토·수정</button>}
      {!work.scenario&&<div className="precision-story-controls">
        <button className="primary" disabled={!paidAvailable||locked||work.story_attempts.length>0} onClick={()=>setApproval('story')}>스토리 만들기</button>
        <details><summary>직접 작성·복구</summary><button disabled={locked} onClick={()=>manual(work)}>직접 작성</button>
        {work.state==='story_failed'&&<p>보관된 응답을 검토하세요. 추가 AI 요청 없이 수정할 수 있습니다.</p>}
        {work.story_attempts.at(-1)?.candidate&&<button onClick={()=>openEditor({scenario:structuredClone(work.story_attempts.at(-1).candidate)})}>보관된 스토리 편집</button>}</details>
      </div>}
      </section>
      <section><h3>3. 영상 제작</h3><p>{work.common.duration}초 · {work.common.scene_count}장면</p>
        <p>{catalog?.video.models[work.video_settings.video_model]??work.video_settings.video_model}</p>
        {work.video_job_id?<><p className="precision-hint">확정한 이미지로 영상 제작을 이어갑니다.</p></>:
          allConfirmed?<p className="precision-hint">장면 검토 아래에서 영상 제작으로 이동하세요.</p>:
          missing.length?<button className="primary" disabled={locked} onClick={()=>void act('quote',{numbers:JSON.stringify(missing.map(s=>s.plan.no))})}>{needsAnchorReview?'배경 기준 장면 먼저 만들기':'장면 이미지 만들기'}</button>:
          <p className="precision-hint">{needsAnchorReview?'첫 장면의 배경·소품을 확정하면 나머지 장면을 만들 수 있습니다.':rows.length?'아래에서 장면 이미지를 확인하세요.':'스토리를 먼저 만들어 주세요.'}</p>}
        <details><summary>저장된 모델·예산</summary><p>이미지 {work.selection.model} · {work.selection.quality}</p>
          <p>이미지 US${work.image_limit} / 스토리·영상 US${work.video_limit}</p>
          {work.scenario&&!work.video_job_id&&<div className="precision-pair"><label>이번 작품 이미지 예산(USD)<input type="number" min="0.000001" step="0.000001" disabled={locked} value={savedImageLimit} onChange={e=>setSavedImageLimit(e.target.value)}/></label>
            <button disabled={locked||!(Number(savedImageLimit)>0)||Number(savedImageLimit)===Number(work.image_limit)} onClick={()=>void act('edit',{scenario:JSON.stringify(work.scenario),image_limit:savedImageLimit})}>이미지 예산 저장</button></div>}
          <small>설정의 요청당 한도도 적용됩니다. 예산 변경으로 이미지를 생성하지 않습니다.</small></details>
      </section>
      </div></details><div className="precision-progress" role="status" aria-live="polite"><strong>{work.common.title} · {stateName[work.state]??work.state}</strong>
      {activity}
      {!storyActive&&!storyFailed&&<span>{completed}/{rows.length||work.common.scene_count}장 완료 · {rows.filter(validConfirmed).length}장 확정</span>}
      {storyFailed&&lastStory?.candidate&&<button disabled={locked} onClick={()=>openEditor({scenario:structuredClone(lastStory.candidate)})}>보관된 응답 검토·수정 · 무료</button>}
      {!busy&&(['writing','generating'].includes(work.state)||rows.some(s=>s.versions.some((v:Item)=>['requesting','unknown'].includes(v.state))))&&<button onClick={()=>void act('reconcile')}>저장된 결과 확인 · 무료</button>}
      <>{!storyActive&&!imageActive&&!storyFailed&&<progress value={completed} max={rows.length||work.common.scene_count}/>}</></div>
      {rows.length>0&&<section ref={reviewArea} className="precision-review-area">
        {work.visual_reference_policy&&completed>0&&!work.video_job_id&&<div className="precision-next-action">
          {needsAnchorReview&&<p>첫 장면의 배경·소품을 확정하면 나머지 장면을 만들 수 있습니다.</p>}
          {missing.length>0&&<button className="primary" disabled={locked} onClick={()=>void act('quote',{numbers:JSON.stringify(missing.map(s=>s.plan.no))})}>나머지 장면 이미지 만들기</button>}
        </div>}
        <div className="precision-review-heading"><h3>장면 이미지 검토</h3>
        {allConfirmed&&!work.video_job_id&&<button className="primary" disabled={locked} onClick={()=>void act('handoff')}>영상 제작으로 이동</button>}
        {work.video_job_id&&<button disabled={!!busy} onClick={()=>void act('revise-connection',{request_id:crypto.randomUUID().replaceAll('-','')})}>연결 보완 초안 · 무료</button>}
        {work.state==='connection_review'&&<button onClick={()=>openEditor({scenario:structuredClone(work.scenario)})}>장면 연결 검토</button>}
        {work.video_job_id&&<a className="button primary" href={`/studio/characters?job_id=${work.video_job_id}`}>영상 제작 열기</a>}</div>
        <details className="precision-batch"><summary>여러 장면 다시 만들기</summary>
          {rows.map(s=><label className="precision-check" key={s.plan.no}><input type="checkbox" disabled={locked} checked={picked.includes(s.plan.no)} onChange={e=>setPicked(e.target.checked?[...picked,s.plan.no]:picked.filter(x=>x!==s.plan.no))}/>장면 {s.plan.no}</label>)}
          <button disabled={locked||!picked.length||rows.some(s=>picked.includes(s.plan.no)&&(s.image_ready===false||picked.includes(s.visual_anchor_scene)))} onClick={()=>void act('quote',{numbers:JSON.stringify(picked),regenerate:'true'})}>선택 장면 다시 만들기</button>
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
              <p className="precision-hint">캐릭터의 좌우 위치, 창문·가구, 소품 모양과 개수, 시작 동작을 확인하세요.</p>
              {work.visual_reference_policy&&<p className="precision-hint">{selected.visual_anchor_scene?`배경 기준: 확정한 장면 ${selected.visual_anchor_scene}`:'이 장소의 배경 기준 이미지입니다.'}</p>}
              <>{staleImage&&<p className="precision-error" role="status">{work.visual_reference_policy?'장면 내용 또는 배경 기준이 변경됐습니다. 기존 이미지는 보존됩니다. 다시 만든 뒤 확정하세요.':'이전 장면의 이미지입니다. 현재 장면에 맞게 다시 만든 뒤 확정하세요.'}</p>}</><div className="precision-scene-actions">
                <button disabled={locked||selected.image_ready===false||selected.versions.some((v:Item)=>['requesting','unknown'].includes(v.state))} onClick={()=>void act('quote',{numbers:JSON.stringify([selected.plan.no]),regenerate:'true'})}>다시 만들기</button>
                <button className={!allConfirmed?'primary':''} disabled={locked||!current?.asset||staleImage||selected.confirmed?.version===current.version}
                  onClick={e=>{if(e.detail>1)return;void act('confirm',{number:String(selected.plan.no),version:String(current.version),reviewed:'true'});}}>
                  {staleImage?'이전 장면 이미지':current&&selected.confirmed?.version===current.version?'사용 중인 이미지':rows.some(s=>s.plan.no!==selected.plan.no&&!s.confirmed)?'확정하고 다음 장면':'이미지 확정'}</button>
              </div>
              <details><summary>버전·프롬프트 더보기</summary>
              <label>이미지 버전<select aria-label={`장면 ${selected.plan.no} 이미지 버전`} value={versions[selected.plan.no]??selected.selected??''} onChange={e=>setVersions({...versions,[selected.plan.no]:+e.target.value})}>
                <option value="">버전 선택</option>{selected.versions.map((v:Item)=><option key={v.version} value={v.version}>버전 {v.version} · {stateName[v.state]??v.state}{v.matches_current_plan===false?' · 이전 장면':''}</option>)}</select></label>
              <p className="precision-prompt">{selected.prompt}</p>
              <button disabled={locked} onClick={()=>openEditor({scenario:structuredClone(work.scenario),number:selected.plan.no})}>장면 내용 수정</button></details>
            </div>
          </div>}
        </div>
      </section>}
    </>}
    {approval==='story'&&<CharacterModal title="스토리 만들기" busy={!!busy} onClose={()=>setApproval(null)} footer={<button className="primary" disabled={!paidAvailable||!!busy||(!work&&!canCreate)} onClick={()=>void act('story',{consent:'true'})}>{storyActive?'스토리 생성 중…':'유료 스토리 생성 승인'}</button>}>
      {(storyActive||storyFailed)&&activity}
      <p>{work?.common.topic??common.topic}</p><p>{work?.video_settings.script_model??video.script_model}</p>
      <p>스토리·영상 작업 한도 US${work?.video_limit??videoLimit}</p><p>캐릭터 특징과 주제를 AI에 전송합니다. 참조 이미지는 보내지 않습니다.</p>
    </CharacterModal>}
    {approval==='images'&&quote&&<CharacterModal title="장면 이미지 만들기" busy={!!busy} onClose={()=>setApproval(null)} footer={<button className="primary" disabled={!paidAvailable||locked} onClick={()=>void act('generate',{quote_hash:quote.hash,consent:'true',reference_consent:'true'})}>{imageActive?'장면 이미지 생성 중…':'참조 이미지 전송·생성 승인'}</button>}>
      {imageActive&&activity}
      <p>장면 {quote.numbers.join(', ')} · {work?.selection.model}</p>
      <p>예상 US${quote.estimated_usd} · 예산 예약 US${quote.reserve_usd}</p>
      <p>선택한 캐릭터와 확정된 배경 기준 이미지를 전송합니다. 실제 청구액과 다를 수 있으며 영상 비용은 별도입니다.</p>
    </CharacterModal>}
    {editing&&<CharacterModal title="장면 내용 수정" busy={!!busy} onClose={closeEditor} footer={<button className="primary" disabled={!!busy} onClick={()=>void act('edit',{scenario:JSON.stringify(editing.scenario)})}>장면 저장 · 무료</button>}>
      {editorNotice&&<p role="status">{editorNotice}</p>}
      {editorError&&<p role="alert" className="precision-error">{editorError}</p>}
      <label>편집할 장면<select value={editing.number??editing.scenario.scenes[0]?.no} onChange={e=>setEditing({...editing,number:Number(e.target.value)})}>
        {editing.scenario.scenes.map((s:Item)=><option key={s.no} value={s.no}>장면 {s.no}</option>)}</select></label>
      <div className="precision-editor">{(editing.scenario.scenes??[]).map((s:Item,i:number)=>{
        if(s.no!==(editing.number??editing.scenario.scenes[0]?.no))return null;
        const set=(key:string,value:unknown)=>{setEditing({...editing,scenario:{...editing.scenario,scenes:editing.scenario.scenes.map((r:Item,j:number)=>j===i?{...r,[key]:value}:r)}});
          setFieldErrors(previous=>Object.fromEntries(Object.entries(previous).filter(([name])=>name!==`${s.no}.${key}`)));};
        const issue=(key:string)=>fieldErrors[`${s.no}.${key}`];
        const field=(key:string,label:string)=><label key={key}>{label}<textarea aria-label={label} aria-invalid={!!issue(key)}
          aria-describedby={issue(key)?`scene-${s.no}-${key}-error`:undefined} value={s[key]??''} onChange={e=>set(key,e.target.value)}/>
          {issue(key)&&<small className="precision-field-error" id={`scene-${s.no}-${key}-error`}>{issue(key)}</small>}</label>;
        return <fieldset key={s.no}><legend>장면 {s.no}</legend><div className="precision-pair">
          {Object.values(work!.cast).map((p:unknown)=>{const person=p as Item;return <label className="precision-check" key={person.id}><input type="checkbox" checked={s.characters.includes(person.id)}
            onChange={e=>set('characters',e.target.checked?[...s.characters,person.id]:s.characters.filter((id:string)=>id!==person.id))}/>{person.name_ko}</label>;})}
          {issue('characters')&&<p className="precision-field-error">{issue('characters')}</p>}
          {Object.entries(basicSceneFields).map(([key,label])=>field(key,label))}
          {['precision-continuity-v2','precision-causal-v3'].includes(work?.continuity_policy)&&<>
            <label>장면 연결<select aria-label="장면 연결" value={s.connection??'cut'} onChange={e=>set('connection',e.target.value)}><option value="cut">새 장면 · 의도적인 전환</option><option value="continue" disabled={i===0}>앞 영상의 마지막 화면에서 이어가기</option></select>{issue('connection')&&<small>{issue('connection')}</small>}</label>
            {Object.entries(connectionSceneFields).filter(([key])=>key!=='transition_reason'||(i>0&&s.connection!=='continue')).map(([key,label])=>field(key,label))}
            {i>0&&s.connection==='continue'&&<button type="button" onClick={()=>set('start_state',editing.scenario.scenes[i-1].end_state??'')}>앞 장면 끝 상태 가져오기</button>}
          </>}
          {work?.continuity_policy==='precision-causal-v3'&&<>
            {field('cause','이 행동을 하는 이유')}{field('result','행동 뒤 달라지는 것')}
            {i>0&&<button type="button" onClick={()=>set('cause',editing.scenario.scenes[i-1].result??'')}>앞 장면 결과 가져오기</button>}
            <details><summary>소품의 변화</summary>
              {(s.prop_states??[]).map((prop:Item,n:number)=><fieldset key={n}><legend>소품 {n+1}</legend>
                {Object.entries({id:'소품 이름',before:'시작 상태 · 수량·형태·위치',after:'끝 상태 · 수량·형태·위치',change:'바뀌는 행동'}).map(([key,label])=><label key={key}>{label}<input value={prop[key]??''} onChange={e=>set('prop_states',s.prop_states.map((p:Item,j:number)=>j===n?{...p,[key]:e.target.value}:p))}/></label>)}
                <button type="button" onClick={()=>set('prop_states',s.prop_states.filter((_:Item,j:number)=>j!==n))}>소품 제외</button></fieldset>)}
              <button type="button" disabled={(s.prop_states??[]).length>=8} onClick={()=>set('prop_states',[...(s.prop_states??[]),{id:'',before:'',after:'',change:''}])}>소품 추가</button>
              {i>0&&<button type="button" onClick={()=>set('prop_states',(editing.scenario.scenes[i-1].prop_states??[]).map((p:Item)=>({id:p.id,before:p.after,after:p.after,change:''})))}>앞 장면 소품 상태 가져오기</button>}
              {issue('prop_states')&&<p role="alert">{issue('prop_states')}</p>}
            </details>
          </>}
          <label>길이(초)<input aria-invalid={!!issue('seconds')} aria-describedby={issue('seconds')?`scene-${s.no}-seconds-error`:undefined} type="number" min={3} max={15} value={s.seconds} onChange={e=>set('seconds',+e.target.value)}/>{issue('seconds')&&<small className="precision-field-error" id={`scene-${s.no}-seconds-error`}>{issue('seconds')}</small>}</label>
        </div><details className="precision-editor-advanced" open={Object.keys(advancedSceneFields).some(key=>!!issue(key))||undefined}><summary>구도·연결·자막·소리 자세히</summary><div className="precision-pair">
          {Object.entries(advancedSceneFields).map(([key,label])=>field(key,label))}
          <label>로컬 효과음<select value={s.sfx?.[0]?.key??''} onChange={e=>set('sfx',e.target.value?[{at:'end',key:e.target.value}]:[])}><option value="">없음</option>{(catalog?.sfx_keys??[]).map((key:string)=><option key={key}>{key}</option>)}</select></label>
        </div></details></fieldset>;})}</div></CharacterModal>}
    {large&&<CharacterModal title="장면 이미지" onClose={()=>setLarge(null)}><img className="precision-large" src={large} alt="장면 확대"/></CharacterModal>}
  </section>;
}
