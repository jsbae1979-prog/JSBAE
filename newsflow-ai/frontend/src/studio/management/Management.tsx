import {
  House,
  WandSparkles,
  Newspaper,
  FolderOpen,
  Share2,
  ChartColumn,
  Settings,
  RefreshCw,
} from "lucide-react";
import { CommandDialog } from "../CommandDialog";
import { titles } from "../contracts";
import Automation from "./Automation";
import Library from "./Library";
import Publishing from "./Publishing";
import Analytics from "./Analytics";
import SettingsPanel from "./Settings";
import { useManagement, Advanced, Empty } from "./shared";
import "./management.css";
const nav = [
  { id: "dashboard", label: "홈", icon: House },
  { id: "create", label: "콘텐츠 제작", icon: WandSparkles },
  { id: "news", label: "뉴스 스튜디오", icon: Newspaper },
  { id: "automation", label: "자동화 센터", icon: Settings },
  { id: "library", label: "라이브러리", icon: FolderOpen },
  { id: "publishing", label: "게시 스튜디오", icon: Share2 },
  { id: "analytics", label: "성과 · 비용", icon: ChartColumn },
  { id: "settings", label: "설정 · 관리", icon: Settings },
];
export default function Management({
  module,
  onNavigate,
}: {
  module: string;
  onNavigate: (page: string) => void;
}) {
  const c = useManagement(module),
    Icon = nav.find((x) => x.id === module)?.icon ?? Settings,
    side = ["publishing", "analytics", "settings"].includes(module);
  const subtitle: Record<string, string> = {
    automation: "제작 예약과 실행 상태를 한곳에서 관리하세요.",
    library: "생성된 이미지와 영상을 보관하고, 미리보기·재사용으로 이어갑니다.",
    publishing: "제작한 콘텐츠를 검토하고, 플랫폼별 승인과 결과를 확인하세요.",
    analytics: "확인된 콘텐츠 성과와 AI 사용량·비용을 구분합니다.",
    settings: "제작 설정, AI 모델, 플랫폼 계정과 Windows 환경을 관리합니다.",
  };
  return (
    <div
      className={"management-ui " + (side ? "with-side" : "")}
      data-management={module}
    >
      <nav className="mg-topnav" aria-label="관리 화면 주 메뉴">
        <button className="mg-brand" onClick={() => onNavigate("dashboard")}>
          <WandSparkles />
          NewsFlow <b>AI</b>
          <small>Studio</small>
        </button>
        {nav.map((x) => (
          <button
            key={x.id}
            aria-current={module === x.id ? "page" : undefined}
            onClick={() => onNavigate(x.id)}
          >
            <x.icon size={18} />
            {x.label}
          </button>
        ))}
        <span className="mg-user">로컬 작업실</span>
      </nav>
      <div className="mg-shell">
        {side && (
          <aside className="mg-side-nav">
            <div>
              {nav.map((x) => (
                <button
                  key={x.id}
                  aria-current={module === x.id ? "page" : undefined}
                  onClick={() => onNavigate(x.id)}
                >
                  <x.icon />
                  {x.label}
                </button>
              ))}
            </div>
            <div className="mg-brand-card">
              <WandSparkles size={34} />
              <strong>NewsFlow AI</strong>
              <p>
                뉴스를 콘텐츠로,
                <br />
                콘텐츠를 내 작업으로
              </p>
              <small>저장 자료 · 실제 인증 별도 확인</small>
            </div>
          </aside>
        )}
        <div className="mg-main">
          <header className="mg-page-heading">
            <span className="mg-page-icon">
              <Icon />
            </span>
            <h1>{titles[module]}</h1>
            <p>{subtitle[module]}</p>
            <span className="mg-origin">
              {c.view
                ? /fixture|synthetic/.test(c.view.dataOrigin)
                  ? "합성 검증 자료"
                  : "로컬 저장 자료"
                : "불러오는 중"}
            </span>
            <button
              aria-label="관리 화면 새로고침"
              onClick={() => void c.load()}
              disabled={c.loading}
            >
              <RefreshCw size={16} />
            </button>
          </header>
          {c.error ? (
            <div className="mg-alert" role="alert">
              {c.error}
              <button onClick={() => void c.load()}>다시 읽기</button>
            </div>
          ) : !c.view ? (
            <Empty>관리 자료를 불러오는 중입니다.</Empty>
          ) : (
            <>
              {module === "automation" ? (
                <Automation c={c} onNavigate={onNavigate} />
              ) : module === "library" ? (
                <Library c={c} />
              ) : module === "publishing" ? (
                <Publishing c={c} />
              ) : module === "analytics" ? (
                <Analytics c={c} />
              ) : (
                <SettingsPanel c={c} onNavigate={onNavigate} />
              )}
              <Advanced c={c} module={module} />
            </>
          )}
          {c.extraError && <p className="mg-warning">{c.extraError}</p>}
          {c.notice && (
            <div className="mg-notice" role="status">
              {c.notice}
              <button aria-label="알림 닫기" onClick={() => c.setNotice("")}>
                닫기
              </button>
            </div>
          )}
          <p className="mg-safety">
            유료 생성·실제 계정 인증·공개 게시는 별도 승인입니다. 결과 불명
            요청은 자동 재전송하지 않습니다.
          </p>
          {c.command && c.view && (
            <CommandDialog
              key={c.command.action.id + JSON.stringify(c.command.context)}
              action={c.command.action}
              context={c.command.context}
              view={c.view}
              onClose={() => c.setCommand(null)}
              onSaved={() => {
                void c.load();
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}
