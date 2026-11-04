import {useEffect,useState} from 'react';

/** Progress is observed state, never a simulated completion percentage. */
export default function PrecisionActivity({active,phase,started,completed,total,failed,unknown,candidate,connectionIssue}:{
  active:boolean;phase:'story'|'images';started:number;completed:number;total:number;
  failed:boolean;unknown:boolean;candidate:boolean;connectionIssue:string;
}) {
  const [now,setNow]=useState(Date.now());
  useEffect(()=>{if(!active)return;setNow(Date.now());const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[active,started]);
  if(!active&&!failed)return null;
  const seconds=Number.isFinite(started)&&started>0?Math.max(0,Math.floor((now-started)/1000)):0;
  const title=failed?(unknown?'스토리 결과 확인 필요':'스토리 응답 검토 필요'):phase==='story'?'스토리 생성 중':'장면 이미지 생성 중';
  return <div className={`precision-activity${failed?' is-failed':''}`} role="status" aria-label="제작 진행 상태" aria-live="polite">
    <div className="precision-activity-heading"><strong>{active&&<span className="precision-spinner" aria-hidden="true"/>}{title}</strong>
      {active&&<time aria-live="off" aria-label="경과 시간">{Math.floor(seconds/60)}분 {seconds%60}초</time>}</div>
    {active?<>
      {phase==='story'?<><progress aria-label="스토리 응답 대기"/><p>AI 응답을 기다린 뒤 장면 구성과 연결을 검사합니다.</p></>:
        <><progress aria-label="장면 이미지 완료 수" value={completed} max={total}/><p>{completed}/{total}장 저장 완료 · 나머지 이미지 응답 대기 중</p></>}
      {seconds>=60&&<small>응답이 평소보다 오래 걸리고 있습니다. 추가 생성 요청은 보내지 않습니다.</small>}
      {connectionIssue&&<p role="alert">{connectionIssue}</p>}
    </>:<p>{unknown?'요청 결과를 아직 확인하지 못했습니다. 기록을 보존했으며 다시 전송하지 않았습니다.':candidate?
      'AI 응답은 보관됐지만 장면 형식 검사를 통과하지 못했습니다. 보관된 응답을 무료로 검토·수정할 수 있습니다.':
      '스토리 생성을 완료하지 못했습니다. 기록을 보존했으며 다시 전송하지 않았습니다.'}</p>}
  </div>;
}
