import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Item } from "../contracts";
import { Panel, Empty } from "./shared";
import "./photo-feed.css";
import { FeedCopyTools, FeedPerformance } from "./FeedGrowthTools";
export default function PhotoFeedEditor({
  batch,
  rank,
  csrf,
  busy,
  local,
  onSaved,
  resultPicker,
}: {
  batch: Item;
  rank: number;
  csrf: string;
  busy: boolean;
  local: (fn: () => Promise<void>) => void;
  onSaved: () => Promise<void>;
  resultPicker: ReactNode;
}) {
  const [state, setState] = useState<Item | null>(null),
    [form, setForm] = useState<Item>({}),
    [background, setBackground] = useState("");
  const [preview, setPreview] = useState(""),
    [message, setMessage] = useState(""),
    [dirty, setDirty] = useState(false),
    [version, setVersion] = useState(0),
    [reviewed, setReviewed] = useState(false);
  const [uploadKind, setUploadKind] = useState("stock"),
    [credit, setCredit] = useState("");
  const modal = useRef<HTMLDialogElement>(null),
    alive = useRef(true);
  const base = `/api/feed-batches/${batch.id}/items/${rank}`;
  function accept(d: Item) {
    if (!alive.current) return;
    setState(d);
    setForm(d.draft);
    setBackground(d.background);
    setDirty(false);
  }
  useEffect(() => {
    alive.current = true;
    const abort = new AbortController();
    fetch(base + "/design", {
      credentials: "same-origin",
      cache: "no-store",
      signal: abort.signal,
    })
      .then(async (r) => {
        const d = await r.json();
        if (!r.ok) throw Error(d.detail || "편집 상태 확인 필요");
        accept(d);
        const v = d.versions.at(-1);
        if (v) {
          setVersion(v.version);
          setPreview(base + "/design-file/" + v.version);
        }
      })
      .catch((e) => {
        if (e.name !== "AbortError") setMessage(e.message);
      });
    return () => {
      alive.current = false;
      abort.abort();
    };
  }, [base]);
  function edit(k: string, v: any) { change({ [k]: v }); }
  function change(patch: Item) {
    setReviewed(false);
    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
    setMessage("수정 중 · 미리보기 적용 후 새 버전으로 저장하세요.");
  }
  async function response(r: Response) {
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw Error(d.detail || "입력·이미지 연결을 확인하세요.");
    }
    return r;
  }
  function run(action: string) {
    local(async () => {
      setMessage("");
      try {
        const r = await response(
          await fetch(base + "/design", {
            method: "POST",
            credentials: "same-origin",
            body: new URLSearchParams({
              csrf_token: csrf,
              revision: String(state?.revision),
              action,
              background,
              design: JSON.stringify(form),
            }),
          }),
        );
        if (action === "preview") {
          setPreview((await r.json()).previewUrl);
          setVersion(0);
          setMessage("현재 편집 미리보기 · 추가 API 호출 없음");
        } else {
          const d = await r.json();
          accept(d);
          if (action === "render") {
            setReviewed(false);
            const v = d.versions.at(-1);
            setVersion(v.version);
            setPreview(base + "/design-file/" + v.version);
            await onSaved();
          }
          setMessage(
            action === "render"
              ? "새 버전 저장 완료 · 기존 결과 보존"
              : "편집 초안을 저장했습니다.",
          );
        }
      } catch (e) {
        setMessage((e as Error).message);
      }
    });
  }
  function upload(file?: File) {
    if (!file) return;
    local(async () => {
      try {
        const data = new FormData();
        data.set("csrf_token", csrf);
        data.set("revision", String(state?.revision));
        data.set("kind", uploadKind);
        data.set("credit", credit);
        data.set("image", file);
        accept(
          await (
            await response(
              await fetch(base + "/design-upload", {
                method: "POST",
                credentials: "same-origin",
                body: data,
              }),
            )
          ).json(),
        );
        setReviewed(false);
        setMessage("이미지와 크레딧을 변경했습니다. 미리보기를 적용하세요.");
      } catch (e) {
        setMessage((e as Error).message);
      }
    });
  }
  const text = (label: string, key: string, rows = 1) => (
    <label>
      {label}
      {rows > 1 ? (
        <textarea
          aria-label={label}
          rows={rows}
          value={form[key] ?? ""}
          onChange={(e) => edit(key, e.target.value)}
        />
      ) : (
        <input
          aria-label={label}
          value={form[key] ?? ""}
          onChange={(e) => edit(key, e.target.value)}
        />
      )}
    </label>
  );
  const range = (
    label: string,
    key: string,
    min: number,
    max: number,
    step: number,
  ) => (
    <label>
      {label}{" "}
      <output>
        {key === "title_size"
          ? `${form[key]}px`
          : `${Math.round((form[key] ?? min) * 100)}%`}
      </output>
      <input
        aria-label={label}
        type="range"
        min={min}
        max={max}
        step={step}
        value={form[key] ?? min}
        onChange={(e) => edit(key, Number(e.target.value))}
      />
    </label>
  );
  const item = batch.items.find((i: Item) => i.rank === rank),
    shown = preview || (item?.mediaUrl ?? "");
  return (
    <>
      <Panel
        title={`TOP ${rank} · 선택 결과 미리보기`}
        className="photo-feed-stage"
      >
        {resultPicker}
        <div className="photo-feed-canvas">
          {shown ? (
            <button
              onClick={() => modal.current?.showModal()}
              aria-label="선택 이미지 크게 보기"
            >
              <img
                src={shown}
                alt={`TOP ${rank} 선택 이미지`}
                onError={() =>
                  setMessage(
                    "이미지 로딩 실패 · 배경과 저장 파일을 확인하세요.",
                  )
                }
              />
            </button>
          ) : (
            <Empty>이미지를 선택하고 무료 미리보기를 적용하세요.</Empty>
          )}
        </div>
        <p>
          {version
            ? `사진 중심 피드 · 버전 ${version}`
            : preview
              ? "저장 전 미리보기"
              : "기존 결과 · 원본 보존"}
        </p>
        {version > 0 && (
          <a
            href={base + "/design-file/" + version + "?download=true"}
            download
          >
            이 버전 이미지 저장
          </a>
        )}
        {state?.versions.length > 0 && (
          <label>
            저장된 편집 버전
            <select
              aria-label="저장된 편집 버전"
              value={version}
              onChange={(e) => {
                const n = Number(e.target.value);
                setVersion(n);
                setPreview(base + "/design-file/" + n);
                const v = state?.versions.find((v: Item) => v.version === n);
                if (v) {
                  setForm(v.design);
                  setBackground(`version:${v.version}`);
                  setDirty(true);
                  setReviewed(false);
                  setMessage(
                    "선택 버전의 편집값을 불러왔습니다. 수정 후 새 버전으로 저장하세요.",
                  );
                }
              }}
            >
              <option value={0} disabled>
                현재 미리보기
              </option>
              {state?.versions.map((v: Item) => (
                <option key={v.version} value={v.version}>
                  버전 {v.version}
                </option>
              ))}
            </select>
          </label>
        )}
        <dialog className="photo-feed-modal" ref={modal}>
          <button onClick={() => modal.current?.close()}>닫기</button>
          {shown && <img src={shown} alt="피드 확대" />}
        </dialog>
      </Panel>
      <Panel
        title={`TOP ${rank} · 사진 중심 피드 편집`}
        className="photo-feed-editor"
      >
        {!state ? (
          <Empty>{message || "편집 상태 불러오는 중…"}</Empty>
        ) : (
          <fieldset disabled={busy}>
            <p className="core-muted">
              이 뉴스만 편집합니다. 원제·요약·다른 결과·자동 제작 기본값은
              유지됩니다.
            </p>
            <FeedCopyTools state={state} form={form} base={base} csrf={csrf} background={background} local={local} onChange={change} />
            {text("피드 제목", "title", 3)}
            {text("핵심 설명", "description", 2)}
            {!form.description && (
              <small>
                확인 필요 · 저장된 요약에서 핵심 사실 1~2줄을 직접 입력하세요.
              </small>
            )}
            <label>
              배경 이미지
              <select
                aria-label="배경 이미지"
                value={background}
                onChange={(e) => {
                  setBackground(e.target.value);
                  const c = state.candidates.find(
                    (c: Item) => c.id === e.target.value,
                  );
                  edit("credit", c?.credit ?? "");
                }}
              >
                <option value="">이미지 선택</option>
                {state.candidates.map((c: Item) => (
                  <option key={c.id} value={c.id}>
                    {c.label} ·{" "}
                    {c.kind === "ai"
                      ? "AI 생성"
                      : c.kind === "photo"
                        ? "실제 사진"
                        : "자료사진"}
                  </option>
                ))}
              </select>
            </label>
            <details>
              <summary>다른 이미지 선택</summary>
              <label>
                이미지 구분
                <select
                  value={uploadKind}
                  onChange={(e) => setUploadKind(e.target.value)}
                >
                  <option value="stock">자료사진</option>
                  <option value="photo">실제 사진</option>
                  <option value="ai">AI 생성</option>
                </select>
              </label>
              <label>
                새 이미지 크레딧
                <input
                  aria-label="새 이미지 크레딧"
                  value={credit}
                  onChange={(e) => setCredit(e.target.value)}
                />
              </label>
              <label>
                로컬 이미지 업로드
                <input
                  aria-label="로컬 이미지 업로드"
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  disabled={!credit.trim()}
                  onChange={(e) => upload(e.target.files?.[0])}
                />
              </label>
              <small>
                사용권을 확인한 이미지만 선택하세요. 외부 이미지는 자동으로
                가져오지 않습니다.
              </small>
            </details>
            <details>
              <summary>배치·색상·자르기</summary>
              {text("강조 단어", "emphasis")}
              <label>
                강조색
                <input
                  aria-label="강조색"
                  type="color"
                  value={form.accent ?? "#76e4ff"}
                  onChange={(e) => edit("accent", e.target.value)}
                />
              </label>
              {range("제목 글자 크기", "title_size", 48, 84, 2)}
              {range("텍스트 세로 위치", "text_y", 0.35, 0.78, 0.01)}
              {range("이미지 차지 높이", "image_height", 0.6, 1, 0.01)}
              {range("그라데이션 높이", "gradient_height", 0.25, 0.9, 0.01)}
              {range("그라데이션 강도", "gradient_strength", 0.3, 1, 0.01)}
              <div className="photo-feed-crop">
                {["왼쪽", "위", "오른쪽", "아래"].map((label, i) => (
                  <label key={label}>
                    자르기 {label} (%)
                    <input
                      type="number"
                      min={0}
                      max={100}
                      step={1}
                      value={Math.round(
                        (form.crop?.[i] ?? [0, 0, 1, 1][i]) * 100,
                      )}
                      onChange={(e) => {
                        const c = [...form.crop];
                        c[i] = Number(e.target.value) / 100;
                        edit("crop", c);
                      }}
                    />
                  </label>
                ))}
              </div>
            </details>
            <details>
              <summary>출처·크레딧</summary>
              {text("브랜드", "brand")}
              {text("날짜", "date")}
              {text("기사 출처", "source", 2)}
              {text("이미지 크레딧", "credit", 2)}
            </details>
            <details>
              <summary>캡션 · 원문 참고</summary>
              {text("캡션 본문", "caption", 5)}
              {text("해시태그", "hashtags", 2)}
              <strong>기사 원제</strong>
              <p>{state.sourceTitle}</p>
              <strong>저장된 요약</strong>
              <p>{state.originalSummary}</p>
              <small>
                숫자·날짜·주체와 검토/예정 등 진행 상태를 유지하세요. 제작자
                메모는 캡션에 넣지 마세요.
              </small>
            </details>
            <div className="photo-feed-actions">
              <button disabled={!background} onClick={() => run("preview")}>
                미리보기 적용 · 무료
              </button>
              <button disabled={!background} onClick={() => run("draft")}>
                편집 초안 저장
              </button>
              <button
                className="primary"
                disabled={!background}
                onClick={() => run("render")}
              >
                새 버전으로 저장
              </button>
            </div>
            {version > 0 && !dirty && (
              <details>
                <summary>이 버전 게시용 검토본 저장</summary>
                <label>
                  <input
                    type="checkbox"
                    checked={reviewed}
                    onChange={(e) => setReviewed(e.target.checked)}
                  />
                  내용·권리·출처·AI 이미지 안전 확인
                </label>
                <button
                  disabled={!reviewed || batch.simulation}
                  onClick={() =>
                    local(async () => {
                      try {
                        await response(
                          await fetch(base + "/design-review", {
                            method: "POST",
                            credentials: "same-origin",
                            body: new URLSearchParams({
                              csrf_token: csrf,
                              version: String(version),
                              reviewed: "true",
                              image_safety_checked: "true",
                            }),
                          }),
                        );
                        setMessage("게시용 검토본 저장 완료 · 실제 게시 없음");
                        accept(
                          await (
                            await response(
                              await fetch(base + "/design", {
                                credentials: "same-origin",
                              }),
                            )
                          ).json(),
                        );
                      } catch (e) {
                        setMessage((e as Error).message);
                      }
                    })
                  }
                >
                  선택 버전 검토본 저장
                </button>
              </details>
            )}
            <FeedPerformance base={base} csrf={csrf} versions={state.versions} busy={busy} local={local} />
            {dirty && <small>저장하지 않은 편집이 있습니다.</small>}
            {message && <p role="status">{message}</p>}
            {state.warnings.map((m: string) => (
              <p className="core-warning" key={m}>
                {m}
              </p>
            ))}
          </fieldset>
        )}
      </Panel>
    </>
  );
}
