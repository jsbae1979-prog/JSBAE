import { useEffect, useRef, useState, type ReactNode } from "react";
import { Sparkles, Save, Pause, Download } from "lucide-react";
import TopThreeFeeds from "../TopThreeFeeds";
import FeedCostReview from "../FeedCostReview";
import FeedGenerationProgress from "./FeedGenerationProgress";
import FeedImagePreview, { completedFeedImages, type FeedEntry } from "./FeedImagePreview";
import { Thumbnail } from "../Thumbnail";
import type { Item } from "../contracts";
import {
  Panel,
  Empty,
  Select,
  State,
  NewsImage,
  type Controller,
} from "./shared";
function FeedImage({ batch, item }: { batch: Item; item: Item }) {
  const expected = `/api/feed-batches/${batch.id}/items/${item.rank}/file`;
  return item.status === "success" && item.mediaUrl === expected ? (
    <Thumbnail src={item.mediaUrl} alt={`TOP ${item.rank} 생성 이미지`} />
  ) : (
    <Empty>
      {item.status === "unknown"
        ? "결과 불명 · 재요청 금지"
        : "검증된 결과 파일 없음"}
    </Empty>
  );
}
function FeedLayout({
  c,
  f,
  tabs,
}: {
  c: Controller;
  f: any;
  tabs: ReactNode;
}) {
  const [scope,setScope]=useState("all");
  const pendingRank=useRef<number|null>(null);
  const [preview,setPreview]=useState<{batchId:number;rank:number}|null>(null);
  const entries=completedFeedImages(f.batches.map((x:Item)=>x.id===f.batch?.id?f.batch:x));
  const previewIndex=preview?entries.findIndex(x=>x.batch.id===preview.batchId&&x.item.rank===preview.rank):-1;
  function openImage({batch,item}:FeedEntry){
    if(f.busy)return;
    if(f.batch?.id!==batch.id){pendingRank.current=item.rank;f.select(batch);}
    setActive(item.rank);
    if(item.status==="success"&&item.mediaUrl===`/api/feed-batches/${batch.id}/items/${item.rank}/file`)
      setPreview({batchId:batch.id,rank:item.rank});
  }
  const [active, setActive] = useState(1),
    b = f.batch,
    blocked = f.busy || !f.ready,
    selection = c.list("selections").find((x) => String(x.id) === f.analysis),
    ranking =
      selection?.ranking ??
      b?.items.map((x: Item) => ({
        ...x.source,
        ...x.content,
        rank: x.rank,
      })) ??
      [];
  useEffect(()=>{if(b){setActive(pendingRank.current??b.items[0]?.rank??1);pendingRank.current=null;setScope(b.plannedImages===1?"selected":"all");}},[b?.id]);
  const item = b?.items.find((x: Item) => x.rank === active),
    hasUnknown = b?.items.some((x: Item) =>
      ["unknown", "running"].includes(x.status),
    );
  return (
    <div className="core-top3">
      <div className="core-top3-grid">
        <div className="core-top3-left">
          {tabs}
          <Panel title="저장된 뉴스 TOP 3" className="core-top3-news">
            <a href="/studio/news">새 뉴스 수집·분석</a>
            <Select
              label="완료된 TOP 3 분석"
              value={f.analysis}
              onChange={f.setAnalysis}
              disabled={blocked}
              options={Object.fromEntries(
                c
                  .list("selections")
                  .filter(
                    (x) => x.status === "success" && x.ranking?.length === 3,
                  )
                  .map((x) => [String(x.id), x.title]),
              )}
            />
            <div className="core-top3-news-list">
              {ranking.map((x: Item) => (
                <button
                  key={x.rank}
                  aria-pressed={active === x.rank}
                  onClick={() => setActive(x.rank)}
                >
                  <div className="core-top3-article-image">
                    <NewsImage
                      item={{
                        thumbnailUrl: Number.isInteger(x.article_ids?.[0])
                          ? `/news/${x.article_ids[0]}/thumbnail`
                          : null,
                      }}
                    />
                    <b>TOP {x.rank}</b>
                  </div>
                  <div className="core-top3-article-copy">
                    <strong>{x.title}</strong>
                    <p>{x.body ?? x.summary ?? "저장 요약 확인 필요"}</p>
                    <small>{x.origin ?? "저장된 분석"}</small>
                  </div>
                </button>
              ))}
              {!ranking.length && (
                <Empty>완료된 분석 결과 3건을 선택하세요.</Empty>
              )}
            </div>
            <p className="core-muted">
              1·2·3위의 뉴스·대본·출처를 재사용합니다. 추가 분석을 요청하지
              않습니다.
            </p>
          </Panel>
        </div>
        <div className="core-top3-center">
          <Panel title="뉴스 이미지 제작 설정">
            <Select label="제작 범위" value={scope} onChange={setScope} disabled={blocked}
              options={{all:"TOP 3 전체 · 이미지 3개",selected:"선택 뉴스 · 이미지 1개"}}/>
            <p>{scope==="all"?"TOP 1·2·3을 각각 제작합니다.":`선택한 TOP ${active} 뉴스만 제작합니다.`}</p>
            <div className="core-two-fields">
              <Select
                label="TOP 3 이미지 모델"
                value={f.options.model}
                onChange={(v) => f.setOptions({ ...f.options, model: v })}
                options={c.view?.catalog.imageModels ?? []}
                disabled={blocked}
              />
              <Select
                label="TOP 3 생성 비율"
                value={f.options.size}
                onChange={(v) => f.setOptions({ ...f.options, size: v })}
                options={{
                  "1024x1280": "4:5 · 피드 권장",
                  "1024x1024": "1:1 · 여백 변환",
                  "1024x1536": "2:3 · 여백 변환",
                }}
                disabled={blocked}
              />
              <Select
                label="TOP 3 품질"
                value={f.options.quality}
                onChange={(v) => f.setOptions({ ...f.options, quality: v })}
                options={c.view?.catalog.qualities ?? {}}
                disabled={blocked}
              />
              <div className="core-output-spec">
                <strong>최종 1080×1350</strong>
                <small>이미지 {scope==="all"?3:1}개 · 4:5</small>
              </div>
            </div>
            <div className="core-actions">
              <button
                className="primary"
                disabled={
                  blocked || !selection || selection.ranking?.length !== 3
                }
                onClick={() =>
                  f.local(async () => {
                    f.show(
                      await f.post("/api/feed-batches", {
                        analysis_id: f.analysis,
                        ...(scope==="selected"?{rank:active}:{}),
                        ...f.options,
                      }),
                    );
                    f.setMessage(
                      "뉴스와 제작 범위를 저장했습니다. 이미지 생성은 아직 실행하지 않았습니다.",
                    );
                  })
                }
              >
                <Save size={16} />
                {scope==="all"?"TOP 3 전체 제작 준비":"선택 뉴스 제작 준비"}
              </button>
              <button
                disabled={blocked}
                onClick={() =>
                  f.local(async () => {
                    await f.post("/api/feed-batches/defaults", f.options);
                    f.setMessage(
                      "자동 제작 기본값을 저장했습니다. 다른 모드·기존 작업은 변경되지 않습니다.",
                    );
                  })
                }
              >
                자동 제작 기본값 저장
              </button>
            </div>
          </Panel>
          <Panel
            title="뉴스 이미지 결과"
            tools={
              b && (
                <span className="core-tag">
                  작업 #{b.id} · 분석 #
                  {b.analysisId ?? b.analysis_id ?? "고정됨"}
                </span>
              )
            }
          >
            {b ? (
              <>
                <FeedGenerationProgress batch={b} busy={f.busy} runningRank={f.runningRank} stopping={f.stopRequested} message={f.message}/>
                <p className="core-muted">
                  {b.simulation ? "합성 검증 결과 · 실제 게시 차단" : b.price} ·
                  저장된 모델·옵션 고정
                </p>
                {b.items.some((x:Item)=>x.image_safety?.sensitive)&&<p role="note" className="core-muted">민감 주제: 인물·국기·사건 장면 없이 상징 이미지로 만듭니다</p>}
                <FeedCostReview batch={b} busy={f.busy} onRefresh={()=>f.local(f.refreshCosts)} onSave={data=>f.local(async()=>f.show(await f.post(`/api/feed-batches/${b.id}/cost-review`,{revision:b.revision,...data})))}/>
                {b.canRecover && <button disabled={blocked} onClick={()=>f.local(async()=>{
                  f.show(await f.post(`/api/feed-batches/${b.id}/change`,{action:"recover",revision:b.revision}));
                  f.setMessage("저장된 결과 확인 완료 · 추가 API 요청 없음. 미확인 항목은 그대로 보존됩니다.");
                })}>저장된 결과 복구 · 무료</button>}
                <div className={`core-feed-results${b.items.length === 1 ? " core-feed-single" : ""}`}>
                  {b.items.map((x: Item) => (
                    <article
                      key={x.rank}
                      className={active === x.rank ? "selected" : ""}
                    >
                      <button
                        className="core-result-select"
                        aria-label={`TOP ${x.rank} 결과 선택`}
                        onClick={() => openImage({batch:b,item:x})}
                      >
                        <FeedImage key={`${x.sha256}`} batch={b} item={x} />
                        <strong>
                          TOP {x.rank} · {x.content?.title}
                        </strong>
                      </button>
                      <State value={f.busy && f.runningRank === x.rank && x.status === "pending" ? "running" : x.status} />
                      <div className="core-actions">
                        {x.status === "success" &&
                          x.mediaUrl ===
                            `/api/feed-batches/${b.id}/items/${x.rank}/file` && (
                            <a href={`${x.mediaUrl}?download=true`} download>
                              <Download size={14} />
                              저장
                            </a>
                          )}
                        <button
                          disabled={blocked || (x.status !== "pending" && !x.canEditTitle)}
                          onClick={() => f.edit(x)}
                        >
                          {x.canEditTitle ? "제목 수정 · 무료" : "문구 수정"}
                        </button>
                        {["success", "failed"].includes(x.status) && (
                          <button
                            disabled={blocked || !b.canPrepareRegeneration}
                            onClick={() => f.approve(x)}
                          >
                            추가 견적
                          </button>
                        )}
                      </div>
                      {x.message && <small>{x.message}</small>}
                    </article>
                  ))}
                </div>
                <div className="core-actions">
                  <button
                    className="primary"
                    disabled={
                      blocked ||
                      !b.canGenerate ||
                      hasUnknown ||
                      !b.items.some((x: Item) => x.status === "pending")
                    }
                    onClick={() => f.approve()}
                  >
                    <Sparkles size={16} />
                    {b.plannedImages===1?"선택 뉴스 생성 · 비용 승인":"TOP 3 전체 생성 · 비용 승인"}
                  </button>
                  {f.busy && f.runningRank != null && (
                    <button onClick={f.pause} disabled={f.stopRequested}>
                      <Pause size={14} />
                      {f.stopRequested ? "중단 요청됨" : "현재 요청 후 중단"}
                    </button>
                  )}
                </div>
                <p className="core-warning">
                  {b.canGenerate
                    ? b.price
                    : b.generationBlock ?? "이미지 생성 비용을 확인하고 승인하세요."}
                </p>
              </>
            ) : (
              <div
                className={`core-feed-results${scope === "selected" ? " core-feed-single" : ""}`}
                aria-label="아직 제작하지 않은 TOP 3 결과"
              >
                {(scope==="all"?[1,2,3]:[active]).map((rank) => (
                  <article key={rank}>
                    <div className="core-result-select">
                      <Empty>TOP {rank} · 제작 작업을 먼저 저장하세요.</Empty>
                      <strong>TOP {rank} · 결과 없음</strong>
                    </div>
                    <State value="pending" />
                  </article>
                ))}
              </div>
            )}
          </Panel>
        </div>
        <Panel title="문구 · 출력 설정" className="core-copy-output">
          {item ? (
            <>
              <strong>TOP {item.rank}</strong>
              <h3>{item.content?.title}</h3>
              <p>{item.content?.body}</p>
              <p className="core-hashtags">{item.content?.hashtags}</p>
              <button
                disabled={blocked || (item.status !== "pending" && !item.canEditTitle)}
                onClick={() => f.edit(item)}
              >
                {item.canEditTitle ? "제목 수정 · 무료" : "선택 뉴스 문구 수정"}
              </button>
              <dl>
                <dt>출력</dt>
                <dd>JPG · 1080×1350</dd>
                <dt>출처</dt>
                <dd>
                  {(item.source?.references ?? item.references ?? [])
                    .map((r: Item) => r.publisher)
                    .join(" · ") || "원문 검토 필요"}
                </dd>
                <dt>게시</dt>
                <dd>최종 승인 전 전송 차단</dd>
              </dl>
              <button
                disabled={blocked || b.simulation || item.status !== "success"}
                onClick={() => f.review(item)}
              >
                게시용 검토본 저장
              </button>
            </>
          ) : (
            <Empty>검토할 결과를 선택하세요.</Empty>
          )}
          <p className="core-muted">
            사용권·출처·AI 표시를 검토합니다. 자동 제작은 Instagram에 게시하지
            않습니다.
          </p>
          <a href="/studio/settings">OpenAI 키 · 연결 안내</a>
        </Panel>
      </div>
      {f.message && (
        <div role="status" className="core-notice">
          {f.message}
        </div>
      )}
      <Panel title="최근 생성 이미지" className="core-recent-panel">
        <div className="feed-image-history">
          {entries.map(({batch,item})=><button key={`${batch.id}:${item.rank}`} className="feed-image-history-card"
            disabled={f.busy} onClick={()=>openImage({batch,item})}
            aria-label={`${item.content?.title || "생성 이미지"} 크게 보기`}
            aria-pressed={b?.id===batch.id&&active===item.rank}>
            <FeedImage key={item.sha256} batch={batch} item={item}/>
            <strong>{item.content?.title || "생성 이미지"}</strong>
            <small>작업 #{batch.id} · 생성 완료</small>
          </button>)}
        </div>
        {!entries.length&&<Empty>완료된 이미지가 여기에 표시됩니다.</Empty>}
      </Panel>
      {previewIndex>=0&&<FeedImagePreview entries={entries} index={previewIndex} onSelect={openImage} onClose={()=>setPreview(null)}/>}

    </div>
  );
}
export default function TopThreeImageStudio({
  c,
  tabs,
}: {
  c: Controller;
  tabs: ReactNode;
}) {
  return c.view ? (
    <>
      <TopThreeFeeds
        selections={c.list("selections")}
        catalog={c.view.catalog}
        csrf={c.view.csrfToken}
        render={(f) => <FeedLayout c={c} f={f} tabs={tabs} />}
      />
    </>
  ) : null;
}
