import { useEffect, useRef, useState } from "react";

/** An explicit metadata check never submits or retries the pending analysis. */
export default function AnalysisConnectionCheck({provider, csrfToken, busy, onBegin, onEnd, onRefresh}: {
  provider: string; csrfToken: string; busy: boolean;
  onBegin: () => void; onEnd: () => void; onRefresh: () => void;
}) {
  const locked = useRef(false);
  const [message, setMessage] = useState("");
  useEffect(() => { setMessage(""); }, [provider]);
  const target = provider === "claude_api" ? "claude" : provider === "openai" ? "openai" : null;
  if (!target) return null;
  async function check() {
    if (busy || locked.current) return;
    locked.current = true;
    onBegin(); setMessage("모델 접근 권한 확인 중…");
    try {
      const response = await fetch(`/api/studio/providers/${target}/check`, {
        method: "POST", credentials: "same-origin",
        body: new URLSearchParams({scope: "text", consent: "true", csrf_token: csrfToken}),
      });
      const result = await response.json().catch(() => ({}));
      setMessage(response.ok && result.verified === true
        ? "모델 연결을 확인했습니다. 실행 조건과 비용 동의는 별도로 확인합니다."
        : "연결을 확인하지 못했습니다. 설정·관리에서 키와 모델을 확인하세요.");
      onRefresh();
    } catch {
      setMessage("연결 응답을 받지 못했습니다. 자동으로 다시 요청하지 않습니다.");
    } finally { locked.current = false; onEnd(); }
  }
  return <section className="analysis-connection-check" aria-label="분석 API 연결 확인">
    <button type="button" disabled={busy} onClick={() => void check()}>API 연결 다시 확인</button>
    <small>모델 정보만 조회합니다. 기사 분석은 실행하지 않습니다.</small>
    {message && <p role="status">{message}</p>}
  </section>;
}
