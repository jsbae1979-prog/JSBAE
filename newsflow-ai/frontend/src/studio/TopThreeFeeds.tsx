import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Image as ImageIcon,
  Play,
  Pause,
  RefreshCw,
  Download,
  ShieldCheck,
  Save,
  AlertTriangle,
} from "lucide-react";
import type { Item } from "./contracts";

const states: Record<string, string> = {
  pending: "생성 대기",
  running: "생성 중",
  success: "검토 필요",
  failed: "실패",
  unknown: "결과 불명 · 재요청 금지",
  missing: "파일 확인 필요",
};
function FeedDialog({
  name,
  onClose,
  children,
}: {
  name: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="top3-dialog"
      aria-label={name}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      {children}
    </dialog>
  );
}
export default function TopThreeFeeds({
  selections,
  catalog,
  csrf,
  render,
}: {
  selections: Item[];
  catalog: Item;
  csrf: string;
  render?: (controller: any) => ReactNode;
}) {
  const [batches, setBatches] = useState<Item[]>([]),
    [batch, setBatch] = useState<Item | null>(null);
  const [analysis, setAnalysis] = useState(""),
    [options, setOptions] = useState<Item>(catalog.imageDefaults ?? {});
  const [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [approval, setApproval] = useState(false);
  const [consent, setConsent] = useState(false),
    [reviewed, setReviewed] = useState(false),
    [editing, setEditing] = useState<Item | null>(null);
  const [postReview, setPostReview] = useState<Item | null>(null),
    [rights, setRights] = useState(false),
    [sources, setSources] = useState(false);
  const [ready, setReady] = useState(false);
  const [runningRank, setRunningRank] = useState<number | null>(null);
  const loadVersion = useRef(0);
  const stop = useRef(false),
    mounted = useRef(true);
  async function load() {
    const version = ++loadVersion.current;
    setReady(false);
    try {
      const r = await fetch("/api/feed-batches", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!r.ok) throw Error("TOP 3 제작 기록을 불러오지 못했습니다.");
      const d = await r.json();
      if (!mounted.current || version !== loadVersion.current) return;
      setBatches(d.batches);
      setOptions(d.defaults ?? catalog.imageDefaults ?? {});
      setBatch(
        (b) =>
          d.batches.find((x: Item) => x.id === b?.id) ?? d.batches[0] ?? null,
      );
    } finally {
      if (mounted.current && version === loadVersion.current) setReady(true);
    }
  }
  useEffect(() => {
    mounted.current = true;
    load().catch((e) => setMessage(String(e.message)));
    return () => {
      stop.current = true;
      mounted.current = false;
      ++loadVersion.current;
    };
  }, []);
  async function post(path: string, data: Item) {
    const form = new URLSearchParams({
      csrf_token: csrf,
      ...Object.fromEntries(
        Object.entries(data)
          .filter(([, v]) => v !== undefined)
          .map(([k, v]) => [k, String(v)]),
      ),
    });
    const r = await fetch(path, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    const d = await r.json();
    if (!r.ok)
      throw Error(
        typeof d.detail === "string"
          ? d.detail
          : "입력과 저장 상태를 확인하세요.",
      );
    return d;
  }
  function show(b: Item) {
    if (!mounted.current) return;
    setBatch(b);
    setBatches((xs) => [b, ...xs.filter((x) => x.id !== b.id)]);
  }
  async function local(action: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await action();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "작업을 확인하세요.");
    } finally {
      if (mounted.current) {
        setBusy(false);
        setRunningRank(null);
      }
    }
  }
  const chosen = selections.find((x) => String(x.id) === analysis);
  async function run(regenerate?: Item) {
    if (!batch) return;
    setApproval(false);
    await local(async () => {
      stop.current = false;
      let b = batch;
      if (regenerate) {
        b = await post(`/api/feed-batches/${b.id}/change`, {
          revision: b.revision,
          action: "regenerate",
          rank: regenerate.rank,
          consent,
          reviewed,
        });
        show(b);
        return;
      }
      if (b.paused) {
        b = await post(`/api/feed-batches/${b.id}/change`, {
          revision: b.revision,
          action: "resume",
        });
        show(b);
      }
      while (
        !stop.current &&
        b.items.some((x: Item) => x.status === "pending")
      ) {
        setRunningRank(
          b.items.find((x: Item) => x.status === "pending")?.rank ?? null,
        );
        b = await post(`/api/feed-batches/${b.id}/step`, { consent, reviewed });
        show(b);
        if (b.items.some((x: Item) => x.status === "unknown")) break;
      }
      if (stop.current) {
        b = await post(`/api/feed-batches/${b.id}/change`, {
          revision: b.revision,
          action: "pause",
        });
        show(b);
      }
      setMessage("제작 상태를 저장했습니다. 실제 게시되지 않았습니다.");
    });
  }
  const [regenerate, setRegenerate] = useState<Item | null>(null);
  const dialogs = (
    <>
      {" "}
      {approval && (
        <FeedDialog
          name="TOP 3 생성 범위 승인"
          onClose={() => setApproval(false)}
        >
          <h2>
            {regenerate
              ? `TOP ${regenerate.rank} 재생성 준비`
              : "TOP 3 자동 제작 승인"}
          </h2>
          <p>
            {batch?.simulation
              ? "Fake 이미지 검증 · 실제 과금 없음"
              : batch?.price}
          </p>
          <p>
            {regenerate
              ? "기존 결과를 보존하고 1회 추가 생성을 준비합니다."
              : "대기 항목만 각 1회 생성합니다. 결과 불명 요청은 재시도하지 않습니다."}
          </p>
          <label>
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
            />
            뉴스·문구·출처·모델을 검토했습니다.
          </label>
          <label>
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            {batch?.simulation
              ? "표시된 Fake 생성 범위에 동의합니다."
              : "표시된 외부 전송·유료 생성 범위에 동의합니다."}
          </label>
          <div className="work-actions">
            <button
              disabled={!consent || !reviewed || !batch?.canGenerate}
              onClick={() => run(regenerate ?? undefined)}
            >
              {regenerate ? "1회 재생성 준비" : "자동 제작 시작"}
            </button>
            <button onClick={() => setApproval(false)}>취소</button>
          </div>
        </FeedDialog>
      )}
      {editing && (
        <FeedDialog name="피드 문구 수정" onClose={() => setEditing(null)}>
          <h2>TOP {editing.rank} 문구 수정</h2>
          <label>
            제목
            <input
              aria-label="TOP 3 수정 제목"
              maxLength={60}
              value={editing.title}
              onChange={(e) =>
                setEditing({ ...editing, title: e.target.value })
              }
            />
          </label>
          <label>
            짧은 요약
            <textarea
              aria-label="TOP 3 수정 요약"
              maxLength={180}
              value={editing.body}
              onChange={(e) => setEditing({ ...editing, body: e.target.value })}
            />
          </label>
          <label>
            해시태그
            <input
              aria-label="TOP 3 수정 해시태그"
              maxLength={200}
              value={editing.hashtags}
              onChange={(e) =>
                setEditing({ ...editing, hashtags: e.target.value })
              }
            />
          </label>
          <p>원문에 없는 사실·수치·발언을 추가하지 마세요.</p>
          <div className="work-actions">
            <button
              disabled={busy || !ready}
              onClick={() =>
                local(async () => {
                  show(
                    await post(`/api/feed-batches/${batch!.id}/change`, {
                      revision: batch!.revision,
                      action: "edit",
                      ...editing,
                    }),
                  );
                  setEditing(null);
                })
              }
            >
              문구 저장
            </button>
            <button onClick={() => setEditing(null)}>취소</button>
          </div>
        </FeedDialog>
      )}
      {postReview && (
        <FeedDialog name="피드 게시용 검토" onClose={() => setPostReview(null)}>
          <h2>TOP {postReview.rank} 게시용 검토</h2>
          <p>
            AI 생성물 표시를 포함한 로컬 검토본만 저장합니다. 계정 연결·이미지
            업로드·공개 게시를 실행하지 않습니다.
          </p>
          <label>
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
            />
            이미지·캡션·해시태그·AI 표시 검토
          </label>
          <label>
            <input
              type="checkbox"
              checked={rights}
              onChange={(e) => setRights(e.target.checked)}
            />
            이미지 사용 권한 확인
          </label>
          <label>
            <input
              type="checkbox"
              checked={sources}
              onChange={(e) => setSources(e.target.checked)}
            />
            원문 출처 확인
          </label>
          <div className="work-actions">
            <button
              disabled={busy || !reviewed || !rights || !sources}
              onClick={() =>
                local(async () => {
                  const r = await post(
                    `/api/feed-batches/${batch!.id}/items/${postReview.rank}/review`,
                    {
                      reviewed,
                      rights,
                      sources_confirmed: sources,
                      ai_disclosure: "disclose",
                    },
                  );
                  setMessage(r.message);
                  setPostReview(null);
                })
              }
            >
              로컬 검토본 저장
            </button>
            <button onClick={() => setPostReview(null)}>취소</button>
          </div>
        </FeedDialog>
      )}
    </>
  );
  if (render)
    return (
      <>
        {render({
          batches,
          batch,
          analysis,
          setAnalysis,
          options,
          setOptions,
          busy,
          message,
          ready,
          runningRank,
          chosen,
          local,
          post,
          show,
          load,
          setMessage,
          approve: (item?: Item) => {
            if (
              !ready ||
              busy ||
              !batch?.canGenerate ||
              batch.items.some((x: Item) =>
                ["unknown", "running"].includes(x.status),
              )
            )
              return;
            setRegenerate(item ?? null);
            setConsent(false);
            setReviewed(false);
            setApproval(true);
          },
          edit: (item: Item) => {
            if (!ready || busy || item.status !== "pending") return;
            setEditing({ ...item.content, rank: item.rank });
          },
          review: (item: Item) => {
            if (busy || batch?.simulation || item.status !== "success") return;
            setPostReview(item);
            setRights(false);
            setSources(false);
            setReviewed(false);
          },
          pause: () => {
            stop.current = true;
          },
          select: (b: Item) => {
            if (!busy) show(b);
          },
        })}
        {dialogs}
      </>
    );
  return (
    <div className="top3-workflow work-stack" aria-busy={busy || !ready}>
      <details className="work-panel top3-new-job" open>
        <summary>
          <span className="section-heading">
            <strong>
              <ImageIcon size={20} />
              {batch ? "새 TOP 3 작업" : "뉴스 TOP 3 자동 제작"}
            </strong>
            <span className="pill">이미지 3개 · 개별 피드</span>
          </span>
        </summary>
        <p className="muted">
          저장된 분석과 대본을 재사용합니다. 새 분석·예약 실행·자동 게시를
          요청하지 않습니다.
        </p>
        <div className="top3-options">
          <label>
            분석 결과
            <select
              aria-label="TOP 3 분석 결과"
              value={analysis}
              disabled={busy || !ready}
              onChange={(e) => setAnalysis(e.target.value)}
            >
              <option value="">선택하세요</option>
              {selections.map((x) => (
                <option
                  key={x.id}
                  value={x.id}
                  disabled={x.status !== "success" || x.ranking?.length !== 3}
                >
                  {x.title}
                  {x.status !== "success" ? " · 선정 확인 필요" : ""}
                </option>
              ))}
            </select>
          </label>
          <label>
            이미지 모델
            <select
              aria-label="TOP 3 이미지 모델"
              value={options.model ?? ""}
              disabled={busy || !ready}
              onChange={(e) =>
                setOptions({ ...options, model: e.target.value })
              }
            >
              {(catalog.imageModels ?? []).map((x: string) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </select>
          </label>
          <label>
            생성 비율
            <select
              aria-label="TOP 3 생성 비율"
              value={options.size ?? "1024x1280"}
              disabled={busy || !ready}
              onChange={(e) => setOptions({ ...options, size: e.target.value })}
            >
              <option value="1024x1280">4:5 · 피드 권장</option>
              <option value="1024x1024">1:1 · 여백으로 맞춤</option>
              <option value="1024x1536">2:3 · 여백으로 맞춤</option>
            </select>
          </label>
          <label>
            품질
            <select
              aria-label="TOP 3 품질"
              value={options.quality ?? "medium"}
              disabled={busy || !ready}
              onChange={(e) =>
                setOptions({ ...options, quality: e.target.value })
              }
            >
              {Object.entries(catalog.qualities ?? {}).map(([k, v]) => (
                <option key={k} value={k}>
                  {String(v)}
                </option>
              ))}
            </select>
          </label>
        </div>
        {(chosen || batch) && (
          <ol className="top3-selection">
            {(
              chosen?.ranking ??
              batch?.items.map((x: Item) => ({
                ...x.source,
                ...x.content,
                rank: x.rank,
              })) ??
              []
            ).map((x: Item) => (
              <li key={x.rank}>
                <strong>
                  TOP {x.rank} · {x.title}
                </strong>
                <p>{x.body}</p>
                <small>
                  {x.origin} ·{" "}
                  {(x.references ?? [])
                    .map((r: Item) => r.publisher)
                    .join(" · ")}
                </small>
              </li>
            ))}
          </ol>
        )}
        <p className="review-note">
          최종 JPG 1080×1350 · 기본 3회 생성 · 공식 견적 미확정 시 유료 실행
          차단
        </p>
        <div className="work-actions">
          <button
            className="primary"
            disabled={busy || !ready || !chosen || chosen.ranking?.length !== 3}
            onClick={() =>
              local(async () => {
                show(
                  await post("/api/feed-batches", {
                    analysis_id: analysis,
                    ...options,
                  }),
                );
                setMessage(
                  "뉴스·대본·모델을 고정한 로컬 작업을 저장했습니다. 아직 생성하지 않았습니다.",
                );
              })
            }
          >
            <Save size={17} />
            TOP 3 제작 작업 저장
          </button>
          <button
            disabled={busy || !ready}
            onClick={() =>
              local(async () => {
                await post("/api/feed-batches/defaults", options);
                setMessage(
                  "자동 제작 기본값을 저장했습니다. 직접 제작·기존 작업은 바뀌지 않습니다.",
                );
              })
            }
          >
            자동 제작 기본값 저장
          </button>
          <a className="studio-link" href="/studio/settings">
            OpenAI 키 설정
          </a>
        </div>
      </details>
      {message && (
        <div className="review-note" role="status">
          <AlertTriangle size={18} />
          {message}
        </div>
      )}
      <section className="work-panel top3-run-panel">
        <div className="section-heading">
          <h2>자동 제작 작업</h2>
          <button
            aria-label="TOP 3 상태 새로고침"
            disabled={busy || !ready}
            onClick={() => local(load)}
          >
            <RefreshCw size={16} />
          </button>
        </div>
        <label>
          저장된 작업
          <select
            aria-label="TOP 3 저장된 작업"
            value={batch?.id ?? ""}
            disabled={busy || !ready}
            onChange={(e) =>
              setBatch(
                batches.find((x) => String(x.id) === e.target.value) ?? null,
              )
            }
          >
            <option value="">작업 없음</option>
            {batches.map((x) => (
              <option key={x.id} value={x.id}>
                분석 #{x.analysisId} · 작업 #{x.id}
                {x.simulation ? " · Fake 검증" : ""}
              </option>
            ))}
          </select>
        </label>
        {batch && (
          <>
            <div className="top3-frozen">
              <strong>
                {batch.simulation
                  ? "Fake 검증 작업 · 실제 공급사 호출 없음"
                  : "뉴스 3개 · 모델·옵션 고정"}
              </strong>
              <span>
                {batch.selection.model} · {batch.selection.size} ·{" "}
                {batch.selection.quality} → 1080×1350
              </span>
              <span>{batch.price}</span>
              <span>
                완료{" "}
                {batch.items.filter((x: Item) => x.status === "success").length}
                /3 · {batch.paused ? "중지됨" : "수동 실행"}
              </span>
            </div>
            <div className="work-actions">
              {batch.items.some((x: Item) => x.status === "running") && (
                <button
                  disabled={busy || !ready}
                  onClick={() =>
                    local(async () => {
                      show(
                        await post(`/api/feed-batches/${batch.id}/change`, {
                          revision: batch.revision,
                          action: "recover",
                        }),
                      );
                      setMessage(
                        "저장된 요청 결과만 복원했습니다. 생성 요청은 다시 보내지 않았습니다.",
                      );
                    })
                  }
                >
                  중단 요청 상태 복원
                </button>
              )}
              <button
                className="primary"
                disabled={
                  busy ||
                  !batch.canGenerate ||
                  batch.items.some((x: Item) =>
                    ["unknown", "running"].includes(x.status),
                  ) ||
                  !batch.items.some((x: Item) => x.status === "pending")
                }
                onClick={() => {
                  setConsent(false);
                  setReviewed(false);
                  setRegenerate(null);
                  setApproval(true);
                }}
              >
                <Play size={17} />
                {batch.paused ? "검토 후 재개" : "검토 후 자동 제작"}
              </button>
              <button
                disabled={!busy}
                onClick={() => {
                  stop.current = true;
                  setMessage(
                    "현재 요청 종료 후 멈춥니다. 이미 전송한 요청은 재전송하지 않습니다.",
                  );
                }}
              >
                <Pause size={17} />
                현재 항목 후 중지
              </button>
            </div>
            {runningRank !== null && (
              <p className="review-note" role="status">
                TOP {runningRank} 이미지 생성 중 · 현재 요청은 다시 보내지
                마세요.
              </p>
            )}
            <div className="top3-results">
              {batch.items.map((x: Item) => (
                <article className="top3-result" key={x.rank}>
                  <div className="section-heading">
                    <h3>TOP {x.rank}</h3>
                    <span
                      className={`state-badge ${x.status === "success" ? "good" : x.status === "unknown" ? "warn" : ""}`}
                    >
                      {runningRank === x.rank
                        ? states.running
                        : (states[x.status] ?? x.status)}
                    </span>
                  </div>
                  {x.mediaUrl ? (
                    <img
                      src={x.mediaUrl}
                      alt={`TOP ${x.rank} 피드 생성 결과`}
                      loading="lazy"
                    />
                  ) : (
                    <div className="top3-empty">
                      <ImageIcon size={30} />
                      <span>생성 결과 없음</span>
                    </div>
                  )}
                  <h3>{x.content.title}</h3>
                  <p>{x.content.body}</p>
                  <p className="muted">{x.content.hashtags}</p>
                  <small>
                    {x.source.origin} ·{" "}
                    {x.source.references
                      .map((r: Item) => r.publisher)
                      .join(" · ")}
                  </small>
                  <details>
                    <summary>문구·지시문·출처 확인</summary>
                    <p className="top3-copy">{x.caption}</p>
                    <p className="top3-copy">{x.prompt}</p>
                    <p>
                      이전 결과 {x.history.length}개 보존 · 생성 시도{" "}
                      {x.attempt}
                    </p>
                  </details>
                  <div className="work-actions">
                    <button
                      disabled={
                        busy || ["unknown", "running"].includes(x.status)
                      }
                      onClick={() => {
                        if (x.status === "pending")
                          setEditing({ ...x.content, rank: x.rank });
                        else {
                          setConsent(false);
                          setReviewed(false);
                          setRegenerate(x);
                          setApproval(true);
                        }
                      }}
                    >
                      {x.status === "pending"
                        ? "문구 수정"
                        : "개별 재생성 준비"}
                    </button>
                    {x.mediaUrl && (
                      <a
                        className="studio-link"
                        href={`${x.mediaUrl}?download=true`}
                        download
                      >
                        <Download size={15} />
                        JPG 저장
                      </a>
                    )}
                    {x.mediaUrl && (
                      <button
                        disabled={busy || batch.simulation}
                        onClick={() => {
                          setPostReview(x);
                          setRights(false);
                          setSources(false);
                          setReviewed(false);
                        }}
                      >
                        게시용 검토
                      </button>
                    )}
                  </div>
                  {x.message && <p className="muted">{x.message}</p>}
                </article>
              ))}
            </div>
            <p className="review-note">
              <ShieldCheck size={18} />
              {batch.publishApproval}
              {batch.simulation ? " · Fake 결과는 실제 게시 준비 차단" : ""}
            </p>
          </>
        )}
      </section>
      <aside className="work-panel top3-policy">
        <h2>
          <ShieldCheck size={18} />
          문구 · 출처 검토
        </h2>
        <p>뉴스 1·2·3위를 각각 하나의 피드 이미지로 제작합니다.</p>
        <p className="muted">
          저장된 뉴스 요약과 대본만 재사용하며, 출처에 없는 사실을 추가하지
          않습니다.
        </p>
        <div className="review-checklist">
          <p>기사별 문구·해시태그·출처 개별 보존</p>
          <p>사용권·AI 표시·최종 게시 승인 별도</p>
          <p>실패·결과 불명은 자동 재요청 금지</p>
        </div>
        <p className="review-note">
          모델·옵션은 작업 저장 시 고정됩니다. 새 기본값은 기존 작업을 바꾸지
          않습니다.
        </p>
        <a className="studio-link" href="/studio/settings">
          API 키·모델 설정
        </a>
      </aside>
      {dialogs}
    </div>
  );
}
