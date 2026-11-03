import { useEffect, useState } from "react";
import { LoaderCircle, CircleCheck, AlertTriangle } from "lucide-react";
import "./request-progress.css";

type Stored = { state: string; elapsedSeconds?: number; detail?: string; runId?: number };
export default function RequestProgress({ collectionId, label, active: submitting, onTerminal }: { collectionId?: number; label: string; active: boolean; onTerminal: (state: "success" | "failed") => void }) {
  const [elapsed, setElapsed] = useState(0);
  const [stored, setStored] = useState<Stored | null>(null);
  const [reachable, setReachable] = useState(true);
  const [checked, setChecked] = useState("");
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    if (!Number.isSafeInteger(collectionId) || !collectionId || collectionId < 1) return;
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
        const value = await response.json();
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
  }, [collectionId, submitting]);
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
    {collectionId && <small>{checked ? `마지막 상태 확인 ${checked}` : "서버 상태 확인 중"}{stored?.runId ? ` · 작업 #${stored.runId}` : ""}</small>}
  </section>;
}
