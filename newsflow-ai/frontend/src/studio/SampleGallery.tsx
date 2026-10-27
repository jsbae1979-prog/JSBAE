import { useEffect, useRef, useState } from "react";
import type { Item } from "./contracts";
import "./samples.css";

export type SampleUse = { asset: Item; copy: Item };
export default function SampleGallery({
  types,
  csrf,
  onUse,
  library = false,
  onScope,
  initialExpanded = true,
  onBusyChange,
}: {
  types?: string[];
  csrf: string;
  onUse?: (value: SampleUse) => void;
  library?: boolean;
  onScope?: (scope: string) => void;
  initialExpanded?: boolean;
  onBusyChange?: (busy: boolean) => void;
}) {
  const [rows, setRows] = useState<Item[]>([]),
    [error, setError] = useState("");
  const [selected, setSelected] = useState<Item | null>(null),
    [notice, setNotice] = useState("");
  const [scope, setScope] = useState("all"),
    [manage, setManage] = useState(false),
    [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [expanded, setExpanded] = useState(initialExpanded);
  const dialog = useRef<HTMLDialogElement>(null),
    video = useRef<HTMLVideoElement>(null);
  async function load() {
    try {
      const r = await fetch("/api/samples", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!r.ok) throw Error();
      const data = await r.json();
      if (data.schemaVersion !== 1 || !Array.isArray(data.assets))
        throw Error();
      setRows(data.assets);
      setError(data.warning || "");
    } catch {
      setError("샘플을 읽지 못했습니다. 내 작업은 보존됩니다.");
    }
  }
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    if (selected) dialog.current?.showModal();
    else {
      video.current?.pause();
      dialog.current?.close();
    }
  }, [selected]);
  async function post(
    item: Item,
    action: string,
    values: Record<string, string>,
  ) {
    const r = await fetch(
      `/api/samples/${encodeURIComponent(item.id)}/${action}`,
      {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ csrf_token: csrf, ...values }),
      },
    );
    if (!r.ok)
      throw Error("샘플 작업을 완료하지 못했습니다. 자동 재요청하지 않습니다.");
    return r.json();
  }
  async function action(item: Item, kind: "copy" | "use" | "hide") {
    if (busy) return;
    setBusy(true);
    onBusyChange?.(true);
    setNotice("");
    try {
      if (kind === "hide")
        await post(item, "visibility", {
          hidden: item.hidden ? "false" : "true",
        });
      else {
        const copy = await post(item, "copy", {
          use: kind === "use" ? "true" : "false",
        });
        setNotice(copy.message);
        if (kind === "use") {
          if (onUse) {
            onUse({ asset: item, copy });
            setExpanded(false);
          } else
            setNotice(
              copy.message +
                " 아래 내 참조 파일 다운로드로 활용하세요. 편집 원본 프로젝트는 아닙니다.",
            );
        }
      }
      await load();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "샘플 작업 실패");
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  }
  const filtered = rows.filter(
    (x) =>
      (!types || types.includes(x.type)) &&
      (manage || !x.hidden || (scope === "mine" && x.copied)) &&
      (scope !== "mine" || x.copied) &&
      String(x.title).includes(query),
  );
  return (
    <section
      className={`sample-gallery ${library ? "sample-library" : "sample-compact"}`}
      aria-label="기본 샘플 콘텐츠"
    >
      <header>
        <h2>
          기본 샘플 콘텐츠 <span>샘플 · 실제 생성 이력 아님</span>
        </h2>
        <div className="sample-actions">
          <button
            type="button"
            aria-expanded={expanded}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? "샘플 접기" : "샘플 펼치기"}
          </button>
          <button
            type="button"
            onClick={() => {
              setManage(!manage);
              setExpanded(true);
            }}
            aria-pressed={manage}
          >
            숨긴 샘플 관리
          </button>
        </div>
      </header>
      {expanded && (
        <p>
          오프라인 예제입니다. 실제 최신 뉴스·AI 공급사 결과가 아닙니다. 영상은
          무음 12초 슬라이드이며 편집 원본 프로젝트가 없습니다. 사용권·재배포
          권한은 별도 확인이 필요합니다.
        </p>
      )}
      {library && (
        <div className="sample-scopes" aria-label="라이브러리 콘텐츠 구분">
          {[
            ["all", "전체"],
            ["mine", "내 콘텐츠"],
            ["samples", "샘플 콘텐츠"],
          ].map(([key, label]) => (
            <button
              key={key}
              aria-pressed={scope === key}
              onClick={() => {
                setExpanded(true);
                setScope(key);
                onScope?.(key);
              }}
            >
              {label}
            </button>
          ))}
          <input
            aria-label="샘플 검색"
            placeholder="샘플 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {expanded && (
        <div className="sample-cards">
          {filtered.map((item) => (
            <article key={item.id} data-sample-id={item.id}>
              <button
                className="sample-preview"
                aria-label={`${item.title} 미리보기`}
                onClick={() => setSelected(item)}
              >
                <img
                  src={item.posterUrl || item.mediaUrl}
                  alt={`${item.title} 샘플`}
                  loading="lazy"
                />
                <span>
                  {item.mime === "video/mp4"
                    ? "▶ 샘플 미리보기 영상 · 무음 12초"
                    : "샘플 이미지"}
                </span>
              </button>
              <h3>{item.title}</h3>
              <small>
                {item.width}×{item.height}
                {item.hidden ? " · 숨김" : ""}
                {item.copied ? " · 내 참조 복사본 있음" : ""}
              </small>
              {item.promptExample && (
                <details>
                  <summary>프롬프트 예제 · 원본 지시문 아님</summary>
                  <p>{item.promptExample}</p>
                </details>
              )}
              <div className="sample-actions">
                <button
                  disabled={busy || !csrf}
                  onClick={() => void action(item, "copy")}
                >
                  내 작업으로 복사
                </button>
                <button
                  disabled={busy || !csrf}
                  onClick={() => void action(item, "use")}
                >
                  {item.type === "character"
                    ? "참조 PNG로 선택"
                    : item.type === "standalone"
                      ? "프롬프트로 새 작업"
                      : "참조 자산으로 활용"}
                </button>
                <button
                  disabled={busy || !csrf}
                  onClick={() => void action(item, "hide")}
                >
                  {item.hidden ? "샘플 다시 표시" : "샘플 숨기기"}
                </button>
              </div>
              {item.copied && (
                <a href={`${item.copyUrl}?download=true`} download>
                  내 참조 파일 다운로드
                </a>
              )}
              {library && item.copied && (
                <a href={`/studio/${item.target}`}>제작실로 이동 · 참조 자료</a>
              )}
            </article>
          ))}
        </div>
      )}
      {expanded && !filtered.length && (
        <p>
          표시할 샘플이 없습니다. 숨긴 샘플 관리에서 다시 표시할 수 있습니다.
        </p>
      )}
      <dialog
        ref={dialog}
        className="sample-dialog"
        onCancel={() => setSelected(null)}
        onClose={() => {
          video.current?.pause();
          setSelected(null);
        }}
      >
        {selected && (
          <>
            <header>
              <h2>{selected.title} · 샘플</h2>
              <button onClick={() => setSelected(null)}>닫기</button>
            </header>
            {selected.mime === "video/mp4" ? (
              <video
                ref={video}
                src={selected.mediaUrl}
                poster={selected.posterUrl}
                controls
                playsInline
                preload="metadata"
                aria-label="샘플 미리보기 영상"
              />
            ) : (
              <img src={selected.mediaUrl} alt={selected.title} />
            )}
            <p>{selected.description}</p>
            <p>
              샘플 참조 자산 · 실제 생성 결과/편집 프로젝트 아님 · 사용권 별도
              확인
            </p>
          </>
        )}
      </dialog>
    </section>
  );
}
