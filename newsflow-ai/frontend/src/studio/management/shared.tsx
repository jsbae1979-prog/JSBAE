import { useEffect, useState, type ReactNode } from "react";
import {
  RefreshCw,
  FolderOpen,
  Film,
  Image as ImageIcon,
  Download,
  ShieldCheck,
} from "lucide-react";
import { actions, status, safeMedia, type Item } from "../contracts";
import { Thumbnail } from "../Thumbnail";
import { useStudio } from "../core/shared";
export type Controller = ReturnType<typeof useManagement>;
export function useManagement(module: string) {
  const c = useStudio(module),
    [workspace, setWorkspace] = useState<Item | null>(null),
    [publishing, setPublishing] = useState<Item | null>(null),
    [extraError, setExtraError] = useState("");
  useEffect(() => {
    let active = true;
    setExtraError("");
    Promise.all(
      ["/api/studio/workspace", "/api/studio/modules/publishing"].map(
        async (url) => {
          const r = await fetch(url, {
            credentials: "same-origin",
            cache: "no-store",
          });
          if (!r.ok) throw Error("연결된 저장 자료를 확인하지 못했습니다.");
          return r.json();
        },
      ),
    )
      .then(([w, p]) => {
        if (active) {
          setWorkspace(w);
          setPublishing(p);
        }
      })
      .catch((e) => {
        if (active) setExtraError(String(e.message));
      });
    return () => {
      active = false;
    };
  }, [module, c.view]);
  return { ...c, workspace, publishing, extraError };
}
export function Panel({
  title,
  children,
  tools,
  className = "",
}: {
  title: string;
  children: ReactNode;
  tools?: ReactNode;
  className?: string;
}) {
  return (
    <section className={"mg-panel " + className}>
      <header>
        <h2>
          <span className="mg-heading-mark">✦</span>
          {title}
        </h2>
        {tools}
      </header>
      {children}
    </section>
  );
}
export function Empty({
  children = "저장된 기록이 없습니다.",
}: {
  children?: ReactNode;
}) {
  return (
    <div className="mg-empty">
      <FolderOpen size={28} />
      <span>{children}</span>
    </div>
  );
}
export function Badge({ value }: { value: unknown }) {
  const v = String(value ?? "pending");
  return (
    <span
      className={
        "mg-badge " +
        (/unknown|fail|blocked|missing/.test(v)
          ? "warn"
          : /success|complete|active/.test(v)
            ? "good"
            : "")
      }
    >
      {status[v] ?? v}
    </span>
  );
}
export function Action({
  c,
  id,
  context = {},
  children,
  primary = false,
  disabled = false,
}: {
  c: Controller;
  id: string;
  context?: Item;
  children?: ReactNode;
  primary?: boolean;
  disabled?: boolean;
}) {
  const a = actions.find((a) => a.id === id);
  return (
    <button
      type="button"
      className={primary ? "mg-primary" : ""}
      disabled={disabled || !a || a.unsupported || !c.view?.commandsAvailable}
      title={a?.reason}
      onClick={() => c.open(id, context)}
    >
      {children ?? a?.label ?? id}
    </button>
  );
}
export function date(v: unknown) {
  if (!v) return "미정";
  const d = new Date(String(v));
  return Number.isFinite(d.getTime())
    ? new Intl.DateTimeFormat("ko-KR", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "Asia/Seoul",
      }).format(d)
    : String(v);
}
export const platforms = [
  { id: "instagram", label: "Instagram Reels · 피드", symbol: "◎" },
  { id: "youtube", label: "YouTube Shorts", symbol: "▶" },
  { id: "tiktok", label: "TikTok", symbol: "♪" },
  { id: "facebook", label: "Facebook Reels", symbol: "f" },
];
export function PlatformIcon({ id }: { id: string }) {
  const p = platforms.find((p) => p.id === id);
  return <span className={"mg-platform-icon " + id}>{p?.symbol ?? "◈"}</span>;
}
export function Media({
  url,
  image = false,
  label = "콘텐츠 미리보기",
}: {
  url?: unknown;
  image?: boolean;
  label?: string;
}) {
  const src = sampleMedia(url) || safeMedia(url);
  return (
    <div
      className={"mg-media " + (image ? "image" : "portrait")}
      aria-label={label}
    >
      {src ? (
        image ? (
          <Thumbnail src={src} alt={label} eager />
        ) : (
          <video
            src={src}
            controls
            playsInline
            preload="metadata"
            aria-label={label}
          />
        )
      ) : (
        <Empty>
          <Film size={28} />
          미리보기 파일 없음
        </Empty>
      )}
    </div>
  );
}
export function sampleMedia(v: unknown) {
  return typeof v === "string" &&
    /^\/api\/samples\/[a-z0-9-]+\/(?:file|poster|copy-file)$/.test(v)
    ? v
    : null;
}
export function Thumb({ item }: { item: Item }) {
  let src = item.sample
    ? sampleMedia(item.posterUrl || item.mediaUrl)
    : safeMedia(item.thumbnailUrl);
  if (src?.startsWith("/studio/assets/design-art-")) src = null;
  if (!src && !item.sample && item.kind === "news") {
    const media = safeMedia(item.mediaUrl);
    if (media && /^\/video\/jobs\/\d+\/file$/.test(media))
      src = media.replace(/\/file$/, "/thumbnail");
  }
  return (
    <div className="mg-thumb">
      {src ? (
        <Thumbnail src={src} alt={item.title || "콘텐츠 썸네일"} />
      ) : (
        <span>
          <ImageIcon size={24} />
          미리보기 없음
        </span>
      )}
    </div>
  );
}
export function Accounts({
  c,
  compact = false,
}: {
  c: Controller;
  compact?: boolean;
}) {
  const accounts = c.publishing?.collections?.accounts;
  const cards = platforms.flatMap((p) => {
    const rows = accounts?.filter((a: Item) => a.platform === p.id) ?? [];
    return rows.length
      ? rows.map((a: Item) => ({ p, rows: [a], key: p.id + a.id }))
      : [{ p, rows: [], key: p.id }];
  });
  return (
    <div className={compact ? "mg-accounts compact" : "mg-accounts"}>
      {cards.map(({ p, rows, key }) => {
        return (
          <article key={key}>
            <h3>
              <PlatformIcon id={p.id} />
              {p.label}
            </h3>
            {rows.length ? (
              rows.map((a: Item) => (
                <p key={a.id}>
                  <strong>{a.label || `계정 #${a.id}`}</strong>
                  <small>등록됨 · 실제 인증/권한 미검증</small>
                </p>
              ))
            ) : (
              <p>{accounts ? "등록 계정 없음" : "계정 정보 미확인"}</p>
            )}
            <Badge
              value={
                ["tiktok", "facebook"].includes(p.id)
                  ? "blocked"
                  : "review_required"
              }
            />
            <Action c={c} id="publishing_account" context={{ platform: p.id }}>
              계정 설정
            </Action>
          </article>
        );
      })}
    </div>
  );
}
export function Advanced({ c, module }: { c: Controller; module: string }) {
  return (
    <details className="mg-advanced">
      <summary>
        <ShieldCheck size={16} />
        기존 상세 기능 · 승인 및 복구
      </summary>
      <p>
        선택하면 기존 검토 창을 엽니다. 유료 실행·계정 인증·공개 게시의 승인을
        대신하지 않습니다.
      </p>
      <div className="mg-actions">
        {actions
          .filter((a) => a.module === module)
          .map((a) => (
            <Action key={a.id} c={c} id={a.id} />
          ))}
      </div>
    </details>
  );
}
export function Refresh({ c }: { c: Controller }) {
  return (
    <button
      aria-label="관리 화면 새로고침"
      onClick={() => void c.load()}
      disabled={c.loading}
    >
      <RefreshCw size={17} />
    </button>
  );
}
export function DownloadLink({ url }: { url: unknown }) {
  const src = sampleMedia(url) || safeMedia(url);
  return src ? (
    <a className="mg-button" href={src + "?download=true"} download>
      <Download size={16} />
      다운로드
    </a>
  ) : null;
}

export function withinPeriod(value: unknown, days: string) {
  if (days === "all") return true;
  const raw = String(value ?? ""),
    day = 86400000,
    today = Math.floor((Date.now() + 9 * 3600000) / day);
  const t = /^\d{4}-\d{2}-\d{2}$/.test(raw)
    ? Date.parse(raw + "T00:00:00Z")
    : Date.parse(raw) + 9 * 3600000;
  const index = Math.floor(t / day);
  return (
    Number.isFinite(index) &&
    index <= today &&
    index >= today - Number(days) + 1
  );
}
