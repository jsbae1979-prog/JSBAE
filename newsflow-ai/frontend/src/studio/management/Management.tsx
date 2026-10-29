import {
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
const headingIcons = {
  automation: Settings,
  library: FolderOpen,
  publishing: Share2,
  analytics: ChartColumn,
  settings: Settings,
};
export default function Management({
  module,
  onNavigate,
}: {
  module: string;
  onNavigate: (page: string) => void;
}) {
  const c = useManagement(module),
    Icon = headingIcons[module as keyof typeof headingIcons] ?? Settings;
  const subtitle: Record<string, string> = {
    automation: "제작 예약과 실행 상태를 한곳에서 관리하세요.",
    library: "생성된 이미지와 영상을 보관하고, 미리보기·재사용으로 이어갑니다.",
    publishing: "제작한 콘텐츠를 검토하고, 플랫폼별 승인과 결과를 확인하세요.",
    analytics: "확인된 콘텐츠 성과와 AI 사용량·비용을 구분합니다.",
    settings: "제작 설정, AI 모델, 플랫폼 계정과 Windows 환경을 관리합니다.",
  };
  return (
    <div
      className="management-ui"
      data-management={module}
    >
      <div className="mg-shell">
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
