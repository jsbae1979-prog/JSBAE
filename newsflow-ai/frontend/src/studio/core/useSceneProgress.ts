import {useEffect,useRef,useState} from "react";
import {actions,type Item,type View} from "../contracts";
import {submitOriginal} from "../CommandDialog";

const INTERVAL=10_000;
const stopped=new Set(["unknown","not_sent","failed","nsfw","canceled","dependency_failed","dependency_quote_changed"]);
export function sceneProgress(job:Item|undefined) {
  const rows:Item[]=Array.isArray(job?.scenes)?job.scenes:[];
  const done=rows.filter(row=>row.state==="downloaded").length;
  const failed=rows.some(row=>stopped.has(row.state));
  return {total:rows.length,done,percent:rows.length?Math.floor(done*100/rows.length):0,
    failed,eligible:job?.automation_version===1&&job?.state==="generating"&&!failed&&rows.length>0};
}

export function useSceneProgress({job,view,enabled,blocked,readError,load}:{
  job:Item|undefined;view:View|null;enabled:boolean;blocked:boolean;readError:string;load:()=>Promise<void>;
}) {
  const [checking,setChecking]=useState(false),[error,setError]=useState("");
  const [resumeKey,setResumeKey]=useState(0);
  const latest=useRef({job,view,enabled,blocked,readError,load});
  latest.current={job,view,enabled,blocked,readError,load};
  const inFlight=useRef(false);
  const eligible=sceneProgress(job).eligible;
  useEffect(()=>{setError("");},[job?.id]);
  useEffect(()=>{
    if(!enabled||!eligible)return;
    let disposed=false;let timer:ReturnType<typeof setTimeout>;
    const schedule=()=>{if(!disposed)timer=setTimeout(()=>void tick(),INTERVAL);};
    async function tick() {
      const value=latest.current;
      if(disposed||!value.enabled||!sceneProgress(value.job).eligible)return;
      if(value.readError){setError("진행 정보를 읽지 못해 자동 확인을 멈췄습니다.");return;}
      if(value.blocked||inFlight.current){schedule();return;}
      const action=actions.find(row=>row.id==="character_act_check");
      if(!action||action.unsupported||!value.view?.commandsAvailable||!value.view.csrfToken)return;
      inFlight.current=true;setChecking(true);
      try {
        // Only the existing authenticated check route. Never submit, retry, quote
        // or render here. The backend owns already-approved continuation claims.
        await submitOriginal(action,{job_id:value.job!.id,consent:true},value.view,{});
        if(!disposed)await value.load();
      } catch {
        if(!disposed){
          setError("진행 확인을 멈췄습니다. 저장된 장면 상태를 확인하세요. 자동 재요청하지 않습니다.");
          await value.load();
        }
        return;
      } finally {inFlight.current=false;setChecking(false);}
      schedule();
    }
    schedule();
    // An in-flight check is never aborted/replayed on navigation or refresh.
    return()=>{disposed=true;clearTimeout(timer);};
  },[job?.id,eligible,enabled,resumeKey]);
  return {checking,error,active:enabled&&eligible&&!error,
    resume:()=>{setError("");setResumeKey(value=>value+1);},...sceneProgress(job)};
}
