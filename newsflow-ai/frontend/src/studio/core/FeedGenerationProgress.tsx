import type { Item } from "../contracts";
import "./feed-generation-progress.css";

export function feedProgress(batch: Item, busy: boolean, runningRank: number | null, stopping = false, message = "") {
  const items: Item[] = batch.items ?? [];
  const total = items.length;
  const completed = items.filter(x => x.status === "success").length;
  const failed = items.filter(x => x.status === "failed").length;
  const uncertain = items.some(x => ["unknown", "missing", "running"].includes(x.status));
  const current = busy && runningRank != null && items.some(x => x.rank === runningRank && ["pending", "running"].includes(x.status)) ? runningRank : null;
  const finished = total > 0 && completed === total;
  const title = current !== null
    ? (stopping ? `중단 대기 · TOP ${current} 응답 확인 중` : `TOP ${current} 이미지 생성 중`)
    : finished ? "이미지 생성 완료"
    : failed ? "생성 중단 · 실패 항목 확인 필요"
    : uncertain ? "결과 확인 필요 · 자동 재요청 없음"
    : batch.paused ? "생성 일시 중단"
    : message && !busy ? message : "생성 시작 전 · 실행 중인 요청 없음";
  return { total, completed, failed, uncertain, current, finished, title, percent: total ? Math.floor(completed / total * 100) : 0 };
}

export default function FeedGenerationProgress({ batch, busy, runningRank, stopping, message }: {
  batch: Item; busy: boolean; runningRank: number | null; stopping?: boolean; message?: string;
}) {
  const p = feedProgress(batch, busy, runningRank, stopping, message);
  return <section className="feed-generation-progress" aria-label="이미지 제작 진행 상황">
    <div role="status" aria-live="polite" aria-atomic="true">
      <strong>{p.current !== null && <span className="feed-generation-spinner" aria-hidden="true" />}{p.title}</strong>
      <span>{p.completed}/{p.total}개 완료 · {p.percent}%</span>
    </div>
    <progress aria-label="이미지 제작 완료율" max={p.total || 1} value={p.completed} />
    <small>{p.current !== null ? "현재 이미지의 응답을 기다리고 있습니다. 완료된 이미지 수를 기준으로 표시합니다."
      : p.finished ? "이미지를 선택해 결과를 검토하세요."
      : p.uncertain ? "이전 요청의 결과 확인이 필요합니다. 자동으로 다시 생성하지 않습니다."
      : p.failed ? `실패 ${p.failed}개 · 완료된 결과는 보존됐습니다.` : "표시된 비율은 완료된 이미지 수입니다. 새 이미지 생성은 견적 확인·승인 후 시작됩니다."}</small>
  </section>;
}
