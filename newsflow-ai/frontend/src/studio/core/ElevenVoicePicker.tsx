import {useEffect,useRef,useState} from "react";
import type {Item} from "../contracts";
import type {Controller} from "./shared";
import {VoicePreview} from "./VoicePreview";

export function ElevenVoicePicker({c,onReady}:{c:Controller;onReady:(ready:boolean)=>void}){
  const voices:Item[]=c.view?.catalog.elevenVoices??[];
  const catalog=c.view?.catalog.elevenVoiceCatalog;
  const saved=String(c.view?.catalog.newsVideo?.ttsVoiceId??"");
  const [selected,setSelected]=useState(saved),[query,setQuery]=useState("");
  const [pending,setPending]=useState(""),[error,setError]=useState("");
  const sending=useRef(false);
  useEffect(()=>{setSelected(saved);},[saved]);
  const known=voices.some(v=>v.id===selected);
  useEffect(()=>{onReady(!!saved&&selected===saved&&known&&!pending);},[saved,selected,known,pending,onReady]);
  const filtered=voices.filter(v=>`${v.label} ${v.id}`.toLowerCase().includes(query.toLowerCase()));
  async function command(kind:"load"|"select",more=false){
    if(sending.current)return;
    sending.current=true;setPending(kind);setError("");
    try{
      const fields:Record<string,string>=kind==="load"?{scope:"all",consent:"true",more:String(more)}:{voice_id:selected,use_for_news:"true"};
      const body=new URLSearchParams({...fields,csrf_token:c.view?.csrfToken??""});
      const response=await fetch(`/video/tts/voices/${kind}`,{method:"POST",credentials:"same-origin",redirect:"manual",headers:{Accept:"application/json"},body});
      if(!response.ok||!response.headers.get("Content-Type")?.includes("application/json"))throw Error();
      const result=await response.json();
      if(kind==="select"?result.voiceId!==selected:result.loaded!==true)throw Error();
      await c.load();
    }catch{setError(kind==="load"?"목소리 목록을 불러오지 못했습니다. API 키·목록 조회 권한을 확인하세요.":"목소리 저장 결과를 확인하지 못했습니다. 새로고침해 선택값을 확인하세요.");}
    finally{sending.current=false;setPending("");}
  }
  return <section className="eleven-voice-picker" aria-label="ElevenLabs 목소리 선택">
    <div className="eleven-voice-tools">
      <strong>ElevenLabs 목소리</strong>
      <button type="button" disabled={!!pending||!catalog?.keyConfigured} onClick={()=>void command("load")}>
        {pending==="load"?"목록 불러오는 중…":"목소리 목록 불러오기"}</button>
    </div>
    {voices.length>0?<>
      <input type="search" aria-label="목소리 검색" placeholder="목소리 검색" value={query} onChange={e=>setQuery(e.target.value)}/>
      <select aria-label="ElevenLabs 목소리" value={selected} disabled={!!pending} onChange={e=>{setSelected(e.target.value);setError("");}}>
        <option value="" disabled>목소리를 선택하세요</option>
        {selected&&!filtered.some(v=>v.id===selected)&&<option value={selected}>{voices.find(v=>v.id===selected)?.label??"기존 선택"}</option>}
        {filtered.map(v=><option key={v.id} value={v.id}>{v.label}{!v.hasSample?" · 미리듣기 없음":""}</option>)}
      </select>
      <VoicePreview c={c} voice="elevenlabs" elevenVoiceId={selected}/>
      <button type="button" disabled={!known||selected===saved||!!pending} onClick={()=>void command("select")}>
        {pending==="select"?"목소리 저장 중…":selected===saved&&known?"사용 중인 목소리":"이 목소리 사용"}</button>
      {catalog?.hasMore&&<button type="button" disabled={!!pending||voices.length>=1000} onClick={()=>void command("load",catalog.scope==="all")}>목소리 더 불러오기</button>}
    </>:<small>{catalog?.keyConfigured?"목록을 불러온 뒤 각 목소리를 미리 듣고 선택하세요.":"설정에서 ElevenLabs API 키를 등록하세요."}</small>}
    {error&&<small role="status">{error}</small>}
  </section>;
}
