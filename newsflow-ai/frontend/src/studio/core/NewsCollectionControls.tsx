import {useEffect, useRef, useState} from "react";
import {LoaderCircle, RefreshCw} from "lucide-react";
import {ActionButton, type Controller} from "./shared";
import "./news-collection-controls.css";

type Collection = {status:string; run_id:number|null; added:number; succeeded:number; failed:number};
type Phase = "" | "requesting" | "accepted" | "unknown";
const states = new Set(["idle", "running", "success", "partial", "failed", "interrupted", "empty"]);
const count = (v:unknown) => typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? v : 0;

export function NewsCollectionControls({c,method,onMethodChange}:{c:Controller;method:string;onMethodChange:(v:string)=>void}) {
  const [rssSource,setRssSource]=useState(method === "popular" ? "popular" : "rss");
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
    if(next==="accepted")void c.load();
  }
  const pending=phase!==""||collection?.status==="running";
  const busy=pending&&!error&&phase!=="unknown";
  const labels:Record<string,string>={success:"최근 수집 완료",partial:"일부 출처 수집 완료",failed:"수집 실패",interrupted:"이전 수집 중단",empty:"활성 RSS 출처 없음"};
  const message=error || (phase==="unknown" ? "수집 요청 결과 확인 필요" : phase==="requesting" ? "수집 요청 전송 중…"
    : phase==="accepted" ? "수집 상태 확인 중…" : collection?.status==="running" ? "뉴스 수집 중…"
    : method==="serpapi" ? c.view?.catalog.serpapi?.last?.message??"" : labels[collection?.status??""]??"");
  return <section className="news-collection-controls" aria-label="뉴스 수집">
    <div className="news-collection-controls-head">
      <label><span>뉴스 수집</span><select aria-label="뉴스 수집 방식" value={method === "serpapi" ? "serpapi" : "rss"} disabled={pending}
        onChange={e=>onMethodChange(e.target.value === "rss" ? rssSource : "serpapi")}>
        <option value="rss">RSS 수집</option><option value="serpapi">SerpApi 수집</option>
      </select></label>
      {method==="rss" ? <ActionButton c={c} id="routes_collect" disabled={pending}
        context={{__collectionProgress:requestState}}>수집 시작</ActionButton>
        : method==="popular" ? <ActionButton c={c} id="curation_refresh" disabled={pending}
          context={{__collectionProgress:requestState}}>수집 시작</ActionButton>
        : <ActionButton c={c} id="serpapi_collect" disabled={pending || !c.view?.catalog.serpapi?.canRequest}
            context={{__collectionProgress:requestState}}>
            수집 시작
          </ActionButton>}
    </div>
    {method!=="serpapi"&&<label className="news-collection-scope"><span>RSS 출처</span>
      <select aria-label="RSS 출처" value={method} disabled={pending}
        onChange={e=>{setRssSource(e.target.value);onMethodChange(e.target.value);}}>
        <option value="rss">등록한 출처</option><option value="popular">분야별 뉴스</option>
      </select>
    </label>}
    <small className="news-collection-provider-info">{method==="rss"?"등록 공개 RSS · API 키 불필요":method==="popular"?"Google News 공개 RSS · 분야·기간 선택":
      c.view?.catalog.serpapi?.keyConfigured?"SerpApi · 키 등록됨":"SerpApi · API 키 미등록"}</small>
    {method==="serpapi"&&<a className="news-collection-settings" href="/studio/settings?tab=sources">설정·관리에서 수집 설정</a>}
    {method==="serpapi"&&!c.view?.catalog.serpapi?.canRequest&&<small>설정·관리에서 키 등록과 사용 승인을 확인하세요.</small>}
    {(c.view?.catalog.categoryCollection ?? []).length > 0 && <ul className="news-category-counts" aria-label="최근 분야별 수집 결과">
      {c.view?.catalog.categoryCollection.map((row: any) => <li key={row.category}>{row.category} · {row.status === "success"
        ? `수집 ${row.collected}건 · 목록 대상 ${row.kept}건`
        : row.status === "pending" ? "요청하지 않음 · 앞선 분야 수집 중단"
        : row.status === "unknown" ? "응답 확인 필요 · 기사 수 미확인"
        : `수집 실패 · ${row.collected > 0 ? `저장 ${row.collected}건` : "기사 수 미확인"}`}{row.skipped_items > 0 && ` · 형식 확인 불가 ${row.skipped_items}건 제외`}</li>)}
    </ul>}
    {c.view?.catalog.newsCollectionSummary && <div className="news-collection-summary">
      <p>이번 수집 목록 대상 {c.view.catalog.newsCollectionSummary.kept}건 · 분야 간 중복 {c.view.catalog.newsCollectionSummary.overlap}건</p>
      <small>분야별 숫자는 수집 출처 기준이며, 기사 목록은 중복을 합친 뒤 저장된 기사 분야로 나눕니다.</small>
      {c.view.catalog.newsCollectionSummary.unknownTime > 0 && <small>발행 시각 미확인 {c.view.catalog.newsCollectionSummary.unknownTime}건 포함</small>}
      {c.view.catalog.newsCollectionSummary.olderIncluded > 0 && <small>기간 내 기사 부족으로 이전 기사 {c.view.catalog.newsCollectionSummary.olderIncluded}건 포함</small>}
    </div>}
    {message&&<div className="news-collection-progress" role="status" aria-live="polite">
      <div>{busy&&<LoaderCircle className="spin" size={16}/>}<strong>{message}</strong>
        {!busy&&<button type="button" aria-label="수집 상태 새로고침" onClick={()=>setRefresh(n=>n+1)}><RefreshCw size={14}/></button>}</div>
      {busy&&<progress aria-label="뉴스 수집 진행 중"/>}
      {method==="rss"&&!busy&&!error&&phase!=="unknown"&&collection&&["success","partial","failed"].includes(collection.status)&&
        <small>신규 {collection.added}건 · 출처 성공 {collection.succeeded}개 · 실패 {collection.failed}개</small>}
    </div>}
  </section>;
}
