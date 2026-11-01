import { useEffect, useRef, useState, type ReactNode } from "react";
import TopThreeFeeds from "../TopThreeFeeds";
import FeedCostReview from "../FeedCostReview";
import FeedGenerationProgress from "./FeedGenerationProgress";
import PhotoFeedEditor from "./PhotoFeedEditor";
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
    [style, setStyle] = useState("photo_feed_v1");
  const pendingRank = useRef<number | null>(null);
  const [preview, setPreview] = useState<{
    batchId: number;
    rank: number;
  } | null>(null);
  const b = f.batch,
    blocked = f.busy || !f.ready,
    selection = c.list("selections").find((x) => String(x.id) === f.analysis);
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
  return (
    <div className="core-top3">
      <div className="photo-feed-grid">
        <div className="core-top3-left">
          {tabs}
          <Panel title="뉴스 선택" className="core-top3-news">
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
              label="새 제작 스타일"
              value={style}
              onChange={setStyle}
              disabled={blocked}
              options={{
                photo_feed_v1: "사진 중심 피드 · 무료 한글 편집",
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
                  f.show(
                    await f.post("/api/feed-batches", {
                      analysis_id: f.analysis,
                      ...(scope === "selected" ? { rank: active } : {}),
                      ...f.options,
                      feed_style: style,
                    }),
                  );
                  f.setMessage(
                    "뉴스와 스타일 저장 · 생성은 비용 승인 후 별도 실행",
                  );
                })
              }
            >
              {scope === "all" ? "TOP 3 전체 제작 준비" : "선택 뉴스 제작 준비"}
            </button>
          </Panel>
          {b && (
            <Panel title={`작업 #${b.id} · 제작 상태`}>
              <FeedGenerationProgress
                batch={b}
                busy={f.busy}
                runningRank={f.runningRank}
                stopping={f.stopRequested}
                message={f.message}
              />
              <details>
                <summary>새 배경 생성 · 견적·비용 승인</summary>
                <p className="core-muted">
                  배경이 있을 때 문구·배치 수정은 오른쪽 무료 편집을 이용하세요.
                </p>
                {b.items.some((x: Item) => x.image_safety?.sensitive) && (
                  <p>
                    민감 주제: 인물·국기·사건 장면 없이 상징 이미지로 만듭니다
                  </p>
                )}
                <FeedCostReview
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
                <button
                  className="primary"
                  disabled={
                    blocked ||
                    !b.canGenerate ||
                    b.items.some((x: Item) =>
                      ["unknown", "running"].includes(x.status),
                    ) ||
                    !b.items.some((x: Item) => x.status === "pending")
                  }
                  onClick={() => f.approve()}
                >
                  {b.plannedImages === 1
                    ? "선택 뉴스 생성 · 비용 승인"
                    : "TOP 3 전체 생성 · 비용 승인"}
                </button>
                {b.items
                  .filter((x: Item) => ["success", "failed"].includes(x.status))
                  .map((x: Item) => (
                    <button
                      key={x.rank}
                      disabled={blocked || !b.canPrepareRegeneration}
                      onClick={() => f.approve(x)}
                    >
                      TOP {x.rank} 새 배경 추가 견적
                    </button>
                  ))}
                {f.busy && f.runningRank != null && (
                  <button onClick={f.pause} disabled={f.stopRequested}>
                    현재 요청 후 중단
                  </button>
                )}
                <p>{b.price}</p>
              </details>
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
              {b.items
                .filter((x: Item) => x.rank === active)
                .map((x: Item) => (
                  <details key={x.rank}>
                    <summary>기존 결과 도구</summary>
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
                          기존 이미지 크게 보기
                        </button>
                        <a href={x.mediaUrl + "?download=true"} download>
                          기존 이미지 저장
                        </a>
                      </>
                    )}
                    <button
                      disabled={
                        blocked ||
                        b.simulation ||
                        x.status !== "success" ||
                        b.feedStyle === "photo_feed_v1"
                      }
                      onClick={() => f.review(x)}
                    >
                      기존 결과 게시용 검토본 저장
                    </button>
                  </details>
                ))}
            </Panel>
          )}
        </div>
        {b?.items.some((x: Item) => x.rank === active) ? (
          <PhotoFeedEditor
            key={`${b.id}:${active}`}
            batch={b}
            rank={active}
            csrf={c.view?.csrfToken ?? ""}
            busy={f.busy}
            local={f.local}
            onSaved={f.load}
            resultPicker={
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
