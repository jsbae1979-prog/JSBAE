import {
  Clapperboard,
  ChevronDown,
  Home,
  Video,
  Image,
  Newspaper,
  CalendarClock,
  Folder,
  Send,
  ChartNoAxesCombined,
  Settings,
  Bot,
} from "lucide-react";
const links = [
  ["dashboard", "홈", Home],
  ["create", "콘텐츠 제작", Video],
  ["news", "뉴스 스튜디오", Newspaper],
  ["automation", "자동화 센터", CalendarClock],
  ["library", "라이브러리", Folder],
  ["publishing", "게시 스튜디오", Send],
  ["analytics", "성과·비용", ChartNoAxesCombined],
  ["settings", "설정·관리", Settings],
] as const;
export default function CoreNavigation({
  module,
  onNavigate,
}: {
  module: string;
  onNavigate: (page: string) => void;
}) {
  return (
    <nav className="core-navigation" aria-label="제작실 메뉴">
      <button className="core-brand" onClick={() => onNavigate("dashboard")}>
        <Clapperboard size={25} />
        <strong>
          NewsFlow <span>AI</span>
        </strong>
      </button>
      <div className="core-navigation-links">
        {links.map(([key, label, Icon]) => (
          <button
            key={key}
            aria-current={
              key === module ||
              (key === "create" && ["characters", "images"].includes(module))
                ? "page"
                : undefined
            }
            onClick={() => onNavigate(key)}
          >
            <Icon size={17} />
            {label}
          </button>
        ))}
      </div>
      <details className="core-studio-switch">
        <summary>
          <ChevronDown size={17} />
          제작실
        </summary>
        <div>
          {[
            ["shorts", "뉴스 쇼츠", Video],
            ["characters", "캐릭터 쇼츠", Bot],
            ["images", "이미지 제작", Image],
          ].map(([key, label, Icon]) => (
            <button key={String(key)} onClick={() => onNavigate(String(key))}>
              {typeof Icon !== "string" && <Icon size={16} />} {String(label)}
            </button>
          ))}
        </div>
      </details>
    </nav>
  );
}
