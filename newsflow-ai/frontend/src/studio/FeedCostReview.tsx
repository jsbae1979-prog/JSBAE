import {useEffect,useState} from 'react';
import type {Item} from './contracts';

export default function FeedCostReview({batch,busy,onSave}:{batch:Item;busy:boolean;onSave:(data:Item)=>void}) {
  const [limit,setLimit]=useState('');
  const cost=batch.costReview;
  useEffect(()=>setLimit(cost?.approvedLimitUsd??''),[batch.id,cost?.approvedLimitUsd]);
  if(batch.simulation||!cost)return null;
  return <details className="core-feed-cost"><summary>이미지 생성 비용·승인</summary>
    <p role="status">{cost.message}</p>
    {cost.ready&&<>
      <p>확인된 생성 비용 상한 US${cost.remainingMaximumUsd} · 기존 요청 보류 US${cost.reservedUsd}</p>
      <label>이번 작업 사용 한도 (USD)<input aria-label="TOP 3 작업 사용 한도" type="number" min="0.01" max="1000" step="0.01" value={limit} onChange={e=>setLimit(e.target.value)} disabled={busy}/></label>
      <button disabled={busy||!Number.isFinite(Number(limit))||Number(limit)<=0} onClick={()=>onSave({limit,quote_hash:cost.quoteHash,consent:true})}>표시된 범위·비용 승인</button>
    </>}
    <button disabled={busy} onClick={()=>onSave({})}>비용 준비 상태 확인</button>
    {cost.approved&&<p>비용 승인 저장됨 · 이미지 생성 버튼으로 시작하세요.</p>}
  </details>;
}
