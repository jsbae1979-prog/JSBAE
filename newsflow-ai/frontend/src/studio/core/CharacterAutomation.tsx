import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import type { Item } from "../contracts";

export async function characterCommand(path: string, csrf: string, values: Record<string, string>) {
  const response = await fetch(path, { method: "POST", credentials: "same-origin",
    body: new URLSearchParams({ ...values, csrf_token: csrf }) });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "저장 상태를 확인하세요. 자동 재요청하지 않습니다.");
  return data;
}
const blankProfile = () => ({ name_ko: "", species: "", appearance: "", personality: "",
  comedy_formula: { world: "", setup: "", reaction: "" },
  style_lock: "", supporting_cast: [] as Item[], audience: "general", made_for_kids: false });
export function CharacterModal({title, busy=false, onClose, children, footer}: {
  title: string; busy?: boolean; onClose:()=>void; children:ReactNode; footer?:ReactNode;
}) {
  const dialog=useRef<HTMLDialogElement>(null), titleId=useId();
  useEffect(()=>{
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    const node=dialog.current;
    node?.showModal();
    node?.querySelector<HTMLElement>('[data-autofocus]')?.focus();
    return ()=>{
      if(node?.open)node.close();
      requestAnimationFrame(()=>{
        if(previous?.isConnected)previous.focus();
        else document.querySelector<HTMLElement>('[data-character-profile-focus]')?.focus();
      });
    };
  },[]);
  return <dialog ref={dialog} className="character-modal" aria-labelledby={titleId} aria-modal="true"
    onCancel={e=>{e.preventDefault();if(!busy)onClose();}}>
    <header className="character-modal-head"><h2 id={titleId}>{title}</h2>
      <button type="button" aria-label={`${title} 닫기`} disabled={busy} onClick={onClose}>×</button></header>
    <div className="character-modal-body">{children}</div>
    {footer&&<footer className="character-modal-footer">{footer}</footer>}
  </dialog>;
}

export function CharacterProfiles({ profiles, selected, onSelect, ensureAsset, model, available,
  csrf, disabled, onRefresh, onBusy, mode, images, selectedAsset, onSelectImage, hasReference }: {
  profiles: Item[]; selected: Item | null; onSelect: (p: Item | null) => void;
  ensureAsset: () => Promise<string>; model: string; available: boolean; csrf: string;
  disabled: boolean; onRefresh: () => Promise<unknown>; onBusy: (value:boolean) => void;
  mode:string; images:Item[]; selectedAsset:string; onSelectImage:(asset:string)=>void; hasReference:boolean;
}) {
  const [editing, setEditing] = useState(false), [record, setRecord] = useState<Item | null>(null);
  const [draft, setDraft] = useState(blankProfile), [asset, setAsset] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [consent, setConsent] = useState(false), [candidates, setCandidates] = useState<Item[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const sending = useRef(false), form=useRef<HTMLFormElement>(null), formId=useId();
  const imageOnly=images.filter(image=>!profiles.some(p=>p.asset===image.id));
  const choice=selected?`profile:${selected.id}`:selectedAsset?`image:${selectedAsset}`:"";
  function begin(row: Item | null) {
    setRecord(row); setEditing(true); setError(""); setCandidates([]); setConsent(false);
    const base = blankProfile();
    setDraft(row ? Object.fromEntries(Object.keys(base).map(k => [k, row[k] ?? base[k as keyof typeof base]])) as typeof base : base);
    setAsset(row?.asset ?? "");
  }
  async function act(kind: "save" | "analyze" | "delete") {
    if (sending.current || disabled) return;
    if(kind==='save'&&!form.current?.reportValidity())return;
    sending.current = true; setBusy(true); onBusy(true); setError("");
    try {
      if (kind === "delete" && selected) {
        await characterCommand(`/api/studio/characters/profiles/${selected.id}/delete`, csrf,
          { revision: String(selected.revision), consent: "true" });
        onSelect(null); setConfirmDelete(false); await onRefresh(); return;
      }
      const reference = asset || await ensureAsset();
      if (!reference) throw Error("참조 이미지를 업로드하거나 저장한 이미지를 선택하세요.");
      setAsset(reference);
      if (kind === "analyze") {
        if (!consent || !available) throw Error("이미지 분석 전송과 유료 요청 승인을 확인하세요.");
        const result = await characterCommand("/api/studio/characters/profiles/analyze", csrf,
          { asset: reference, model, request_id: crypto.randomUUID().replaceAll("-", ""), consent: "true" });
        setDraft(v => ({ ...v, species: result.species, appearance: result.appearance, style_lock: result.style_suggestion }));
        setCandidates(result.candidates ?? []); setConsent(false);
      } else {
        const row = await characterCommand("/api/studio/characters/profiles/save", csrf,
          { asset: reference, profile: JSON.stringify(draft), identifier: record?.id ?? "", revision: String(record?.revision ?? 0) });
        setEditing(false); onSelect(row); await onRefresh();
      }
    } catch (e) {
      const message=e instanceof Error ? e.message : "캐릭터 정보를 확인하세요.";
      const generic=message.startsWith('입력·저장 상태')||message.startsWith('저장 상태를 확인')||message.startsWith('이미지 분석을 완료하지 못했습니다');
      setError(kind==='analyze'?`특징 초안을 만들지 못했습니다.${generic?'':` ${message}`}`:
        generic?(kind==='save'?'캐릭터 정보를 저장하지 못했습니다. 필수 항목을 확인하세요.':'캐릭터 등록을 삭제하지 못했습니다.'):message);
    }
    finally { sending.current = false; setBusy(false); onBusy(false); }
  }
  return <section className="character-profile-editor" aria-label="캐릭터 선택과 특징">
    {mode==='mine'&&<label>저장된 캐릭터<select aria-label="저장된 캐릭터" data-character-profile-focus disabled={disabled || busy} value={choice}
      onChange={e => {
        const value=e.target.value;
        if(value.startsWith('profile:'))onSelect(profiles.find(p=>p.id===value.slice(8))??null);
        else if(value.startsWith('image:'))onSelectImage(value.slice(6));
        else onSelect(null);
        setError('');
      }}>
      <option value="">캐릭터를 선택하세요</option>
      {selected && !profiles.some(p=>p.id===selected.id) && <option value={`profile:${selected.id}`}>{selected.name_ko} · 작업에 보존된 특징</option>}
      {profiles.length>0&&<optgroup label="캐릭터 · 특징 등록 완료">{profiles.map(p=><option key={p.id} value={`profile:${p.id}`}>{p.name_ko}</option>)}</optgroup>}
      {imageOnly.length>0&&<optgroup label="저장한 참조 이미지 · 특징 미등록">{imageOnly.map(image=><option key={image.id} value={`image:${image.id}`}>{image.label} · 특징 미등록</option>)}</optgroup>}
    </select></label>}
    {selected ? <>
      <div className="character-profile-summary"><strong>{selected.name_ko}</strong><span>특징 등록 완료</span><p>{selected.personality}</p></div>
      <div className="character-profile-actions"><button type="button" disabled={disabled||busy} onClick={()=>begin(selected)}>특징 수정</button>
        <button type="button" disabled={disabled||busy} onClick={()=>setConfirmDelete(true)}>등록 삭제</button></div>
    </>:<>
      <button type="button" data-character-profile-focus disabled={disabled||busy||!hasReference} onClick={()=>begin(null)}>{mode==='mine'?'이 이미지로 캐릭터 등록':'새 캐릭터 등록'}</button>
    </>}
    {confirmDelete&&<CharacterModal title="캐릭터 등록 삭제" busy={busy} onClose={()=>setConfirmDelete(false)} footer={<>
      <button type="button" disabled={busy} onClick={()=>setConfirmDelete(false)}>취소</button>
      <button type="button" disabled={busy} onClick={()=>void act('delete')}>등록 삭제 확인</button></>}>
      <p>등록만 삭제합니다. 이전 작업·이미지·영상·비용 기록은 보존됩니다.</p>{error&&<p role="alert">{error}</p>}
    </CharacterModal>}
    {editing&&<CharacterModal title={record?'캐릭터 특징 수정':'새 캐릭터 등록'} busy={busy} onClose={()=>setEditing(false)} footer={<>
      {error&&<p role="alert" className="character-modal-feedback">{error}</p>}
      <button type="button" disabled={busy} onClick={()=>setEditing(false)}>취소</button>
      <button type="submit" form={formId} disabled={disabled||busy} className="primary">{busy?'처리 중…':'캐릭터 저장'}</button></>}>
      <form id={formId} ref={form} className="character-profile-form" onSubmit={e=>{e.preventDefault();void act('save');}}>
        <p>선택한 이미지에 이름과 특징을 저장합니다. 사용 권한이 있는 캐릭터만 등록하세요.</p>
        <fieldset disabled={disabled||busy} className="character-profile-fields">
          <label className="character-profile-wide">캐릭터 이름<input data-autofocus required value={draft.name_ko} maxLength={60} onChange={e=>setDraft(v=>({...v,name_ko:e.target.value}))}/></label>
          <label>외형 · 영어<textarea required value={draft.appearance} maxLength={400} rows={3} onChange={e=>setDraft(v=>({...v,appearance:e.target.value}))}/></label>
          <label>성격<textarea required value={draft.personality} maxLength={800} rows={3} onChange={e=>setDraft(v=>({...v,personality:e.target.value}))}/></label>
          {([['setup','반복되는 상황'],['reaction','캐릭터만의 반응']] as const).map(([key,label])=><label key={key}>{label}<input required value={draft.comedy_formula[key]} maxLength={60} onChange={e=>setDraft(v=>({...v,comedy_formula:{...v.comedy_formula,[key]:e.target.value}}))}/></label>)}
        </fieldset>
        <details className="character-profile-optional"><summary>추가 정보 · 선택</summary>
          <fieldset disabled={disabled||busy} className="character-profile-fields">
            <label>종류<input value={draft.species} maxLength={40} placeholder="예: rabbit" onChange={e=>setDraft(v=>({...v,species:e.target.value}))}/></label>
            <label>이야기의 세계<input value={draft.comedy_formula.world} maxLength={60} onChange={e=>setDraft(v=>({...v,comedy_formula:{...v.comedy_formula,world:e.target.value}}))}/></label>
            <label className="character-profile-wide">고정 스타일 · 영어<input value={draft.style_lock} maxLength={600} placeholder="비워두면 기본 스타일 사용" onChange={e=>setDraft(v=>({...v,style_lock:e.target.value}))}/></label>
          </fieldset>
        </details>
        <details className="character-profile-ai"><summary>AI로 특징 초안 만들기 · 선택 사항</summary>
          <fieldset disabled={disabled||busy}>
            <label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/>선택한 AI에 참조 이미지를 전송하는 유료 분석에 동의합니다.</label>
            <button type="button" disabled={!consent||!available} onClick={()=>void act('analyze')}>이미지로 특징 초안 만들기</button>
            <small>요청별 사용 한도를 적용합니다. 직접 입력하여 무료로 등록할 수도 있습니다.</small>
            {candidates.length>0&&<div className="character-profile-actions">{candidates.map((p,i)=><button type="button" key={i} onClick={()=>setDraft(v=>({...v,name_ko:p.name_ko,personality:p.personality,comedy_formula:p.comedy_formula}))}>{p.name_ko} 선택</button>)}</div>}
          </fieldset>
        </details>
        <details className="character-profile-extra"><summary>조연·대상 시청자</summary><fieldset disabled={disabled||busy}>
          <label>대상 시청자<input value={draft.audience} maxLength={80} onChange={e=>setDraft(v=>({...v,audience:e.target.value}))}/></label>
          <small>조연은 설명만 저장합니다. 등록 캐릭터 여러 명의 동시 출연은 지원하지 않습니다.</small>
          {draft.supporting_cast.map((cast,index)=><div key={index} className="character-profile-cast">
            <label>조연 식별명 · 영문<input value={cast.id} maxLength={40} onChange={e=>setDraft(v=>({...v,supporting_cast:v.supporting_cast.map((c,i)=>i===index?{...c,id:e.target.value}:c)}))}/></label>
            <label>외형 설명 · 영어<textarea rows={2} value={cast.appearance} maxLength={600} onChange={e=>setDraft(v=>({...v,supporting_cast:v.supporting_cast.map((c,i)=>i===index?{...c,appearance:e.target.value}:c)}))}/></label>
            <button type="button" onClick={()=>setDraft(v=>({...v,supporting_cast:v.supporting_cast.filter((_,i)=>i!==index)}))}>조연 제거</button></div>)}
          <button type="button" disabled={draft.supporting_cast.length>=3} onClick={()=>setDraft(v=>({...v,supporting_cast:[...v.supporting_cast,{id:'',appearance:''}]}))}>조연 설명 추가</button>
        </fieldset></details>
        {busy&&<p role="status">처리 중…</p>}
      </form>
    </CharacterModal>}
  </section>;
}
export function CharacterTopics({ profile, model, available, topic, onTopic, csrf, disabled, settings, episodeLimit, jobs, onRefresh, onJob, onBusy }: {
  profile: Item | null; model: string; available: boolean; topic: string; onTopic: (value: string) => void;
  csrf: string; disabled: boolean; settings: Item; episodeLimit: string; jobs: Item[];
  onRefresh: () => Promise<unknown>; onJob: (id: string) => void; onBusy: (value:boolean) => void;
}) {
  const [rows, setRows] = useState<Item[]>([]), [count, setCount] = useState(10);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [consent, setConsent] = useState(false), [csv, setCsv] = useState("");
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [queue, setQueue] = useState<Item | null>(null), [queues, setQueues] = useState<Item[]>([]);
  const [scriptConsent, setScriptConsent] = useState(false), [videoConsent, setVideoConsent] = useState(false);
  const [queueCap, setQueueCap] = useState("");
  const sending = useRef(false);
  useEffect(() => {
    setRows([]); setError(""); setSelectedTopics([]); setQueue(null); let active = true;
    fetch("/api/studio/characters/queues", { credentials: "same-origin" }).then(async r=>r.ok?r.json():{queues:[]})
      .then(data=>{if(active)setQueues(data.queues??[]);}).catch(()=>{});
    if (profile) fetch(`/api/studio/characters/profiles/${profile.id}/topics`, { credentials: "same-origin" })
      .then(async r => { if (!r.ok) throw Error("주제 목록을 읽지 못했습니다."); return r.json(); })
      .then(data => { if (active) setRows(data.topics ?? []); }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [profile?.id]);
  async function act(kind: "generate" | "manual" | "import", value?: Item, status?: string) {
    if (!profile || sending.current || disabled) return;
    sending.current = true; setBusy(true); onBusy(true); setError("");
    try {
      if (kind === "generate" && (!consent || !available)) throw Error("주제 생성의 유료 요청 승인을 확인하세요.");
      const data = await characterCommand(`/api/studio/characters/profiles/${profile.id}/topics/${value ? `${value.id}/status` : kind}`, csrf,
        value ? { status: status ?? "skipped" } : kind === "generate" ?
          { count: String(count), model, consent: "true", request_id: crypto.randomUUID().replaceAll("-", "") } :
          kind === "manual" ? { topic } : { content: csv });
      setRows(data.topics ?? [...rows.filter(r => r.id !== data.id), data]); setConsent(false);
    } catch (e) { setError(e instanceof Error ? e.message : "주제 작업을 확인하세요."); }
    finally { sending.current = false; setBusy(false); onBusy(false); }
  }
  const queueJobs: Item[] = (queue?.rows ?? []).map((row: Item) => jobs.find(j => j.id === row.job_id)).filter(Boolean);
  const quoted = queueJobs.length > 0 && queueJobs.length === queue?.rows?.length && queueJobs.every(j => j.state === "quoted" && j.quote_hash);
  const queueQuote = queueJobs.reduce((sum,j) => sum + Number(j.quote ?? 0), 0);
  async function batch(kind: "scripts" | "approve" | "advance" | "read", identifier?: string) {
    if (!profile || sending.current || disabled) return;
    sending.current = true; setBusy(true); onBusy(true); setError("");
    try {
      if (kind === "scripts") {
        if (!scriptConsent || !available || selectedTopics.length === 0) throw Error("선택한 대본 요청의 유료 사용을 승인하세요.");
        const created = await characterCommand("/api/studio/characters/queues/create", csrf,
          { character_id: profile.id, topic_ids: JSON.stringify(selectedTopics), settings: JSON.stringify(settings),
            episode_limit: episodeLimit, request_id: crypto.randomUUID().replaceAll("-", "") });
        setQueue(created);
        const result = await characterCommand(`/api/studio/characters/queues/${created.id}/scripts`, csrf, { consent: "true" });
        setQueue(result); setScriptConsent(false);
      } else if (kind === "approve" && queue) {
        if (!quoted || !videoConsent || !(Number(queueCap) >= queueQuote)) throw Error("각 대본의 검토·공식 견적과 전체 승인 금액을 확인하세요.");
        const approved = await characterCommand(`/api/studio/characters/queues/${queue.id}/approve-videos`, csrf,
          { approvals: JSON.stringify(queueJobs.map(j=>({job_id:j.id,quote_hash:j.quote_hash}))), max_total_usd: queueCap, consent: "true" });
        setQueue(approved); setVideoConsent(false);
        const result = await characterCommand(`/api/studio/characters/queues/${queue.id}/advance`, csrf, { consent: "true" });
        setQueue(result);
      } else if (kind === "advance" && queue) {
        setQueue(await characterCommand(`/api/studio/characters/queues/${queue.id}/advance`, csrf, { consent: "true" }));
      } else if (kind === "read" && identifier) {
        const response = await fetch(`/api/studio/characters/queues/${identifier}`, { credentials: "same-origin" });
        if (!response.ok) throw Error("대기열을 읽지 못했습니다."); setQueue(await response.json());
      }
      await onRefresh();
    } catch(e) {setError(e instanceof Error?e.message:"대기열을 중단했습니다. 자동 재시도하지 않습니다.");}
    finally {sending.current=false;setBusy(false);onBusy(false);}
  }
  return <details className="character-topic-tools"><summary>주제 자동 생성·기록</summary>
    <fieldset disabled={disabled || busy || !profile}>
      <div className="character-topic-create">
        <label>주제 개수<input type="number" min={1} max={50} value={count} onChange={e=>setCount(Number(e.target.value))} /></label>
        <button disabled={!consent || !available} onClick={()=>void act("generate")}>주제 자동 생성</button>
      </div>
      <label className="check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)} />주제 생성 유료 요청에 동의합니다.</label>
      <button className="character-topic-save" disabled={!topic.trim()} onClick={()=>void act("manual")}>입력한 주제 저장</button>
      <div className="character-topic-list">{rows.map(row=><div key={row.id}>
        <label className="check"><input type="checkbox" aria-label={`${row.topic} 대기열 선택`} checked={selectedTopics.includes(row.id)}
          onChange={e=>setSelectedTopics(v=>e.target.checked?[...v,row.id]:v.filter(id=>id!==row.id))} />
        <button onClick={()=>onTopic(row.topic)}>{row.topic}</button></label>
        <select aria-label={`${row.topic} 상태`} value={row.status} onChange={e=>void act("manual",row,e.target.value)}>
          <option value="new">미사용</option><option value="scripted">대본 작성</option><option value="produced">게시 완료</option><option value="skipped">보류</option>
        </select>
      </div>)}</div>
      <details className="character-batch"><summary>선택 주제 일괄 제작 ({selectedTopics.length}개)</summary>
        <p>편당 한도 US${episodeLimit} · 선택한 {selectedTopics.length}편 상한 US${(Number(episodeLimit||0)*selectedTopics.length).toFixed(2)}</p>
        <label className="check"><input type="checkbox" checked={scriptConsent} onChange={e=>setScriptConsent(e.target.checked)} />
          선택한 {selectedTopics.length}편의 유료 대본 생성에 동의합니다.</label>
        <button disabled={!scriptConsent||!available||!selectedTopics.length} onClick={()=>void batch("scripts")}>선택한 주제 대본 생성</button>
        <label>저장된 대기열<select value={queue?.id??""} onChange={e=>{if(e.target.value)void batch("read",e.target.value);}}>
          <option value="">대기열 선택</option>{queues.filter(q=>q.character_id===profile?.id).map(q=><option key={q.id} value={q.id}>{q.created_at??q.id} · {q.rows?.length??0}편</option>)}
        </select></label>
        {queue && <div><p role="status">대기열 상태: {queue.state}</p>
          {(queue.rows??[]).map((row:Item)=><button key={row.job_id} onClick={()=>onJob(row.job_id)}>대본 검토 · {jobs.find(j=>j.id===row.job_id)?.topic??row.topic_id}</button>)}
          <p>공식 견적 합계: {quoted?`US$${queueQuote.toFixed(2)}`:"모든 대본을 검토하고 견적을 받아야 합니다."}</p>
          <label>이번 대기열 영상 승인 한도 (USD)<input inputMode="decimal" value={queueCap} onChange={e=>setQueueCap(e.target.value)}/></label>
          <label className="check"><input type="checkbox" checked={videoConsent} onChange={e=>setVideoConsent(e.target.checked)} />각 대본·견적을 검토했고 합계 비용에 동의합니다.</label>
          <button disabled={!quoted||!videoConsent||!(Number(queueCap)>=queueQuote)} onClick={()=>void batch("approve")}>견적 승인 후 순차 영상 생성</button>
          <button onClick={()=>void batch("advance")}>승인된 대기열 진행 확인</button>
          <small>실패·결과 불명에서 중단합니다. 완료 장면을 다시 요청하지 않으며 최종 합성은 별도 검토 후 실행합니다.</small>
        </div>}
      </details>
      <details className="character-topic-import"><summary>CSV 주제 가져오기</summary><label>번호, 카테고리, 주제<textarea value={csv} maxLength={48000} onChange={e=>setCsv(e.target.value)} /></label>
        <button disabled={!csv.trim()} onClick={()=>void act("import")}>CSV 가져오기</button></details>
    </fieldset>
    {!profile && <small>등록된 캐릭터를 먼저 선택하세요.</small>}
    {busy && <p role="status">주제 처리 중…</p>}{error && <p role="alert">{error}</p>}
  </details>;
}

export function CharacterScriptEditor({ job, csrf, disabled, onRefresh, onDirty }: {
  job: Item; csrf: string; disabled: boolean; onRefresh: () => Promise<unknown>; onDirty: (dirty: boolean) => void;
}) {
  const [script,setScript]=useState<Item>(()=>structuredClone(job.story));
  const [advanced,setAdvanced]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState("");
  const sending=useRef(false);
  useEffect(()=>{setScript(structuredClone(job.story));setError("");},[job.id,job.script_hash]);
  useEffect(()=>{onDirty(JSON.stringify(script)!==JSON.stringify(job.story));},[script,job.story,onDirty]);
  useEffect(()=>()=>onDirty(false),[onDirty]);
  function scene(index:number,key:string,value:unknown) {
    setScript(v=>({...v,scenes:v.scenes.map((row:Item,i:number)=>i===index?{...row,[key]:value}:row)}));
  }
  async function save() {
    if(sending.current || disabled)return;
    sending.current=true;setBusy(true);setError("");
    try {await characterCommand(`/api/studio/characters/${job.id}/script`,csrf,
      {script:JSON.stringify(script),expected_hash:job.script_hash});await onRefresh();}
    catch(e){setError(e instanceof Error?e.message:"대본 저장을 확인하세요.");}
    finally {sending.current=false;setBusy(false);}
  }
  return <details className="character-script-editor"><summary>장면 연출·자막·효과음 검토</summary>
    <dl>{([["situation","상황"],["escalation","일의 전개"],["reaction","캐릭터 반응"],["punchline","결말"]] as const).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{script.plan?.[key]}</dd></div>)}</dl>
    <p>{job.playback_seconds != null ? `편집 후 ${Number(job.playback_seconds).toFixed(2)}초 · ` : ""}최종 {job.duration}초</p>
    <label className="check"><input type="checkbox" checked={advanced} onChange={e=>setAdvanced(e.target.checked)} />고급 편집 · 행동·카메라</label>
    <fieldset disabled={disabled||busy||!["script_review","quoted"].includes(job.state)}>
      <label>첫 자막<input value={script.hook_caption??""} maxLength={20} onChange={e=>setScript(v=>({...v,hook_caption:e.target.value}))}/></label>
      {script.scenes.map((s:Item,i:number)=><section key={i}>
        <strong>장면 {s.no} · {s.seconds}초 · {s.continuity==="continue"?`${s.from}번에서 이어짐`:"새 컷"}</strong>
        <p>속도 {s.speed}{s.speed==="fast"?` (${s.fast_intensity})`:""} · 끝 정지 {s.freeze_end}</p>
        <small>카메라: {s.camera}<br/>환경음: {s.sound||"없음"}</small>
        <label>상황 자막<input value={s.caption} maxLength={20} onChange={e=>scene(i,"caption",e.target.value)}/></label>
        {advanced&&<><label>행동 · 영어<textarea value={s.action} maxLength={300} onChange={e=>scene(i,"action",e.target.value)}/></label>
          <label>카메라 · 영어<textarea value={s.camera} maxLength={120} onChange={e=>scene(i,"camera",e.target.value)}/></label></>}
        {(s.sfx??[]).map((fx:Item,n:number)=><div className="character-profile-actions" key={n}>
          <select aria-label={`장면 ${i+1} 효과음 ${n+1}`} value={fx.key} onChange={e=>scene(i,"sfx",s.sfx.map((row:Item,j:number)=>j===n?{...row,key:e.target.value}:row))}>
            {(job.sfx_keys??[]).map((key:string)=><option key={key}>{key}</option>)}
          </select>
          <select aria-label={`장면 ${i+1} 효과음 ${n+1} 위치`} value={fx.at} onChange={e=>scene(i,"sfx",s.sfx.map((row:Item,j:number)=>j===n?{...row,at:e.target.value}:row))}>
            <option value="start">장면 시작</option><option value="end">정지 시작</option>
          </select>
          <button onClick={()=>scene(i,"sfx",s.sfx.filter((_:Item,j:number)=>j!==n))}>효과음 제거</button>
        </div>)}
        {(s.sfx??[]).length<2&&<select aria-label={`장면 ${i+1} 효과음 추가`} value="" onChange={e=>{if(e.target.value)scene(i,"sfx",[...(s.sfx??[]),{at:"end",key:e.target.value}]);}}>
          <option value="">끝 효과음 추가</option>{(job.sfx_keys??[]).map((key:string)=><option key={key}>{key}</option>)}
        </select>}
      </section>)}
      <label>끝 자막<input value={script.end_caption??""} maxLength={20} onChange={e=>setScript(v=>({...v,end_caption:e.target.value}))}/></label>
      <button onClick={()=>void save()}>변경 저장 · 승인 다시 받기</button>
    </fieldset>
    <details><summary>업로드 정보</summary><p>{script.upload?.title}</p><p>{script.upload?.description}</p><p>{script.upload?.hashtags?.join(" ")}</p></details>
    {error&&<p role="alert">{error}</p>}
  </details>;
}


export function CharacterRegeneration({job,csrf,disabled,onRefresh,onBusy}:{job:Item;csrf:string;disabled:boolean;onRefresh:()=>Promise<unknown>;onBusy:(value:boolean)=>void}) {
  const [position,setPosition]=useState(1),[quoteConsent,setQuoteConsent]=useState(false),[paidConsent,setPaidConsent]=useState(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");const sending=useRef(false);
  useEffect(()=>{setPaidConsent(false);setQuoteConsent(false);setError("");},[job.id,job.regeneration_hash]);
  async function run(kind:"quote"|"submit"|"cancel") {
    if(sending.current||disabled||(kind!=="cancel"&&!(kind==="quote"?quoteConsent:paidConsent)))return;
    sending.current=true;setBusy(true);onBusy(true);setError("");
    try {await characterCommand(`/api/studio/characters/${job.id}/regeneration/${kind}`,csrf,
      kind==="quote"?{position:String(position),consent:"true"}:{quote_hash:job.regeneration_hash,consent:"true"});
      setPaidConsent(false);setQuoteConsent(false);await onRefresh();}
    catch(e){setError(e instanceof Error?e.message:"재생성 상태를 확인하세요. 자동 재요청하지 않습니다.");}
    finally {sending.current=false;setBusy(false);onBusy(false);}
  }
  if(job.automation_version!==1||!["clips_review","completed","regeneration_quoted"].includes(job.state))return null;
  return <details className="character-regeneration"><summary>선택 장면 다시 만들기</summary>
    <fieldset disabled={disabled||busy}>
    {job.state!=="regeneration_quoted"?<>
      <label>대상 장면<select value={position} onChange={e=>setPosition(Number(e.target.value))}>
        {(job.scenes??[]).map((s:Item)=><option key={s.position} value={s.position}>장면 {s.position}</option>)}
      </select></label>
      <p>이 장면에서 이어지는 장면도 다시 만듭니다. 기존 영상은 보관되며 새 견적을 승인하기 전에는 생성하지 않습니다.</p>
      <label className="check"><input type="checkbox" checked={quoteConsent} onChange={e=>setQuoteConsent(e.target.checked)}/>대상 장면·이어지는 장면의 견적 조회에 동의합니다.</label>
      <button disabled={!quoteConsent} onClick={()=>void run("quote")}>재생성 견적 확인</button>
    </>:<>
      <p>다시 만들 장면: {job.regeneration?.affected?.join(", ")} · 이번 견적 US${job.regeneration?.quote_total_usd}</p>
      <p>이번 회차 기존 비용·보류액 US${job.regeneration?.exposure_usd} · 요청 후 합계 US${job.regeneration?.total_after_usd}</p>
      <label className="check"><input type="checkbox" checked={paidConsent} onChange={e=>setPaidConsent(e.target.checked)}/>대상 장면과 이번 유료 견적을 검토하고 승인합니다.</label>
      <button disabled={!paidConsent} onClick={()=>void run("submit")}>승인한 장면만 다시 생성</button>
      <button onClick={()=>void run("cancel")}>재생성 취소 · 기존 영상 유지</button>
    </>}
    </fieldset>{error&&<p role="alert">{error}</p>}
  </details>;
}
