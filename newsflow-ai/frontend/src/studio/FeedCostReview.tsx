import {useEffect,useState} from 'react';
import type {Item} from './contracts';

export default function FeedCostReview({batch,busy,onSave,onRefresh}:{batch:Item;busy:boolean;onSave:(data:Item)=>void;onRefresh:()=>void}) {
  const [limit,setLimit]=useState('');
  const cost=batch.costReview;
  useEffect(()=>setLimit(cost?.approvedLimitUsd??''),[batch.id,cost?.approvedLimitUsd]);
  if(batch.simulation||!cost)return null;
  const readiness=cost.readiness;
  return <details className="core-feed-cost"><summary>이미지 생성 비용·승인</summary>
    {!cost.ready&&<p role="status">{cost.message}</p>}
    <details><summary>계산 근거·연결 상태</summary>
    {cost.ready&&<p>{cost.message}</p>}
    {readiness&&<div className="core-muted">
      <p>OpenAI 키: {readiness.keyConfigured?'등록됨':'미등록'} · 선택 모델: {readiness.modelVerified?'조회 확인됨':'미확인'}</p>
      {readiness.rateReference&&<p>공개 단가: 텍스트 입력 100만 토큰 US${readiness.rateReference.textInputPerMillionUsd} · 이미지 출력 100만 토큰 US${readiness.rateReference.imageOutputPerMillionUsd}. 총액 견적과 다릅니다. <a href={readiness.rateReference.source} target="_blank" rel="noreferrer">공식 단가</a></p>}
    </div>}
    </details>
    {cost.ready&&<>
      <p>{cost.basis==='app_budget_estimate'?`예상 US$${cost.estimatedUsd} · 계획 예산 US$${cost.remainingMaximumUsd} (여유분 2배 포함)`:`확인된 생성 비용 상한 US$${cost.remainingMaximumUsd}`} · 기존 요청 반영 US${cost.reservedUsd}</p>
      {cost.basis==='app_budget_estimate'&&<small>앱 예산 기준 · 실제 청구액은 다를 수 있습니다.</small>}
      <label>이번 작업 사용 한도 (USD)<input aria-label="TOP 3 작업 사용 한도" type="number" min="0.01" max="1000" step="0.01" value={limit} onChange={e=>setLimit(e.target.value)} disabled={busy}/></label>
      <button disabled={busy||!Number.isFinite(Number(limit))||Number(limit)<=0} onClick={()=>onSave({limit,quote_hash:cost.quoteHash,consent:true})}>예산 적용</button>
    </>}
    <div className="core-actions">
      <button disabled={busy} onClick={onRefresh}>비용 상태 새로고침</button>
      {!cost.ready&&<button disabled={busy||batch.canRecover||(readiness?.budgetAvailable===false || (readiness?.budgetAvailable===undefined && readiness?.costBoundVerified===false))} onClick={()=>onSave({})}>새 견적 준비</button>}
    </div>
    {cost.basis==='app_budget_estimate'&&<p>응답 사용량 기준 US${cost.usageCalculatedUsd} · {cost.usageUnknown?'미확인 요청 있음':'실제 청구액 별도'}</p>}
    {cost.approved&&<p>예산 적용됨</p>}
  </details>;
}
