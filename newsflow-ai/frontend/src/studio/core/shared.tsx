import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  RefreshCw,
  ShieldCheck,
  Image as ImageIcon,
  Download,
  Film,
  Sparkles,
  Newspaper,
  Layers3,
  Bot,
  BookOpen,
} from "lucide-react";
import {
  actions,
  safeMedia,
  status,
  type Item,
  type View,
  type Action,
} from "../contracts";
import CoreNavigation from "./CoreNavigation";
import { CommandDialog } from "../CommandDialog";
import { Thumbnail } from "../Thumbnail";

export type Controller = ReturnType<typeof useStudio>;
export function useStudio(module: string) {
  const [view, setView] = useState<View | null>(null),
    [context, setContext] = useState<Item | null>(null),
    [error, setError] = useState("");
  const [notice, setNotice] = useState(""),
    [loading, setLoading] = useState(true),
    [command, setCommand] = useState<{ action: Action; context: Item } | null>(
      null,
    );
  const version = useRef(0);
  const load = useCallback(async () => {
    const n = ++version.current;
    setLoading(true);
    setError("");
    try {
      const fetchJson = async (url: string) => {
        const r = await fetch(url, {
          credentials: "same-origin",
          cache: "no-store",
        });
        if (!r.ok)
          throw Error(
            "저장 자료를 읽지 못했습니다. 생성 요청을 다시 보내지 않고 새로고침하세요.",
          );
        return r.json();
      };
      const [v, c] = await Promise.all([
        fetchJson(`/api/studio/modules/${module}`),
        ["shorts", "news"].includes(module)
          ? fetchJson("/api/studio/production-context")
          : Promise.resolve({ schemaVersion: 1, top3: [], selection: null }),
      ]);
      if (
        v.schemaVersion !== 1 ||
        v.module !== module ||
        !v.collections ||
        c.schemaVersion !== 1 ||
        !Array.isArray(c.top3)
      )
        throw Error("자료 형식을 확인하세요.");
      if (n === version.current) {
        setView(v);
        setContext(c);
      }
    } catch (e) {
      if (n === version.current)
        setError(e instanceof Error ? e.message : "불러오기 실패");
    } finally {
      if (n === version.current) setLoading(false);
    }
  }, [module]);
  useEffect(() => {
    void load();
    return () => {
      ++version.current;
    };
  }, [load]);
  function open(id: string, ctx: Item = {}) {
    const action = actions.find((a) => a.id === id);
    if (!action || action.unsupported || !view?.commandsAvailable) {
      setNotice(action?.reason ?? "현재 명령을 사용할 수 없습니다.");
      return;
    }
    setCommand({ action, context: ctx });
  }
  return {
    view,
    context,
    error,
    notice,
    setNotice,
    loading,
    load,
    open,
    command,
    setCommand,
    list: (key: string) => view?.collections[key] ?? [],
  };
}
export function Panel({
  title,
  children,
  className = "",
  tools,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  tools?: ReactNode;
}) {
  return (
    <section className={`core-panel ${className}`}>
      <header>
        <h2>
          <span className="core-panel-icon" aria-hidden="true">
            {/영상|스토리보드/.test(title) ? (
              <Film size={20} />
            ) : /뉴스|출처/.test(title) ? (
              <Newspaper size={20} />
            ) : /설정|기록|이력/.test(title) ? (
              <Layers3 size={20} />
            ) : (
              <Sparkles size={20} />
            )}
          </span>
          {title}
        </h2>
        {tools}
      </header>
      {children}
    </section>
  );
}
export function Empty({
  children = "저장된 결과가 없습니다.",
}: {
  children?: ReactNode;
}) {
  return (
    <div className="core-empty">
      <ImageIcon size={30} />
      <span>{children}</span>
    </div>
  );
}
export function State({ value }: { value: unknown }) {
  const v = String(value ?? "draft");
  return (
    <span
      className={`core-state ${/unknown|fail|missing|blocked/.test(v) ? "attention" : ""}`}
    >
      {status[v] ?? v}
    </span>
  );
}
export function Media({
  url,
  kind = "video",
  label = "9:16 미리보기",
}: {
  url?: unknown;
  kind?: "video" | "image";
  label?: string;
}) {
  const src = safeMedia(url);
  return (
    <div className={`core-media ${kind}`} aria-label={label}>
      {src ? (
        kind === "video" ? (
          <video
            controls
            playsInline
            preload="metadata"
            src={src}
            aria-label={label}
          />
        ) : (
          <Thumbnail src={src} alt={label} />
        )
      ) : (
        <Empty>
          {kind === "video" ? (
            <>
              <Film size={24} />
              완성 영상이 없습니다.
            </>
          ) : (
            "미리보기 없음"
          )}
        </Empty>
      )}
      {src && (
        <a className="core-download" href={`${src}?download=true`} download>
          <Download size={15} />
          저장
        </a>
      )}
    </div>
  );
}
export function NewsImage({ item }: { item: Item }) {
  const src =
    typeof item.thumbnailUrl === "string" &&
    /^\/news\/\d+\/thumbnail$/.test(item.thumbnailUrl)
      ? item.thumbnailUrl
      : safeMedia(item.thumbnailUrl);
  return src ? (
    <Thumbnail src={src} alt="기사 대표 이미지" />
  ) : (
    <Empty>기사 이미지 없음</Empty>
  );
}
export function ImageTabs({
  mode,
  onChange,
}: {
  mode: string;
  onChange: (mode: string) => void;
}) {
  return (
    <div className="core-tabs" role="tablist" aria-label="이미지 제작실">
      <button
        role="tab"
        aria-label="AI 이미지 생성"
        aria-selected={mode === "standalone"}
        onClick={() => onChange("standalone")}
      >
        <ImageIcon size={25} />
        <span>
          <strong>AI 이미지 생성</strong>
          <small>원하는 이미지를 직접 생성합니다</small>
        </span>
      </button>
      <button
        role="tab"
        aria-label="뉴스 기반 이미지"
        aria-selected={mode === "top3"}
        onClick={() => onChange("top3")}
      >
        <Newspaper size={25} />
        <span>
          <strong>뉴스 기반 이미지</strong>
          <small>저장된 TOP 3 분석을 재사용합니다</small>
        </span>
      </button>
    </div>
  );
}
export function Command({ c }: { c: Controller }) {
  return c.command && c.view ? (
    <CommandDialog
      key={`${c.command.action.id}-${JSON.stringify(c.command.context)}`}
      action={c.command.action}
      context={c.command.context}
      view={c.view}
      onClose={() => c.setCommand(null)}
      onSaved={() => {
        void c.load();
      }}
    />
  ) : null;
}
export function StudioFrame({
  c,
  title,
  subtitle,
  module,
  imageMode,
  onNavigate,
  children,
}: {
  c: Controller;
  title: string;
  subtitle: string;
  module: string;
  imageMode: string;
  onNavigate: (page: string) => void;
  children: ReactNode;
}) {
  return (
    <div
      className="core-studio"
      data-module={module}
      data-image-mode={imageMode}
    >
      {module !== "shorts" &&
        !(module === "images" && imageMode === "top3") && (
          <CoreNavigation module={module} onNavigate={onNavigate} />
        )}
      <div className="core-content">
        <div className="core-heading">
          <div>
            <span className="core-title-icon" aria-hidden="true">
              {module === "characters" ? (
                <Bot size={27} />
              ) : module === "news" ? (
                <Newspaper size={27} />
              ) : module === "images" ? (
                <ImageIcon size={27} />
              ) : (
                <Film size={27} />
              )}
            </span>
            <h1>{title}</h1>
            <p>{subtitle}</p>
          </div>
          <div className="core-actions">
            <span className="core-origin">
              {c.view
                ? /fixture|synthetic/.test(c.view.dataOrigin)
                  ? "합성 검증 자료"
                  : "로컬 저장 자료"
                : "불러오는 중"}
            </span>
            <button
              onClick={() => void c.load()}
              disabled={c.loading}
              aria-label="제작실 새로고침"
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </div>
        {c.error ? (
          <div role="alert" className="core-notice">
            {c.error}
            <button onClick={() => void c.load()}>다시 읽기</button>
          </div>
        ) : c.view ? (
          children
        ) : (
          <Empty>제작실 자료를 불러오는 중입니다.</Empty>
        )}
        {c.notice && (
          <div role="status" className="core-notice">
            {c.notice}
          </div>
        )}
        <p className="core-safety">
          <ShieldCheck size={14} /> 생성·비용 승인과 최종 게시 승인은
          별도입니다. 결과 불명 요청은 자동 재실행하지 않습니다.
        </p>
      </div>
      <Command c={c} />
    </div>
  );
}
export function ActionButton({
  c,
  id,
  context = {},
  children,
  disabled = false,
  primary = false,
  title,
}: {
  c: Controller;
  id: string;
  context?: Item;
  children: ReactNode;
  disabled?: boolean;
  primary?: boolean;
  title?: string;
}) {
  const a = actions.find((a) => a.id === id);
  return (
    <button
      type="button"
      className={primary ? "primary" : ""}
      disabled={disabled || !c.view?.commandsAvailable || !a || !!a.unsupported}
      title={title ?? a?.reason}
      onClick={() => c.open(id, context)}
    >
      {children}
    </button>
  );
}
export function Select({
  label,
  value,
  onChange,
  options,
  disabled = false,
}: {
  label: string;
  value: unknown;
  onChange: (v: string) => void;
  options: Record<string, string> | string[];
  disabled?: boolean;
}) {
  const entries = Array.isArray(options)
    ? options.map((x) => [x, x])
    : Object.entries(options);
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={String(value ?? "")}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
      >
        {!entries.some(([k]) => k === "") && (
          <option value="" disabled>
            선택하세요
          </option>
        )}
        {entries.map(([k, v]) => (
          <option key={k} value={k}>
            {v}
          </option>
        ))}
      </select>
    </label>
  );
}
