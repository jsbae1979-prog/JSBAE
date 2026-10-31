import {useEffect, useRef, useState} from "react";
import {LoaderCircle, RefreshCw} from "lucide-react";
import {ActionButton, type Controller} from "./shared";
import "./news-collection-controls.css";

type Collection = {status:string; run_id:number|null; added:number; succeeded:number; failed:number};
type Phase = "" | "requesting" | "accepted" | "unknown";
const states = new Set(["idle", "running", "success", "partial", "failed", "interrupted", "empty"]);
const count = (v:unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : 0;

export function NewsCollectionControls({c}:{c:Controller}) {
  const [method,setMethod]=useState("rss");
  const [collection,setCollection]=useState<Collection|null>(null);
  const [phase,setPhase]=useState<Phase>("");
  const [error,setError]=useState("");
  const [refresh,setRefresh]=useState(0);
  const last=useRef<Collection|null>(null);
  const baseline=useRef<number|null>(null);
  useEffect(()=>{
    let cancelled=false, timer:ReturnType<typeof setTimeout>|undefined;
    const controller=new AbortController();
    async function readStatus(){
      const timeout=setTimeout(()=>controller.abort(),8000);
      try {
        const response=await fetch("/api/collection",{credentials:"same-origin",cache:"no-store",signal:controller.signal});
        if(!response.ok)throw Error();
        const data=await response.json();
        if(!states.has(data.status) || (data.run_id!==null && (!Number.isSafeInteger(data.run_id)||data.run_id<1)))throw Error();
        if(cancelled)return;
        const next={status:data.status,run_id:data.run_id,added:count(data.added),succeeded:count(data.succeeded),failed:count(data.failed)};
        const finished=last.current?.status==="running" && next.status!=="running";
        last.current=next;setCollection(next);setError("");
        setPhase(p=>p==="accepted" || (p==="unknown"&&next.run_id!==baseline.current) ? "" : p);
        if(next.status==="running")timer=setTimeout(readStatus,1500);
        else if(finished)void c.load();
      } catch {
        if(!cancelled)setError("수집 상태를 확인하지 못했습니다.");
      } finally {clearTimeout(timeout);}
    }
    void readStatus();
    return ()=>{cancelled=true;controller.abort();clearTimeout(timer);};
  },[c.view,refresh]);
  function requestState(next:Phase){
    if(next==="requesting")baseline.current=last.current?.run_id??null;
    setPhase(next);
    if(next==="accepted"||next==="unknown")setRefresh(n=>n+1);
  }
  const pending=phase!==""||collection?.status==="running";
  const busy=pending&&!error&&phase!=="unknown";
  const labels:Record<string,string>={success:"최근 수집 완료",partial:"일부 출처 수집 완료",failed:"수집 실패",interrupted:"이전 수집 중단",empty:"활성 RSS 출처 없음"};
  const message=error || (phase==="unknown" ? "수집 요청 결과 확인 필요" : phase==="requesting" ? "수집 요청 전송 중…"
    : phase==="accepted" ? "수집 상태 확인 중…" : collection?.status==="running" ? "뉴스 수집 중…"
    : labels[collection?.status??""]??"");
  return <section className="news-collection-controls" aria-label="뉴스 수집">
    <div className="news-collection-controls-head">
      <label><span>뉴스 수집</span><select aria-label="뉴스 수집 방식" value={method} disabled={pending}
        onChange={e=>setMethod(e.target.value)}>
        <option value="rss">등록 RSS</option><option value="serpapi">SerpApi</option>
      </select></label>
      {method==="rss" ? <ActionButton c={c} id="routes_collect" disabled={pending}
        context={{__collectionProgress:requestState}}>등록 RSS 수집 · 확인</ActionButton>
        : <ActionButton c={c} id="serpapi_settings" disabled={!c.view?.catalog.serpapi?.registrationAvailable}>
            SerpApi 키·수집 설정
          </ActionButton>}
    </div>
    {message&&<div className="news-collection-progress" role="status" aria-live="polite">
      <div>{busy&&<LoaderCircle className="spin" size={16}/>}<strong>{message}</strong>
        {!busy&&<button type="button" aria-label="수집 상태 새로고침" onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={14}/></button>}</div>
      {busy&&<progress aria-label="뉴스 수집 진행 중"/>}
      {!busy&&!error&&phase!=="unknown"&&collection&&["success","partial","failed"].includes(collection.status)&&
        <small>신규 {collection.added}건 · 출처 성공 {collection.succeeded}개 · 실패 {collection.failed}개</small>}
    </div>}
  </section>;
}
