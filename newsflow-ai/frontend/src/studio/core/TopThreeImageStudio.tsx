import SampleGallery from "../SampleGallery";
import { useState, type ReactNode } from "react";
import { Sparkles, Save, Pause, Download } from "lucide-react";
import TopThreeFeeds from "../TopThreeFeeds";
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
  const item = b?.items.find((x: Item) => x.rank === active),
    hasUnknown = b?.items.some((x: Item) =>
      ["unknown", "running"].includes(x.status),
    );
  return (
    <div className="core-top3">
      <div className="core-top3-grid">
        <div className="core-top3-left">
          {tabs}
          <Panel title="실시간 인기 뉴스 TOP 3" className="core-top3-news">
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
          <Panel title="공통 이미지 생성 설정">
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
                <small>개별 이미지 3개 · 4:5</small>
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
                        ...f.options,
                      }),
                    );
                    f.setMessage(
                      "TOP 3 작업을 고정해 저장했습니다. 아직 생성하지 않았습니다.",
                    );
                  })
                }
              >
                <Save size={16} />
                TOP 3 제작 작업 저장
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
            title="TOP 3 이미지 결과"
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
                <p className="core-muted">
                  {b.simulation ? "합성 검증 결과 · 실제 게시 차단" : b.price} ·
                  저장된 모델·옵션 고정
                </p>
                <div className="core-feed-results">
                  {b.items.map((x: Item) => (
                    <article
                      key={x.rank}
                      className={active === x.rank ? "selected" : ""}
                    >
                      <button
                        className="core-result-select"
                        aria-label={`TOP ${x.rank} 결과 선택`}
                        onClick={() => setActive(x.rank)}
                      >
                        <FeedImage batch={b} item={x} />
                        <strong>
                          TOP {x.rank} · {x.content?.title}
                        </strong>
                      </button>
                      <State value={x.status} />
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
                          disabled={blocked || x.status !== "pending"}
                          onClick={() => f.edit(x)}
                        >
                          문구 수정
                        </button>
                        {["success", "failed"].includes(x.status) && (
                          <button
                            disabled={blocked || hasUnknown || !b.canGenerate}
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
                    TOP 3 생성 · 비용 승인
                  </button>
                  {f.busy && (
                    <button onClick={f.pause}>
                      <Pause size={14} />
                      현재 요청 후 중단
                    </button>
                  )}
                </div>
                <p className="core-warning">
                  {b.canGenerate
                    ? b.price
                    : "공식 견적·실행 권한 미확정 · 유료 생성 차단"}
                </p>
              </>
            ) : (
              <div
                className="core-feed-results"
                aria-label="아직 제작하지 않은 TOP 3 결과"
              >
                {[1, 2, 3].map((rank) => (
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
                disabled={blocked || item.status !== "pending"}
                onClick={() => f.edit(item)}
              >
                선택 뉴스 문구 수정
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
      <Panel title="최근 생성 이미지 · 작업 기록" className="core-recent-panel">
        <div className="core-recent">
          {f.batches.map((x: Item) => (
            <button
              key={x.id}
              disabled={f.busy}
              onClick={() => f.select(x)}
              aria-pressed={b?.id === x.id}
            >
              <strong>작업 #{x.id}</strong>
              <div className="core-feed-mini">
                {x.items.map((i: Item) => (
                  <FeedImage key={i.rank} batch={x} item={i} />
                ))}
              </div>
              <small>
                {x.items.filter((i: Item) => i.status === "success").length}/3
                성공 · 기존 결과 보존
              </small>
            </button>
          ))}
        </div>
      </Panel>
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
      <SampleGallery
        initialExpanded={c.list("selections").length === 0}
        types={["news-top3"]}
        csrf={c.view.csrfToken}
      />
    </>
  ) : null;
}
