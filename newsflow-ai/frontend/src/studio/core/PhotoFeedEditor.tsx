import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Item } from "../contracts";
import { Panel, Empty } from "./shared";
import "./photo-feed.css";
// Only pixels affect the local preview; caption/hashtags remain separate.
function visualKey(form: Item, background: string) {
  const keys = [
    "style",
    "typography",
    "title",
    "description",
    "brand",
    "date",
    "source",
    "credit",
    "emphasis",
    "accent",
    "title_size",
    "text_y",
    "image_height",
    "gradient_height",
    "gradient_strength",
    "crop",
  ];
  return JSON.stringify([background, keys.map((k) => form[k])]);
}
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
    [version, setVersion] = useState(0);
  const [uploadKind, setUploadKind] = useState("stock"),
    [credit, setCredit] = useState("");
  const [previewState, setPreviewState] = useState(""),
    [previewError, setPreviewError] = useState("");
  const renderedKey = useRef("");
  const previewRequest = useRef<AbortController | null>(null);
  const previewSequence = useRef(0);
  const modal = useRef<HTMLDialogElement>(null),
    alive = useRef(true);
  const base = `/api/feed-batches/${batch.id}/items/${rank}`;
  function accept(d: Item) {
    if (!alive.current) return;
    setState(d);
    const fresh=d.candidates.find((c:Item)=>c.id===d.newGeneratedBackground);
    setForm(fresh?{...d.draft,credit:fresh.credit}:d.draft);
    setBackground(fresh?fresh.id:d.background);
    setDirty(!!fresh);
    if(fresh){setVersion(0);setMessage("새 배경을 반영했습니다. 이전 버전은 보존됩니다.");}
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
        if (
          v && !d.newGeneratedBackground &&
          visualKey(v.design, `version:${v.version}`) ===
            visualKey(d.draft, d.background)
        ) {
          renderedKey.current = visualKey(d.draft, d.background);
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
  function edit(k: string, v: any) {
    change({ [k]: v });
  }
  function change(patch: Item) {
    setVersion(0);

    setForm((f) => ({ ...f, ...patch }));
    setDirty(true);
    setMessage("");
  }
  async function response(r: Response) {
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      throw Error(d.detail || "입력·이미지 연결을 확인하세요.");
    }
    return r;
  }
  const visual = visualKey(form, background);
  useEffect(() => {
    const sequence = ++previewSequence.current;
    const controller = new AbortController();
    previewRequest.current = controller;
    setPreviewError("");
    if (!state || !background || busy || visual === renderedKey.current) {
      setPreviewState("");
      return () => controller.abort();
    }
    setPreviewState("이미지·편집 반영 중…");
    // Debounce rapid edits, abort superseded requests and discard late responses.
    // This endpoint runs the same local renderer as Save, without saving a version.
    const timer = window.setTimeout(async () => {
      try {
        const r = await response(
          await fetch(base + "/design", {
            method: "POST",
            credentials: "same-origin",
            signal: controller.signal,
            body: new URLSearchParams({
              csrf_token: csrf,
              revision: String(state.revision),
              action: "preview",
              background,
              design: JSON.stringify(form),
            }),
          }),
        );
        const d = await r.json();
        if (
          controller.signal.aborted ||
          sequence !== previewSequence.current ||
          !alive.current
        )
          return;
        renderedKey.current = visual;
        setPreview(d.previewUrl);
        setVersion(0);
        setPreviewState("미리보기 반영됨 · 저장 전");
      } catch (e) {
        if (
          controller.signal.aborted ||
          sequence !== previewSequence.current ||
          !alive.current
        )
          return;
        setPreviewState("");
        setPreviewError((e as Error).message);
      }
    }, 250);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [visual, state?.revision, base, csrf, busy]);

  function run(action: string) {
    previewRequest.current?.abort();
    ++previewSequence.current;
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
        const d = await r.json();
        accept(d);
        if (action === "render") {
          renderedKey.current = visualKey(d.draft, d.background);
          setPreviewError("");

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
        const d = await (
          await response(
            await fetch(base + "/design-upload", {
              method: "POST",
              credentials: "same-origin",
              body: data,
            }),
          )
        ).json();
        // Replacing an image must not discard unsaved title/layout edits.
        accept(d);
        setForm({ ...form, credit: d.draft.credit });
        setVersion(0);
        setDirty(true);

        setMessage("배경 이미지 변경 완료");
      } catch (e) {
        setMessage((e as Error).message);
      }
    });
  }
  const currentImage=state?.candidates.find((c:Item)=>c.id==='generated'||c.aliases?.includes('generated'));
  const selectedImage=state?.candidates.find((c:Item)=>c.id===background||c.aliases?.includes(background));
  const hasNewBackground=!!currentImage && selectedImage?.sha256!==currentImage.sha256;
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
        <div className="photo-feed-preview-status" aria-live="polite">
          {previewState && <small role="status">{previewState}</small>}
          {previewError && <p role="alert">{previewError} 마지막 정상 미리보기를 표시합니다.</p>}
        </div>
        <div className="photo-feed-canvas" aria-busy={previewState === "이미지·편집 반영 중…"}>
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
            <Empty>배경 이미지를 선택하세요.</Empty>
          )}
        </div>
        {state?.designReview && <small role="status">{state.designReview.layout === 'passed'
          ? '자동 구성 완료 · 내용과 이미지를 확인하세요.' : '배경 생성 완료 · 문구를 조정하세요.'}</small>}
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
                  renderedKey.current = visualKey(
                    v.design,
                    `version:${v.version}`,
                  );
                  setForm(v.design);
                  setBackground(`version:${v.version}`);
                  setDirty(false);

                  setMessage(
                    `버전 ${v.version}을 불러왔습니다.`,
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
            {text("피드 제목", "title", 3)}
            {text("핵심 설명", "description", 2)}
            {!form.description && (
              <small>
                확인 필요 · 기사 요약에서 핵심 사실 1~2줄을 직접 입력하세요.
              </small>
            )}
            <details>
              <summary>배치·색상·자르기</summary>
              {state.autoDesign && currentImage && <button type="button" onClick={()=>{
                setBackground(currentImage.id);change(state.autoDesign);
              }}>자동 구성으로 되돌리기 · 무료</button>}
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
            <div className="photo-feed-actions">
              <button
                className="primary"
                disabled={!background || (!dirty && version > 0) || !!previewError || previewState === "이미지·편집 반영 중…"}
                onClick={() => run("render")}
              >
                새 버전으로 저장
              </button>
              {version > 0 && !dirty && version === state.versions.at(-1)?.version && !item?.libraryHidden && (
                <a className="button" href={"/studio/publishing?project_id=" + encodeURIComponent(state.posts?.[String(version)] ? `post:${state.posts[String(version)]}` : `feed:${batch.id}:${rank}`)}>게시 스튜디오로 이동</a>
              )}
            </div>
            <details className="photo-feed-advanced">
              <summary>추가 편집</summary>
              <details>
                <summary>제목 추천</summary>
                {(state.copyOptions?.titleCandidates ?? []).map((candidate: Item) => (
                  <button key={candidate.text} type="button" onClick={() => edit("title", candidate.text)}>{candidate.text}</button>
                ))}
              </details>
              <label>
                  배경 이미지
                  {hasNewBackground&&<button type="button" disabled={busy} onClick={()=>{
                    setBackground(currentImage.id);edit('credit',currentImage.credit??'');
                  }}>새로 생성한 배경 적용 · 무료</button>}
                  <select
                  aria-label="배경 이미지"
                  value={state.candidates.find((c:Item)=>c.id===background || c.aliases?.includes(background))?.id ?? background}
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
                <summary>내 이미지 올리기</summary>
                <label>
                  이미지 종류
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
                  업로드 이미지 출처
                  <input
                    aria-label="업로드 이미지 출처"
                    value={credit}
                    onChange={(e) => setCredit(e.target.value)}
                  />
                </label>
                <label>
                  이미지 파일 선택
                  <input
                    aria-label="이미지 파일 선택"
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
                <summary>출처 정보</summary>
                {text("기사 출처", "source", 2)}
                {text("이미지 출처", "credit", 2)}
              </details>
              <details>
                <summary>게시글 내용</summary>
                {text("게시글 본문", "caption", 5)}
                {text("해시태그", "hashtags", 2)}
                <strong>기사 원제</strong>
                <p>{state.sourceTitle}</p>
                <strong>기사 요약</strong>
                <p>{state.originalSummary}</p>
                <small>
                  숫자·날짜·주체와 검토/예정 등 진행 상태를 유지하세요. 제작자
                  메모는 캡션에 넣지 마세요.
                </small>
              </details>
              <button disabled={!background} onClick={() => run("draft")}>
                입력 내용 저장
              </button>
            </details>
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
