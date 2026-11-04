import { useCallback, useEffect, useRef, useState } from "react";
import { Panel } from "./shared";
import "./youtube-accounts.css";

type Channel = { id: number; label: string; channel_id?: string; status: string; ready: boolean; message?: string; refresh_needed?: boolean };
type Connection = { client_configured: boolean; storage_supported: boolean; pending: boolean; accounts: Channel[] };

export default function YouTubeAccounts({ csrf, enabled }: { csrf: string; enabled: boolean }) {
  const [state, setState] = useState<Connection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [selected, setSelected] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const lock = useRef(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    const r = await fetch("/api/youtube/status", { credentials: "same-origin", cache: "no-store" });
    if (!r.ok) throw Error("status_unavailable");
    const data: Connection = await r.json();
    setState(data);
    return data;
  }, []);
  useEffect(() => { let active = true; load().catch(() => { if(active) setError("연결 상태를 불러오지 못했습니다. 상태 새로고침을 눌러 주세요."); }); return () => { active=false; }; }, [load]);
  // Local status reads only. Opening the screen never starts Google authentication.
  useEffect(() => {
    if (!state?.pending) return;
    const timer = window.setInterval(() => { load().catch(() => setError("연결 상태 확인이 중단됐습니다. 상태 새로고침을 눌러 주세요.")); }, 3000);
    return () => window.clearInterval(timer);
  }, [state?.pending, load]);
  async function refresh() {
    setError("");
    try { await load(); } catch { setError("연결 상태를 불러오지 못했습니다."); }
  }
  async function send(path: string, values: Record<string,string>, success: string) {
    if (lock.current || !enabled || !csrf) return;
    lock.current=true; setBusy(true); setError(""); setMessage("");
    try {
      const r = await fetch(path, { method:"POST", credentials:"same-origin", body:new URLSearchParams({...values,csrf_token:csrf}) });
      if(!r.ok) { setError("처리를 완료하지 못했습니다. 앱 설정과 연결 상태를 확인하세요. 자동으로 다시 요청하지 않습니다."); return; }
      setMessage(success); setConsent(false);
      try { await load(); } catch { setError("요청 후 상태를 확인하지 못했습니다. 다시 연결하기 전에 상태를 새로고침하세요."); }
    } catch { setError("응답을 확인하지 못했습니다. 다시 연결하기 전에 상태를 새로고침하세요."); }
    finally { lock.current=false; setBusy(false); }
  }
  async function saveFile() {
    if (!file || busy || state?.pending || !state?.storage_supported) return;
    if(file.size>7000) {setError("Google 데스크톱 앱 JSON 파일을 선택하세요(최대 7KB).");return;}
    try {
      const raw = await file.text();
      const parsed = JSON.parse(raw);
      if(!parsed.installed?.client_id || !parsed.installed?.client_secret) throw Error("invalid");
      await send("/youtube/client",{client_json:raw},"Google 앱 설정을 저장했습니다. 이제 채널을 연결하세요.");
    } catch { setError("Google Cloud에서 내려받은 데스크톱 앱 JSON 파일인지 확인하세요."); }
    finally {setFile(null);if(fileInput.current) fileInput.current.value="";}
  }
  const canConnect=enabled && !!csrf && !!state?.client_configured && !!state?.storage_supported && !state.pending && !busy && consent;
  return <Panel title="YouTube 채널 연결" className="youtube-connection">
    <p>Google 로그인에서 사용할 계정과 채널을 선택하세요. 이메일·비밀번호·토큰을 여기에 입력할 필요가 없습니다.</p>
    <div className="youtube-connection-bar"><span>{!state ? "연결 상태 확인 중…" : state.pending ? "Google 로그인 완료 대기 중" : state.accounts.some(a=>a.ready) ? "연결된 채널이 있습니다" : "채널 연결이 필요합니다"}</span><button type="button" disabled={busy} onClick={refresh}>상태 새로고침</button></div>
    {state && !state.storage_supported && <p role="alert">Windows 보호 저장소를 사용할 수 없어 연결할 수 없습니다.</p>}
    {state && <details open={!state.client_configured}>
      <summary>Google 앱 설정 · {state.client_configured ? "저장됨" : "처음 한 번 필요"}</summary>
      <p>Google Cloud에서 YouTube Data API를 켜고, ‘데스크톱 앱’ OAuth 설정 파일(JSON)을 내려받아 선택하세요.</p>
      <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noopener noreferrer">Google Cloud 설정 열기</a>
      <label>Google 앱 설정 파일<input ref={fileInput} type="file" accept=".json,application/json" disabled={busy||state.pending||!enabled} onChange={e=>setFile(e.target.files?.[0]??null)} /></label>
      <button type="button" disabled={!file||busy||state.pending||!enabled||!csrf||!state.storage_supported} onClick={saveFile}>설정 파일 저장</button>
      <small>파일은 이 PC에 암호화해 저장합니다. Google 테스트 앱이면 로그인할 계정을 테스트 사용자로 등록하세요.</small>
    </details>}
    {!!state?.accounts.length && <label>연결할 채널<select aria-label="연결할 채널" value={selected} onChange={e=>setSelected(e.target.value)} disabled={busy||state.pending}>
      <option value="">다른 채널 추가</option>{state.accounts.map(a=><option key={a.id} value={a.id}>{a.label} · 다시 연결</option>)}
    </select></label>}
    <label className="youtube-consent"><input type="checkbox" checked={consent} disabled={busy||state?.pending} onChange={e=>setConsent(e.target.checked)} />Google 로그인으로 채널 확인·업로드 권한을 연결합니다.</label>
    <button className="mg-primary" type="button" disabled={!canConnect} onClick={()=>{if(canConnect) void send("/youtube/connect",{consent:"true",...(selected?{account_id:selected}:{})},"Google 창에서 계정과 채널을 선택하세요.");}}>{busy?"처리 중…":selected?"Google로 다시 연결":"Google로 채널 연결"}</button>
    <small>연결만으로 영상이 업로드되거나 게시되지 않습니다.</small>
    {state?.accounts.map(a=><article className="youtube-channel" key={a.id}><strong>{a.label}</strong><span>{a.ready?"채널 연결됨":["authorizing","exchanging","refreshing"].includes(a.status)?"연결 진행 중":"다시 연결 필요"}</span><p>{a.message}</p>
      {a.channel_id && <small>채널 ID: {a.channel_id}</small>}
      {a.status==="authorizing" && <button disabled={busy||!enabled} onClick={()=>send(`/youtube/connect/${a.id}/reopen`,{},"Google 로그인 창을 다시 열었습니다.")}>Google 로그인 창 다시 열기</button>}
      {["authorizing","exchanging","refreshing"].includes(a.status) && <button disabled={busy||!enabled} onClick={()=>send(`/youtube/connect/${a.id}/cancel`,{},"연결을 취소했습니다.")}>연결 취소</button>}
    </article>)}
    {message&&<p role="status">{message}</p>}{error&&<p role="alert">{error}</p>}
  </Panel>;
}

