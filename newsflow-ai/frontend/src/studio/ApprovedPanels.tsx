import {
  Check,
  ChevronRight,
  Image as ImageIcon,
  ShieldCheck,
  Settings2,
  Video as Youtube,
  Camera as Instagram,
  Music2,
  Globe as Facebook,
} from "lucide-react";
import type { Item } from "./contracts";

export const platforms = [
  { id: "instagram", name: "Instagram Reels · 피드", icon: Instagram },
  { id: "youtube", name: "YouTube Shorts", icon: Youtube },
  { id: "tiktok", name: "TikTok", icon: Music2 },
  { id: "facebook", name: "Facebook Reels", icon: Facebook },
];
export function WorkflowSteps({ labels }: { labels: string[] }) {
  return (
    <ol className="approved-steps" aria-label="작업 흐름">
      {labels.map((name, i) => (
        <li key={name}>
          <span>{i + 1}</span>
          <strong>{name}</strong>
          {i < labels.length - 1 && <ChevronRight size={17} />}
        </li>
      ))}
    </ol>
  );
}
export function PlatformAccounts({
  accounts,
  title = "플랫폼 계정",
  onSettings,
}: {
  accounts: Item[] | null;
  title?: string;
  onSettings?: () => void;
}) {
  return (
    <section className="work-panel approved-accounts">
      <div className="section-heading">
        <h2>
          <ShieldCheck size={19} />
          {title}
        </h2>
        {onSettings && (
          <button onClick={onSettings}>
            <Settings2 size={15} />
            설정·연결 안내
          </button>
        )}
      </div>
      <div className="platform-account-grid">
        {platforms.map((p) => {
          const items = accounts?.filter((x) => x.platform === p.id) ?? [];
          return (
            <article key={p.id} className={`platform-account platform-${p.id}`}>
              <h3>
                <p.icon size={25} />
                {p.name}
              </h3>
              {accounts === null ? (
                <p className="muted">계정 정보를 아직 확인하지 못했습니다.</p>
              ) : items.length ? (
                <ul>
                  {items.map((x) => (
                    <li key={x.id}>
                      <strong>{x.label || `계정 #${x.id}`}</strong>
                      <small>계정 등록 · 실제 권한 미검증</small>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">등록된 계정 없음</p>
              )}
              <span className="state-badge warn">
                {["tiktok", "facebook"].includes(p.id)
                  ? "실전송 차단"
                  : "게시 전 검토·권한·승인 필요"}
              </span>
            </article>
          );
        })}
      </div>
    </section>
  );
}
export function PlatformFilter({
  value,
  onChange,
  accounts,
  account,
  onAccount,
}: {
  value: string;
  onChange: (s: string) => void;
  accounts: Item[] | null;
  account: string;
  onAccount: (s: string) => void;
}) {
  const choices =
    accounts?.filter((x) => value === "all" || x.platform === value) ?? [];
  return (
    <div className="approved-platform-filters">
      <div className="filters" role="group" aria-label="성과 플랫폼 필터">
        <button aria-pressed={value === "all"} onClick={() => onChange("all")}>
          전체
        </button>
        {platforms.map((p) => (
          <button
            key={p.id}
            aria-pressed={value === p.id}
            onClick={() => onChange(p.id)}
          >
            <p.icon size={16} />
            {p.name}
          </button>
        ))}
      </div>
      <label className="account-filter">
        계정
        <select
          aria-label="성과 계정 필터"
          value={account}
          onChange={(e) => onAccount(e.target.value)}
          disabled={!choices.length}
        >
          <option value="all">
            {accounts === null ? "계정 정보 미확인" : "전체 등록 계정"}
          </option>
          {choices.map((x) => (
            <option key={x.id} value={x.id}>
              {x.label || `계정 #${x.id}`}
            </option>
          ))}
        </select>
      </label>
    </div>
  );
}
export function CostSummary({ usage }: { usage: Item[] }) {
  const known = usage.filter(
    (x) =>
      Number.isFinite(x.prompt_tokens) && Number.isFinite(x.completion_tokens),
  );
  return (
    <div className="approved-summary">
      <article>
        <span>기록된 AI 사용량</span>
        <strong>
          {known.length
            ? known
                .reduce((n, x) => n + x.prompt_tokens + x.completion_tokens, 0)
                .toLocaleString("ko-KR")
            : "기록 없음"}
        </strong>
        <small>입력 + 출력 토큰 · 청구액과 별개</small>
      </article>
      <article>
        <span>예상 비용</span>
        <strong>견적 확인 필요</strong>
        <small>모델·요금 근거 없는 금액 표시 안 함</small>
      </article>
      <article>
        <span>실제 청구액</span>
        <strong>미확인</strong>
        <small>공급사 청구 내역 검증 전</small>
      </article>
    </div>
  );
}
export function ImageOptions({
  catalog,
  value,
  onChange,
}: {
  catalog: Item;
  value: Item;
  onChange: (v: Item) => void;
}) {
  const models: string[] = catalog.imageModels ?? [];
  return (
    <fieldset className="approved-image-options">
      <legend>
        <ImageIcon size={17} />
        모델·비율·품질
      </legend>
      <label>
        이미지 모델
        <select
          aria-label="독립 이미지 모델"
          value={value.model ?? ""}
          onChange={(e) => onChange({ ...value, model: e.target.value })}
        >
          {!models.includes(value.model) && (
            <option value={value.model ?? ""}>
              {value.model || "등록 모델 확인 필요"}
            </option>
          )}
          {models.map((x) => (
            <option key={x} value={x}>
              {x}
            </option>
          ))}
        </select>
      </label>
      <label>
        생성 크기·비율
        <select
          aria-label="독립 이미지 크기"
          value={value.size ?? ""}
          onChange={(e) => onChange({ ...value, size: e.target.value })}
        >
          <option value="" disabled>
            크기 선택
          </option>
          {Object.entries(catalog.sizes ?? {}).map(([k, v]) => (
            <option key={k} value={k}>
              {String(v)}
            </option>
          ))}
        </select>
      </label>
      <label>
        이미지 품질
        <select
          aria-label="독립 이미지 품질"
          value={value.quality ?? ""}
          onChange={(e) => onChange({ ...value, quality: e.target.value })}
        >
          <option value="" disabled>
            품질 선택
          </option>
          {Object.entries(catalog.qualities ?? {}).map(([k, v]) => (
            <option key={k} value={k}>
              {String(v)}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        아래 초안에 적용 · 생성 전 기존 검토·비용 승인 유지
      </p>
    </fieldset>
  );
}
export function SetupOverview({
  settings,
  onGuide,
}: {
  settings: Record<string, string> | undefined;
  onGuide: () => void;
}) {
  let saved: Item = {};
  try {
    saved = JSON.parse(settings?.easy_setup ?? "{}");
  } catch {}
  const labels = [
    "시작",
    "뉴스 자료",
    "분석 AI",
    "영상 형식",
    "음성·자막",
    "저장 위치",
    "완료",
  ];
  return (
    <section className="work-panel approved-setup">
      <div>
        <h2>시작 가이드 · 7단계</h2>
        <p className="muted">
          저장된 진행 상태만 표시합니다. 설정 저장과 실제 연결 확인은
          별개입니다.
        </p>
        <button onClick={onGuide}>
          시작 가이드 열기
          <ChevronRight size={16} />
        </button>
      </div>
      <ol>
        {labels.map((name, i) => (
          <li
            key={name}
            aria-current={Number(saved.step) === i + 1 ? "step" : undefined}
          >
            <span>
              {saved.completed || Number(saved.step) > i + 1 ? (
                <Check size={16} />
              ) : (
                i + 1
              )}
            </span>
            <small>{name}</small>
          </li>
        ))}
      </ol>
    </section>
  );
}
