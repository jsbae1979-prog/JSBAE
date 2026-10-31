import {useState} from "react";
import type {Item} from "../contracts";
import {ActionButton,type Controller} from "./shared";

export function NewsAnalysisControls({c,selected,collectionMethod}:{c:Controller;selected?:Item;collectionMethod:string}){
  const [scope,setScope]=useState("article");
  const config=c.view?.catalog.newsAnalysis;
  const provider=config?.provider;
  const providerLabel=c.view?.catalog.analysisProviders?.[provider]??"설정 미확인";
  const all=scope==="collection";
  return <section className="news-analysis-controls" aria-label="뉴스 분석 설정">
    <dl>
      <div><dt>선택 수집 방식</dt><dd>{collectionMethod==="serpapi"?"SerpApi":"등록 RSS"}</dd></div>
      <div><dt>분석 API</dt><dd>{providerLabel}</dd></div>
      <div><dt>모델</dt><dd>{config?.model??"설정 미확인"}</dd></div>
    </dl>
    <div className="news-analysis-action">
      <label>분석 범위<select aria-label="뉴스 분석 범위" value={scope} onChange={e=>setScope(e.target.value)}>
        <option value="article">선택 기사</option><option value="collection">이번 수집 회차 TOP 3</option>
      </select></label>
      <ActionButton c={c} id={all?"curation_analyze":"intelligence_analyze"}
        context={all?{collection_context_id:config?.collectionContextId}:{article_ids:selected?[selected.id]:[],articleTitle:selected?.title}}
        disabled={all?!config?.collectionReady:!selected} primary>
        {all?"TOP 3 분석 · 승인":"기사 분석 · 승인"}
      </ActionButton>
    </div>
    {all&&!config?.collectionReady&&<small>이번 수집 회차의 뉴스·Trends 자료와 분석 API 설정을 확인하세요.</small>}
  </section>;
}
