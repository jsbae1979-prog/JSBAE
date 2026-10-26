import { useEffect, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import {
  House,
  WandSparkles,
  Clapperboard,
  Bot,
  FolderOpen,
  Send,
  ChartNoAxesCombined,
  Settings2,
  Search,
  Bell,
  CircleHelp,
  ChevronRight,
  ChevronLeft,
  ChevronDown,
  Plus,
  Play,
  Film,
  FileText,
  Clock3,
  Image as ImageIcon,
  Mic,
  Globe2,
  Check,
  X,
  LayoutGrid,
  List,
  ArrowRight,
  RefreshCw,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  CalendarDays,
  Sparkles,
  CircleAlert,
  MoreHorizontal,
} from "lucide-react";
import "./style.css";
import Workbench from "./studio/Workbench";

type Kind = "news" | "character" | "image";
type Project = {
  id: string;
  title: string;
  kind: Kind;
  technicalStatus: string;
  contentReviewStatus: string;
  publishApprovalStatus: string;
  updatedAt: string;
  href: string;
  thumbnailUrl: string | null;
  mediaUrl: string | null;
  sourceLabel: string;
};
type Workspace = {
  schemaVersion: 1;
  capabilities?: { legacyAvailable: boolean; workspaceReadOnly: boolean };
  dataOrigin: "local-workspace" | "development-fixtures";
  projects: Project[];
  stats: {
    running: number;
    ready: number;
    publishDrafts: number;
    total: number;
  };
  today: {
    done: number;
    running: number;
    waiting: number;
    failed: number;
    unknown: number;
    total: number;
  };
  services: {
    id: string;
    label: string;
    configured: boolean;
    verified: boolean;
    href: string;
  }[];
  upcoming: { title: string; at: string; href: string }[];
  upcomingStatus: string;
  activity: { title: string; at: string; href: string }[];
};
const TYPES = [
  {
    id: "news" as Kind,
    title: "뉴스 쇼츠",
    subtitle: "뉴스를 AI 영상으로 빠르게 제작",
    art: 4,
    icon: Clapperboard,
    features: [
      "뉴스 수집·화제성 선정",
      "AI 분석 및 대본 검토",
      "선택한 음성·영상 제작",
    ],
    href: "/create",
    tag: "뉴스에서 영상까지",
  },
  {
    id: "character" as Kind,
    title: "캐릭터 쇼츠",
    subtitle: "참조 캐릭터와 이야기로 만드는 영상",
    art: 1,
    icon: Bot,
    features: [
      "캐릭터 참조 이미지",
      "Claude 스토리·장면 구성",
      "공식 견적·검토 후 합성",
    ],
    href: "/character",
    tag: "일관된 캐릭터, 새로운 이야기",
  },
  {
    id: "image" as Kind,
    title: "이미지",
    subtitle: "AI 이미지와 뉴스 이미지 게시물",
    art: 6,
    icon: ImageIcon,
    features: [
      "독립 AI 이미지 생성",
      "뉴스 이미지 카드·상위 3건 피드",
      "검토·저장·소재 재사용",
    ],
    href: "/image-studio",
    tag: "한 장으로 전하는 메시지",
  },
];
const NAV = [
  { id: "dashboard", label: "홈", icon: House },
  { id: "create", label: "콘텐츠 제작", icon: WandSparkles },
  { id: "news", label: "뉴스 스튜디오", icon: Clapperboard, legacy: "/news" },
  { id: "automation", label: "자동화 센터", icon: Bot, legacy: "/schedules" },
  {
    id: "library",
    label: "라이브러리",
    icon: FolderOpen,
    legacy: "/?show=videos",
  },
  {
    id: "publishing",
    label: "게시 스튜디오",
    icon: Send,
    legacy: "/publishing",
  },
  {
    id: "analytics",
    label: "성과 · 비용",
    icon: ChartNoAxesCombined,
    legacy: "/analytics",
  },
  {
    id: "settings",
    label: "설정 · 관리",
    icon: Settings2,
    legacy: "/settings",
  },
];
const labels: Record<string, string> = {
  success: "파일 생성 완료",
  completed: "파일 생성 완료",
  ready: "파일 생성 완료",
  running: "제작 중",
  queued: "대기 중",
  needs_script: "대본 준비",
  needs_review: "검토 필요",
  review_required: "검토 필요",
  failed: "실패 · 확인 필요",
  unknown: "결과 불명",
  draft: "초안",
  blocked: "실행 준비 필요",
  missing: "파일 확인 필요",
};
const art = (n: number) => `/studio/assets/design-art-${n}.webp`;
function date(s: string) {
  const d = new Date(s);
  return Number.isNaN(d.valueOf())
    ? "시각 미확인"
    : new Intl.DateTimeFormat("ko-KR", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Seoul",
      }).format(d);
}
function localHref(url: string) {
  if (!url.startsWith("/") || url.startsWith("//") || url.includes("\\"))
    return "/studio/dashboard";
  if (
    url.startsWith("/studio/") ||
    /\/(?:file|thumbnail|clip)(?:\?|$)/.test(url)
  )
    return url;
  const [path, rawParams] = url.split("?");
  const query = new URLSearchParams(rawParams ?? "");
  if (path.startsWith("/image-posts")) query.set("mode", "news");
  const params = query.toString();
  const page = path.startsWith("/schedules")
    ? "automation"
    : path.startsWith("/character")
      ? "characters"
      : path.startsWith("/image")
        ? "images"
        : path.startsWith("/video") ||
            path.startsWith("/ai") ||
            path === "/create"
          ? "shorts"
          : path.startsWith("/news") || path.startsWith("/sources")
            ? "news"
            : path.startsWith("/publishing")
              ? "publishing"
              : path.startsWith("/analytics")
                ? "analytics"
                : path.includes("settings")
                  ? "settings"
                  : "library";
  return `/studio/${page}${params ? "?" + params : ""}`;
}

function routePage() {
  const parts = location.pathname.split("/");
  if (parts[2] === "create" && parts[3])
    return (
      (
        { news: "shorts", character: "characters", image: "images" } as Record<
          string,
          string
        >
      )[parts[3]] ?? "create"
    );
  return parts[2] || "dashboard";
}
function App() {
  const [page, setPage] = useState(routePage());
  const [routeVersion, setRouteVersion] = useState(0);
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const [display, setDisplay] = useState<"grid" | "list">("grid");
  const [dialog, setDialog] = useState<{
    title: string;
    body: ReactNode;
  } | null>(null);
  const modal = useRef<HTMLDialogElement>(null);
  const search = useRef<HTMLInputElement>(null);
  async function load() {
    setLoading(true);
    setError("");
    try {
      const r = await fetch("/api/studio/workspace", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!r.ok) throw Error("작업 정보를 불러오지 못했습니다.");
      const x: Workspace = await r.json();
      if (x.schemaVersion !== 1 || !Array.isArray(x.projects))
        throw Error("화면 데이터 형식을 확인하세요.");
      setData(x);
    } catch (e) {
      setError(e instanceof Error ? e.message : "연결을 확인하세요.");
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
    const pop = () => setPage(routePage());
    window.addEventListener("popstate", pop);
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        search.current?.focus();
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("popstate", pop);
      window.removeEventListener("keydown", key);
    };
  }, []);
  useEffect(() => {
    if (dialog && !modal.current?.open) modal.current?.showModal();
    if (!dialog && modal.current?.open) modal.current?.close();
  }, [dialog]);
  function go(value: string) {
    setPage(value);
    history.pushState({}, "", `/studio/${value}`);
    setRouteVersion((x) => x + 1);
    window.scrollTo({ top: 0 });
    setQuery("");
    setKind("all");
  }
  function info(title: string, body: ReactNode) {
    setDialog({ title, body });
  }
  function LegacyLink({
    href,
    children,
    className = "primary",
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) {
    return (
      <button
        className={className}
        onClick={() => bridge("작업 이어가기", href)}
      >
        {children}
      </button>
    );
  }

  function bridge(label: string, href: string) {
    const target = href.startsWith("/schedules")
      ? "automation"
      : href.startsWith("/character")
        ? "characters"
        : href.startsWith("/image")
          ? "images"
          : href.startsWith("/ai") ||
              href.startsWith("/video") ||
              href === "/create"
            ? "shorts"
            : href.startsWith("/news") || href.startsWith("/sources")
              ? "news"
              : href.startsWith("/publishing")
                ? "publishing"
                : href.startsWith("/analytics")
                  ? "analytics"
                  : href.startsWith("/settings") ||
                      href.startsWith("/api-settings")
                    ? "settings"
                    : "library";
    setDialog(null);
    go(target);
    const params = new URLSearchParams(href.split("?")[1] ?? "");
    if (href.startsWith("/image-posts")) params.set("mode", "news");
    if (params.size)
      history.replaceState({}, "", `/studio/${target}?${params.toString()}`);
  }
  const projects = (data?.projects ?? []).filter(
    (p) =>
      (kind === "all" || p.kind === kind) &&
      p.title.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const synthetic = data?.dataOrigin === "development-fixtures";
  function ProjectCards({ compact = false }: { compact?: boolean }) {
    return (
      <div className={`projects ${display} ${compact ? "compact" : ""}`}>
        {projects.length ? (
          projects.slice(0, compact ? 4 : 12).map((p) => (
            <button
              className="project"
              key={p.id}
              onClick={() =>
                info(
                  p.title,
                  <>
                    <div className="detail-status">
                      <span className="pill">
                        {labels[p.technicalStatus] ?? p.technicalStatus}
                      </span>
                      <span>
                        내용·출처:{" "}
                        {p.contentReviewStatus === "approved"
                          ? "검토 기록 있음"
                          : "검토 필요"}
                      </span>
                      <span>
                        공개 게시:{" "}
                        {p.publishApprovalStatus === "approved"
                          ? "별도 승인 기록 있음"
                          : "별도 승인 필요"}
                      </span>
                    </div>
                    <p className="muted">
                      파일 생성과 사실·사용권 검토, 공개 게시 승인은 각각
                      확인합니다.
                    </p>
                    {p.mediaUrl &&
                    ["success", "completed", "ready"].includes(
                      p.technicalStatus,
                    ) ? (
                      p.kind === "image" ? (
                        <img
                          className="verified-image"
                          src={localHref(p.mediaUrl)}
                          alt="검토할 생성 이미지"
                        />
                      ) : (
                        <video
                          className="verified-video"
                          controls
                          preload="metadata"
                          src={localHref(p.mediaUrl)}
                        />
                      )
                    ) : (
                      <p className="empty-small">
                        재생할 완성 영상이 없습니다.
                      </p>
                    )}
                    <LegacyLink href={p.href}>
                      현재 작업 열기 <ArrowRight size={17} />
                    </LegacyLink>
                  </>,
                )
              }
            >
              <div className="project-visual">
                {p.thumbnailUrl ? (
                  <img
                    src={localHref(p.thumbnailUrl)}
                    alt={`${p.title} · ${p.sourceLabel}`}
                    loading="lazy"
                    onError={(e) => {
                      e.currentTarget.hidden = true;
                    }}
                  />
                ) : (
                  <div className={`project-placeholder ${p.kind}`}>
                    <Film size={30} />
                    <span>미리보기 없음</span>
                  </div>
                )}
                <span className="type-tag">
                  {TYPES.find((t) => t.id === p.kind)?.title}
                </span>
                {synthetic && <span className="sample-tag">합성 자료</span>}
              </div>
              <div className="project-copy">
                <strong>{p.title}</strong>
                <div className="project-meta">
                  <time>{date(p.updatedAt)}</time>
                  <span className={`pill ${p.technicalStatus}`}>
                    {labels[p.technicalStatus] ?? p.technicalStatus}
                  </span>
                </div>
              </div>
            </button>
          ))
        ) : (
          <div className="empty-state">
            <FolderOpen />
            <strong>
              {query
                ? "검색 결과가 없습니다"
                : "아직 제작한 프로젝트가 없습니다"}
            </strong>
            <span>
              {query
                ? "보관 프로젝트 제목으로 다시 검색하세요."
                : "콘텐츠 유형을 골라 첫 프로젝트를 시작하세요."}
            </span>
            <button
              className="secondary"
              onClick={() => {
                setQuery("");
                go("create");
              }}
            >
              콘텐츠 제작하기 <ArrowRight size={15} />
            </button>
          </div>
        )}
      </div>
    );
  }
  function QuickCards({ full = false }: { full?: boolean }) {
    return (
      <div className={`quick-cards ${full ? "large" : ""}`}>
        {TYPES.map((t) => (
          <button
            key={t.id}
            className={`quick-card ${t.id}`}
            onClick={() =>
              info(
                `${t.title} 시작하기`,
                <>
                  <p>{t.tag}</p>
                  <ul>
                    {t.features.map((x) => (
                      <li key={x}>{x}</li>
                    ))}
                  </ul>
                  {t.id === "image" ? (
                    <div className="workflow-options">
                      <LegacyLink href="/image-studio">
                        <Sparkles size={17} /> AI 이미지 생성
                      </LegacyLink>
                      <LegacyLink className="secondary" href="/image-posts">
                        <FileText size={17} /> 뉴스 이미지 게시물
                      </LegacyLink>
                      <p className="muted">
                        두 기능은 별도 작업입니다. 참조 이미지의 유료 AI 편집은
                        아직 지원하지 않습니다.
                      </p>
                    </div>
                  ) : (
                    <>
                      <p className="muted">
                        모델·비용·외부 전송 범위를 확인한 뒤 승인합니다. 지금은
                        제작실로만 이동합니다.
                      </p>
                      <LegacyLink href={t.href}>
                        {t.title} 제작실 열기 <ArrowRight size={17} />
                      </LegacyLink>
                    </>
                  )}
                </>,
              )
            }
          >
            <img src={art(t.art)} className="feature-art" alt="" />
            <div className="quick-copy">
              {full && <span className="eyebrow">{t.tag}</span>}
              <h3>{t.title}</h3>
              <p>{t.subtitle}</p>
              <ul>
                {t.features.map((x, i) => (
                  <li key={x}>
                    {i === 0 ? (
                      <Globe2 size={15} />
                    ) : i === 1 ? (
                      <FileText size={15} />
                    ) : (
                      <Clapperboard size={15} />
                    )}{" "}
                    {x}
                  </li>
                ))}
              </ul>
            </div>
            <span className="quick-arrow">
              <ArrowRight />
            </span>
          </button>
        ))}
      </div>
    );
  }
  const stats = data?.stats;
  const today = data?.today;
  const todayTotal = today?.total ?? 0;
  const todayDone = today?.done ?? 0;
  return (
    <div className={`app ${collapsed ? "collapsed" : ""}`}>
      <a className="skip-link" href="#main">
        본문으로 이동
      </a>
      <aside className="sidebar">
        <button
          className="brand"
          onClick={() => go("dashboard")}
          aria-label="NewsFlow AI Studio 홈"
        >
          <span className="brand-icon">
            <WandSparkles />
          </span>
          <span>
            NewsFlow <b>AI Studio</b>
          </span>
        </button>
        <nav aria-label="주 메뉴">
          {NAV.map((n) => (
            <button
              key={n.id}
              className={`nav-item ${page === n.id || (n.id === "create" && ["shorts", "characters", "images"].includes(page)) ? "active" : ""}`}
              aria-current={
                page === n.id ||
                (n.id === "create" &&
                  ["shorts", "characters", "images"].includes(page))
                  ? "page"
                  : undefined
              }
              title={n.label}
              onClick={() =>
                n.id === "dashboard" || n.id === "create"
                  ? go(n.id)
                  : bridge(n.label, n.legacy!)
              }
            >
              <n.icon size={23} />
              <span>{n.label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="local-status">
            <ShieldCheck size={18} />
            <div>
              <strong>내 PC 작업실</strong>
              <small>실행·공개 게시 별도 승인</small>
            </div>
          </div>
          <button
            className="sidebar-collapse"
            onClick={() => setCollapsed(!collapsed)}
            aria-label={collapsed ? "메뉴 펼치기" : "메뉴 접기"}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
            <span>메뉴 접기</span>
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <div className="global-search">
            <Search size={20} />
            <input
              ref={search}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="프로젝트 제목을 검색하세요..."
              aria-label="보관 프로젝트 검색"
            />
            <kbd>Ctrl + K</kbd>
            {query && !["dashboard", "create"].includes(page) && (
              <div
                className="global-search-results"
                role="listbox"
                aria-label="보관 프로젝트 검색 결과"
              >
                {projects.length ? (
                  projects.slice(0, 6).map((project) => (
                    <button
                      key={project.id}
                      role="option"
                      aria-selected="false"
                      onClick={() => bridge(project.title, project.href)}
                    >
                      <FileText size={17} />
                      <span>{project.title}</span>
                      <ChevronRight size={16} />
                    </button>
                  ))
                ) : (
                  <p>검색된 보관 프로젝트가 없습니다.</p>
                )}
              </div>
            )}
          </div>
          <div className="top-actions">
            {synthetic && <span className="dev-badge">개발용 합성 자료</span>}
            <button
              className="icon-button"
              aria-label="알림"
              onClick={() =>
                info(
                  "알림",
                  <p>
                    자동 새 요청이나 유료 재시도를 실행하지 않습니다. 진행
                    상황은 현재 작업에서 확인하세요.
                  </p>,
                )
              }
            >
              <Bell size={21} />
            </button>
            <button
              className="icon-button"
              aria-label="사용 안내"
              onClick={() =>
                info(
                  "작업실 사용 안내",
                  <>
                    <p>
                      콘텐츠 유형을 선택하고, 저장된 작업을 이어서 진행하세요.
                    </p>
                    <p>
                      새 React 화면은 기존 Python 제작 엔진과 같은 검토·동의
                      경계를 사용합니다. 실제 API·계정 연결·공개 게시 성공은
                      따로 검증해야 합니다.
                    </p>
                  </>,
                )
              }
            >
              <CircleHelp size={21} />
            </button>
            <span className="top-divider" />
            <button
              className="profile"
              onClick={() => bridge("설정 · 관리", "/settings")}
            >
              <span className="avatar">
                <House size={18} />
              </span>
              <span>로컬 작업실</span>
              <ChevronDown size={15} />
            </button>
          </div>
        </header>
        <main id="main" tabIndex={-1} className="main">
          <div className="screen-reader" aria-live="polite">
            {loading
              ? "작업 정보 불러오는 중"
              : error || `${projects.length}개 프로젝트`}
          </div>
          {error && (
            <div className="error-bar" role="alert">
              <CircleAlert size={19} />
              {error}
              <button onClick={() => void load()}>
                <RefreshCw size={16} />
                다시 불러오기
              </button>
            </div>
          )}
          {page === "dashboard" ? (
            <div className="dashboard">
              <div className="dashboard-center">
                <section className="hero panel">
                  <img
                    className="hero-art"
                    src={art(7)}
                    alt="지구와 뉴스·캐릭터 콘텐츠를 표현한 브랜드 일러스트"
                  />
                  <div className="hero-copy">
                    <span className="eyebrow">NEWSFLOW AI STUDIO</span>
                    <h1>
                      뉴스가 세상을 움직입니다
                      <br />
                      <em>AI로 더 빠르고, 더 강력하게</em>
                    </h1>
                    <p>
                      아이디어를 뉴스로, 뉴스를 영상으로.
                      <br />
                      세상의 모든 이야기를 AI와 함께 만드세요.
                    </p>
                    <button
                      className="primary hero-button"
                      onClick={() => go("create")}
                    >
                      <Plus size={22} />새 프로젝트 시작하기
                      <ChevronRight size={20} />
                    </button>
                  </div>
                </section>
                <section className="stats" aria-label="제작 현황">
                  {[
                    {
                      icon: Play,
                      label: "진행 중 작업",
                      value: stats?.running,
                      href: "/?show=tasks",
                      cls: "cyan",
                    },
                    {
                      icon: Film,
                      label: "생성된 파일",
                      value: stats?.ready,
                      href: "/?show=videos",
                      cls: "purple",
                    },
                    {
                      icon: Clock3,
                      label: "게시 초안",
                      value: stats?.publishDrafts,
                      href: "/publishing",
                      cls: "pink",
                    },
                    {
                      icon: FileText,
                      label: "전체 제작 기록",
                      value: stats?.total,
                      href: "/?show=tasks",
                      cls: "indigo",
                    },
                  ].map((s) => (
                    <button
                      className="stat panel"
                      key={s.label}
                      title="뉴스 영상·독립 이미지·캐릭터 제작 기록 기준"
                      onClick={() => bridge(s.label, s.href)}
                    >
                      <span className={`stat-icon ${s.cls}`}>
                        <s.icon size={26} />
                      </span>
                      <div>
                        <span>{s.label}</span>
                        <strong>{loading ? "—" : (s.value ?? "—")}</strong>
                      </div>
                      <ChevronRight className="stat-chevron" size={19} />
                    </button>
                  ))}
                </section>
                <section className="recent">
                  <div className="section-heading">
                    <h2>최근 프로젝트</h2>
                    <button
                      className="text-button"
                      onClick={() => go("create")}
                    >
                      전체 보기 <ChevronRight size={15} />
                    </button>
                  </div>
                  <ProjectCards compact />
                </section>
                <section className="quick-section">
                  <div className="section-heading">
                    <h2>빠른 제작 시작</h2>
                    <p>
                      만들 콘텐츠를 선택하고, AI와 함께 이야기를 완성하세요.
                    </p>
                  </div>
                  <QuickCards />
                </section>
              </div>
              <aside
                className="dashboard-side"
                aria-label="작업 현황과 연결 상태"
              >
                <section className="panel today">
                  <div className="section-heading">
                    <h2>오늘의 작업 상태</h2>
                    <button
                      className="text-button"
                      aria-label="오늘 작업 상태 자세히"
                      onClick={() => bridge("작업 현황", "/?show=tasks")}
                    >
                      자세히 보기 <ChevronRight size={14} />
                    </button>
                  </div>
                  <p className="date">
                    {new Intl.DateTimeFormat("ko-KR", {
                      dateStyle: "full",
                      timeZone: "Asia/Seoul",
                    }).format(new Date())}
                  </p>
                  <div className="today-body">
                    <div className="ring">
                      <svg viewBox="0 0 120 120" aria-hidden="true">
                        <circle cx="60" cy="60" r="49" className="ring-track" />
                        <circle
                          cx="60"
                          cy="60"
                          r="49"
                          className="ring-progress"
                          strokeDasharray={`${todayTotal ? (todayDone / todayTotal) * 308 : 0} 308`}
                        />
                      </svg>
                      <div>
                        <strong>
                          {todayDone}
                          <small>/{todayTotal}</small>
                        </strong>
                        <span>오늘의 작업</span>
                      </div>
                    </div>
                    <dl className="legend">
                      {[
                        ["완료", todayDone, "done"],
                        ["진행 중", today?.running ?? 0, "running"],
                        ["검토·대기", today?.waiting ?? 0, "waiting"],
                      ].map(([k, v, c]) => (
                        <div key={String(k)}>
                          <dt>
                            <i className={String(c)} />
                            {k}
                          </dt>
                          <dd>{v}</dd>
                        </div>
                      ))}
                    </dl>
                  </div>
                  {!!(today?.failed || today?.unknown) && (
                    <p className="attention">
                      실패 {today?.failed ?? 0} · 결과 불명{" "}
                      {today?.unknown ?? 0} — 재요청 금지
                    </p>
                  )}
                </section>
                <section className="panel upcoming">
                  <div className="section-heading">
                    <h2>다가오는 일정</h2>
                    <button
                      className="text-button"
                      onClick={() => bridge("제작 스케줄", "/schedules")}
                    >
                      전체 보기 <ChevronRight size={14} />
                    </button>
                  </div>
                  {data?.upcoming.length ? (
                    <ol className="schedule-list">
                      {data.upcoming.map((s, i) => (
                        <li key={i}>
                          <time>{date(s.at)}</time>
                          <a href={localHref(s.href)}>{s.title}</a>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <div className="side-empty">
                      <CalendarDays size={29} />
                      <strong>
                        {data?.upcomingStatus === "not-connected"
                          ? "일정 조회 연결 준비 중"
                          : "예약된 일정이 없습니다"}
                      </strong>
                      <button
                        className="text-button"
                        onClick={() => bridge("제작 스케줄", "/schedules")}
                      >
                        제작 일정 살펴보기 <ChevronRight size={14} />
                      </button>
                    </div>
                  )}
                </section>
                <section className="panel services">
                  <div className="section-heading">
                    <h2>AI 서비스</h2>
                    <button
                      className="text-button"
                      onClick={() => bridge("API 연결 설정", "/settings")}
                    >
                      관리하기 <ChevronRight size={14} />
                    </button>
                  </div>
                  <div className="service-list">
                    {data?.services.map((s, i) => (
                      <button
                        key={s.id}
                        onClick={() => bridge(s.label, s.href)}
                      >
                        <span className={`service-icon s${i}`}>
                          <Sparkles size={19} />
                        </span>
                        <strong>{s.label}</strong>
                        <span
                          className={`connection ${s.verified ? "verified" : s.configured ? "configured" : ""}`}
                        >
                          <i />
                          {s.verified
                            ? "확인됨"
                            : s.configured
                              ? "키 저장 · 미검증"
                              : "미설정"}
                        </span>
                      </button>
                    ))}
                  </div>
                  <p className="service-note">
                    저장된 키와 실제 연결 확인은 별개입니다.
                  </p>
                </section>
                <section className="panel activity">
                  <div className="section-heading">
                    <h2>최근 활동</h2>
                    <button
                      className="text-button"
                      onClick={() => bridge("작업 기록", "/?show=tasks")}
                    >
                      전체 보기 <ChevronRight size={14} />
                    </button>
                  </div>
                  {data?.activity.length ? (
                    <ul>
                      {data.activity.slice(0, 3).map((a, i) => (
                        <li key={i}>
                          <span className="activity-icon">
                            <FileText size={19} />
                          </span>
                          <a href={localHref(a.href)}>
                            {a.title}
                            <time>{date(a.at)}</time>
                          </a>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="empty-small">아직 활동 기록이 없습니다.</p>
                  )}
                </section>
              </aside>
            </div>
          ) : page === "create" ? (
            <div className="create-page">
              <div className="create-heading">
                <div>
                  <span className="eyebrow">CONTENT CREATION</span>
                  <h1>어떤 콘텐츠를 만들까요?</h1>
                  <p>
                    뉴스, 캐릭터, 이미지. 아이디어에 맞는 제작실을 선택하세요.
                  </p>
                </div>
                <span className="creation-mark">
                  <WandSparkles size={38} />
                </span>
              </div>
              <QuickCards full />
              <section className="projects-section">
                <div className="section-heading">
                  <div>
                    <h2>이어서 작업하기</h2>
                    <p>저장된 프로젝트의 모델과 검토 상태를 이어갑니다.</p>
                  </div>
                  <div className="view-switch">
                    <button
                      aria-label="카드 보기"
                      aria-pressed={display === "grid"}
                      onClick={() => setDisplay("grid")}
                    >
                      <LayoutGrid size={18} />
                    </button>
                    <button
                      aria-label="목록 보기"
                      aria-pressed={display === "list"}
                      onClick={() => setDisplay("list")}
                    >
                      <List size={18} />
                    </button>
                  </div>
                </div>
                <div className="filters" aria-label="프로젝트 유형">
                  {[
                    ["all", "전체"],
                    ["news", "뉴스 쇼츠"],
                    ["character", "캐릭터 쇼츠"],
                    ["image", "이미지"],
                  ].map(([id, label]) => (
                    <button
                      key={id}
                      aria-pressed={kind === id}
                      onClick={() => setKind(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <ProjectCards />
              </section>
              <div className="local-footer">
                <ShieldCheck size={18} />
                <span>
                  원본 파일은 내 PC에 보관됩니다. 외부 생성과 공개 게시는 별도
                  승인이 필요합니다.
                </span>
              </div>
            </div>
          ) : (
            <Workbench
              key={`${page}-${routeVersion}`}
              module={page}
              onNavigate={go}
            />
          )}
        </main>
        <dialog
          ref={modal}
          onCancel={() => setDialog(null)}
          onClose={() => setDialog(null)}
          onClick={(e) => {
            if (e.target === modal.current) setDialog(null);
          }}
        >
          <div className="dialog-head">
            <h2>{dialog?.title}</h2>
            <button
              className="icon-button"
              aria-label="닫기"
              onClick={() => setDialog(null)}
            >
              <X size={22} />
            </button>
          </div>
          <div className="dialog-content">{dialog?.body}</div>
        </dialog>
      </div>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
