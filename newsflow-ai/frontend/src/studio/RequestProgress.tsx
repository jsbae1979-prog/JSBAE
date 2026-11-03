import { useEffect, useState } from "react";
import { LoaderCircle, CircleCheck, AlertTriangle } from "lucide-react";
import "./request-progress.css";

type Stored = { state: string; elapsedSeconds?: number; detail?: string; runId?: number; canRetry?: boolean };
export default function RequestProgress({ collectionId, label, active: submitting, onTerminal, onRetry, retrySourceRunId }: { collectionId?: number; label: string; active: boolean; onTerminal: (state: "success" | "failed") => void; onRetry: (id: number, event: React.FormEvent) => void; retrySourceRunId?: number }) {
  const [confirmRetry, setConfirmRetry] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [stored, setStored] = useState<Stored | null>(null);
  const [reachable, setReachable] = useState(true);
  const [checked, setChecked] = useState("");
  useEffect(() => {
    const started = Date.now();
    setElapsed(0);
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [submitting]);
  useEffect(() => {
    if (!Number.isSafeInteger(collectionId) || !collectionId || collectionId < 1) return;
    if (submitting) { setStored(null); setConfirmRetry(false); }
    let active = true;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    async function read() {
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 5000);
      let terminal = false;
      try {
        const response = await fetch(`/api/curation/analysis-status?collection_context_id=${collectionId}`, {
          credentials: "same-origin", cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error("status unavailable");
        let value = await response.json();
        // Until the new claim is visible, the previous failed run is not this attempt's result.
        if (submitting && retrySourceRunId && value.runId === retrySourceRunId)
          value = {state: "pending", elapsedSeconds: 0, canRetry: false};
        if (!["pending", "running", "delayed", "success", "failed", "unknown"].includes(value.state)) throw new Error("invalid status");
        if (active) {
          setStored(value); setReachable(true); setChecked(new Date().toLocaleTimeString("ko-KR"));
          terminal = ["success", "failed"].includes(value.state);
          if (terminal) onTerminal(value.state);
        }
      } catch {
        if (active) setReachable(false);
      } finally {
        window.clearTimeout(timeout);
        if (active && !terminal && (submitting || stored?.state === "running")) timer = window.setTimeout(read, 3000);
      }
    }
    void read();
    return () => { active = false; window.clearTimeout(timer); controller?.abort(); };
  }, [collectionId, submitting, retrySourceRunId]);
  const state = reachable ? stored?.state ?? "pending" : "disconnected";
  const terminal = state === "success" || state === "failed";
  const uncertain = ["disconnected", "unknown", "delayed"].includes(state);
  const seconds = terminal ? stored?.elapsedSeconds ?? elapsed : Math.max(elapsed, stored?.elapsedSeconds ?? 0);
  const title = state === "success" ? "분석 완료" : state === "failed" ? "분석 실패" :
    state === "disconnected" ? "서버 상태 확인이 지연되고 있습니다" : state === "delayed" ? "처리가 지연되고 있습니다" :
    state === "unknown" ? "요청 상태 확인 필요" : collectionId ? "기사 분석 중" : `${label} · 처리 중`;
  if (!submitting && (!stored || state === "pending")) return null;
  return <section className={`request-progress ${terminal ? state : uncertain ? "delayed" : "running"}`}
    role="status" aria-label="요청 진행 상태" aria-live="polite">
    <div className="request-progress-heading">
      {state === "success" ? <CircleCheck size={22}/> : terminal || uncertain ? <AlertTriangle size={22}/> : <LoaderCircle className="spin" size={22}/>}
      <strong>{title}</strong><span aria-live="off">{Math.floor(seconds / 60)}분 {String(seconds % 60).padStart(2, "0")}초</span>
    </div>
    {!terminal && !uncertain && <progress aria-label="응답 대기 중"/>}
    <p>{state === "failed" ? stored?.detail : state === "success" ? "결과를 저장했습니다. 화면에 반영하는 중입니다." :
      uncertain ? "완료 여부를 확인 중입니다. 새 생성 요청은 보내지 않습니다." :
      state === "running" ? "서버에서 요청을 처리하고 있습니다. AI 응답을 기다려 주세요." : "요청 응답을 기다리고 있습니다."}</p>
    {!submitting && state === "failed" && stored?.canRetry && stored.runId && <div className="analysis-retry">
      {confirmRetry ? <>
        <strong>같은 기사로 다시 분석할까요?</strong>
        <p>기존 기록은 보존됩니다. 설정된 작업 한도 안에서 추가 API 비용이 발생할 수 있습니다.</p>
        <div><button type="button" onClick={() => setConfirmRetry(false)}>취소</button>
          <button type="button" className="primary" onClick={event => { setConfirmRetry(false); onRetry(stored.runId!, event); }}>동의하고 다시 분석</button></div>
      </> : <button type="button" className="primary" onClick={() => setConfirmRetry(true)}>다시 분석하기</button>}
    </div>}
    {collectionId && <small>{checked ? `마지막 상태 확인 ${checked}` : "서버 상태 확인 중"}{stored?.runId ? ` · 작업 #${stored.runId}` : ""}</small>}
  </section>;
}
