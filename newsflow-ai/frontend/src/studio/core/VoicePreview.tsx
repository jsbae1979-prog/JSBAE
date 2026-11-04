import {useEffect,useRef,useState} from "react";
import {Headphones,LoaderCircle} from "lucide-react";
import type {Item} from "../contracts";
import type {Controller} from "./shared";

function sampleUrl(value:unknown){
  return typeof value==="string" && /^\/(?:voices\/preview\/preview-[a-f0-9]{32}\.wav|video\/tts\/voices\/[A-Za-z0-9_-]+\/sample)$/.test(value)?value:null;
}

export function VoicePreview({c,voice,elevenVoiceId}:{c:Controller;voice:string;elevenVoiceId?:string}){
  const [url,setUrl]=useState<string|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  const sending=useRef(false), player=useRef<HTMLAudioElement>(null), generation=useRef(0);
  const config=c.view?.catalog.newsVideo;
  const eleven=voice==="elevenlabs";
  const selectedId=elevenVoiceId??String(config?.ttsVoiceId??"");
  const elevenOption=(c.view?.catalog.elevenVoices??[]).find((v:Item)=>v.id===selectedId);
  const sample=(c.view?.collections.audioSamples??[]).find(s=>eleven?s.provider==="elevenlabs"&&s.id===selectedId:s.provider==="windows"&&s.voice===voice);
  const cached=sampleUrl(sample?.mediaUrl);
  const muted=voice==="offline-silence";
  const supported=!muted&&!voice.startsWith("supertonic:")&&(!eleven||!!cached||elevenOption?.hasSample===true);
  useEffect(()=>{++generation.current;player.current?.pause();setUrl(null);setError("");},[voice,selectedId]);
  async function preview(){
    if(sending.current||!supported)return;
    const current=generation.current;
    setError("");
    if(url){if(player.current){player.current.currentTime=0;void player.current.play().catch(()=>setError("재생 버튼을 눌러 미리 들어 주세요."));}return;}
    if(cached){setUrl(cached);return;}
    sending.current=true;setBusy(true);
    try{
      const path=eleven?"/video/tts/voices/preview":"/voices/preview";
      const defaults=c.view?.formDefaults?.voice_preview??{};
      const fields:Record<string,string>=eleven?{voice_id:selectedId,sample_consent:"true"}:
        {voice,rate:String(defaults.rate??"0"),pause_ms:String(defaults.pause_ms??"250")};
      const body=new URLSearchParams({...fields,csrf_token:c.view?.csrfToken??""});
      const response=await fetch(path,{method:"POST",credentials:"same-origin",redirect:"manual",headers:{Accept:"application/json"},body});
      if(!response.ok||!response.headers.get("Content-Type")?.includes("application/json"))throw Error();
      const result=await response.json();
      const expected=eleven?`/video/tts/voices/${selectedId}/sample`:null;
      if(typeof result.mediaUrl!=="string" || (eleven?result.mediaUrl!==expected:!/^\/voices\/preview\/preview-[a-f0-9]{32}\.wav$/.test(result.mediaUrl)))throw Error();
      if(generation.current===current)setUrl(sampleUrl(result.mediaUrl));
    }catch{if(generation.current===current)setError("미리듣기를 준비하지 못했습니다. 음성 설정을 확인하세요.");}
    finally{sending.current=false;setBusy(false);}
  }
  return <div className="news-voice-preview" aria-label="선택 음성 미리듣기">
    <button type="button" onClick={()=>void preview()} disabled={busy||!supported}>
      {busy?<LoaderCircle className="spin" size={15}/>:<Headphones size={15}/>}{busy?"미리듣기 준비 중…":"목소리 미리듣기"}
    </button>
    {muted&&<small>목소리를 선택하면 미리 들을 수 있습니다.</small>}
    {eleven&&supported&&<small>ElevenLabs {elevenOption?.sampleLabel??"공식 음성 샘플"}</small>}
    {!muted&&!supported&&<small>{eleven?"이 목소리는 공급사 미리듣기 샘플이 없습니다.":"설정에서 미리듣기 가능한 목소리를 확인하세요."}</small>}
    {url&&<audio key={url} ref={player} src={url} controls autoPlay preload="none" aria-label="선택한 목소리 샘플"
      onError={()=>setError("샘플을 재생하지 못했습니다.")}/>}
    {error&&<small role="status">{error}</small>}
  </div>;
}
