import { useEffect, useRef, useState } from "react";
import { X, ShieldCheck, LoaderCircle, AlertTriangle } from "lucide-react";
import {
  type Action,
  type Field,
  type Item,
  type View,
  label,
  safeMedia,
  status,
} from "./contracts";
function ReferencePreview({ file }: { file: File }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [message, setMessage] = useState("로컬 이미지 확인 중");
  useEffect(() => {
    let active = true;
    createImageBitmap(file)
      .then((bitmap) => {
        if (!active) {
          bitmap.close();
          return;
        }
        const node = canvas.current;
        if (node) {
          const scale = Math.min(280 / bitmap.width, 240 / bitmap.height, 1);
          node.width = Math.max(1, Math.round(bitmap.width * scale));
          node.height = Math.max(1, Math.round(bitmap.height * scale));
          node
            .getContext("2d")
            ?.drawImage(bitmap, 0, 0, node.width, node.height);
          setMessage(
            `${bitmap.width}×${bitmap.height} · 저장 전 로컬 미리보기`,
          );
        }
        bitmap.close();
      })
      .catch(() => setMessage("이미지 형식을 확인하세요."));
    return () => {
      active = false;
    };
  }, [file]);
  return (
    <div className="local-reference-preview">
      <canvas
        ref={canvas}
        role="img"
        aria-label="선택한 참조 이미지 로컬 미리보기"
      />
      <small>{message}</small>
    </div>
  );
}
const secrets =
  /client_json|(?:^key$|api_key|secret|access_token|refresh_token)/;
export function localCharacterRenderReview(
  action: Action,
  values: Item,
  view: View,
  loaded: Record<string, number> = {},
) {
  if (action.id !== "character_act_render") return null;
  const id = String(values.job_id ?? "");
  const job = (view.collections.jobs ?? []).find(
    (item) => String(item.id) === id,
  );
  const rows: Item[] = Array.isArray(job?.scenes) ? job.scenes : [];
  const clips = rows.map((item) => {
    const position = item.position;
    const mediaUrl =
      Number.isInteger(position) &&
      position > 0 &&
      item.mediaUrl === `/character/${id}/clips/${position}`
        ? safeMedia(item.mediaUrl)
        : null;
    const actual = loaded[String(position)] ?? item.media?.duration;
    const actualKnown =
      typeof actual === "number" && Number.isFinite(actual) && actual > 0;
    const planned = rows.length === 1 ? job?.duration : item.seconds;
    const seconds = actualKnown
      ? actual
      : typeof planned === "number" && planned > 0
        ? planned
        : null;
    return {
      position,
      state: String(item.state ?? "unknown"),
      mediaUrl,
      seconds,
      durationBasis: actualKnown ? "파일 확인" : "작업 기준",
    };
  });
  return {
    job,
    clips,
    ready:
      !!job &&
      (["clips_review", "completed"].includes(job.state) ||
        (["compose_failed", "composing"].includes(job.state) && job.composeRecoveryAvailable === true)) &&
      clips.length > 0 &&
      clips.every((clip) => clip.state === "downloaded" && !!clip.mediaUrl),
  };
}
function choices(
  f: Field,
  view: View,
  values: Item,
  action: Action,
): [string, string][] {
  const c = view.catalog;
  if (f.name === "voice_id")
    return (c.elevenVoices ?? []).map((x: Item) => [x.id, x.label]);
  if (action.id === "voice_listening" && c.listening?.items?.[f.name])
    return Object.entries(c.listening.values);
  if (action.id === "voice_listening" && f.name === "verdict")
    return Object.entries(c.listening?.verdicts ?? {});
  if (action.id === "operations_review" && c.operationsItems?.[f.name])
    return ["NOT VERIFIED", "PASS", "FAIL"].map((x) => [x, x]);
  if (action.id === "operations_startup" && f.name === "command")
    return [
      ["register", "자동 시작 등록"],
      ["remove", "자동 시작 해제"],
    ];
  if (/^source_\d+$/.test(f.name))
    return [
      ["card", "기본 카드"],
      ["local", "로컬 이미지"],
      ["generated", "AI 생성 영상 · 별도 승인"],
    ];
  if (/^model_\d+$/.test(f.name))
    return (view.collections.models ?? []).map((x) => [x.path, x.label]);
  if (/^material_\d+$/.test(f.name))
    return (c.assets ?? []).map((x: string) => [x, x]);
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
  if (f.name === "provider" && action.id === "video_ai_save_settings")
    return [
      ["off", "기본 영상 · 외부 영상 생성 없음"],
      ["higgsfield", "Higgsfield · 별도 승인 필요"],
    ];
  if (f.name === "video_provider")
    return [
      ["off", "기본 FFmpeg 영상"],
      ["higgsfield", "Higgsfield AI 영상"],
    ];
  if (f.name === "provider" && action.id === "ai_settings_save_ai_settings")
    return Object.entries(c.legacyProviders ?? {});
  if (f.name === "model" && action.id === "ai_settings_save_ai_settings")
    return [];
  if (f.name === "model" && action.id === "video_save_tts")
    return (c.ttsModels ?? []).map((x: string) => [x, x]);
  if (f.name === "provider" && action.id.startsWith("api_settings_"))
    return Object.keys(c.apiModels ?? {}).map((x) => [
      x,
      x === "claude_api" ? "Claude API" : "OpenAI API",
    ]);
  if (f.name === "provider")
    return action.module === "images"
      ? [["openai", "OpenAI · 이미지"]]
      : Object.entries(
          c.analysisProviders ?? {
            offline: "로컬 체험",
            openai: "OpenAI API",
            claude_api: "Claude API",
          },
        );
  if (["model", "script_model"].includes(f.name)) {
    const models: [string, string][] = (
      action.module === "images" && action.id.startsWith("creation_")
        ? (c.imageModels ?? [])
        : (c.apiModels?.[
            values.provider ??
              (action.module === "characters" ||
              action.id === "image_post_claude_card"
                ? "claude_api"
                : "offline")
          ] ?? [])
    ).map((x: string) => [x, x] as [string, string]);
    const stored = values[f.name];
    if (stored && !models.some((x) => x[0] === stored))
      models.unshift([
        String(stored),
        String(stored) + " · 저장 선택 · 지원 확인 필요",
      ]);
    return models;
  }
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
  if (f.name === "kind" && action.id === "production_selection")
    return [
      ["news", "뉴스 수집 방식"],
      ["voice", "음성"],
      ["video", "영상 방식"],
    ];
  if (f.name === "value" && action.id === "production_selection")
    return values.kind === "video"
      ? [
          ["off", "기본 영상 · FFmpeg"],
          ["higgsfield", "AI 영상 · Higgsfield"],
        ]
      : values.kind === "voice"
        ? (c.voices ?? []).map((x: Item) => [x.id, x.label])
        : Object.entries(c.newsMethods ?? {});
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
  const fixed: Record<string, [string, string][]> = {
    source: [
      ["sample", "체험 자료"],
      ["feeds", "등록 RSS"],
    ],
    ai: [["offline", "외부 API 없는 검토용 대본"]],
    font_size: [
      ["40", "작게"],
      ["48", "기본"],
      ["56", "크게"],
    ],
    subtitle_y: [
      ["1280", "중앙 아래"],
      ["1420", "안전 영역"],
    ],
    rate: [...Array(7)].map((_, i) => [String(i - 3), String(i - 3)]),
    pause_ms: ["0", "150", "250", "400", "600"].map((x) => [x, `${x}ms`]),
    storage_confirmed: [["yes", "저장 위치를 확인했습니다"]],
  };
  if (action.id === "setup_step_save" && fixed[f.name]) return fixed[f.name];
  if (action.id === "setup_step_save" && f.name === "platform")
    return [
      ["youtube", "YouTube Shorts"],
      ["instagram", "Instagram Reels"],
    ];
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
      f.type === "boolean"
        ? /consent|reviewed|confirmed|permission|rights/.test(f.name)
          ? false
          : Boolean(
              context[f.name] ??
              view.formDefaults?.[action.id]?.[f.name] ??
              f.default ??
              false,
            )
        : (context[f.name] ??
          view.formDefaults?.[action.id]?.[f.name] ??
          f.default ??
          "");
  }
  if (action.id === "character_act_retry-scene")
    v.quote_hash =
      context.state === "retry_quoted" ? (context.retry_hash ?? "") : "";
  if (action.id.startsWith("creation_") && action.id !== "creation_reuse")
    Object.assign(v, view.catalog.imageDefaults ?? {}, context);
  if (
    action.id === "character_create" ||
    action.id === "character_character_defaults"
  )
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
  for (const [k, v] of Object.entries(extra)) {
    if (Array.isArray(v)) for (const value of v) body.append(k, String(value));
    else body.append(k, String(v));
  }
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
    const summary: Item = {};
    for (const key of [
      "status",
      "tier",
      "character_count",
      "character_limit",
      "remaining",
      "ready",
      "message",
      "currency",
      "model",
    ])
      if (["string", "number", "boolean"].includes(typeof data[key]))
        summary[key] = String(data[key]).slice(0, 200);
    return Object.keys(summary).length ? summary : undefined;
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
  const [responseSummary, setResponseSummary] = useState<Item | null>(null);
  const [clipDurations, setClipDurations] = useState<Record<string, number>>(
    {},
  );
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  const dynamic: Field[] = [];
  if (action.id === "voice_listening")
    for (const name of [
      "listener",
      "voice",
      "rate",
      "pause_ms",
      "preview",
      ...Object.keys(view.catalog.listening?.items ?? {}),
      "verdict",
      "notes",
    ])
      dynamic.push({
        name,
        type: "text",
        required: name !== "notes",
        default: context[name] ?? "",
        path: false,
      });
  if (action.id === "operations_review")
    for (const name of Object.keys(view.catalog.operationsItems ?? {}))
      dynamic.push({
        name,
        type: "text",
        required: true,
        default: "NOT VERIFIED",
        path: false,
      });
  if (action.id === "video_ai_review")
    for (const scene of view.collections.scenes ?? [])
      if (String(scene.plan_id) === String(values.plan_id))
        dynamic.push({
          name: `reviewed_${scene.position}`,
          type: "boolean",
          required: false,
          default: false,
          path: false,
        });
  if (action.id === "setup_step_save") {
    const steps: Record<number, string[]> = {
      2: ["source"],
      3: ["ai"],
      4: ["duration", "platform"],
      5: ["voice", "font_size", "subtitle_y", "rate", "pause_ms"],
      6: ["storage_confirmed"],
    };
    for (const name of steps[Number(values.step)] ?? [])
      dynamic.push({
        name,
        type: "text",
        required: true,
        default: "",
        path: false,
      });
  }
  if (action.id === "video_ai_save_scenes")
    for (const scene of view.collections.scenes ?? [])
      if (String(scene.plan_id) === String(values.plan_id))
        for (const key of ["source", "material", "prompt", "model", "discard"])
          dynamic.push({
            name: `${key}_${scene.position}`,
            type: key === "discard" ? "boolean" : "text",
            required: false,
            default: scene[key === "model" ? "model_path" : key] ?? "",
            path: false,
          });
  const localRender = localCharacterRenderReview(
    action,
    values,
    view,
    clipDurations,
  );
  const localRenderTitle = "장면 검토 후 영상 합성";
  const checkingCharacterScenes = action.id === "character_act_check";
  const diagnosingCharacterScenes = action.id === "character_act_diagnose";
  const effective = {
    ...action,
    fields: localRender
      ? action.fields.filter((f) => ["job_id", "reviewed"].includes(f.name))
      : [...action.fields, ...dynamic],
  };
  const risky = !localRender && action.risk !== "local";
  const set = (key: string, v: unknown) => {
    setValues((old) => {
      const next = { ...old, [key]: v };
      if (key === "provider")
        next.model = view.catalog.studioModels?.[String(v)] ?? "";
      return next;
    });
  };
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || (risky && !ack)) return;
    if (localRender && (!localRender.ready || values.reviewed !== true)) {
      setError("실제 합성 대상 영상을 확인한 뒤 장면 검토를 체크하세요.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await submitOriginal(
        effective,
        values,
        view,
        files,
        localRender ? {} : (context.__extra ?? {}),
      );
      onSaved();
      if (result) setResponseSummary(result);
      else onClose();
    } catch (e) {
      setAck(false);
      const detail = e instanceof Error ? e.message : "저장 결과를 확인하세요.";
      if (checkingCharacterScenes) {
        onSaved();
        setError(`상태 조회가 중단됐습니다. 저장된 장면별 상태를 확인하세요. ${detail}`);
      } else if (diagnosingCharacterScenes) {
        onSaved();
        setError(`실패 상세 조회를 완료하지 못했습니다. 저장된 조회 결과를 확인하세요. ${detail}`);
      } else setError(detail);
    } finally {
      setBusy(false);
    }
  }
  const field = (f: Field) => {
    const fieldLabel =
      (diagnosingCharacterScenes && f.name === "consent"
        ? "기존 실패 상세 조회에 동의합니다"
        : checkingCharacterScenes && f.name === "consent"
        ? "기존 장면 상태 조회·완료 영상 저장에 동의합니다"
        : f.name === "job_limit"
        ? action.id === "video_save_tts"
          ? "1회 음성 입력 글자 수 한도"
          : "1회 영상 제작 한도 (" + String(values.currency ?? "USD") + ")"
        : action.id === "video_ai_review" && f.name === "statement"
          ? "모든 장면과 AI 생성 표시를 검토했습니다"
          : undefined) ??
      view.catalog.operationsItems?.[f.name] ??
      view.catalog.listening?.items?.[f.name] ??
      label(f.name);
    const opts = choices(f, view, values, action);
    const v = values[f.name] ?? f.default;
    if (["approval_token", "quote_hash"].includes(f.name) && context[f.name])
      return (
        <p className="bound-field" key={f.name}>
          {fieldLabel} <strong>저장된 검토·견적 기록 연결됨</strong>
        </p>
      );
    if (f.path && context[f.name] != null)
      return (
        <p className="bound-field" key={f.name}>
          {fieldLabel} <strong>{String(v)}</strong>
        </p>
      );
    return (
      <label
        key={f.name}
        className={f.type === "boolean" ? "check-field" : "form-field"}
      >
        {f.type !== "boolean" && (
          <span>
            {fieldLabel}
            {f.required ? " *" : ""}
          </span>
        )}
        {f.type === "boolean" ? (
          <>
            <input
              aria-label={fieldLabel}
              type="checkbox"
              checked={v === true}
              onChange={(e) => set(f.name, e.target.checked)}
            />
            {fieldLabel}
          </>
        ) : f.type === "file" ? (
          <input
            aria-label={fieldLabel}
            type="file"
            accept="image/png"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                if (file.size > 10 * 1024 * 1024 || file.type !== "image/png") {
                  setError("참조 이미지는 10MB 이하 PNG를 선택하세요.");
                  return;
                }
                setError("");
                setFiles({ ...files, [f.name]: file });
              }
            }}
          />
        ) : opts.length ? (
          <select
            aria-label={fieldLabel}
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
            aria-label={fieldLabel}
            rows={4}
            required={f.required}
            value={String(v ?? "")}
            maxLength={f.max_length}
            onChange={(e) => set(f.name, e.target.value)}
          />
        ) : (
          <input
            aria-label={fieldLabel}
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
        {f.type === "file" && files[f.name] && (
          <ReferencePreview file={files[f.name]} />
        )}
      </label>
    );
  };
  const basic = effective.fields.filter(
    (f) =>
      f.required ||
      f.path ||
      f.type === "boolean" ||
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
        <h2>{localRender ? localRenderTitle : action.label}</h2>
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
          {view.dataOrigin === "development-fixtures" &&
            action.fields.some((f) => secrets.test(f.name)) && (
              <p className="scope-note">
                합성 검증 화면입니다. 실제 키·개인정보를 입력하지 마세요. 이
                화면의 인증정보 저장은 차단됩니다.
              </p>
            )}
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
                    {diagnosingCharacterScenes
                      ? "실패한 기존 요청의 처리 결과와 오류 설명만 확인합니다. 영상 생성·재시도·새 견적은 요청하지 않습니다."
                      : checkingCharacterScenes
                      ? "접수된 장면을 확인·저장합니다. 이어지는 장면은 승인된 견적 범위에서 앞 장면의 마지막 프레임으로 연결합니다. 실패 장면은 재시도하지 않습니다."
                      : "대상과 선택 모델을 확인하세요. 외부 전송·유료 사용·공개 게시 동의는 각각 별도로 적용되며, 실패·결과 불명 시 자동 재요청하지 않습니다."}
                  </p>
                </div>
              )}
              {action.id === "character_act_retry-scene" &&
                context.retryQuote && (
                  <p className="scope-note">
                    재시도 대상 장면 {context.retryQuote.position} · 공식 견적
                    USD {context.retryQuote.quote_usd}
                  </p>
                )}
              {localRender ? (
                <section aria-label="실제 합성 대상 영상 검토">
                  <p>
                    저장된 실제 영상 {localRender.clips.length}개를 내 PC의
                    FFmpeg로 연결·저장합니다. {localRender.job?.automation_version===1&&!localRender.job?.directVideo
                      ? "검토한 자막·코믹 효과음을 더하고 장면의 환경음을 연결합니다. 새 음성·나레이션은 추가하지 않습니다."
                      : "자막이나 새 음성·나레이션은 추가하지 않고, 장면에 포함된 원래 소리만 유지합니다."}
                    새 AI 생성이나 외부 전송은 실행하지 않습니다.
                  </p>
                  {localRender.job && (
                    <p className="bound-field">
                      대상 작업 <strong>{localRender.job.topic}</strong>
                    </p>
                  )}
                  <div className="form-grid">
                    {localRender.clips.map((clip) => (
                      <article
                        className="form-field"
                        key={String(clip.position)}
                      >
                        <strong>실제 영상 {clip.position}</strong>
                        <small>
                          {clip.seconds === null
                            ? "길이 확인 필요"
                            : `${Number(clip.seconds.toFixed(3))}초 · ${clip.durationBasis}`}{" "}
                          · {status[clip.state] ?? clip.state}
                        </small>
                        {clip.mediaUrl ? (
                          <video
                            controls
                            preload="metadata"
                            width="180"
                            height="320"
                            aria-label={`실제 합성 대상 영상 ${clip.position} 미리보기`}
                            src={clip.mediaUrl}
                            onLoadedMetadata={(event) => {
                              const seconds = event.currentTarget.duration;
                              if (Number.isFinite(seconds) && seconds > 0)
                                setClipDurations((old) => ({
                                  ...old,
                                  [String(clip.position)]: seconds,
                                }));
                            }}
                          />
                        ) : (
                          <p role="status">
                            검증된 영상 파일을 확인할 수 없습니다.
                          </p>
                        )}
                      </article>
                    ))}
                  </div>
                  {!localRender.ready && (
                    <p role="alert">
                      다운로드·검증된 실제 영상이 모두 준비되어야 합성할 수
                      있습니다.
                    </p>
                  )}
                  <label className="check-field">
                    <input
                      type="checkbox"
                      aria-label="실제 합성 대상 영상 검토 완료"
                      required
                      disabled={busy || !localRender.ready}
                      checked={values.reviewed === true}
                      onChange={(event) =>
                        set("reviewed", event.target.checked)
                      }
                    />
                    실제 영상 {localRender.clips.length}개의 화면·소리·장면
                    연결을 검토했습니다.
                  </label>
                </section>
              ) : (
                <div className="form-grid">{basic.map(field)}</div>
              )}
              {!localRender && advanced.length > 0 && (
                <details className="advanced">
                  <summary>세부 설정 · 검토 항목 ({advanced.length})</summary>
                  <div className="form-grid">{advanced.map(field)}</div>
                </details>
              )}
              {!localRender && (
                <p className="muted">
                  {view.policy?.price ??
                    "실제 계정 사용 가능 여부와 비용은 아직 확인되지 않았습니다."}
                </p>
              )}
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
          {responseSummary && (
            <div className="response-summary">
              <h3>조회 응답</h3>
              <dl className="property-list">
                {Object.entries(responseSummary).map(([k, v]) => (
                  <div key={k}>
                    <dt>{label(k)}</dt>
                    <dd>{String(v)}</dd>
                  </div>
                ))}
              </dl>
              <p className="muted">
                {localRender
                  ? "이 로컬 합성 요청의 응답입니다. 저장된 작업 상태를 확인하세요."
                  : "이 요청의 응답입니다. 다른 기능의 연결·생성·과금 성공을 의미하지 않습니다."}
              </p>
            </div>
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
              !!responseSummary ||
              (view.dataOrigin === "development-fixtures" &&
                action.fields.some((f) => secrets.test(f.name))) ||
              action.unsupported ||
              !view.commandsAvailable ||
              (risky && !ack) ||
              (!!localRender &&
                (!localRender.ready || values.reviewed !== true))
            }
          >
            {busy ? (
              <LoaderCircle className="spin" size={18} />
            ) : (
              <ShieldCheck size={18} />
            )}{" "}
            {busy
              ? localRender ? "FFmpeg로 최종 영상 합성 중…" : "응답 확인 중 · 재요청 금지"
              : localRender
                ? localRenderTitle
                : action.label}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
