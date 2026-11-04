import { useEffect, useRef, useState, type ReactNode } from "react";
import TopThreeFeeds, { FeedDialog } from "../TopThreeFeeds";
import FeedCostReview from "../FeedCostReview";
import FeedGenerationProgress from "./FeedGenerationProgress";
import PhotoFeedEditor from "./PhotoFeedEditor";
import CompleteFeedEditor from "./CompleteFeedEditor";
import FeedImageHistory from "./FeedImageHistory";
import FeedImagePreview, {
  completedFeedImages,
  type FeedEntry,
} from "./FeedImagePreview";
import { Thumbnail } from "../Thumbnail";
import type { Item } from "../contracts";
import { Panel, Empty, Select, NewsImage, type Controller } from "./shared";
function FeedLayout({
  c,
  f,
  tabs,
}: {
  c: Controller;
  f: any;
  tabs: ReactNode;
}) {
  const [active, setActive] = useState(1),
    [scope, setScope] = useState("all"),
    [style, setStyle] = useState("ai_design_v1");
  const [costOpen, setCostOpen] = useState(false);
  const pendingRank = useRef<number | null>(null);
  const [preview, setPreview] = useState<{
    batchId: number;
    rank: number;
  } | null>(null);
  const b = f.batch,
    blocked = f.busy || !f.ready,
    selection = c.list("selections").find((x) => String(x.id) === f.analysis);
  const matching = f.batches.find((x:Item)=>String(x.analysisId)===f.analysis && x.feedStyle===style &&
    (scope==='all' ? x.plannedImages===3 : x.plannedImages===1 && x.items[0]?.rank===active));
  const ranking =
    selection?.ranking ??
    b?.items.map((x: Item) => ({ ...x.source, ...x.content, rank: x.rank })) ??
    [];
  const entries = completedFeedImages(
    f.batches.map((x: Item) => (x.id === b?.id ? b : x)),
  );
  const previewIndex = preview
    ? entries.findIndex(
        (x) => x.batch.id === preview.batchId && x.item.rank === preview.rank,
      )
    : -1;
  useEffect(() => {
    if (b) {
      const params = new URLSearchParams(window.location.search);
      const requested = params.get("batch_id") === String(b.id) ? Number(params.get("rank")) : 0;
      setActive(pendingRank.current ?? (b.items.some((x: Item)=>x.rank===requested) ? requested : b.items[0]?.rank ?? 1));
      pendingRank.current = null;
      setScope(b.plannedImages === 1 ? "selected" : "all");
      setStyle(b.feedStyle ?? "legacy");
    }
  }, [b?.id]);
  function openImage({ batch, item }: FeedEntry) {
    if (f.busy) return;
    if (b?.id !== batch.id) {
      pendingRank.current = item.rank;
      f.select(batch);
    }
    setActive(item.rank);
    setPreview({ batchId: batch.id, rank: item.rank });
  }
  const productionStatus = b && (
            <Panel title={`작업 #${b.id} · 제작 상태`}>
              <FeedGenerationProgress
                batch={b}
                busy={f.busy}
                runningRank={f.runningRank}
                stopping={f.stopRequested}
                message={f.message}
              />
              {b.costReview?.settingsLimitUsd && <p>작업 한도 US${b.costReview.settingsLimitUsd} · 설정값 사용</p>}
              <button className="primary" disabled={blocked} onClick={()=>{
                if(b.costReview?.settingsLimitUsd){if(b.items.some((x:Item)=>x.status==='pending'))f.runSettings();else f.runSettings({action:'regenerate',rank:active,consent:true,reviewed:true});return;}
                setCostOpen(true);
              }}>
                {b.items.some((x:Item)=>x.status==="pending") ? "이미지 생성" : `TOP ${active} 이미지 다시 만들기`}
              </button>
              {f.busy && f.runningRank != null && <button onClick={f.pause} disabled={f.stopRequested}>현재 요청 후 중단</button>}
              {costOpen && <FeedDialog name="이미지 생성 비용 확인" onClose={()=>setCostOpen(false)}>
                <h2>{b.items.some((x:Item)=>x.status==="pending") ? "이미지 생성" : `TOP ${active} 이미지 다시 만들기`}</h2>
                <FeedCostReview expanded
                  batch={b}
                  busy={f.busy}
                  onRefresh={() => f.local(f.refreshCosts)}
                  onSave={(data) =>
                    f.local(async () =>
                      f.show(
                        await f.post(`/api/feed-batches/${b.id}/cost-review`, {
                          revision: b.revision,
                          ...data,
                        }),
                      ),
                    )
                  }
                />
                {b.items.some((x:Item)=>x.status==="pending") && <button
                  className="primary"
                  disabled={
                    blocked ||
                    !b.canGenerate ||
                    b.items.some((x: Item) =>
                      ["unknown", "running"].includes(x.status),
                    ) ||
                    !b.items.some((x: Item) => x.status === "pending")
                  }
                  onClick={() => {setCostOpen(false);f.approve();}}
                >
                  {b.plannedImages === 1
                    ? "선택 뉴스 생성 · 비용 승인"
                    : "TOP 3 전체 생성 · 비용 승인"}
                </button>}
                {b.items
                  .filter((x: Item) => x.rank === active && ["success", "failed"].includes(x.status))
                  .map((x: Item) => (
                    <button
                      key={x.rank}
                      disabled={blocked || !b.canPrepareRegeneration}
                      onClick={() => {setCostOpen(false);f.approve(x);}}
                    >
                      선택 이미지 새 견적 준비
                    </button>
                  ))}
                <button onClick={()=>setCostOpen(false)}>닫기</button>
              </FeedDialog>}
              {b.canRecover && (
                <button
                  disabled={blocked}
                  onClick={() =>
                    f.local(async () =>
                      f.show(
                        await f.post(`/api/feed-batches/${b.id}/change`, {
                          action: "recover",
                          revision: b.revision,
                        }),
                      ),
                    )
                  }
                >
                  저장된 결과 복구 · 무료
                </button>
              )}
            </Panel>
          );
  return (
    <div className="core-top3">
      <div className="photo-feed-grid">
        <div className="core-top3-left">
          {tabs}
          <Panel title="뉴스 선택" className="core-top3-news">
            {f.batches.length>0&&<details><summary>이전 작업 열기</summary><Select label="저장된 이미지 작업" value={b?String(b.id):""}
              options={Object.fromEntries(f.batches.map((x:Item)=>[String(x.id),`작업 #${x.id} · ${x.items[0]?.content?.title??"뉴스 이미지"}`]))}
              onChange={v=>{const x=f.batches.find((x:Item)=>String(x.id)===v);if(x)f.select(x);}} disabled={blocked}/></details>}
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
                  disabled={blocked}
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
                  <strong>{x.title}</strong>
                </button>
              ))}
            </div>
            <Select
              label="제작 범위"
              value={scope}
              onChange={setScope}
              disabled={blocked}
              options={{
                all: "TOP 3 전체 · 개별 이미지 3장",
                selected: `선택 뉴스 TOP ${active} · 1장`,
              }}
            />
            <Select
              label="제작 스타일"
              value={style}
              onChange={setStyle}
              disabled={blocked}
              options={{
                ai_design_v1: "AI 완성 피드 · 한글·디자인 함께 생성",
                photo_feed_v1: "사진 중심 피드 · 무료 글자 편집",
                legacy: "기존 뉴스 카드",
              }}
            />
            <details>
              <summary>모델·품질·생성 설정</summary>
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
                  "1024x1024": "1:1",
                  "1024x1536": "2:3",
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
              <button
                disabled={blocked}
                onClick={() =>
                  f.local(async () => {
                    await f.post("/api/feed-batches/defaults", f.options);
                    f.setMessage("자동 제작 기본값 저장 · 기존 작업 불변");
                  })
                }
              >
                자동 제작 기본값 저장
              </button>
            </details>
            <button
              className="primary"
              disabled={
                blocked || !selection || selection.ranking?.length !== 3
              }
              onClick={() =>
                f.local(async () => {
                  if(matching){f.select(matching);f.setMessage("저장된 작업을 열었습니다. 제작 상태의 이미지 생성 버튼에서 진행하세요.");return;}
                  f.show(
                    await f.post("/api/feed-batches", {
                      analysis_id: f.analysis,
                      ...(scope === "selected" ? { rank: active } : {}),
                      ...f.options,
                      feed_style: style,
                    }),
                  );
                  f.setMessage(
                    "뉴스와 스타일 저장 · 이미지 생성 버튼으로 진행하세요",
                  );
                })
              }
            >
              {matching ? "저장된 작업 열기" : scope === "all" ? "TOP 3 전체 제작 준비" : "선택 뉴스 제작 준비"}
            </button>
          </Panel>

        </div>
        {b?.feedStyle==='ai_design_v1' ? <CompleteFeedEditor statusPanel={productionStatus} batch={b} rank={active} f={f} onSelect={setActive} csrf={c.view?.csrfToken??""}/> : b?.items.some((x: Item) => x.rank === active) ? (
          <PhotoFeedEditor
            statusPanel={productionStatus}
            key={`${b.id}:${active}:${b.items.find((x:Item)=>x.rank===active)?.generation_id??"none"}`}
            batch={b}
            rank={active}
            csrf={c.view?.csrfToken ?? ""}
            busy={f.busy}
            local={f.local}
            onSaved={f.load}
            resultPicker={
              <>
              <div className="photo-feed-thumbs">
                {b.items.map((x: Item) => (
                  <button
                    key={x.rank}
                    aria-label={`TOP ${x.rank} 결과 선택`}
                    aria-pressed={active === x.rank}
                    disabled={blocked}
                    onClick={() => setActive(x.rank)}
                  >
                    {(x.designMediaUrl || x.mediaUrl) && (
                      <Thumbnail
                        src={x.designMediaUrl || x.mediaUrl}
                        alt={`TOP ${x.rank}`}
                      />
                    )}
                    <strong>TOP {x.rank}</strong>
                    <small>
                      {x.designVersion
                        ? `편집 버전 ${x.designVersion}`
                        : x.status === "success"
                          ? "배경 준비됨"
                          : x.status === "pending"
                            ? "생성 대기"
                            : x.message || x.status}
                    </small>
                  </button>
                ))}
              </div>
              {b.items
                .filter((x: Item) => x.rank === active && !x.designVersion && b.feedStyle !== "photo_feed_v1")
                .map((x: Item) => (
                  <details key={x.rank}>
                    <summary>원본 이미지</summary>
                    <button
                      disabled={
                        blocked || (x.status !== "pending" && !x.canEditTitle)
                      }
                      onClick={() => f.edit(x)}
                    >
                      {x.canEditTitle ? "제목 수정 · 무료" : "문구 수정"}
                    </button>
                    {x.mediaUrl && (
                      <>
                        <button
                          onClick={() => openImage({ batch: b, item: x })}
                        >
                          원본 보기
                        </button>
                        <a href={x.mediaUrl + "?download=true"} download>
                          원본 저장
                        </a>
                      </>
                    )}
                  </details>
                ))}
              </>
            }
          />
        ) : (
          <Panel title="사진 중심 피드">
            <Empty>
              왼쪽에서 뉴스와 제작 범위를 저장하세요. 저장만으로 생성 API가
              실행되지 않습니다.
            </Empty>
          </Panel>
        )}
      </div>
      {f.message && (
        <div role="status" className="core-notice">
          {f.message}
        </div>
      )}
      <Panel title="최근 생성 이미지">
        <FeedImageHistory entries={entries} busy={f.busy} csrf={c.view?.csrfToken ?? ""}
          onOpen={openImage} onRemoved={async()=>{setPreview(null);await f.load();await c.load();}}/>
      </Panel>
      {previewIndex >= 0 && (
        <FeedImagePreview
          entries={entries}
          index={previewIndex}
          onSelect={openImage}
          onClose={() => setPreview(null)}
        />
      )}
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
    <TopThreeFeeds
      selections={c.list("selections")}
      catalog={c.view.catalog}
      csrf={c.view.csrfToken}
      render={(f) => <FeedLayout c={c} f={f} tabs={tabs} />}
    />
  ) : null;
}
