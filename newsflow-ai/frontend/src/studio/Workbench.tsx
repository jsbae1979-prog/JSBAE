import { useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  Image as ImageIcon,
  Bot,
  Search,
  RefreshCw,
  Plus,
  Check,
  Play,
  Download,
  FolderOpen,
  FileText,
  ShieldCheck,
  Clock3,
  ChevronRight,
  Save,
  ArrowLeft,
  AlertTriangle,
  SlidersHorizontal,
  ExternalLink,
  Send,
  CalendarDays,
  Mic,
  Layers,
  Info,
} from "lucide-react";
import {
  actions,
  type Action,
  type Item,
  type View,
  titles,
  status,
  label,
  safeMedia,
  itemTitle,
} from "./contracts";
import { CommandDialog, submitOriginal } from "./CommandDialog";
import "./workbench.css";
const intro: Record<string, string> = {
  news: "보관 기사에서 이야기를 선택하세요.",
  shorts: "기사 · 대본 · 음성 · 영상을 한 작업으로 이어갑니다.",
  characters: "참조 캐릭터와 스토리로 만드는 쇼츠.",
  images: "독립 AI 이미지와 뉴스 이미지 게시물을 제작합니다.",
  automation: "예약과 실행 기록을 한눈에 확인합니다.",
  library: "영상 · 이미지 · 작업 기록을 보관합니다.",
  publishing: "로컬 초안부터 플랫폼별 검토와 게시까지.",
  analytics: "확인된 성과와 사용량만 표시합니다.",
  settings: "다음 작업 기본값과 서비스 연결을 관리합니다.",
  onboarding: "내 PC의 제작 환경을 차례로 준비합니다.",
};
function Badge({ value }: { value: unknown }) {
  const v = String(value ?? "draft");
  return (
    <span
      className={`state-badge ${/fail|error|missing|blocked/.test(v) ? "bad" : /unknown|reserved|review|pending/.test(v) ? "warn" : /success|complete|approved|downloaded/.test(v) ? "good" : ""}`}
    >
      {status[v] ?? v}
    </span>
  );
}
function Empty({ text = "아직 저장된 항목이 없습니다." }: { text?: string }) {
  return (
    <div className="work-empty">
      <FolderOpen size={34} />
      <strong>{text}</strong>
      <span>샘플을 실제 작업으로 표시하지 않습니다.</span>
    </div>
  );
}
function Collection({
  title,
  items,
  onSelect,
  selected,
}: {
  title: string;
  items: Item[];
  onSelect?: (x: Item) => void;
  selected?: unknown;
}) {
  return (
    <section className="work-panel">
      <div className="section-heading">
        <h2>{title}</h2>
        <span className="muted">{items.length}개</span>
      </div>
      {items.length ? (
        <div className="record-list">
          {items.map((x, i) => (
            <button
              type="button"
              className={`record-row ${selected === x.id ? "selected" : ""}`}
              key={x.id ?? x.key ?? i}
              onClick={() => onSelect?.(x)}
              disabled={!onSelect}
            >
              <span className="record-icon">
                <FileText size={19} />
              </span>
              <span>
                <strong>{itemTitle(x)}</strong>
                <small>
                  {x.publisher ??
                    x.platform ??
                    x.model ??
                    x.local_time ??
                    x.created_at ??
                    "저장 기록"}
                </small>
              </span>
              <Badge value={x.status ?? x.state ?? x.review_status} />
              {onSelect && <ChevronRight size={16} />}
            </button>
          ))}
        </div>
      ) : (
        <Empty />
      )}
    </section>
  );
}
export default function Workbench({
  module,
  onNavigate,
}: {
  module: string;
  onNavigate: (page: string) => void;
}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [command, setCommand] = useState<{
    action: Action;
    context: Item;
  } | null>(null);
  const [selected, setSelected] = useState<Item | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("전체");
  const [tab, setTab] = useState("independent");
  const [selectedArticles, setSelectedArticles] = useState<number[]>([]);
  const [scene, setScene] = useState(0);
  const [stage, setStage] = useState(1);
  const [editor, setEditor] = useState<Item | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [zoom, setZoom] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  async function load() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/api/studio/modules/${module}`, {
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!response.ok)
        throw Error("작업 정보를 불러오지 못했습니다. 저장 내용은 유지됩니다.");
      const data: View = await response.json();
      if (
        data.schemaVersion !== 1 ||
        data.module !== module ||
        !data.collections
      )
        throw Error("화면 데이터 형식을 확인하세요.");
      setView(data);
      setSelected((old) => {
        if (!old) return null;
        for (const list of Object.values(data.collections)) {
          const found = list.find((x) => String(x.id) === String(old.id));
          if (found) return found;
        }
        return old;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : "연결을 확인하세요.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    setView(null);
    setSelected(null);
    setEditor(null);
    setEditorDirty(false);
    setQuery("");
    setNotice("");
    setCommand(null);
    void load();
  }, [module]);
  const collections = view?.collections ?? {};
  const list = (key: string) => collections[key] ?? [];
  const catalog = view?.catalog ?? {};
  function open(id: string, context: Item = {}) {
    const action = actions.find((x) => x.id === id);
    if (!action) {
      setNotice("이 기능의 연결 계약을 확인하세요.");
      return;
    }
    if (!view?.commandsAvailable) {
      setNotice("현재 읽기 전용 화면에서는 실행할 수 없습니다.");
      return;
    }
    setCommand({ action, context });
  }
  function saved() {
    setNotice(
      "요청 응답을 받았습니다. 갱신된 기록에서 저장·생성 상태를 확인하세요.",
    );
    void load();
  }
  function selectDraft(draft: Item) {
    if (
      editorDirty &&
      !window.confirm(
        "저장하지 않은 편집 내용이 있습니다. 다른 대본으로 이동할까요?",
      )
    )
      return;
    setSelected(draft);
    let content = draft.content;
    try {
      const recovery = sessionStorage.getItem(
        `studio-script-${draft.id}-${draft.revision}`,
      );
      if (recovery) {
        content = JSON.parse(recovery);
        setNotice("이 브라우저에서 저장 전 편집 내용을 복구했습니다.");
      }
    } catch {}
    setEditor(structuredClone(content ?? {}));
    setEditorDirty(false);
    setScene(0);
  }
  function updateEditor(next: Item) {
    setEditor(next);
    setEditorDirty(true);
    if (selected)
      sessionStorage.setItem(
        `studio-script-${selected.id}-${selected.revision}`,
        JSON.stringify(next),
      );
  }
  async function saveScript() {
    if (!view || !selected || !editor || busy) return;
    setBusy(true);
    try {
      const action = actions.find((x) => x.id === "intelligence_edit")!;
      await submitOriginal(
        action,
        {
          draft_id: selected.id,
          revision: selected.revision,
          content: JSON.stringify(editor),
        },
        view,
        {},
      );
      sessionStorage.removeItem(
        `studio-script-${selected.id}-${selected.revision}`,
      );
      setEditorDirty(false);
      saved();
    } catch (e) {
      setNotice(e instanceof Error ? e.message : "저장 상태를 확인하세요.");
    } finally {
      setBusy(false);
    }
  }
  const context = selected
    ? {
        ...selected,
        identifier: selected.id,
        job_id: selected.id,
        draft_id: selected.id,
        plan_id: selected.id,
        run_id: selected.id,
        schedule_id: selected.id,
        account_id: selected.id,
      }
    : {};
  const button = (id: string, ctx: Item = context, primary = false) => {
    const a = actions.find((x) => x.id === id);
    return a ? (
      <button
        type="button"
        className={primary ? "primary" : ""}
        disabled={!view?.commandsAvailable || a.unsupported}
        title={a.reason}
        onClick={() => open(id, ctx)}
      >
        <Plus size={16} />
        {a.label}
      </button>
    ) : null;
  };
  const editorScenes = Array.isArray(editor?.scenes) ? editor.scenes : [];
  const project = (view?.projects ?? []).find(
    (x) => selected && String(x.draftId) === String(selected.id),
  );
  const currentMedia = safeMedia(selected?.mediaUrl ?? project?.mediaUrl);
  const preview = (media: string | null, kind = "video") => (
    <section className="work-panel preview-panel">
      <div className="section-heading">
        <h2>{kind === "image" ? "이미지 캔버스" : "9:16 미리보기"}</h2>
        {media && (
          <a
            className="icon-button"
            href={`${media}?download=true`}
            download
            aria-label="파일 다운로드"
          >
            <Download size={18} />
          </a>
        )}
      </div>
      <div
        className={`studio-canvas ${kind === "image" ? "image-canvas" : ""} ${zoom ? "zoomed" : ""}`}
      >
        {media ? (
          kind === "image" ? (
            <img src={media} alt="검증된 생성 결과" />
          ) : (
            <video ref={video} controls preload="metadata" src={media} />
          )
        ) : (
          <div className="canvas-placeholder">
            {kind === "image" ? (
              <ImageIcon size={48} />
            ) : (
              <Clapperboard size={48} />
            )}
            <strong>
              검증된 {kind === "image" ? "이미지" : "완성 영상"}을 선택하세요
            </strong>
            <span>실패·결과 불명·누락 파일은 재생하지 않습니다.</span>
          </div>
        )}
      </div>
      {kind === "image" && media && (
        <button className="text-button" onClick={() => setZoom(!zoom)}>
          {zoom ? "캔버스 맞춤" : "크게 보기"}
        </button>
      )}
      <p className="muted">
        파일 생성 · 내용 검토 · 공개 게시 승인은 별도입니다.
      </p>
    </section>
  );
  return (
    <div className="workbench" data-module={module}>
      <header className="work-heading">
        <div>
          <span className="eyebrow">NEWSFLOW AI STUDIO</span>
          <h1>{titles[module] ?? "작업 화면"}</h1>
          <p>{intro[module]}</p>
        </div>
        <div className="work-actions">
          <button onClick={() => onNavigate("create")}>
            <ArrowLeft size={17} />
            제작 홈
          </button>
          <button
            onClick={() => void load()}
            disabled={loading}
            aria-label="현재 화면 새로고침"
          >
            <RefreshCw className={loading ? "spin" : ""} size={18} />
          </button>
        </div>
      </header>
      {view?.dataOrigin === "development-fixtures" && (
        <p className="fixture-banner">
          <ShieldCheck size={16} />
          개발용 합성 자료 · 실제 계정·실제 API·공개 게시 없음
        </p>
      )}
      {error && (
        <div className="command-error" role="alert">
          <AlertTriangle size={19} />
          {error}
          <button onClick={() => void load()}>다시 불러오기</button>
        </div>
      )}
      {notice && (
        <div className="work-notice" role="status">
          <Info size={18} />
          {notice}
          <button className="text-button" onClick={() => setNotice("")}>
            닫기
          </button>
        </div>
      )}
      {loading && !view ? (
        <div className="work-empty">
          <RefreshCw className="spin" />
          저장된 자료를 불러오는 중
        </div>
      ) : (
        view && (
          <>
            {module === "news" && (
              <>
                <div className="work-toolbar">
                  <label className="work-search">
                    <Search size={18} />
                    <input
                      aria-label="보관 기사 검색"
                      placeholder="보관 기사 검색"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </label>
                  {button("routes_collect", {}, true)}
                  {button("serpapi_collect", {})}
                  {button("intelligence_analyze", {
                    article_ids: selectedArticles,
                  })}
                  <button onClick={() => onNavigate("shorts")}>
                    <Clapperboard size={17} />
                    쇼츠 제작실
                  </button>
                </div>
                <div className="filters">
                  {[
                    "전체",
                    "정치",
                    "경제",
                    "사회",
                    "IT·과학",
                    "문화",
                    "스포츠",
                    "국제",
                    "미분류",
                    ...list("articles").map((x) => x.category),
                  ]
                    .filter((x, i, a) => x && a.indexOf(x) === i)
                    .map((c) => (
                      <button
                        key={c}
                        aria-pressed={category === c}
                        onClick={() => setCategory(c)}
                      >
                        {c}
                      </button>
                    ))}
                </div>
                <div className="work-columns news-columns">
                  <section className="work-panel">
                    <div className="section-heading">
                      <h2>보관 뉴스</h2>
                      <span>{selectedArticles.length}건 선택</span>
                    </div>
                    <div className="news-cards">
                      {list("articles")
                        .filter(
                          (x) =>
                            (category === "전체" || x.category === category) &&
                            `${x.title} ${x.summary}`
                              .toLowerCase()
                              .includes(query.toLowerCase()),
                        )
                        .map((x) => (
                          <article
                            className={`news-card ${selected?.id === x.id ? "selected" : ""}`}
                            key={x.id}
                          >
                            <label className="article-select">
                              <input
                                type="checkbox"
                                aria-label={`${x.title} 선택`}
                                checked={selectedArticles.includes(x.id)}
                                onChange={(e) =>
                                  setSelectedArticles((a) =>
                                    e.target.checked
                                      ? [...a, x.id]
                                      : a.filter((id) => id !== x.id),
                                  )
                                }
                              />
                            </label>
                            <button onClick={() => setSelected(x)}>
                              <span className="news-art">
                                <ImageIcon size={25} />
                                {x.thumbnailUrl && (
                                  <img
                                    loading="lazy"
                                    src={x.thumbnailUrl}
                                    alt="출처 제공 대표 이미지"
                                    onError={(e) => {
                                      e.currentTarget.hidden = true;
                                    }}
                                  />
                                )}
                              </span>
                              <span>
                                <small>
                                  {x.category} · {x.publisher}
                                </small>
                                <strong>{x.title}</strong>
                                <p>{x.summary}</p>
                              </span>
                            </button>
                          </article>
                        ))}
                    </div>
                    {!list("articles").length && (
                      <Empty text="먼저 뉴스를 수집하세요." />
                    )}
                  </section>
                  <aside className="work-panel inspector">
                    <h2>기사와 출처</h2>
                    {selected ? (
                      <>
                        <Badge value="review_required" />
                        <h3>{selected.title}</h3>
                        <p>{selected.summary}</p>
                        <p className="muted">
                          {selected.publisher} ·{" "}
                          {selected.published_at ?? "발행일 미확인"}
                        </p>
                        {/^https?:\/\//.test(selected.url ?? "") && (
                          <a
                            className="text-button"
                            href={selected.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            기사 원문 <ExternalLink size={16} />
                          </a>
                        )}
                        {button(
                          "intelligence_analyze",
                          { article_ids: [selected.id] },
                          true,
                        )}
                        <p className="muted">
                          대표 이미지의 목록 표시와 영상 사용 권한은 별개입니다.
                        </p>
                      </>
                    ) : (
                      <Empty text="기사를 선택하세요." />
                    )}
                  </aside>
                </div>
              </>
            )}
            {module === "shorts" && (
              <>
                <nav className="stage-rail" aria-label="제작 단계">
                  {["뉴스", "대본 · 자막", "음성", "영상 · 장면", "검토"].map(
                    (x, i) => (
                      <button
                        key={x}
                        aria-current={stage === i ? "step" : undefined}
                        onClick={() => {
                          document
                            .getElementById(
                              i < 2
                                ? "script-editor"
                                : i === 2
                                  ? "voice-options"
                                  : "ai-scenes",
                            )
                            ?.scrollIntoView({
                              behavior: "smooth",
                              block: "start",
                            });
                        }}
                      >
                        <span>{i + 1}</span>
                        {x}
                      </button>
                    ),
                  )}
                </nav>
                <div className="work-toolbar">
                  {button("intelligence_generate", {}, true)}
                  {button("production_selection", {})}
                  <button onClick={() => onNavigate("news")}>
                    <FileText size={16} />
                    뉴스 선택
                  </button>
                </div>
                <div className="work-columns production-columns">
                  <div className="work-stack">
                    <Collection
                      title="저장된 대본"
                      items={list("drafts")}
                      onSelect={selectDraft}
                      selected={selected?.id}
                    />
                    <section
                      className="work-panel script-editor"
                      id="script-editor"
                    >
                      <div className="section-heading">
                        <h2>대본 · 장면 편집</h2>
                        {selected && <span>버전 {selected.revision}</span>}
                      </div>
                      {editor ? (
                        <>
                          <label className="form-field">
                            <span>제목</span>
                            <input
                              value={editor.title ?? ""}
                              maxLength={100}
                              onChange={(e) =>
                                updateEditor({
                                  ...editor,
                                  title: e.target.value,
                                })
                              }
                            />
                          </label>
                          <label className="form-field">
                            <span>HOOK · 첫 문장</span>
                            <textarea
                              value={editor.hook ?? ""}
                              maxLength={200}
                              onChange={(e) =>
                                updateEditor({
                                  ...editor,
                                  hook: e.target.value,
                                })
                              }
                            />
                          </label>
                          <div className="scene-tabs">
                            {editorScenes.map((s: Item, i: number) => (
                              <button
                                key={i}
                                aria-pressed={scene === i}
                                onClick={() => {
                                  setScene(i);
                                  if (video.current)
                                    video.current.currentTime = editorScenes
                                      .slice(0, i)
                                      .reduce(
                                        (n: number, x: Item) =>
                                          n + Number(x.seconds ?? 0),
                                        0,
                                      );
                                }}
                              >
                                <span>장면 {i + 1}</span>
                                <small>{s.seconds}초</small>
                              </button>
                            ))}
                          </div>
                          {editorScenes[scene] && (
                            <div className="scene-editor">
                              <label className="form-field">
                                <span>방송용 내레이션</span>
                                <textarea aria-label="방송용 내레이션"
                                  value={editorScenes[scene].narration ?? ""}
                                  maxLength={400}
                                  onChange={(e) => {
                                    const scenes =
                                      structuredClone(editorScenes);
                                    scenes[scene].narration = e.target.value;
                                    updateEditor({ ...editor, scenes });
                                  }}
                                />
                              </label>
                              <label className="form-field">
                                <span>화면 자막</span>
                                <textarea aria-label="화면 자막"
                                  value={editorScenes[scene].caption ?? ""}
                                  maxLength={150}
                                  onChange={(e) => {
                                    const scenes =
                                      structuredClone(editorScenes);
                                    scenes[scene].caption = e.target.value;
                                    updateEditor({ ...editor, scenes });
                                  }}
                                />
                              </label>
                              <label className="form-field">
                                <span>장면 소재</span>
                                <input
                                  value={editorScenes[scene].material ?? ""}
                                  onChange={(e) => {
                                    const scenes =
                                      structuredClone(editorScenes);
                                    scenes[scene].material = e.target.value;
                                    updateEditor({ ...editor, scenes });
                                  }}
                                />
                              </label>
                              <div className="review-note">
                                <ShieldCheck size={17} />
                                <span>
                                  검토 메모 · 방송에 포함하지 않음
                                  <br />
                                  {(
                                    editorScenes[scene].review_notes ??
                                    selected?.review_notes ??
                                    []
                                  ).join(" · ") || "별도 검토 메모 없음"}
                                </span>
                              </div>
                            </div>
                          )}
                          <div className="work-actions">
                            <button
                              className="primary"
                              disabled={
                                busy || !editorDirty || !view.commandsAvailable
                              }
                              onClick={() => void saveScript()}
                            >
                              <Save size={17} />
                              {busy ? "저장 확인 중" : "대본 저장"}
                            </button>
                            <span className="muted">
                              {editorDirty
                                ? "저장 전 편집 · 브라우저 복구 가능"
                                : "저장된 내용"}
                            </span>
                          </div>
                          <details>
                            <summary>출처 확인</summary>
                            <pre>
                              {JSON.stringify(selected?.sources ?? {}, null, 2)}
                            </pre>
                          </details>
                        </>
                      ) : (
                        <Empty text="대본을 선택해 장면을 편집하세요." />
                      )}
                    </section>
                    <section className="work-panel" id="voice-options">
                      <h2>
                        <Mic size={19} /> 이번 작업 음성
                      </h2>
                      <p className="muted">
                        작업에 고정된 음성을 사용합니다. 다음 작업 기본값은 기존
                        작업을 바꾸지 않습니다.
                      </p>
                      <div className="work-actions">
                        {button(
                          "video_render",
                          {
                            draft_id: selected?.id,
                            duration: selected?.duration,
                          },
                          true,
                        )}
                        {button("video_load_elevenlabs_voices", {})}
                        {button("video_select_elevenlabs_voice", {})}
                        {button("voice_preview", {})}
                      </div>
                    </section>
                    <section className="work-panel" id="ai-scenes">
                      <div className="section-heading">
                        <h2>
                          <Layers size={19} /> AI 영상 · 장면 타임라인
                        </h2>
                        {button("video_ai_create_plan", {
                          draft_id: selected?.id,
                          duration: selected?.duration,
                        })}
                      </div>
                      <Collection
                        title="장면 계획"
                        items={list("plans")}
                        onSelect={(x) => {
                          setSelected({ ...x, __type: "plan" });
                          setScene(0);
                        }}
                        selected={selected?.id}
                      />
                      <div className="timeline">
                        {list("scenes")
                          .filter((x) => x.plan_id === selected?.id)
                          .map((x, i) => (
                            <button
                              key={x.id}
                              aria-pressed={scene === i}
                              onClick={() => setScene(i)}
                            >
                              <span>장면 {(x.position ?? i) + 1}</span>
                              <Badge value={x.status} />
                              <small>
                                {Math.round(x.start_ms / 1000)}–
                                {Math.round(x.end_ms / 1000)}초
                              </small>
                              <p>{x.caption}</p>
                            </button>
                          ))}
                      </div>
                      {selected?.__type === "plan" && (
                        <div className="work-actions">
                          {button("video_ai_save_scenes", {
                            plan_id: selected.id,
                            revision: selected.revision,
                          })}
                          {button("video_ai_confirm", {
                            plan_id: selected.id,
                            revision: selected.revision,
                          })}
                          {button("video_ai_review", {
                            plan_id: selected.id,
                            revision: selected.revision,
                          })}
                          {button("video_ai_approve", {
                            plan_id: selected.id,
                            revision: selected.revision,
                          })}
                        </div>
                      )}
                    </section>
                  </div>
                  <aside className="work-stack">
                    {preview(currentMedia)}
                    <section className="work-panel">
                      <h2>완성 파일</h2>
                      {(view.projects ?? [])
                        .filter((x) => x.kind === "news")
                        .map((x) => (
                          <button
                            className="record-row"
                            key={x.id}
                            onClick={() => setSelected(x)}
                          >
                            <Play size={18} />
                            {x.title}
                            <Badge value={x.technicalStatus} />
                          </button>
                        ))}
                    </section>
                    <section className="work-panel">
                      <h2>
                        <ShieldCheck size={19} /> 제작 준비
                      </h2>
                      <p>
                        대본 검토 정책 · 소재 사용권 · 외부 음성 동의 · AI 장면
                        승인을 기존 엔진에서 검사합니다.
                      </p>
                      <p className="muted">
                        1080×1920 · FFmpeg 합성
                        <br />
                        공개 게시 승인은 제작 검토와 별도입니다.
                      </p>
                    </section>
                  </aside>
                </div>
              </>
            )}
            {module === "characters" && (
              <>
                <div className="work-toolbar">
                  {button("character_create", {}, true)}
                  {button("character_character_defaults", {})}
                </div>
                <div className="work-columns production-columns">
                  <div className="work-stack">
                    <Collection
                      title="캐릭터 프로젝트"
                      items={list("jobs")}
                      onSelect={setSelected}
                      selected={selected?.id}
                    />
                    <section className="work-panel">
                      <h2>스토리 · 스토리보드</h2>
                      {selected ? (
                        <>
                          <h3>{selected.topic}</h3>
                          <Badge value={selected.state} />
                          <div className="story-copy">
                            {typeof selected.story === "string" ? selected.story : <><h3>{selected.story?.title}</h3><p>{selected.story?.plan?.situation ?? "저장된 장면 구성을 확인하세요."}</p></>}
                          </div>
                          <div className="timeline">
                            {(selected.scenes?.length ? selected.scenes : selected.story?.scenes ?? []).map((x: Item, i: number) => (
                              <button
                                key={x.position ?? i}
                                onClick={() => setScene(x.position ?? i)}
                                aria-pressed={scene === (x.position ?? i)}
                              >
                                <span>장면 {(x.position ?? i) + 1}</span>
                                <Badge value={x.state} />
                                <p>{x.caption ?? x.narration ?? x.action ?? x.prompt}</p>
                                <small>{x.seconds ?? "규격 확인"}초</small>
                              </button>
                            ))}
                          </div>
                          <div className="work-actions">
                            {[
                              "write",
                              "prepare",
                              "submit",
                              "check",
                              "render",
                            ].map((x) =>
                              button(
                                `character_act_${x}`,
                                {
                                  job_id: selected.id,
                                  quote_hash: selected.quote_hash ?? "",
                                },
                                x === "write",
                              ),
                            )}
                          </div>
                        </>
                      ) : (
                        <Empty text="캐릭터 PNG와 이야기 주제로 시작하세요." />
                      )}
                    </section>
                  </div>
                  <aside className="work-stack">
                    {preview(currentMedia)}
                    <section className="work-panel inspector">
                      {selected?.referenceUrl && <img className="character-reference" src={selected.referenceUrl} alt="검증된 캐릭터 참조 PNG"/>}
        <h2>작업에 고정된 설정</h2>
                      <dl className="property-list">
                        {Object.entries(
                          selected?.selection ??
                            catalog.characterDefaults ??
                            {},
                        )
                          .filter(
                            ([k]) =>
                              !/(fingerprint|credential|price_basis)/.test(k),
                          )
                          .map(([k, v]) => (
                            <div key={k}>
                              <dt>{label(k)}</dt>
                              <dd>
                                {typeof v === "object"
                                  ? "저장된 설정"
                                  : String(v)}
                              </dd>
                            </div>
                          ))}
                      </dl>
                      <h3>공식 견적</h3>
                      <p>
                        {selected?.quote
                          ? JSON.stringify(selected.quote)
                          : "아직 조회하지 않았습니다."}
                      </p>
                      <p className="muted">
                        Seedance 참조 계약을 유지합니다. 계정 지원 여부는 실제
                        조회 전 미검증입니다.
                      </p>
                    </section>
                  </aside>
                </div>
              </>
            )}
            {module === "images" && (
              <>
                <div
                  className="filters"
                  role="tablist"
                  aria-label="이미지 제작 방식"
                >
                  <button
                    role="tab"
                    aria-selected={tab === "independent"}
                    onClick={() => {
                      setTab("independent");
                      setSelected(null);
                    }}
                  >
                    독립 AI 이미지
                  </button>
                  <button
                    role="tab"
                    aria-selected={tab === "news"}
                    onClick={() => {
                      setTab("news");
                      setSelected(null);
                    }}
                  >
                    뉴스 이미지 게시물
                  </button>
                </div>
                <div className="work-columns production-columns">
                  <div className="work-stack">
                    {tab === "independent" ? (
                      <>
                        <section className="work-panel prompt-panel">
                          <div className="section-heading">
                            <h2>
                              <ImageIcon size={20} /> 이미지 지시문
                            </h2>
                            <span className="pill">OpenAI · 별도 선택</span>
                          </div>
                          <textarea
                            className="prompt-input"
                            aria-label="이미지 지시문"
                            placeholder="어떤 이미지를 만들까요? 주제 · 구도 · 분위기를 적어주세요."
                            value={prompt}
                            onChange={(e) => setPrompt(e.target.value)}
                          />
                          <div className="work-actions">
                            {button("creation_draft", { prompt }, true)}
                            {button("creation_defaults", {})}
                          </div>
                          <div className="review-note">
                            <Info size={17} />
                            <span>
                              참조 이미지는 로컬에 보관됩니다. 참조 기반 유료 AI
                              편집 생성은 미구현이며 실행되지 않습니다.
                            </span>
                          </div>
                        </section>
                        <Collection
                          title="이미지 초안과 결과"
                          items={list("drafts")}
                          onSelect={setSelected}
                          selected={selected?.id}
                        />
                        {selected && (
                          <section className="work-panel">
                            <h2>{itemTitle(selected)}</h2>
                            <Badge value={selected.status} />
                            <div className="work-actions">
                              {button(
                                "creation_generate",
                                { identifier: selected.id },
                                true,
                              )}
                              {button("creation_reuse", {
                                identifier: selected.id,
                              })}
                            </div>
                            <p className="muted">
                              이미지 초안 #{selected.id} · 생성 결과{" "}
                              {selected.outputId
                                ? `#${selected.outputId}`
                                : "없음"}
                            </p>
                          </section>
                        )}
                      </>
                    ) : (
                      <>
                        <section className="work-panel">
                          <h2>뉴스 기반 이미지</h2>
                          <p>
                            기사 선택 → 카드 기획 → 이미지·문구 확인 → 출처 검토
                            → 게시 준비
                          </p>
                          <Collection
                            title="보관 기사"
                            items={list("articles")}
                            onSelect={setSelected}
                            selected={selected?.id}
                          />
                          <div className="work-actions">
                            {button("image_post_claude_card", {
                              article_id: selected?.id,
                            })}
                            {button(
                              "image_post_create",
                              { article_id: selected?.id },
                              true,
                            )}
                          </div>
                        </section>
                        <Collection
                          title="뉴스 이미지 게시물"
                          items={list("posts")}
                          onSelect={setSelected}
                        />
                        <Collection
                          title="상위 3건 선정 기록"
                          items={list("selections")}
                          onSelect={setSelected}
                        />
                        <p className="muted">
                          순위는 저장된 화제성 평가를 사용합니다. 단일 이미지
                          피드만 지원합니다.
                        </p>
                      </>
                    )}
                  </div>
                  <aside className="work-stack">
                    {preview(currentMedia, "image")}
                    <section className="work-panel inspector">
                      <h2>이미지 속성</h2>
                      <dl className="property-list">
                        {Object.entries(
                          selected?.selection ?? catalog.imageDefaults ?? {},
                        ).map(([k, v]) => (
                          <div key={k}>
                            <dt>{label(k)}</dt>
                            <dd>{String(v)}</dd>
                          </div>
                        ))}
                      </dl>
                      <Badge value={selected?.status ?? "draft"} />
                      <p className="muted">{view.policy?.price}</p>
                      <button onClick={() => onNavigate("library")}>
                        <FolderOpen size={17} />
                        소재 라이브러리
                      </button>
                    </section>
                  </aside>
                </div>
              </>
            )}
            {module === "automation" && (
              <>
                <div className="work-toolbar">
                  {button("scheduler_save", {}, true)}
                  {button("autopilot_quick_start", {})}
                </div>
                <div className="work-columns">
                  <div className="work-stack">
                    <Collection
                      title="제작 예약"
                      items={list("schedules")}
                      onSelect={(x) =>
                        setSelected({ ...x, __type: "schedule" })
                      }
                      selected={selected?.id}
                    />
                    <Collection
                      title="예약 실행 기록"
                      items={list("runs")}
                      onSelect={setSelected}
                    />
                    <Collection
                      title="자동 제작 작업"
                      items={list("jobs")}
                      onSelect={setSelected}
                    />
                  </div>
                  <section className="work-panel inspector">
                    <h2>
                      <CalendarDays size={20} /> 선택한 예약
                    </h2>
                    {selected ? (
                      <>
                        <h3>{itemTitle(selected)}</h3>
                        <Badge value={selected.status} />
                        <dl className="property-list">
                          {[
                            "kind",
                            "local_time",
                            "next_run_at",
                            "revision",
                          ].map((k) => (
                            <div key={k}>
                              <dt>{label(k)}</dt>
                              <dd>{String(selected[k] ?? "—")}</dd>
                            </div>
                          ))}
                        </dl>
                        {selected.__type === "schedule" && (
                          <div className="work-actions">
                            {button("scheduler_save", {
                              ...selected,
                              schedule_id: selected.id,
                            })}
                            {button("scheduler_state", {
                              schedule_id: selected.id,
                              revision: selected.revision,
                            })}
                          </div>
                        )}
                        <p>
                          예약 저장과 활성화는 별도입니다. 결과 불명 작업은 자동
                          재요청하지 않습니다.
                        </p>
                      </>
                    ) : (
                      <Empty text="예약을 선택하세요." />
                    )}
                  </section>
                </div>
              </>
            )}
            {module === "library" && (
              <>
                <div className="work-toolbar">
                  <label className="work-search">
                    <Search size={18} />
                    <input
                      aria-label="라이브러리 검색"
                      placeholder="프로젝트·소재 검색"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </label>
                  <div className="filters">
                    {["전체", "news", "character", "image"].map((x) => (
                      <button
                        key={x}
                        aria-pressed={category === x}
                        onClick={() => setCategory(x)}
                      >
                        {(
                          {
                            news: "뉴스 영상",
                            character: "캐릭터",
                            image: "이미지",
                          } as Item
                        )[x] ?? x}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="media-library">
                  {(view.projects ?? [])
                    .filter(
                      (x) =>
                        (category === "전체" || x.kind === category) &&
                        x.title.toLowerCase().includes(query.toLowerCase()),
                    )
                    .map((x) => (
                      <button
                        className="media-tile work-panel"
                        key={x.id}
                        onClick={() => setSelected(x)}
                      >
                        <div className="media-tile-art">
                          {safeMedia(x.thumbnailUrl) ? (
                            <img src={x.thumbnailUrl} alt="저장된 소재" />
                          ) : (
                            <FolderOpen size={36} />
                          )}
                        </div>
                        <strong>{x.title}</strong>
                        <Badge value={x.technicalStatus} />
                      </button>
                    ))}
                </div>
                {selected && (
                  <div className="work-columns">
                    {preview(
                      currentMedia,
                      selected.kind === "image" ? "image" : "video",
                    )}
                    <section className="work-panel">
                      <h2>{selected.title}</h2>
                      <Badge value={selected.technicalStatus} />
                      <button
                        onClick={() =>
                          onNavigate(
                            selected.kind === "news"
                              ? "shorts"
                              : selected.kind === "image"
                                ? "images"
                                : "characters",
                          )
                        }
                      >
                        제작실로 이동 <ChevronRight size={16} />
                      </button>
                      <details>
                        <summary>보관 관리</summary>
                        {selected.kind === "news" && button("cleanup_remove_video", {
                          identifier: String(selected.id).split(":")[1],
                        })}
                      </details>
                    </section>
                  </div>
                )}
                <Collection
                  title="휴지 보관"
                  items={list("removed")}
                  onSelect={(x) => open("cleanup_restore", { item: x.key })}
                />
              </>
            )}
            {module === "publishing" && (
              <>
                <div className="work-toolbar">
                  {button("unified_publishing_local_draft", {}, true)}
                  {button("unified_publishing_review", {})}
                </div>
                <div className="work-columns">
                  <div className="work-stack">
                    <Collection
                      title="로컬 게시 초안"
                      items={list("drafts")}
                      onSelect={setSelected}
                      selected={selected?.id}
                    />
                    <Collection
                      title="플랫폼별 게시 기록"
                      items={list("jobs")}
                      onSelect={setSelected}
                    />
                    <Collection
                      title="단일 이미지 전달 · 게시"
                      items={list("deliveries")}
                      onSelect={setSelected}
                    />
                  </div>
                  <aside className="work-stack">
                    <section className="work-panel inspector">
                      <h2>
                        <Send size={20} /> 게시 검토
                      </h2>
                      {selected ? (
                        <>
                          <h3>{itemTitle(selected)}</h3>
                          <p>{selected.description}</p>
                          <Badge value={selected.state ?? selected.status} />
                          {selected.__type==="cohort" && <><div className="review-checklist">{(selected.targets??[]).map((x:Item)=><p key={x.platform}>{x.platform} <Badge value={x.status}/></p>)}</div>{selected.can_execute?button("unified_publishing_execute",{cohort_id:selected.id,approval_token:selected.approval_token},true):<p className="command-error">검토·권한·플랫폼별 상태를 먼저 확인하세요.</p>}</>}
                          <div className="review-checklist">
                            {[
                              "content_reviewed",
                              "copyright_confirmed",
                              "sources_confirmed",
                            ].map((k) => (
                              <p key={k}>
                                <Check size={16} />
                                {label(k)} ·{" "}
                                {selected[k] ? "기록 있음" : "확인 필요"}
                              </p>
                            ))}
                          </div>
                          <div className="work-actions">
                            {button("publishing_edit", {
                              draft_id: selected.id,
                              ...selected,
                            })}
                            {button("publishing_validate", {
                              draft_id: selected.id,
                            })}
                          </div>
                          <p className="muted">
                            로컬 초안 저장은 계정 연결 없이 가능합니다. 실제
                            게시에는 플랫폼별 승인과 권한이 필요합니다.
                          </p>
                        </>
                      ) : (
                        <Empty text="초안을 선택하세요." />
                      )}
                    </section>
                    <Collection
                      title="계정 연결 메타데이터"
                      items={list("accounts")}
                    />
                    <section className="work-panel">
                      <h2>공개 게시 전 확인</h2>
                      <p>
                        MP4 · 단일 이미지의 게시 상태는 독립적으로 보존됩니다.
                        성공한 게시와 결과 불명 요청은 다시 실행하지 않습니다.
                      </p>
                    </section>
                  </aside>
                </div>
              </>
            )}
            {module === "analytics" && (
              <>
                <div className="work-toolbar">
                  {button("social_collect", {})}
                </div>
                <section className="work-panel">
                  <div className="section-heading">
                    <h2>플랫폼 성과</h2>
                    <span className="muted">실제 수집 기록 기준</span>
                  </div>
                  {list("metrics").length ? (
                    <div className="metric-grid">
                      {list("metrics").map((x) => (
                        <div key={x.id}>
                          <small>
                            {x.platform} ·{" "}
                            {x.synthetic ? "합성 검증 자료" : "수집 지표"}
                          </small>
                          <h3>{x.metric}</h3>
                          <strong>
                            {x.value} <small>{x.unit}</small>
                          </strong>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <Empty text="아직 수집된 성과 지표가 없습니다." />
                  )}
                </section>
                <section className="work-panel">
                  <h2>AI 사용량</h2>
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>모델</th>
                          <th>작업</th>
                          <th>상태</th>
                          <th>입력 토큰</th>
                          <th>출력 토큰</th>
                        </tr>
                      </thead>
                      <tbody>
                        {list("usage").map((x) => (
                          <tr key={x.id}>
                            <td>
                              {x.provider}
                              <small>{x.model}</small>
                            </td>
                            <td>{x.kind}</td>
                            <td>
                              <Badge value={x.status} />
                            </td>
                            <td>{x.prompt_tokens}</td>
                            <td>{x.completion_tokens}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <p className="muted">
                    토큰 사용량은 실제 청구액과 다릅니다. 확인되지 않은 비용을
                    0원으로 표시하지 않습니다.
                  </p>
                </section>
                <Collection
                  title="요청 · 결과 불명 기록"
                  items={list("requests")}
                />
              </>
            )}
            {module === "settings" && (
              <>
                <div className="work-columns">
                  <div className="work-stack">
                    <section className="work-panel">
                      <h2>제작 모드별 기본값</h2>
                      <div className="settings-cards">
                        {[
                          {
                            mode: "shorts",
                            title: "뉴스 쇼츠",
                            icon: Clapperboard,
                            action: "production_preferences",
                          },
                          {
                            mode: "images",
                            title: "독립 이미지",
                            icon: ImageIcon,
                            action: "creation_defaults",
                          },
                          {
                            mode: "characters",
                            title: "캐릭터 쇼츠",
                            icon: Bot,
                            action: "character_character_defaults",
                          },
                        ].map((x) => (
                          <div key={x.mode}>
                            <x.icon size={25} />
                            <h3>{x.title}</h3>
                            <p>다음 작업에 적용 · 기존 작업 설정 유지</p>
                            <button onClick={() => onNavigate(x.mode)}>
                              제작실 열기
                            </button>
                            {button(x.action, {})}
                          </div>
                        ))}
                      </div>
                    </section>
                    <section className="work-panel">
                      <h2>AI · 음성 · 영상 모델</h2>
                      <div className="work-actions">
                        {button("ai_settings_save_ai_settings", {})}
                        {button("video_save_tts", {})}
                        {button("video_ai_save_model_route", {})}
                      </div>
                      <Collection
                        title="등록 영상 모델"
                        items={list("models")}
                      />
                      <p className="muted">
                        등록 계약·공식 가격 근거와 실제 계정 사용 가능 여부는
                        별개입니다.
                      </p>
                    </section>
                    <Collection
                      title="수집 출처"
                      items={list("sources")}
                      onSelect={(x) =>
                        open("sources_edit_source", { ...x, source_id: x.id })
                      }
                    />
                  </div>
                  <aside className="work-stack">
                    <section className="work-panel">
                      <h2>
                        <ShieldCheck size={20} /> API 연결
                      </h2>
                      {(view.services ?? []).map((x) => (
                        <div className="connection-row" key={x.id}>
                          <strong>{x.label}</strong>
                          <Badge
                            value={
                              x.verified
                                ? "success"
                                : x.configured
                                  ? "review_required"
                                  : "blocked"
                            }
                          />
                          <span>
                            {x.configured
                              ? "키 저장 · 인증 미검증"
                              : "키 미설정"}
                          </span>
                        </div>
                      ))}
                      <div className="work-actions">
                        {button("ai_settings_save_key", {})}
                        {button("video_save_tts_key", {})}
                        {button("video_ai_save_key", {})}
                      </div>
                      <p className="muted">
                        저장된 비밀값을 화면·로그·브라우저 저장소로 보내지
                        않습니다.
                      </p>
                    </section>
                    <section className="work-panel">
                      <h2>처음 시작하나요?</h2>
                      <p>기본 설정과 제작 준비 상태를 순서대로 확인합니다.</p>
                      <button onClick={() => onNavigate("onboarding")}>
                        시작 가이드 <ChevronRight size={16} />
                      </button>
                    </section>
                  </aside>
                </div>
              </>
            )}
            {module === "onboarding" && (
              <>
                <section className="work-panel">
                  <h2>제작 환경 준비</h2>
                  <div className="setup-steps">
                    {[
                      "뉴스 자료",
                      "분석 AI",
                      "콘텐츠 길이",
                      "자막",
                      "음성",
                      "제작 점검",
                      "완료",
                    ].map((x, i) => (
                      <button
                        key={x}
                        aria-pressed={scene === i}
                        onClick={() => setScene(i)}
                      >
                        <span>{i + 1}</span>
                        <strong>{x}</strong>
                      </button>
                    ))}
                  </div>
                  <p>
                    선택한 단계의 설정을 저장합니다. 연결 확인과 로컬 제작
                    점검은 사용자가 해당 동작을 선택할 때만 실행됩니다.
                  </p>
                  {button(
                    "setup_step_save",
                    {
                      step: scene + 1,
                      revision: (() => {
                        try {
                          return (
                            JSON.parse(view.settings?.easy_setup ?? "{}")
                              .revision ?? 0
                          );
                        } catch {
                          return 0;
                        }
                      })(),
                    },
                    true,
                  )}
                  <details>
                    <summary>기존 설정 상태</summary>
                    <pre>
                      {view.settings?.easy_setup ?? "아직 시작하지 않았습니다."}
                    </pre>
                  </details>
                </section>
                <div className="work-actions">
                  {button("setup_check", {})}
                  {button("setup_test_production", {})}
                </div>
              </>
            )}
            <details className="work-panel command-catalog">
              <summary>
                <SlidersHorizontal size={18} /> {titles[module]} 세부 기능 ·
                승인 및 복구
              </summary>
              <p className="muted">
                기존 서비스의 개별 저장·확인·승인 경로입니다. 선택만으로
                실행되지 않습니다.
              </p>
              <div className="catalog-actions">
                {actions
                  .filter((x) => x.module === module)
                  .map((x) => (
                    <button
                      key={x.id}
                      disabled={!view.commandsAvailable || x.unsupported}
                      title={x.reason}
                      onClick={() => open(x.id, context)}
                    >
                      <span>{x.label}</span>
                      <small>
                        {x.unsupported
                          ? "미지원"
                          : x.risk === "local"
                            ? "로컬 저장·검토"
                            : "범위·승인 확인"}
                      </small>
                      <ChevronRight size={15} />
                    </button>
                  ))}
              </div>
            </details>
          </>
        )
      )}
      {command && view && (
        <CommandDialog
          key={`${command.action.id}-${JSON.stringify(command.context)}`}
          action={command.action}
          context={command.context}
          view={view}
          onClose={() => setCommand(null)}
          onSaved={saved}
        />
      )}
    </div>
  );
}
