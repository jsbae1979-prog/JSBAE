import { useEffect, useRef, useState } from "react";
import type { Item } from "../contracts";

type Local = (fn: () => Promise<void>) => void;
async function json(r: Response) {
  const value = await r.json().catch(() => ({}));
  if (!r.ok) throw Error(value.detail || "입력과 연결 상태를 확인하세요.");
  return value;
}
export function FeedCopyTools({ state, form, base, csrf, background, local, onChange }: {
  state: Item; form: Item; base: string; csrf: string; background: string; local: Local;
  onChange: (patch: Item) => void;
}) {
  const [message, setMessage] = useState("");
  const parts = form.caption_sections ?? {};
  return <details className="feed-growth-copy">
    <summary>제목 후보 · 캡션 구성</summary>
    <p className="core-muted">저장된 문구를 재사용합니다 · 무료</p>
    <div className="feed-title-options" role="group" aria-label="제목 후보 비교">
      {(state.copyOptions?.titleCandidates ?? []).map((c: Item) =>
        <button key={c.text} type="button" onClick={() => onChange({ title: c.text })}>
          <small>{c.label} · {c.characters}자{!c.korean ? " · 한국어 편집 필요" : ""}</small><span>{c.text}</span>
        </button>)}
    </div>
    <button type="button" onClick={() => {
      const facts = state.originalSummary || "";
      onChange({ caption_sections: { lead: form.description || form.title || "", facts: facts.length <= 1200 ? facts : "", meaning: "", question: "" } });
      setMessage(facts.length > 1200 ? "요약이 길어 자동 입력하지 않았습니다. 핵심 사실을 직접 정리하세요." : "구성을 불러왔습니다. 검토 후 캡션에 적용하세요.");
    }}>저장된 내용으로 구성 불러오기</button>
    {[["lead", "캡션 첫 문장", 180], ["facts", "핵심 사실", 1200], ["meaning", "독자에게 중요한 점 · 선택", 300], ["question", "독자에게 묻기 · 선택", 180]].map(([key, label, max]) =>
      <label key={String(key)}>{label}<textarea aria-label={String(label)} rows={key === "facts" ? 4 : 2}
        maxLength={Number(max)} value={parts[key] ?? ""}
        onChange={e => onChange({ caption_sections: { ...parts, [key]: e.target.value } })} /></label>)}
    <button type="button" onClick={() => local(async () => {
      try {
        const result = await json(await fetch(base + "/design", { method: "POST", credentials: "same-origin",
          body: new URLSearchParams({ csrf_token: csrf, revision: String(state.revision), action: "caption", background: background || "caption-only", design: JSON.stringify(parts) }) }));
        onChange({ caption: result.caption }); setMessage("캡션에 적용했습니다. 편집 초안 또는 새 버전으로 저장하세요.");
      } catch (e) { setMessage((e as Error).message); }
    })}>캡션에 적용 · 무료</button>
    <small>확인되지 않은 의미나 숫자는 추가하지 마세요. 원문·출처는 유지됩니다.</small>
    {message && <p role="status">{message}</p>}
  </details>;
}
const fields = [["reach", "도달 계정"], ["saves", "저장"], ["shares", "공유"], ["follows", "팔로우 증가"]];
function localNow() { const now = new Date(); return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
export function FeedPerformance({ base, csrf, versions, busy, local }: { base: string; csrf: string; versions: Item[]; busy: boolean; local: Local }) {
  const [state, setState] = useState<Item | null>(null), [message, setMessage] = useState("");
  const [form, setForm] = useState<Item>({ version: "0", url: "", publishedAt: "", observedAt: localNow(), reach: "", saves: "", shares: "", follows: "" });
  const [confirmed, setConfirmed] = useState(false);
  const [open, setOpen] = useState(false);
  const loadedBase = useRef("");
  useEffect(() => {
    if (!open || loadedBase.current === base) return;
    setState(null); setMessage("");
    const abort = new AbortController();
    fetch(base + "/design-performance", { credentials: "same-origin", cache: "no-store", signal: abort.signal })
      .then(json).then(value => {
        if (!abort.signal.aborted) { loadedBase.current = base; setState(value); }
      }).catch(e => { if (!abort.signal.aborted) setMessage(e.message); });
    return () => abort.abort();
  }, [base, open]);
  const update = (key: string, value: string) => setForm(old => ({ ...old, [key]: value }));
  const number = (value: unknown) => value == null ? "미확인" : Number(value).toLocaleString("ko-KR");
  const rate = (value: unknown) => value == null ? "—" : `${value}%`;
  return <details className="feed-performance" onToggle={e => setOpen(e.currentTarget.open)}>
    <summary>게시 후 성과 비교 · 직접 입력</summary>
    <p className="core-muted">Instagram에서 확인한 수치입니다. 자동 조회·게시되지 않습니다.</p>
    <fieldset disabled={busy || !state}>
      <label>게시한 이미지<select aria-label="성과 이미지 버전" value={form.version} onChange={e => update("version", e.target.value)}>
        <option value="0">기존 제작 결과</option>{versions.map(v => <option key={v.version} value={v.version}>사진 중심 피드 · 버전 {v.version}</option>)}
      </select></label>
      <label>Instagram 게시물 주소<input aria-label="Instagram 게시물 주소" type="url" placeholder="https://www.instagram.com/p/…/" value={form.url} onChange={e => update("url", e.target.value)} /></label>
      <div className="feed-growth-fields">
        {[["publishedAt", "게시 시각"], ["observedAt", "측정 시각"]].map(([key, label]) => <label key={key}>{label}<input aria-label={label} type="datetime-local" value={form[key]} onChange={e => update(key, e.target.value)} /></label>)}
        {fields.map(([key, label]) => <label key={key}>{label}<input aria-label={label} type="number" min={0} max={1000000000} step={1} placeholder="미확인" value={form[key]} onChange={e => update(key, e.target.value)} /></label>)}
      </div>
      <label className="feed-growth-confirm"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />실제 게시한 이미지의 성과를 입력했습니다</label>
      <button type="button" disabled={!confirmed || !form.url || !form.publishedAt || !form.observedAt} onClick={() => local(async () => {
        try {
          const metrics = { version: Number(form.version), url: form.url.trim(), publishedAt: new Date(form.publishedAt).toISOString(), observedAt: new Date(form.observedAt).toISOString(), publishedConfirmed: confirmed,
            ...Object.fromEntries(fields.map(([key]) => [key, form[key] === "" ? null : Number(form[key])])) };
          setState(await json(await fetch(base + "/design-performance", { method: "POST", credentials: "same-origin", body: new URLSearchParams({ csrf_token: csrf, revision: String(state?.revision), metrics: JSON.stringify(metrics) }) })));
          setMessage("성과 기록을 저장했습니다. 기존 기록은 유지됩니다.");
          setConfirmed(false);
        } catch (e) { setMessage((e as Error).message); }
      })}>성과 기록 저장</button>
    </fieldset>
    {message && <p role="status">{message}</p>}
    {state?.records.length ? <div className="feed-performance-table"><table><caption>버전별 성과 · 사용자 입력</caption><thead><tr><th>스타일 / 버전</th><th>게시 후</th><th>도달</th><th>저장 / 비율</th><th>공유 / 비율</th><th>팔로우 / 비율</th></tr></thead><tbody>
      {state.records.map((r: Item) => <tr key={r.id}><th>{r.style === "legacy" ? "기존 카드" : "사진 중심"}{r.version ? ` v${r.version}` : ""}<small>{new Date(r.observedAt).toLocaleString("ko-KR")}</small></th><td>{r.elapsedHours}시간</td><td>{number(r.reach)}</td><td>{number(r.saves)} / {rate(r.rates.saves)}</td><td>{number(r.shares)} / {rate(r.rates.shares)}</td><td>{number(r.follows)} / {rate(r.rates.follows)}</td></tr>)}
    </tbody></table></div> : <p className="core-muted">{state ? "저장된 게시 성과가 없습니다." : message ? "성과 기록을 불러오지 못했습니다." : "성과 기록 불러오는 중…"}</p>}
    <small>비율 = 각 반응 ÷ 도달 계정. 측정 기간과 독자층이 비슷한 게시물을 비교하세요. 결과만으로 디자인 효과를 단정할 수 없습니다.</small>
  </details>;
}
