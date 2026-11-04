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
import { Thumbnail } from "./Thumbnail";
import TopThreeFeeds from "./TopThreeFeeds";
import {
  WorkflowSteps,
  PlatformAccounts,
  PlatformFilter,
  CostSummary,
  ImageOptions,
  SetupOverview,
} from "./ApprovedPanels";
import "./approved.css";
import CoreStudios from "./core/CoreStudios";
import Management from "./management/Management";
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
      <span>저장된 제작 자료만 표시합니다.</span>
    </div>
  );
}
function recordDate(value: unknown) {
  const date = new Date(String(value ?? ""));
  return Number.isFinite(date.getTime())
    ? new Intl.DateTimeFormat("ko-KR", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Seoul",
      }).format(date)
    : "저장 기록";
}
function Collection({
  title,
  items,
  onSelect,
  selected,
  className = "",
}: {
  title: string;
  items: Item[];
  onSelect?: (x: Item) => void;
  selected?: unknown;
  className?: string;
}) {
  return (
    <section className={`work-panel ${className}`}>
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
                {safeMedia(x.thumbnailUrl) ? (
                  <Thumbnail
                    src={safeMedia(x.thumbnailUrl)}
                    alt="저장된 항목 썸네일"
                  />
                ) : (
                  <FileText size={19} />
                )}
              </span>
              <span>
                <strong>{itemTitle(x)}</strong>
                <small>
                  {x.publisher ??
                    x.platform ??
                    x.model ??
                    x.local_time ??
                    (x.created_at ? recordDate(x.created_at) : "저장 기록")}
                </small>
              </span>
              {(x.status ?? x.state ?? x.review_status) && (
                <Badge value={x.status ?? x.state ?? x.review_status} />
              )}
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
function LegacyWorkbench({
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
  const [tab, setTab] = useState(
    location.pathname.includes("/feed") ||
      new URLSearchParams(location.search).get("mode") === "news"
      ? "news"
      : "independent",
  );
  const [selectedArticles, setSelectedArticles] = useState<number[]>([]);
  const [scene, setScene] = useState(0);
  const [characterScene, setCharacterScene] = useState<{
    jobId: string;
    index: number;
  } | null>(null);
  const characterSceneSelected =
    characterScene !== null && characterScene.jobId === selected?.id;
  const characterSceneIndex = characterSceneSelected
    ? (characterScene?.index ?? 0)
    : 0;
  const [stage, setStage] = useState(1);
  const [editor, setEditor] = useState<Item | null>(null);
  const [activeDraft, setActiveDraft] = useState<Item | null>(null);
  const [sceneImages, setSceneImages] = useState<string[]>([]);
  const [editorDirty, setEditorDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [characterTopic, setCharacterTopic] = useState("");
  const [zoom, setZoom] = useState(false);
  const [settingsTab, setSettingsTab] = useState("overview");
  const [platformFilter, setPlatformFilter] = useState("all");
  const [accountFilter, setAccountFilter] = useState("all");
  const [accountMetadata, setAccountMetadata] = useState<Item[] | null>(null);
  const [newsMetadata, setNewsMetadata] = useState<Item[] | null>(null);
  const [imageOptions, setImageOptions] = useState<Item>({});
  useEffect(() => {
    setAccountMetadata(null);
    setNewsMetadata(null);
    setPlatformFilter("all");
    setAccountFilter("all");
    if (!["settings", "analytics", "shorts"].includes(module)) return;
    const controller = new AbortController();
    const sourceModule = module === "shorts" ? "news" : "publishing";
    fetch(`/api/studio/modules/${sourceModule}`, {
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
    })
      .then((r) => {
        if (!r.ok) throw Error("account metadata unavailable");
        return r.json();
      })
      .then((d) => {
        if (controller.signal.aborted) return;
        if (d.schemaVersion !== 1 || d.module !== sourceModule) return;
        if (sourceModule === "news" && Array.isArray(d.collections?.articles))
          setNewsMetadata(d.collections.articles);
        else if (Array.isArray(d.collections?.accounts))
          setAccountMetadata(d.collections.accounts);
      })
      .catch(() => {
        if (!controller.signal.aborted) setAccountMetadata(null);
      });
    return () => controller.abort();
  }, [module]);
  const [startupStatus, setStartupStatus] = useState<Item | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const routeInitialized = useRef(false);
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
      if (!routeInitialized.current) {
        routeInitialized.current = true;
        const query = new URLSearchParams(location.search);
        const last = location.pathname.split("/").at(-1) ?? "";
        if (module === "images") {
          const post = query.get("post_id");
          const id = post ?? query.get("draft_id");
          if (id) {
            const item = (
              data.collections[post ? "posts" : "drafts"] ?? []
            ).find((x) => String(x.id) === id);
            if (item)
              setSelected({ ...item, __collection: post ? "posts" : "drafts" });
          }
          if (post) setTab("news");
        }
        if (module === "characters") {
          const id =
            query.get("job_id") ?? (/^[a-f0-9]{32}$/.test(last) ? last : "");
          const item = data.collections.jobs?.find((x) => x.id === id);
          if (item) setSelected(item);
        }
        if (module === "shorts") {
          const id =
            query.get("draft_id") ??
            (/script\/\d+$/.test(location.pathname) ? last : "");
          const draft = data.collections.drafts?.find(
            (x) => String(x.id) === id,
          );
          if (draft) selectDraft(draft);
          const job = query.get("job_id");
          const project = data.projects?.find((x) => x.id === `news:${job}`);
          if (project) setSelected(project);
        }
        if (module === "news") {
          const id =
            query.get("article_id") ?? (/^\d+$/.test(last) ? last : "");
          const item = data.collections.articles?.find(
            (x) => String(x.id) === id,
          );
          if (item) setSelected(item);
        }
      }
      setActiveDraft((old) =>
        old
          ? (data.collections.drafts?.find(
              (x) => String(x.id) === String(old.id),
            ) ?? old)
          : null,
      );
      setSelected((old) => {
        if (!old) return null;
        if (old.__collection) {
          const fresh = data.collections[old.__collection]?.find(
            (x) => String(x.id ?? x.key) === String(old.id ?? old.key),
          );
          return fresh ? { ...fresh, __collection: old.__collection } : old;
        }
        if (old.__type === "plan") {
          const fresh = data.collections.plans?.find(
            (x) => String(x.id) === String(old.id),
          );
          return fresh ? { ...fresh, __type: "plan" } : old;
        }
        if (old.__type === "cohort") {
          const fresh = data.collections.cohorts?.find(
            (x) => String(x.id) === String(old.id),
          );
          return fresh ? { ...fresh, __type: "cohort" } : old;
        }
        if (typeof old.id === "string" && old.id.includes(":"))
          return data.projects?.find((x) => x.id === old.id) ?? old;
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
    routeInitialized.current = false;
    setView(null);
    setSelected(null);
    setEditor(null);
    setActiveDraft(null);
    setSceneImages([]);
    setEditorDirty(false);
    setQuery("");
    setNotice("");
    setCommand(null);
    void load();
  }, [module]);
  const collections = view?.collections ?? {};
  const list = (key: string) => collections[key] ?? [];
  const catalog = view?.catalog ?? {};
  const imageSelection = Object.keys(imageOptions).length
    ? imageOptions
    : (catalog.imageDefaults ?? {});
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
  async function inspectLocal(kind: "voices" | "startup") {
    try {
      const response = await fetch(
        `/api/studio/${kind === "voices" ? "local-voices" : "system-startup"}`,
        { cache: "no-store", credentials: "same-origin" },
      );
      if (!response.ok)
        throw Error(
          "로컬 상태 조회를 완료하지 못했습니다. 기존 설정은 유지됩니다.",
        );
      const result: Item = await response.json();
      if (kind === "startup") setStartupStatus(result);
      else
        setView((old) =>
          old
            ? {
                ...old,
                catalog: {
                  ...old.catalog,
                  voices: result.voices.filter((x: Item) => x.available),
                },
              }
            : old,
        );
      setNotice(
        kind === "voices"
          ? "로컬 목록을 확인했습니다. 실제 음성 생성·사용 가능 검증은 별도입니다."
          : "자동 시작의 현재 상태를 확인했습니다. 등록·해제는 별도 동의가 필요합니다.",
      );
    } catch (e) {
      setNotice(
        e instanceof Error ? e.message : "로컬 정책과 준비 상태를 확인하세요.",
      );
    }
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
    setActiveDraft(draft);
    setSceneImages(
      (draft.imageLinks ?? []).map((x: Item) =>
        x.mode === "manual" ? (x.name ?? "") : "",
      ),
    );
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
    if (activeDraft)
      sessionStorage.setItem(
        `studio-script-${activeDraft.id}-${activeDraft.revision}`,
        JSON.stringify(next),
      );
  }
  async function saveScript() {
    if (!view || !activeDraft || !editor || busy) return;
    setBusy(true);
    try {
      const action = actions.find((x) => x.id === "intelligence_edit")!;
      await submitOriginal(
        action,
        {
          draft_id: activeDraft.id,
          revision: activeDraft.revision,
          content: JSON.stringify(editor),
        },
        view,
        {},
      );
      sessionStorage.removeItem(
        `studio-script-${activeDraft.id}-${activeDraft.revision}`,
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
  function unavailable(action: Action) {
    if (action.unsupported) return action.reason ?? "미지원 기능입니다.";
    if (action.id === "creation_generate" && selected?.reference)
      return "참조 기반 유료 이미지 편집 생성은 미구현입니다.";
    if (action.id === "creation_generate" && selected?.outputId != null)
      return "기존 생성·실패·결과 불명 기록을 보존합니다. 자동 재요청하지 않습니다.";
    if (
      action.id === "creation_reuse" &&
      selected &&
      !safeMedia(selected.mediaUrl)
    )
      return "성공한 검증 이미지가 필요합니다.";
    const allowed: Record<string, string[]> = {
      character_act_write: ["needs_script", "script_failed"],
      character_act_prepare: ["script_review"],
      character_act_submit: ["quoted"],
      character_act_check: ["generating"],
      character_act_render: ["clips_review"],
      "character_act_retry-scene": ["retry_quoted"],
    };
    if (
      action.id === "character_act_retry-scene" &&
      (!selected?.retry_hash || !selected?.retryQuote)
    )
      return "실패 장면의 새 공식 견적과 승인을 먼저 확인하세요.";
    if (
      allowed[action.id] &&
      selected?.state &&
      !allowed[action.id].includes(selected.state)
    )
      return "현재 작업 단계에서 실행할 수 없습니다. 저장된 상태를 먼저 확인하세요.";
    return "";
  }
  const button = (
    id: string,
    ctx: Item = context,
    primary = false,
    caption?: string,
  ) => {
    const a = actions.find((x) => x.id === id);
    const Icon = /key|review|approve|confirm/.test(id)
      ? ShieldCheck
      : /render|video/.test(id)
        ? Clapperboard
        : /write|analyze|generate/.test(id)
          ? Bot
          : /save|draft|defaults|selection/.test(id)
            ? Save
            : Plus;
    return a ? (
      <button
        type="button"
        className={primary ? "primary" : ""}
        disabled={!view?.commandsAvailable || !!unavailable(a)}
        title={unavailable(a)}
        onClick={() => open(id, ctx)}
      >
        <Icon size={16} />
        {caption ?? a.label}
      </button>
    ) : null;
  };
  const editorScenes = Array.isArray(editor?.scenes) ? editor.scenes : [];
  const project = (view?.projects ?? []).find(
    (x) => activeDraft && String(x.draftId) === String(activeDraft.id),
  );
  const characterClipMode =
    module === "characters" &&
    (characterSceneSelected || selected?.state === "clips_review");
  const currentClip = characterClipMode
    ? (selected?.scenes?.[characterSceneIndex]?.mediaUrl ?? null)
    : selected?.__type === "plan"
      ? list("scenes").filter((x) => x.plan_id === selected.id)[scene]?.mediaUrl
      : null;
  const currentMedia = safeMedia(
    characterClipMode
      ? currentClip
      : (currentClip ?? selected?.mediaUrl ?? project?.mediaUrl),
  );
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
            <video
              ref={video}
              controls
              preload="metadata"
              src={media}
              poster={
                !currentClip
                  ? (safeMedia(
                      selected?.thumbnailUrl ?? project?.thumbnailUrl,
                    ) ?? undefined)
                  : undefined
              }
            />
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
    <div
      className="workbench approved-studio"
      data-module={module}
      data-image-mode={tab}
      data-settings-tab={settingsTab}
    >
      <header className="work-heading">
        <div>
          <span className="eyebrow">NEWSFLOW AI STUDIO</span>
          <h1>
            <span className="approved-heading-icon">
              {module === "characters" ? (
                <Bot />
              ) : module === "images" ? (
                <ImageIcon />
              ) : module === "settings" ? (
                <SlidersHorizontal />
              ) : module === "shorts" ? (
                <Clapperboard />
              ) : (
                <Layers />
              )}
            </span>
            {titles[module] ?? "작업 화면"}
          </h1>
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
      {(view?.catalog.imageError || view?.catalog.characterError) && (
        <div className="command-error" role="alert">
          <AlertTriangle size={18} />
          <span>{view.catalog.imageError ?? view.catalog.characterError}</span>
          <button onClick={() => onNavigate("settings")}>기본값 확인</button>
        </div>
      )}
      {notice && (
        <div className="work-notice" role="status">
          <Info size={18} />
          <span>{notice}</span>
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
                <div className="work-columns news-columns approved-news-grid">
                  <section className="work-panel news-archive">
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
                  <aside className="work-panel inspector news-inspector">
                    <h2>선택한 기사</h2>
                    {selected ? (
                      <>
                        <Badge value="review_required" />
                        <div className="approved-article-hero">
                          <Thumbnail
                            src={safeMedia(selected.thumbnailUrl)}
                            alt="선택한 기사 대표 이미지"
                            eager
                          />
                          <h3>{selected.title}</h3>
                        </div>
                        <h3>저장된 기사 요약</h3>
                        <p>{selected.summary || "저장된 요약 없음"}</p>
                      </>
                    ) : (
                      <Empty text="기사를 선택하세요." />
                    )}
                    <section
                      className="news-analysis-panel"
                      aria-label="AI 분석 정보"
                    >
                      <h2>
                        <Bot size={18} /> AI 분석 정보
                      </h2>
                      <p className="review-note">
                        현재 응답에는 기사별 AI 분석 본문·키워드 연결이 제공되지
                        않습니다. 저장된 기사 요약을 AI 분석 결과로 표시하지
                        않습니다.
                      </p>
                      <Collection
                        title="저장된 분석 실행 기록"
                        items={list("analyses")}
                      />
                      <p className="muted">
                        실행 기록은 선택한 기사에 귀속된 분석 본문이 아닙니다.
                      </p>
                    </section>
                  </aside>
                  <aside className="work-panel news-next">
                    <section className="news-source-review">
                      <h2>출처 · 검토</h2>
                      {selected ? (
                        <>
                          {" "}
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
                            대표 이미지의 목록 표시와 영상 사용 권한은
                            별개입니다.
                          </p>
                        </>
                      ) : (
                        <p className="muted">
                          기사를 선택하면 출처를 확인할 수 있습니다.
                        </p>
                      )}
                    </section>
                    <h2>
                      <ChevronRight size={19} />
                      다음 단계로 이동
                    </h2>
                    <p className="muted">
                      선택한 기사와 출처를 확인한 후 제작실로 이동하세요.
                    </p>
                    <button
                      className="primary"
                      onClick={() => onNavigate("shorts")}
                    >
                      <Clapperboard size={18} />
                      뉴스 쇼츠 제작실
                    </button>
                    <button onClick={() => onNavigate("images")}>
                      <ImageIcon size={18} />
                      이미지 제작실
                    </button>
                    <button onClick={() => onNavigate("characters")}>
                      <Bot size={18} />
                      캐릭터 쇼츠 제작실
                    </button>
                    <h3>뉴스 수집 · 분석</h3>
                    <div className="work-actions">
                      {button("routes_collect", {})}
                      {button("serpapi_collect", {})}
                      {button("intelligence_analyze", {
                        article_ids: selectedArticles,
                      })}
                    </div>
                    <p className="review-note">
                      보관 기사 검색과 신규 뉴스 수집은 구분됩니다. 수집 실패 시
                      과거 기사를 최신 뉴스로 표시하지 않습니다.
                    </p>
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
                <div className="work-columns production-columns approved-shorts-grid">
                  <div className="work-stack">
                    <section className="work-panel shorts-source">
                      <h2>
                        <FileText size={18} />
                        기사 및 소재 선택
                      </h2>
                      <div className="record-list">
                        {(newsMetadata ?? []).map((x) => (
                          <button
                            key={x.id}
                            className="record-row"
                            disabled={!view.commandsAvailable}
                            aria-label={`기사 분석 검토 · ${x.title}`}
                            onClick={() =>
                              open("intelligence_analyze", {
                                article_ids: [x.id],
                              })
                            }
                          >
                            <span className="record-icon">
                              <Thumbnail
                                src={safeMedia(x.thumbnailUrl)}
                                alt="기사 출처 제공 썸네일"
                              />
                            </span>
                            <span>
                              <strong>{x.title}</strong>
                              <small>
                                {x.publisher} · {x.category}
                              </small>
                            </span>
                            <ChevronRight size={14} />
                          </button>
                        ))}
                      </div>
                      {newsMetadata === null && (
                        <p className="muted">
                          기사 목록 미확인 · 뉴스 스튜디오에서 선택할 수
                          있습니다.
                        </p>
                      )}
                      <Collection
                        className="shorts-drafts"
                        title="저장된 대본"
                        items={list("drafts")}
                        onSelect={selectDraft}
                        selected={selected?.id}
                      />{" "}
                    </section>
                    <section
                      className="work-panel shorts-edit-group"
                      aria-label="대본 및 세로 미리보기"
                    >
                      <section
                        className="work-panel script-editor"
                        id="script-editor"
                      >
                        <div className="section-heading">
                          <h2>대본 · 장면 편집</h2>
                          {activeDraft && (
                            <span>버전 {activeDraft.revision}</span>
                          )}
                        </div>
                        {editor ? (
                          <>
                            <div className="shorts-editor-fields">
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
                                    <textarea
                                      aria-label="방송용 내레이션"
                                      value={
                                        editorScenes[scene].narration ?? ""
                                      }
                                      maxLength={400}
                                      onChange={(e) => {
                                        const scenes =
                                          structuredClone(editorScenes);
                                        scenes[scene].narration =
                                          e.target.value;
                                        updateEditor({ ...editor, scenes });
                                      }}
                                    />
                                  </label>
                                  <label className="form-field">
                                    <span>화면 자막</span>
                                    <textarea
                                      aria-label="화면 자막"
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
                                  <label className="form-field">
                                    <span>이번 장면 이미지</span>
                                    <select
                                      aria-label="이번 장면 이미지"
                                      value={sceneImages[scene] ?? ""}
                                      onChange={(e) =>
                                        setSceneImages((old) => {
                                          const next = [...old];
                                          next[scene] = e.target.value;
                                          return next;
                                        })
                                      }
                                    >
                                      <option value="">
                                        뉴스 연결 이미지 자동 선택
                                      </option>
                                      <option value="__card__">
                                        기본 이미지 카드
                                      </option>
                                      {(catalog.assets ?? []).map(
                                        (name: string) => (
                                          <option key={name} value={name}>
                                            {name}
                                          </option>
                                        ),
                                      )}
                                    </select>
                                  </label>
                                  <p className="muted">
                                    {activeDraft?.imageLinks?.[scene]?.reason ??
                                      (activeDraft?.imageLinks?.[scene]?.name
                                        ? `저장 연결 · ${activeDraft.imageLinks[scene].name}`
                                        : "이미지 사용권과 출처를 확인한 뒤 제작합니다.")}
                                  </p>
                                  <div className="review-note">
                                    <ShieldCheck size={17} />
                                    <span>
                                      검토 메모 · 방송에 포함하지 않음
                                      <br />
                                      {(
                                        editorScenes[scene].review_notes ??
                                        activeDraft?.review_notes ??
                                        []
                                      ).join(" · ") || "별도 검토 메모 없음"}
                                    </span>
                                  </div>
                                </div>
                              )}
                            </div>
                            <div className="work-actions">
                              <button
                                className="primary"
                                disabled={
                                  busy ||
                                  !editorDirty ||
                                  !view.commandsAvailable
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
                                {JSON.stringify(
                                  activeDraft?.sources ?? {},
                                  null,
                                  2,
                                )}
                              </pre>
                            </details>
                          </>
                        ) : (
                          <Empty text="대본을 선택해 장면을 편집하세요." />
                        )}
                      </section>
                      {preview(currentMedia)}
                    </section>
                    <section
                      className="work-panel shorts-settings"
                      id="voice-options"
                    >
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
                            draft_id: activeDraft?.id,
                            duration: activeDraft?.duration,
                            __extra: {
                              images: editorScenes.map(
                                (_: Item, i: number) => sceneImages[i] ?? "",
                              ),
                            },
                          },
                          true,
                        )}
                        {button("video_load_elevenlabs_voices", {})}
                        {button("video_select_elevenlabs_voice", {})}
                        {button("voice_preview", {})}
                        <button onClick={() => void inspectLocal("voices")}>
                          <RefreshCw size={16} />
                          로컬 음성 목록 확인
                        </button>
                      </div>
                      {view.listeningSummary && (
                        <p className="muted">
                          최근 사람 청취: {view.listeningSummary.label} ·{" "}
                          {view.listeningSummary.date} ·{" "}
                          {view.listeningSummary.sample_linked
                            ? "실제 샘플 연결 기록"
                            : "샘플 연결 확인 필요 · 과거 기록"}
                        </p>
                      )}
                      <div className="audio-samples">
                        {list("audioSamples").map((sample) => (
                          <div key={sample.id}>
                            <strong>{sample.title}</strong>
                            <span className="muted">
                              {sample.provider === "windows"
                                ? "로컬 음성 · 샘플 근거 있음"
                                : "ElevenLabs · 저장된 공개 샘플"}
                            </span>
                            {/^\/(?:video\/tts\/voices\/[a-zA-Z0-9_-]+\/sample|voices\/preview\/preview-[a-f0-9]{32}\.wav)$/.test(
                              sample.mediaUrl ?? "",
                            ) && (
                              <audio
                                controls
                                preload="none"
                                src={sample.mediaUrl}
                              />
                            )}{" "}
                            {sample.provider === "windows" &&
                              button("voice_listening", {
                                preview: sample.id,
                                voice: sample.voice,
                                rate: sample.rate,
                                pause_ms: sample.pause_ms,
                              })}
                          </div>
                        ))}
                      </div>
                    </section>
                    <section className="work-panel" id="ai-scenes">
                      <div className="section-heading">
                        <h2>
                          <Layers size={19} /> AI 영상 · 장면 타임라인
                        </h2>
                        {button("video_ai_create_plan", {
                          draft_id: activeDraft?.id,
                          duration: activeDraft?.duration,
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
                        {(selected?.__type === "plan"
                          ? list("scenes").filter(
                              (x) => x.plan_id === selected.id,
                            )
                          : editorScenes.map((x: Item, i: number) => ({
                              ...x,
                              id: `draft-scene-${i}`,
                              position: i,
                              start_ms:
                                editorScenes
                                  .slice(0, i)
                                  .reduce(
                                    (n: number, v: Item) =>
                                      n + Number(v.seconds ?? 0),
                                    0,
                                  ) * 1000,
                              end_ms:
                                editorScenes
                                  .slice(0, i + 1)
                                  .reduce(
                                    (n: number, v: Item) =>
                                      n + Number(v.seconds ?? 0),
                                    0,
                                  ) * 1000,
                              status: "review_required",
                            }))
                        ).map((x: Item, i: number) => (
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
                    <section className="work-panel shorts-files">
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
                    <section className="work-panel shorts-preflight">
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
                <WorkflowSteps
                  labels={["캐릭터 선택", "스토리 생성", "영상 제작 · 검토"]}
                />
                <div className="work-toolbar">
                  {button("character_create", {}, true)}
                  {button("character_character_defaults", {})}
                </div>
                <div className="work-columns production-columns approved-character-grid">
                  <div className="work-stack">
                    <section className="work-panel character-story">
                      <h2>스토리 · 스토리보드</h2>
                      <label className="form-field">
                        <span>새 이야기 주제</span>
                        <textarea
                          aria-label="새 캐릭터 이야기 주제"
                          placeholder="캐릭터가 어떤 이야기를 들려줄까요?"
                          value={characterTopic}
                          onChange={(e) => setCharacterTopic(e.target.value)}
                        />
                      </label>
                      <div className="work-actions">
                        {button(
                          "character_create",
                          { topic: characterTopic },
                          true,
                          "이 주제로 새 작업 초안",
                        )}
                      </div>
                      <p className="muted">
                        새 작업에만 적용 · 아래 저장된 스토리는 변경하지
                        않습니다.
                      </p>
                      {selected ? (
                        <>
                          <h3>{selected.topic}</h3>
                          <Badge value={selected.state} />
                          <div className="story-copy">
                            {typeof selected.story === "string" ? (
                              selected.story
                            ) : (
                              <>
                                <h3>{selected.story?.title}</h3>
                                <p>
                                  {selected.story?.plan?.situation ??
                                    "저장된 장면 구성을 확인하세요."}
                                </p>
                              </>
                            )}
                          </div>

                          <div className="work-actions">
                            {button(
                              "character_act_write",
                              {
                                job_id: selected.id,
                                quote_hash: selected.quote_hash ?? "",
                              },
                              true,
                            )}
                          </div>
                        </>
                      ) : (
                        <Empty text="캐릭터 PNG와 이야기 주제로 시작하세요." />
                      )}
                    </section>
                  </div>
                  <aside className="work-stack">
                    <section
                      className="work-panel character-reference-panel"
                      aria-label="캐릭터 참조 이미지"
                    >
                      <h2>
                        <ImageIcon size={18} />
                        캐릭터 참조 PNG
                      </h2>
                      <div className="character-reference-frame">
                        <Thumbnail
                          src={
                            selected?.referenceUrl ===
                            `/api/studio/characters/${selected?.id}/reference`
                              ? selected.referenceUrl
                              : null
                          }
                          alt="선택한 작업에 저장된 캐릭터 참조 PNG"
                          eager
                        />
                      </div>
                      <p className="muted">
                        {selected?.referenceUrl
                          ? "이 작업에 저장한 참조 파일 · 생성 결과와 별개"
                          : "저장된 참조 PNG 없음 · 캐릭터 작업 초안에서 선택하세요."}
                      </p>
                    </section>
                    <section
                      className="character-video-group"
                      aria-label="영상 미리보기와 견적"
                    >
                      {preview(currentMedia)}
                      <section className="work-panel inspector">
                        <h2>영상 설정 · 견적</h2>
                        <dl className="property-list">
                          {Object.entries(
                            selected?.selection ??
                              catalog.characterDefaults ??
                              {},
                          )
                            .filter(([k]) =>
                              [
                                "script_model",
                                "video_model",
                                "resolution",
                                "aspect_ratio",
                              ].includes(k),
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
                        <details className="character-advanced">
                          <summary>고급 설정 · 저장된 작업 값</summary>
                          <dl className="property-list">
                            {Object.entries(
                              selected?.selection ??
                                catalog.characterDefaults ??
                                {},
                            )
                              .filter(
                                ([k]) =>
                                  !/(fingerprint|credential|price_basis)/.test(
                                    k,
                                  ) &&
                                  ![
                                    "script_model",
                                    "video_model",
                                    "resolution",
                                    "aspect_ratio",
                                  ].includes(k),
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
                        </details>
                        <h3>공식 견적</h3>
                        <p>
                          {selected?.state === "retry_quoted" &&
                          selected?.retryQuote
                            ? `장면 ${selected.retryQuote.position} 재시도 · USD ${selected.retryQuote.quote_usd}`
                            : selected?.quote
                              ? `전체 장면 · USD ${selected.quote}`
                              : "아직 조회하지 않았습니다."}
                        </p>
                        {selected && (
                          <>
                            <div className="work-actions">
                              {selected.state === "completed" &&
                                selected.mediaUrl && (
                                  <button
                                    type="button"
                                    onClick={() => setCharacterScene(null)}
                                  >
                                    <Play size={16} />
                                    완성 영상 보기
                                  </button>
                                )}
                              {["prepare", "submit", "check", "render"].map(
                                (x) =>
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
                        )}
                        <p className="muted">
                          Seedance 참조 계약을 유지합니다. 계정 지원 여부는 실제
                          조회 전 미검증입니다.
                        </p>
                      </section>
                    </section>
                  </aside>
                </div>
                {selected && (
                  <section className="work-panel character-storyboard">
                    <h2>
                      <Layers size={19} />
                      장면 스토리보드
                    </h2>{" "}
                    <div className="timeline">
                      {(selected.scenes?.length
                        ? selected.scenes
                        : (selected.story?.scenes ?? [])
                      ).map((x: Item, i: number) => (
                        <button
                          key={x.position ?? i}
                          onClick={() => {
                            setCharacterScene({
                              jobId: selected.id,
                              index: i,
                            });
                          }}
                          aria-pressed={
                            (characterSceneSelected ||
                              selected.state === "clips_review") &&
                            characterSceneIndex === i
                          }
                        >
                          <span>장면 {x.position ?? i + 1}</span>
                          <Badge value={x.state} />
                          <p>
                            {[x.caption ?? x.narration, x.action ?? x.prompt]
                              .filter(Boolean)
                              .join(" · ")}
                          </p>
                          <small>{x.seconds ?? "규격 확인"}초</small>
                        </button>
                      ))}
                    </div>
                  </section>
                )}
                <Collection
                  className="character-projects"
                  title="캐릭터 프로젝트"
                  items={list("jobs")}
                  onSelect={setSelected}
                  selected={selected?.id}
                />
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
                  <button
                    role="tab"
                    aria-selected={tab === "top3"}
                    onClick={() => {
                      setTab("top3");
                      setSelected(null);
                    }}
                  >
                    뉴스 TOP 3 자동 제작
                  </button>
                </div>
                {tab === "top3" ? (
                  <TopThreeFeeds
                    selections={list("selections")}
                    catalog={catalog}
                    csrf={view.csrfToken}
                  />
                ) : (
                  <div
                    className={`work-columns production-columns approved-image-grid image-layout-${tab}`}
                  >
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
                            <ImageOptions
                              catalog={catalog}
                              value={imageSelection}
                              onChange={setImageOptions}
                            />
                            <div className="work-actions">
                              {button(
                                "creation_draft",
                                { prompt, ...imageSelection },
                                true,
                              )}
                              {button("creation_defaults", imageSelection)}
                            </div>
                            <div className="review-note">
                              <Info size={17} />
                              <span>
                                참조 이미지는 로컬에 보관됩니다. 참조 기반 유료
                                AI 편집 생성은 미구현이며 실행되지 않습니다.
                              </span>
                            </div>
                          </section>
                          <Collection
                            className="image-history"
                            title="이미지 초안과 결과"
                            items={list("drafts")}
                            onSelect={(x) =>
                              setSelected({ ...x, __collection: "drafts" })
                            }
                            selected={selected?.id}
                          />
                          {selected && (
                            <section className="work-panel image-selected">
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
                          <section className="work-panel news-image-input">
                            <h2>뉴스 기반 이미지</h2>
                            <p>
                              기사 선택 → 카드 기획 → 이미지·문구 확인 → 출처
                              검토 → 게시 준비
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
                            className="news-image-concepts"
                            title="Claude 카드 · 이미지 지시문"
                            items={list("cards")}
                            onSelect={(x) =>
                              setSelected({ ...x, __collection: "cards" })
                            }
                          />
                          <Collection
                            className="news-image-generations"
                            title="뉴스 이미지 생성 결과"
                            items={list("generations")}
                            onSelect={(x) =>
                              setSelected({ ...x, __collection: "generations" })
                            }
                          />
                          {selected?.plan && (
                            <section className="work-panel news-image-plan">
                              <h2>{selected.title}</h2>
                              <Badge value={selected.status} />
                              <p>{selected.plan.body}</p>
                              <details>
                                <summary>이미지 지시문</summary>
                                <p>
                                  {selected.plan.image_prompt ??
                                    "기존 저장 기획"}
                                </p>
                              </details>
                              <div className="work-actions">
                                {selected.__collection === "cards" &&
                                  selected.status === "success" &&
                                  button(
                                    "image_post_generate_card_image",
                                    {
                                      ...selected.options,
                                      card_id: selected.id,
                                    },
                                    true,
                                  )}
                                {selected.__collection === "generations" &&
                                  safeMedia(selected.mediaUrl) &&
                                  button(
                                    "image_post_create",
                                    {
                                      ...selected.options,
                                      card_id: undefined,
                                      generated_id: selected.id,
                                      title: selected.plan.title,
                                      body: selected.plan.body,
                                      hashtags: Array.isArray(
                                        selected.plan.hashtags,
                                      )
                                        ? selected.plan.hashtags.join(" ")
                                        : (selected.plan.hashtags ?? ""),
                                    },
                                    true,
                                  )}
                              </div>
                              <p className="muted">
                                지시문과 생성 파일, 검토한 게시 이미지는 각각
                                보존됩니다.
                              </p>
                            </section>
                          )}
                          <Collection
                            className="news-image-posts"
                            title="뉴스 이미지 게시물"
                            items={list("posts")}
                            onSelect={(x) =>
                              setSelected({ ...x, __collection: "posts" })
                            }
                          />
                          <Collection
                            className="news-image-selections"
                            title="상위 3건 선정 기록"
                            items={list("selections")}
                            onSelect={(x) =>
                              setSelected({ ...x, __collection: "selections" })
                            }
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
                      <section className="work-panel inspector image-properties">
                        <h2>이미지 속성 · 출처</h2>
                        {tab === "news" && selected && (
                          <div className="image-copy-review">
                            <h3>{itemTitle(selected)}</h3>
                            <p>
                              {selected.plan?.body ??
                                selected.body ??
                                selected.summary ??
                                "문구 검토 필요"}
                            </p>
                            <p className="muted">
                              {selected.publisher ??
                                "저장된 출처와 사용권을 확인하세요."}
                            </p>
                          </div>
                        )}
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
                )}
              </>
            )}
            {module === "automation" && (
              <>
                <div className="work-toolbar">
                  {button("scheduler_save", {}, true)}
                  {button("autopilot_quick_start", {})}
                </div>
                <div className="work-columns approved-automation-grid">
                  <div className="work-stack">
                    <section className="work-panel schedule-list">
                      <div className="section-heading">
                        <h2>제작 예약</h2>
                        <span className="muted">
                          {list("schedules").length}개
                        </span>
                      </div>
                      {list("schedules").length ? (
                        <div className="table-scroll">
                          <table className="schedule-table">
                            <thead>
                              <tr>
                                <th>예약명</th>
                                <th>주기</th>
                                <th>실행 시간</th>
                                <th>다음 실행</th>
                                <th>상태</th>
                              </tr>
                            </thead>
                            <tbody>
                              {list("schedules").map((x) => (
                                <tr
                                  key={x.id}
                                  className={
                                    selected?.__type === "schedule" &&
                                    selected.id === x.id
                                      ? "selected"
                                      : ""
                                  }
                                >
                                  <td>
                                    <button
                                      type="button"
                                      aria-pressed={
                                        selected?.__type === "schedule" &&
                                        selected.id === x.id
                                      }
                                      onClick={() =>
                                        setSelected({
                                          ...x,
                                          __type: "schedule",
                                        })
                                      }
                                    >
                                      {x.name || `예약 #${x.id}`}
                                    </button>
                                  </td>
                                  <td>{label(x.kind)}</td>
                                  <td>{x.local_time || "미정"}</td>
                                  <td>
                                    {x.next_run_at
                                      ? recordDate(x.next_run_at)
                                      : "미정"}
                                  </td>
                                  <td>
                                    <Badge value={x.status} />
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <Empty text="저장된 예약이 없습니다." />
                      )}
                      <p className="muted">
                        예약 저장과 활성화는 별도입니다. 지원되지 않는 제작
                        유형은 표시하지 않습니다.
                      </p>
                    </section>
                    <Collection
                      className="schedule-history"
                      title="예약 실행 기록"
                      items={list("runs")}
                      onSelect={setSelected}
                    />
                    <Collection
                      className="autopilot-history"
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
                <div className="approved-library-grid">
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
                          aria-pressed={selected?.id === x.id}
                          key={x.id}
                          onClick={() => setSelected(x)}
                        >
                          <div className="media-tile-art">
                            <Thumbnail
                              src={
                                typeof x.thumbnailUrl === "string" &&
                                x.thumbnailUrl.startsWith(
                                  "/studio/assets/design-art-",
                                )
                                  ? null
                                  : safeMedia(x.thumbnailUrl)
                              }
                              alt="저장된 소재 미리보기"
                            />
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
                          {selected.kind === "news" &&
                            button("cleanup_remove_video", {
                              identifier: String(selected.id).split(":")[1],
                            })}
                        </details>
                      </section>
                    </div>
                  )}
                </div>
                <Collection
                  title="휴지 보관"
                  items={list("removed")}
                  onSelect={(x) => open("cleanup_restore", { item: x.key })}
                />
              </>
            )}
            {module === "publishing" && (
              <>
                <WorkflowSteps
                  labels={[
                    "콘텐츠 선택",
                    "게시 설정",
                    "검토",
                    "최종 승인",
                    "결과 확인",
                  ]}
                />
                <div className="work-toolbar">
                  {button("unified_publishing_local_draft", {}, true)}
                  {button("unified_publishing_review", {})}
                </div>
                <div className="work-columns approved-publishing-grid">
                  <div className="work-stack">
                    <Collection
                      className="publish-drafts"
                      title="로컬 게시 초안"
                      items={list("drafts")}
                      onSelect={setSelected}
                      selected={selected?.id}
                    />
                    <Collection
                      className="publish-history"
                      title="플랫폼별 게시 기록"
                      items={list("jobs")}
                      onSelect={setSelected}
                    />
                    <Collection
                      className="publish-deliveries"
                      title="단일 이미지 전달 · 게시"
                      items={list("deliveries")}
                      onSelect={setSelected}
                    />
                  </div>
                  <aside className="work-stack">
                    <section
                      className="publish-review-group"
                      aria-label="콘텐츠 미리보기와 게시 검토"
                    >
                      {preview(
                        safeMedia(
                          selected?.mediaUrl ??
                            (view.projects ?? []).find(
                              (x) => x.id === `news:${selected?.render_job_id}`,
                            )?.mediaUrl,
                        ),
                      )}
                      <section className="work-panel inspector">
                        <h2>
                          <Send size={20} /> 게시 검토
                        </h2>
                        {selected ? (
                          <>
                            <h3>{itemTitle(selected)}</h3>
                            <p>{selected.description}</p>
                            <Badge value={selected.state ?? selected.status} />
                            {selected.__type === "cohort" && (
                              <>
                                <div className="review-checklist">
                                  {(selected.targets ?? []).map((x: Item) => (
                                    <p key={x.platform}>
                                      {x.platform} <Badge value={x.status} />
                                    </p>
                                  ))}
                                </div>
                                {selected.can_execute ? (
                                  button(
                                    "unified_publishing_execute",
                                    {
                                      cohort_id: selected.id,
                                      approval_token: selected.approval_token,
                                    },
                                    true,
                                  )
                                ) : (
                                  <p className="command-error">
                                    검토·권한·플랫폼별 상태를 먼저 확인하세요.
                                  </p>
                                )}
                              </>
                            )}
                            <div className="review-checklist">
                              {[
                                "content_reviewed",
                                "copyright_confirmed",
                                "sources_confirmed",
                              ].map((k) => (
                                <p key={k}>
                                  {selected[k] ? (
                                    <Check size={16} />
                                  ) : (
                                    <AlertTriangle size={16} />
                                  )}
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
                    </section>
                    <PlatformAccounts
                      accounts={list("accounts")}
                      onSettings={() => onNavigate("settings")}
                    />
                    <section className="work-panel publish-policy">
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
                <CostSummary usage={list("usage")} />
                <PlatformFilter
                  value={platformFilter}
                  onChange={(value) => {
                    setPlatformFilter(value);
                    setAccountFilter("all");
                  }}
                  accounts={accountMetadata}
                  account={accountFilter}
                  onAccount={setAccountFilter}
                />
                <details className="analytics-account-details">
                  <summary>
                    등록 계정 · 권한 확인{" "}
                    <span>
                      {accountMetadata === null
                        ? "계정 정보 미확인"
                        : `${accountMetadata.length}개 등록 · 실제 권한 별도 확인`}
                    </span>
                  </summary>
                  <PlatformAccounts
                    accounts={accountMetadata}
                    onSettings={() => onNavigate("settings")}
                  />
                </details>
                <div className="work-toolbar">
                  {button("social_collect", {})}
                </div>
                <div className="approved-analytics-grid">
                  <div className="work-stack">
                    {" "}
                    <section className="work-panel analytics-metrics">
                      <div className="section-heading">
                        <h2>플랫폼 성과</h2>
                        <span className="muted">수집 · 합성 · 미수집 구분</span>
                      </div>
                      {list("metrics").length ? (
                        <div className="metric-grid">
                          {list("metrics")
                            .filter(
                              (x) =>
                                (platformFilter === "all" ||
                                  x.platform === platformFilter) &&
                                (accountFilter === "all" ||
                                  String(x.account_id) === accountFilter),
                            )
                            .map((x) => (
                              <div key={x.id}>
                                <small>
                                  {x.platform} ·{" "}
                                  {x.synthetic ? "합성 검증 자료" : "수집 지표"}
                                </small>
                                <h3>{x.metric}</h3>
                                <strong>
                                  {x.value == null ? "미수집" : x.value}{" "}
                                  <small>{x.unit}</small>
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
                        토큰 사용량은 실제 청구액과 다릅니다. 확인되지 않은
                        비용을 0원으로 표시하지 않습니다.
                      </p>
                    </section>
                    <p className="review-note">
                      계정 정보가 없는 지표는 계정별 성과로 표시하지 않습니다.
                      계정 선택 시 해당 계정 식별자가 있는 기록만 표시합니다.
                    </p>
                    <Collection
                      title="요청 · 결과 불명 기록"
                      items={list("requests")}
                    />
                  </div>
                  <aside className="work-stack">
                    <Collection
                      title="콘텐츠 기록"
                      items={view.projects ?? []}
                      onSelect={setSelected}
                      selected={selected?.id}
                    />
                    {preview(
                      currentMedia,
                      selected?.kind === "image" ? "image" : "video",
                    )}
                    <section className="work-panel">
                      <h2>비용 자료 구분</h2>
                      <p>
                        AI 토큰 사용량 · 공식 견적 · 실제 청구액은 서로 다른
                        자료입니다.
                      </p>
                      <p className="muted">
                        확인되지 않은 금액과 계정 수는 임의로 채우지 않습니다.
                      </p>
                    </section>
                  </aside>
                </div>
              </>
            )}
            {module === "settings" && (
              <>
                <nav
                  className="approved-settings-tabs"
                  aria-label="설정 항목"
                  role="tablist"
                >
                  {[
                    ["overview", "개요"],
                    ["accounts", "플랫폼 계정"],
                    ["ai", "AI 모델 · API 키"],
                    ["defaults", "제작 기본값"],
                    ["sources", "뉴스 수집"],
                    ["windows", "Windows · 실행"],
                    ["system", "시스템 · 가이드"],
                  ].map(([id, title]) => (
                    <button
                      key={id}
                      role="tab"
                      aria-selected={settingsTab === id}
                      onClick={() => setSettingsTab(id)}
                    >
                      {title}
                    </button>
                  ))}
                </nav>
                {settingsTab === "overview" && (
                  <SetupOverview
                    settings={view.settings}
                    onGuide={() => onNavigate("onboarding")}
                  />
                )}
                {(settingsTab === "overview" || settingsTab === "accounts") && (
                  <PlatformAccounts
                    accounts={accountMetadata}
                    onSettings={() => setSettingsTab("ai")}
                  />
                )}

                <div className="work-columns">
                  <div className="work-stack">
                    <section
                      className="work-panel settings-defaults"
                      hidden={!["overview", "defaults"].includes(settingsTab)}
                    >
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
                    <section
                      className="work-panel settings-models"
                      hidden={!["overview", "ai"].includes(settingsTab)}
                    >
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
                      className={
                        !["overview", "sources"].includes(settingsTab)
                          ? "settings-sources tab-hidden"
                          : "settings-sources"
                      }
                      title="수집 출처"
                      items={list("sources")}
                      onSelect={(x) =>
                        open("sources_edit_source", { ...x, source_id: x.id })
                      }
                    />
                  </div>
                  <aside className="work-stack">
                    <section
                      className="work-panel settings-api"
                      hidden={!["overview", "ai"].includes(settingsTab)}
                    >
                      <h2>
                        <ShieldCheck size={20} /> API 연결
                      </h2>
                      {(view.services ?? []).map((x) => (
                        <div className="connection-row" key={x.id}>
                          <strong>{x.label}</strong>
                          {x.verified ? (
                            <span className="state-badge good">인증 확인</span>
                          ) : (
                            <Badge
                              value={x.configured ? "review_required" : "blocked"}
                            />
                          )}
                          <span>
                            {x.verified
                              ? "인증·모델 확인"
                              : x.configured
                                ? "키 저장 · 인증 미검증"
                                : "키 미설정"}
                          </span>
                        </div>
                      ))}
                      <div className="work-actions">
                        {button(
                          "api_settings_save_key",
                          {},
                          false,
                          "OpenAI · Claude 키 설정",
                        )}
                        {button(
                          "video_save_tts_key",
                          {},
                          false,
                          "ElevenLabs 키 설정",
                        )}
                        {button(
                          "video_ai_save_key",
                          {},
                          false,
                          "Higgsfield 키 설정",
                        )}
                      </div>
                      <p className="muted">
                        저장된 비밀값을 화면·로그·브라우저 저장소로 보내지
                        않습니다.
                      </p>
                    </section>
                    <section
                      className="work-panel settings-windows"
                      hidden={
                        !["overview", "windows", "system"].includes(settingsTab)
                      }
                    >
                      <h2>Windows 실행 · 사용자 검토</h2>
                      <p className="muted">
                        상태는 버튼을 선택할 때만 조회합니다. 등록·해제와 사람
                        검토 기록은 별도입니다.
                      </p>
                      <div className="work-actions">
                        <button onClick={() => void inspectLocal("startup")}>
                          <RefreshCw size={16} />
                          자동 시작 상태 확인
                        </button>
                        {startupStatus?.revision &&
                          button("operations_startup", {
                            revision: startupStatus.revision,
                          })}
                        {button("operations_review", {
                          revision: view.operationsReview?.revision ?? 0,
                        })}
                      </div>
                      {startupStatus && (
                        <p>
                          {startupStatus.status} ·{" "}
                          {startupStatus.message ?? "조회 완료 · 변경 없음"}
                        </p>
                      )}
                      <h2 className="setup-guide-heading">처음 시작하나요?</h2>
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
                      "시작",
                      "뉴스 자료",
                      "분석 AI",
                      "영상 형식",
                      "음성 · 자막",
                      "저장 위치",
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
                  .filter(
                    (x) =>
                      x.module === module &&
                      !x.id.startsWith("creation_feed_batch_"),
                  )
                  .map((x) => (
                    <button
                      key={x.id}
                      disabled={!view.commandsAvailable || !!unavailable(x)}
                      title={unavailable(x)}
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

export default function Workbench(props: {
  module: string;
  onNavigate: (page: string) => void;
}) {
  return ["shorts", "characters", "images", "news"].includes(props.module) ? (
    <CoreStudios key={props.module} {...props} />
  ) : ["automation", "library", "publishing", "analytics", "settings"].includes(
      props.module,
    ) ? (
    <Management key={props.module} {...props} />
  ) : (
    <LegacyWorkbench {...props} />
  );
}
