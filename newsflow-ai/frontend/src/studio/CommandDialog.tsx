import { useEffect, useRef, useState } from "react";
import { X, ShieldCheck, LoaderCircle, AlertTriangle } from "lucide-react";
import {
  type Action,
  type Field,
  type Item,
  type View,
  label,
} from "./contracts";
function ReferencePreview({file}:{file:File}) {
  const canvas=useRef<HTMLCanvasElement>(null);
  const [message,setMessage]=useState("로컬 이미지 확인 중");
  useEffect(()=>{let active=true;createImageBitmap(file).then(bitmap=>{if(!active){bitmap.close();return;}const node=canvas.current;if(node){const scale=Math.min(280/bitmap.width,240/bitmap.height,1);node.width=Math.max(1,Math.round(bitmap.width*scale));node.height=Math.max(1,Math.round(bitmap.height*scale));node.getContext("2d")?.drawImage(bitmap,0,0,node.width,node.height);setMessage(`${bitmap.width}×${bitmap.height} · 저장 전 로컬 미리보기`);}bitmap.close();}).catch(()=>setMessage("이미지 형식을 확인하세요."));return()=>{active=false;};},[file]);
  return <div className="local-reference-preview"><canvas ref={canvas} role="img" aria-label="선택한 참조 이미지 로컬 미리보기"/><small>{message}</small></div>;
}
const secrets = /(?:^key$|api_key|secret|access_token|refresh_token)/;
function choices(
  f: Field,
  view: View,
  values: Item,
  action: Action,
): [string, string][] {
  const c = view.catalog;
  const list = (rows: Item[]) =>
    rows.map(
      (x) =>
        [
          String(x.id),
          String(x.title ?? x.topic ?? x.name ?? x.label ?? x.id),
        ] as [string, string],
    );
  const resources: Record<string, string> = {
    article_id: "articles",
    article_ids: "articles",
    analysis_id: "analyses",
    draft_id: "drafts",
    source_draft_id: "drafts",
    plan_id: "plans",
    source_id: "sources",
    schedule_id: "schedules",
    run_id: "runs",
    account_id: "accounts",
    render_job_id: "renders",
  };
  if (resources[f.name] && view.collections[resources[f.name]]?.length)
    return list(view.collections[resources[f.name]]);
  if (f.name === "reference_asset")
    return (c.referenceAssets ?? []).map((x: string) => [x, x]);
  if (f.name === "provider")
    return action.module === "images"
      ? [["openai", "OpenAI · 이미지"]]
      : ["offline", ...Object.keys(c.apiModels ?? {})].map((x) => [
          x,
          x === "claude_api"
            ? "Claude API"
            : x === "openai_api"
              ? "OpenAI API"
              : x === "offline"
                ? "로컬 체험"
                : x,
        ]);
  if (["model", "script_model"].includes(f.name))
    return (
      action.module === "images" && action.id.startsWith("creation_")
        ? (c.imageModels ?? [])
        : (c.apiModels?.[
            values.provider ??
              (action.module === "characters" ? "claude_api" : "offline")
          ] ?? [])
    ).map((x: string) => [x, x]);
  if (f.name === "video_model")
    return c.characterDefaults?.video_model
      ? [[c.characterDefaults.video_model, c.characterDefaults.video_model]]
      : [];
  if (f.name === "model_path")
    return (view.collections.models ?? c.videoModels ?? [])
      .filter((x: Item) => x.confirmed_at)
      .map((x: Item) => [x.path, x.label]);
  if (f.name === "size") return Object.entries(c.sizes ?? {});
  if (f.name === "quality") return Object.entries(c.qualities ?? {});
  if (f.name === "duration")
    return [
      ["30", "30초"],
      ["45", "45초"],
      ["60", "60초"],
    ];
  if (f.name === "mode")
    return [
      ["mixed", "장면별 선택"],
      ["full", "전체 AI 장면"],
    ];
  if (f.name === "voice")
    return (c.voices ?? []).map((x: Item) => [x.id, x.label]);
  if (f.name === "kind" && action.id === "production_selection") return [["news","뉴스 수집 방식"],["voice","음성"],["video","영상 방식"]];
  if (f.name === "value" && action.id === "production_selection") return values.kind === "video" ? [["off","기본 영상 · FFmpeg"],["higgsfield","AI 영상 · Higgsfield"]] : values.kind === "voice" ? (c.voices??[]).map((x:Item)=>[x.id,x.label]) : [["offline|rss","RSS · 로컬 분석"],["claude_api|rss","RSS · Claude 분석"],["claude_api|web_search","Claude 웹 검색"]];
  if (f.name === "kind")
    return [
      ["daily", "매일"],
      ["weekly", "매주"],
      ["once", "한 번"],
    ];
  if (f.name === "action" && action.id === "scheduler_state")
    return [
      ["pause", "일시 정지"],
      ["enable", "활성화 · 별도 동의"],
      ["remove", "예약 제거"],
    ];
  if (f.name === "target" && action.id === "creation_reuse")
    return [
      ["news", "뉴스 영상 소재"],
      ["character", "캐릭터 참조 소재"],
    ];
  const fixed:Record<string,[string,string][]>={source:[["sample","체험 자료"],["feeds","등록 RSS"]],ai:[["offline","외부 API 없는 검토용 대본"]],font_size:[["40","작게"],["48","기본"],["56","크게"]],subtitle_y:[["1280","중앙 아래"],["1420","안전 영역"]],rate:[...Array(7)].map((_,i)=>[String(i-3),String(i-3)]),pause_ms:["0","150","250","400","600"].map(x=>[x,`${x}ms`]),storage_confirmed:[["yes","저장 위치를 확인했습니다"]]};
  if(action.id==="setup_step_save" && fixed[f.name])return fixed[f.name];
  if(action.id==="setup_step_save" && f.name==="platform")return [["youtube","YouTube Shorts"],["instagram","Instagram Reels"]];
  if (f.name === "privacy")
    return [
      ["private", "비공개"],
      ["unlisted", "일부 공개"],
      ["public", "공개 · 별도 승인 필요"],
    ];
  return [];
}
function initial(action: Action, context: Item, view: View) {
  const v: Item = {};
  for (const f of action.fields) {
    v[f.name] =
      f.type === "boolean" ? false : (context[f.name] ?? f.default ?? "");
  }
  if (action.id.startsWith("creation_") && action.id !== "creation_reuse")
    Object.assign(v, view.catalog.imageDefaults ?? {}, context);
  if (action.id === "character_create")
    Object.assign(v, view.catalog.characterDefaults ?? {}, context);
  return v;
}
export async function submitOriginal(
  action: Action,
  values: Item,
  view: View,
  files: Record<string, File>,
  extra: Item = {},
) {
  if (!view.commandsAvailable || !view.csrfToken)
    throw Error("현재 화면은 저장 기능이 연결되지 않았습니다.");
  let path = action.path;
  for (const f of action.fields.filter((x) => x.path)) {
    const v = String(values[f.name] ?? "");
    if (!/^[a-zA-Z0-9_-]+$/.test(v))
      throw Error(`${label(f.name)}을 선택하세요.`);
    path = path.replace(`{${f.name}}`, encodeURIComponent(v));
  }
  if (path.includes("{") || !path.startsWith("/") || path.startsWith("//"))
    throw Error("작업 경로를 확인하세요.");
  const multipart = action.fields.some((x) => x.type === "file");
  const body = multipart ? new FormData() : new URLSearchParams();
  body.append("csrf_token", view.csrfToken);
  for (const f of action.fields.filter((x) => !x.path && x.type !== "file")) {
    const v = values[f.name] ?? f.default;
    if (f.type === "boolean") {
      if (v === true) body.append(f.name, "true");
    } else if (Array.isArray(v)) {
      for (const a of v) body.append(f.name, String(a));
    } else if (v !== "" && v != null) body.append(f.name, String(v));
  }
  for (const [k, v] of Object.entries(extra)) body.append(k, String(v));
  if (body instanceof FormData)
    for (const [k, v] of Object.entries(files)) body.append(k, v);
  const response = await fetch(path, {
    method: "POST",
    body,
    credentials: "same-origin",
    redirect: "manual",
  });
  if (
    response.type === "opaqueredirect" ||
    response.status === 303 ||
    response.status === 302
  )
    return;
  const type = response.headers.get("content-type") ?? "";
  if (type.includes("json")) {
    const data = await response.json();
    if (!response.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : "입력·동의·저장 버전을 확인하세요.",
      );
    if (data.error) throw Error(String(data.error));
    return;
  }
  const text = await response.text();
  const doc = new DOMParser().parseFromString(text, "text/html");
  const error = doc
    .querySelector(".notice.error,.error,[role=alert]")
    ?.textContent?.trim();
  if (error) throw Error(error.slice(0, 600));
  if (!response.ok)
    throw Error(
      response.status === 409
        ? "다른 화면에서 변경됐습니다. 입력을 보존한 뒤 최신 내용을 다시 불러오세요."
        : `요청을 완료하지 못했습니다 (${response.status}). 재시도 전에 상태를 확인하세요.`,
    );
}
export function CommandDialog({
  action,
  context,
  view,
  onClose,
  onSaved,
}: {
  action: Action;
  context: Item;
  view: View;
  onClose: () => void;
  onSaved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [values, setValues] = useState<Item>(() =>
    initial(action, context, view),
  );
  const [files, setFiles] = useState<Record<string, File>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [ack, setAck] = useState(false);
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  const dynamic: Field[] = [];
  if(action.id === "setup_step_save"){
    const steps:Record<number,string[]>={2:["source"],3:["ai"],4:["duration","platform"],5:["voice","font_size","subtitle_y","rate","pause_ms"],6:["storage_confirmed"]};
    for(const name of steps[Number(values.step)]??[]) dynamic.push({name,type:"text",required:true,default:"",path:false});
  }
  if(action.id === "video_ai_save_scenes")for(const scene of view.collections.scenes??[])if(String(scene.plan_id)===String(values.plan_id))for(const key of ["source","material","prompt","model","discard"])dynamic.push({name:`${key}_${scene.position}`,type:key==="discard"?"boolean":"text",required:false,default:scene[key==="model"?"model_path":key]??"",path:false});
  const effective={...action,fields:[...action.fields,...dynamic]};
  const risky = action.risk !== "local";
  const set = (key: string, v: unknown) => {
    setValues((old) => {
      const next = { ...old, [key]: v };
      if (key === "provider") next.model = "";
      return next;
    });
  };
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || (risky && !ack)) return;
    setBusy(true);
    setError("");
    try {
      await submitOriginal(effective, values, view, files, context.__extra ?? {});
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "저장 결과를 확인하세요.");
    } finally {
      setBusy(false);
    }
  }
  const field = (f: Field) => {
    const opts = choices(f, view, values, action);
    const v = values[f.name] ?? f.default;
    if (f.path && context[f.name] != null)
      return (
        <p className="bound-field" key={f.name}>
          {label(f.name)} <strong>{String(v)}</strong>
        </p>
      );
    return (
      <label
        key={f.name}
        className={f.type === "boolean" ? "check-field" : "form-field"}
      >
        {f.type !== "boolean" && (
          <span>
            {label(f.name)}
            {f.required ? " *" : ""}
          </span>
        )}
        {f.type === "boolean" ? (
          <>
            <input
              aria-label={label(f.name)}
              type="checkbox"
              checked={v === true}
              onChange={(e) => set(f.name, e.target.checked)}
            />
            {label(f.name)}
          </>
        ) : f.type === "file" ? (
          <input
              aria-label={label(f.name)}
            type="file"
            accept="image/png"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) { if(file.size>10*1024*1024||file.type!=="image/png"){setError("참조 이미지는 10MB 이하 PNG를 선택하세요.");return;} setError(""); setFiles({ ...files, [f.name]: file }); }
            }}
          />
        ) : opts.length ? (
          <select
              aria-label={label(f.name)}
            required={f.required}
            multiple={f.type === "array"}
            value={f.type === "array" ? (Array.isArray(v) ? v : []) : String(v)}
            onChange={(e) =>
              set(
                f.name,
                f.type === "array"
                  ? Array.from(e.target.selectedOptions, (x) => x.value)
                  : e.target.value,
              )
            }
          >
            <option value="" disabled={f.required}>
              선택하세요
            </option>
            {opts.map(([id, text]) => (
              <option key={id} value={id}>
                {text}
              </option>
            ))}
          </select>
        ) : /prompt|description|caption|content|summary|statement|source_text|review_notes|body/.test(
            f.name,
          ) ? (
          <textarea
              aria-label={label(f.name)}
            rows={4}
            required={f.required}
            value={String(v ?? "")}
            maxLength={f.max_length}
            onChange={(e) => set(f.name, e.target.value)}
          />
        ) : (
          <input
              aria-label={label(f.name)}
            type={
              secrets.test(f.name)
                ? "password"
                : f.type === "number"
                  ? "number"
                  : f.name === "local_time"
                    ? "time"
                    : "text"
            }
            autoComplete={secrets.test(f.name) ? "new-password" : "off"}
            required={f.required}
            value={String(v ?? "")}
            min={f.ge}
            max={f.le}
            maxLength={f.max_length}
            onChange={(e) =>
              set(
                f.name,
                f.type === "array"
                  ? e.target.value.split(",").filter(Boolean)
                  : e.target.value,
              )
            }
          />
        )}
        {f.type==="file" && files[f.name] && <ReferencePreview file={files[f.name]}/>}
      </label>
    );
  };
  const basic = effective.fields.filter(
    (f) =>
      f.required ||
      f.path ||
      [
        "prompt",
        "model",
        "provider",
        "size",
        "quality",
        "reference",
        "script_model",
        "video_model",
        "duration",
        "voice",
        "mode",
        "consent",
        "reviewed",
        "confirmed",
        "approved",
        "asset_permission",
        "external_tts_consent",
      ].includes(f.name),
  );
  const advanced = effective.fields.filter((f) => !basic.includes(f));
  return (
    <dialog
      ref={dialog}
      className="command-dialog"
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else onClose();
      }}
    >
      <div className="dialog-head">
        <h2>{action.label}</h2>
        <button
          className="icon-button"
          aria-label="닫기"
          disabled={busy}
          onClick={onClose}
        >
          <X />
        </button>
      </div>
      <form onSubmit={submit}>
        <div className="command-body">
          {action.unsupported ? (
            <p role="alert">
              {action.reason ?? "현재 Adapter에서 지원하지 않습니다."}
            </p>
          ) : (
            <>
              {risky && (
                <div className="scope-note">
                  <ShieldCheck size={20} />
                  <p>
                    대상과 선택 모델을 확인하세요. 외부 전송·유료 사용·공개 게시
                    동의는 각각 별도로 적용되며, 실패·결과 불명 시 자동
                    재요청하지 않습니다.
                  </p>
                </div>
              )}
              <div className="form-grid">{basic.map(field)}</div>
              {advanced.length > 0 && (
                <details className="advanced">
                  <summary>세부 설정 · 검토 항목 ({advanced.length})</summary>
                  <div className="form-grid">{advanced.map(field)}</div>
                </details>
              )}
              <p className="muted">
                {view.policy?.price ??
                  "실제 계정 사용 가능 여부와 비용은 아직 확인되지 않았습니다."}
              </p>
              {risky && (
                <label className="check-field approval">
                  <input
              aria-label="이 요청의 실행 범위 확인"
                    type="checkbox"
                    checked={ack}
                    onChange={(e) => setAck(e.target.checked)}
                  />
                  표시된 이 요청의 범위를 확인했습니다. 실제 실행에 필요한 기존
                  승인 조건을 적용합니다.
                </label>
              )}
            </>
          )}
          {error && (
            <p role="alert" className="command-error">
              <AlertTriangle size={18} />
              {error}
            </p>
          )}
        </div>
        <footer>
          <button type="button" onClick={onClose} disabled={busy}>
            취소
          </button>
          <button
            className="primary"
            disabled={
              busy ||
              action.unsupported ||
              !view.commandsAvailable ||
              (risky && !ack)
            }
          >
            {busy ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <ShieldCheck size={18} />
            )}{" "}
            {busy ? "응답 확인 중 · 재요청 금지" : action.label}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
