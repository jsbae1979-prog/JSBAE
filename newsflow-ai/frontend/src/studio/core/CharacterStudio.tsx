import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  BookOpen,
  Bot,
  ChevronRight,
  Clapperboard,
  Clock3,
  ImagePlus,
  Info,
  Play,
  Settings2,
  Sparkles,
  WandSparkles,
  Ratio,
  Monitor,
  Mic,
  Coins,
  ChevronDown,
  Trash2,
  RotateCcw,
  X,
} from "lucide-react";
import { Thumbnail } from "../Thumbnail";
import { safeMedia, type Item } from "../contracts";
import {
  Empty,
  Media,
  Select,
  State,
  ActionButton,
  type Controller,
} from "./shared";
import "./character-studio.css";
import { CharacterModal, CharacterProfiles, CharacterTopics, CharacterScriptEditor, CharacterRegeneration } from "./CharacterAutomation";

import {
  adjustModel,
  publicEstimate,
  quotedSettingsDirty,
  type CharacterVideoSettings as Settings,
} from "./videoModelSettings";
function CapabilitySelect({
  label,
  value,
  onChange,
  values,
  supported,
  disabled = false,
  hint,
  icon,
  ariaLabel,
  unsupportedHint,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  values: Record<string, string>;
  supported: string[];
  disabled?: boolean;
  hint?: string;
  icon?: ReactNode;
  ariaLabel?: string;
  unsupportedHint?: string;
}) {
  return (
    <label className="kling-capability-field">
      <span className="kling-setting-label">
        {icon}
        <span>{label}</span>
      </span>
      <span className="kling-control-wrap">
        <select
          aria-label={ariaLabel ?? label}
          title={values[value] ?? value}
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {Object.entries(values).map(([id, title]) => (
            <option
              key={id}
              value={id}
              disabled={!supported.includes(id)}
              title={
                !supported.includes(id)
                  ? (unsupportedHint ?? "이 모델에서는 지원하지 않아요")
                  : undefined
              }
            >
              {title}
            </option>
          ))}
        </select>
        <ChevronDown aria-hidden="true" size={13} />
      </span>
      {hint && <small className="kling-field-note">{hint}</small>}
    </label>
  );
}
function LocalReference({ file }: { file: File }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let active = true;
    createImageBitmap(file)
      .then((bitmap) => {
        if (active && canvas.current) {
          const k = Math.min(480 / bitmap.width, 640 / bitmap.height, 1);
          canvas.current.width = Math.round(bitmap.width * k);
          canvas.current.height = Math.round(bitmap.height * k);
          canvas.current
            .getContext("2d")
            ?.drawImage(
              bitmap,
              0,
              0,
              canvas.current.width,
              canvas.current.height,
            );
        }
        bitmap.close();
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [file]);
  return (
    <canvas ref={canvas} role="img" aria-label="선택한 캐릭터 로컬 미리보기" />
  );
}
type TrialStatus = {
  ready: boolean;
  reasons: string[];
  model: string;
  keyConfigured: boolean;
  authenticationVerified: boolean;
  authAttempted: boolean;
  archiveReady: boolean;
  unknownCount: number;
  archivedCount: number;
};
function CharacterTrialConnection({
  csrfToken,
  disabled,
  onBusy,
  onAuthenticated,
}: {
  csrfToken: string;
  disabled: boolean;
  onBusy: (value: boolean) => void;
  onAuthenticated: () => Promise<unknown>;
}) {
  const [status, setStatus] = useState<TrialStatus | null>(null);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(true);
  const [posting, setPosting] = useState(false);
  const attempted = useRef(false);
  const [archiveConfirmation, setArchiveConfirmation] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const archiveAttempted = useRef(false);
  useEffect(() => {
    let active = true;
    fetch("/api/studio/characters/trial-status", { credentials: "same-origin" })
      .then(async (response) => {
        if (!response.ok) throw Error("status");
        return response.json();
      })
      .then((data: TrialStatus) => {
        if (active) {
          setStatus(data);
          attempted.current = data.authAttempted === true;
        }
      })
      .catch(() => {
        if (active)
          setMessage(
            "연결 상태를 불러오지 못했습니다. 자동으로 재요청하지 않습니다.",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);
  async function authenticate() {
    if (attempted.current || posting || disabled || !status?.ready) return;
    attempted.current = true;
    setPosting(true);
    onBusy(true);
    setMessage("");
    setStatus((value) =>
      value ? { ...value, authAttempted: true, ready: false } : value,
    );
    try {
      const body = new URLSearchParams();
      body.set("csrf_token", csrfToken);
      body.set("consent", "true");
      const response = await fetch(
        "/api/studio/characters/trial-authenticate",
        {
          method: "POST",
          credentials: "same-origin",
          body,
        },
      );
      const data = await response.json().catch(() => ({}));
      if (response.ok && data.ok === true) {
        setStatus((value) =>
          value ? { ...value, authenticationVerified: true } : value,
        );
        setMessage(
          typeof data.message === "string"
            ? data.message
            : "Claude 모델 접근을 확인했습니다. 생성은 실행하지 않았습니다.",
        );
        try {
          await onAuthenticated();
        } catch {
          /* Verification is not repeated when refreshing the screen fails. */
        }
      } else {
        setMessage(
          typeof data.message === "string"
            ? data.message
            : "연결을 확인하지 못했습니다. 이번 확인은 다시 실행하지 않습니다.",
        );
      }
    } catch {
      setMessage(
        "연결 확인 결과가 불명확합니다. 자동 재시도하지 않습니다. 새 생성은 진행하지 마세요.",
      );
    } finally {
      setPosting(false);
      onBusy(false);
    }
  }
  async function archiveUnknown() {
    if (
      archiveAttempted.current ||
      archiving ||
      disabled ||
      !status?.archiveReady
    )
      return;
    archiveAttempted.current = true;
    setArchiving(true);
    onBusy(true);
    setMessage("");
    setStatus((value) => (value ? { ...value, archiveReady: false } : value));
    try {
      const body = new URLSearchParams();
      body.set("csrf_token", csrfToken);
      body.set("consent", "true");
      const response = await fetch("/api/studio/characters/trial-archive", {
        method: "POST",
        credentials: "same-origin",
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (
        !response.ok ||
        data.status !== "archived_unknown" ||
        data.replay_authorized !== false
      ) {
        setMessage(
          typeof data.message === "string"
            ? data.message
            : "이전 불명 기록 정리를 확인하지 못했습니다. 자동 재시도하지 않습니다.",
        );
        return;
      }
      setMessage(
        `이전 불명 기록 ${Number(data.count) || 0}건을 활성 목록에서 정리했습니다. 원본과 재요청 방지 기록은 보관됩니다.`,
      );
      setStatus((value) =>
        value
          ? {
              ...value,
              unknownCount: 0,
              archivedCount: value.archivedCount + (Number(data.count) || 0),
            }
          : value,
      );
      try {
        await onAuthenticated();
        const updated = await fetch("/api/studio/characters/trial-status", {
          credentials: "same-origin",
        });
        if (updated.ok) {
          const value: TrialStatus = await updated.json();
          setStatus(value);
          attempted.current ||= value.authAttempted === true;
        }
      } catch {
        /* Only status reads may fail here; the archive request is never repeated. */
      }
    } catch {
      setMessage(
        "이전 불명 기록 정리 결과가 불명확합니다. 자동 재시도하지 않습니다.",
      );
    } finally {
      setArchiveConfirmation(false);
      setArchiving(false);
      onBusy(false);
    }
  }
  return (
    <section
      className="kling-character-help kling-character-trial"
      aria-label="이번 제작 API 연결"
    >
      <div>
        <strong>이번 제작 API 연결</strong>
        <span role="status">
          {loading
            ? "상태 확인 중…"
            : status?.authenticationVerified
              ? "Claude 연결 확인됨"
              : status?.authAttempted || attempted.current
                ? "연결 확인 시도 완료"
                : status?.keyConfigured
                  ? "Claude 연결 확인 필요"
                  : "연결 준비 필요"}
        </span>
        {status?.model && <small>스토리 모델: {status.model}</small>}
      </div>
      <div>
        <button
          type="button"
          disabled={
            disabled ||
            loading ||
            posting ||
            !status?.ready ||
            status.authAttempted ||
            attempted.current
          }
          onClick={() => void authenticate()}
        >
          {posting ? "Claude 연결 확인 중…" : "Claude 연결 확인"}
        </button>
        <small>모델 접근만 확인 · 스토리·영상 생성 없음</small>
      </div>
      {!!status?.unknownCount && (
        <div>
          <button
            type="button"
            disabled={
              disabled ||
              loading ||
              posting ||
              archiving ||
              !status.archiveReady ||
              archiveAttempted.current
            }
            onClick={() => setArchiveConfirmation(true)}
          >
            {archiving
              ? "이전 불명 기록 정리 중…"
              : `이전 불명 기록 ${status.unknownCount}건 정리`}
          </button>
          <small>원본과 재요청 방지 기록은 보관 · 활성 목록만 정리</small>
        </div>
      )}
      {!!status?.archivedCount && (
        <small>
          보관된 불명 기록 {status.archivedCount}건 · 재요청 허용 아님
        </small>
      )}
      {message && <p role="status">{message}</p>}
      {archiveConfirmation && (
        <CharacterDialog
          title="이전 불명 기록 정리"
          busy={archiving}
          onClose={() => setArchiveConfirmation(false)}
          confirmation
        >
          <p>
            이전 불명 기록 {status?.unknownCount ?? 0}건을 활성 목록에서만
            정리합니다. 원본과 재요청 방지 기록은 보관하며, 같은 요청을 다시
            실행하도록 허용하지 않습니다.
          </p>
          <div className="kling-character-history-tools">
            <button
              type="button"
              disabled={archiving}
              onClick={() => setArchiveConfirmation(false)}
            >
              취소
            </button>
            <button
              type="button"
              disabled={archiving || archiveAttempted.current}
              onClick={() => void archiveUnknown()}
            >
              {archiving ? "정리 중…" : "기록 보관 후 목록 정리"}
            </button>
          </div>
        </CharacterDialog>
      )}
    </section>
  );
}
function CharacterDialog({
  title,
  busy,
  onClose,
  children,
  confirmation = false,
}: {
  title: string;
  busy: boolean;
  onClose: () => void;
  children: ReactNode;
  confirmation?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    if (node && !node.open) node.showModal();
    return () => {
      if (node?.open) node.close();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="command-dialog kling-character-dialog"
      role={confirmation ? "alertdialog" : "dialog"}
      aria-label={title}
      onCancel={(e) => {
        if (busy) e.preventDefault();
        else onClose();
      }}
    >
      <div className="dialog-head">
        <h2>{title}</h2>
        <button
          type="button"
          aria-label={`${title} 닫기`}
          disabled={busy}
          onClick={onClose}
        >
          <X size={18} />
        </button>
      </div>
      <div className="command-body">{children}</div>
    </dialog>
  );
}
const historyProtectedStates = new Set([
  "writing",
  "preparing",
  "generating",
  "retry_quoting",
  "composing",
]);
type VisibilityTarget = {
  id: string;
  topic: string;
  scope: "history" | "recent";
  hidden: boolean;
};
const defaultSettings: Settings = {
  video_model: "",
  script_model: "",
  style: "",
  aspect_ratio: "9:16",
  native_resolution: "model_default",
  output_quality: "1080p",
  sound: "on",
  clip_seconds: 11,
  duration: 55,
};
const stamp = (n: number) =>
  `${Math.floor(Math.round(n) / 60)}:${String(Math.round(n) % 60).padStart(2, "0")}`;

export default function CharacterStudio({ c }: { c: Controller }) {
  const [id, setId] = useState(() => {
      const query = new URLSearchParams(window.location.search);
      if (!query.has("job_id")) return "";
      const requested = query.get("job_id") ?? "";
      return /^[a-f0-9]{32}$/.test(requested) ? requested : "unavailable";
    }),
    [topic, setTopic] = useState(""),
    [scene, setScene] = useState(-1);
  const [settings, setSettings] = useState<Settings>(defaultSettings),
    [tab, setTab] = useState("upload");
  const [file, setFile] = useState<File | null>(null);
  const [referencePreview, setReferencePreview] = useState(false);
  const [activeProfile, setActiveProfile] = useState<Item | null>(null);
  const [scriptDirty, setScriptDirty] = useState(false);
  const [automationBusy, setAutomationBusy] = useState(false);
  const [saveToLibrary, setSaveToLibrary] = useState(false);
  const [libraryBusy, setLibraryBusy] = useState(false);
  const [libraryMessage, setLibraryMessage] = useState("");
  const librarySending = useRef(false);
  const savedUploads = useRef(new WeakMap<File, string>());
  const [confirmedLibraryAssets, setConfirmedLibraryAssets] = useState<Record<string, boolean>>({});

  const [scenePreview, setScenePreview] = useState<{
    url: string;
    title: string;
    seconds: number;
  } | null>(null);
  const [asset, setAsset] = useState("");
  const [referenceJob, setReferenceJob] = useState("");
  const [storyReuseRequests, setStoryReuseRequests] = useState<
    Record<string, string>
  >({});
  const [storyRequests, setStoryRequests] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false),
    [history, setHistory] = useState(false),
    [help, setHelp] = useState(false),
    [videoAdvanced, setVideoAdvanced] = useState(false);
  const [perOverrides, setPerOverrides] = useState<Record<string, string>>({});
  const [failure, setFailure] = useState("");
  const pending = useRef<string | null>(null),
    upload = useRef<HTMLInputElement>(null),
    sending = useRef(false);
  const [visibilityBusy, setVisibilityBusy] = useState(false);
  const [trialBusy, setTrialBusy] = useState(false);
  const [visibilityTarget, setVisibilityTarget] =
    useState<VisibilityTarget | null>(null);
  const [showTrash, setShowTrash] = useState(false);
  const visibilitySending = useRef(false);
  const allJobs = c.list("jobs"),
    jobs = allJobs.filter((x) => !x.trashed),
    job =
      id === "new"
        ? undefined
        : id ? jobs.find((x) => String(x.id) === id) : jobs[0];
  const selectionUnavailable = !c.loading && !!c.view && id !== "" && id !== "new" && !job;
  const perKey = job?.id ? String(job.id) : "new";
  const per = perOverrides[perKey] ?? (job ? String(job.episode_limit ?? "") : "10");
  function setPer(value: string) {
    setPerOverrides((current) => ({ ...current, [perKey]: value }));
  }
  const caps = c.view?.catalog.characterStudio,
    ready = caps?.version === 2,
    choices = Object.fromEntries(
      (caps?.modelsDetailed ?? [])
        .filter((m: Item) => m.enabled)
        .map((m: Item) => [m.id, m.label]),
    );
  const currentModel: Item | undefined = caps?.modelsDetailed?.find(
    (m: Item) => m.id === settings.video_model,
  );
  const trialEnabled = caps?.liveTrial?.enabled === true;
  const executionEnabled = trialEnabled || caps?.manualExecutionEnabled !== false;
  const [adjustments, setAdjustments] = useState<Record<string, string>>({});
  const estimate = publicEstimate(currentModel, job?.automation_version === 1 && job.story?.scenes
    ? { ...settings, duration: job.story.scenes.reduce((total: number, row: Item) => total + Number(row.seconds), 0) }
    : settings);
  useEffect(() => {
    if (ready && !job?.studio_selection) {
      setSettings(
        trialEnabled && !job
          ? { ...caps.defaults, duration: 15, clip_seconds: 3 }
          : caps.defaults,
      );
      setAdjustments(caps.restoredNotes ?? {});
    }
  }, [caps?.revision, job?.id, trialEnabled]);
  function changeModel(id: string) {
    const model = caps?.modelsDetailed?.find((m: Item) => m.id === id);
    if (!model) return;
    const adjusted = adjustModel(settings, model, caps.character);
    setSettings(adjusted.value);
    setAdjustments(adjusted.notes);
  }
  function changeDuration(v: string) {
    const total = Number(v);
    if (total < 15 || total > 60 || total % 5 !== 0) return;
    setSettings((x) => ({ ...x, duration: total }));
  }
  const story = job?.story,
    scenes: Item[] = story?.scenes ?? [],
    clips: Item[] = job?.scenes ?? [];
  const pendingSceneChecks = clips.some((clip) => clip.state === "submitted");
  const canCheckScenes = job?.state === "generating" || (job?.state === "scene_review" && pendingSceneChecks);
  const sceneProgressSummary = [
    ["failed", "실패"], ["submitted", "상태 확인 대기"], ["downloaded", "저장"], ["unknown", "결과 불명"],
  ].map(([state, label]) => {
    const count = clips.filter((clip) => clip.state === state).length;
    return count ? `${label} ${count}` : "";
  }).filter(Boolean).join(" · ");
  const failureDetails = clips.filter((clip) => ["failed", "nsfw", "canceled"].includes(clip.state)).map((clip) => {
    const details = clip.status_diagnostics;
    const diagnosed = !!details && typeof details === "object" && !Array.isArray(details);
    const observedLabels: Record<string, string> = {
      failed: "실패", nsfw: "제한됨", canceled: "취소됨", queued: "대기",
      in_progress: "진행 중", completed: "완료", unknown: "확인 불가",
    };
    return {
      position: clip.position,
      diagnosed,
      observed: diagnosed ? observedLabels[details.observed_state] ?? "확인 불가" : "",
      message: !diagnosed ? "아직 실패 상세를 확인하지 않았습니다."
        : details.detail_available === true && typeof details.error_message === "string" && details.error_message.trim()
          ? details.error_message : "공급사가 오류 설명을 제공하지 않았습니다.",
      mismatch: diagnosed && details.state_mismatch === true,
      checkedAt: diagnosed && typeof details.checked_at === "string" && Number.isFinite(Date.parse(details.checked_at))
        ? new Date(details.checked_at).toLocaleString("ko-KR") : "",
    };
  });
  const canDiagnoseScenes = job?.state === "scene_review" && !!job?.studio_selection && failureDetails.length > 0
    && clips.every((clip) => ["failed", "nsfw", "canceled", "submitted", "downloaded"].includes(clip.state));
  const selectedClip = clips.find((x) => x.position === scene + 1);
  const singleVideo =
    clips.length === 1 &&
    Number(job?.duration ?? job?.studio_selection?.duration) === 15;
  const previewUrl = singleVideo
    ? (job?.mediaUrl ?? clips[0]?.mediaUrl)
    : scene >= 0
      ? selectedClip?.mediaUrl
      : job?.mediaUrl;
  const selectedReference =
    job?.referenceUrl === `/api/studio/characters/${job?.id}/reference`
      ? job.referenceUrl
      : null;
  const clonedReference =
    referenceJob && /^[a-f0-9]{32}$/.test(referenceJob)
      ? `/api/studio/characters/${referenceJob}/reference`
      : null;
  // A new story keeps its selected profile after leaving a saved job.
  // Existing jobs still use their immutable reference, not the current profile.
  const referenceAssetId = asset || (!job ? activeProfile?.asset ?? "" : "");
  const savedReference = /^studio-[a-f0-9]{64}\.png$/.test(referenceAssetId)
    ? `/image-studio/assets/${referenceAssetId}`
    : null;
  const reference = file || savedReference || clonedReference || selectedReference;
  function storyRequestKey() {
    const selected = activeProfile
      ? ["profile", activeProfile.id, activeProfile.revision, activeProfile.reference_image?.sha256]
      : referenceJob
      ? ["job", referenceJob]
      : file
        ? ["upload", file.name, file.size, file.lastModified]
        : asset
          ? ["asset", asset]
          : ["job", job?.id || ""];
    return JSON.stringify([
      topic.replace(/[\r\n\t]+/g, " ").trim(), settings, Number(per), selected,
    ]);
  }
  const blockedStoryRequest = !!storyRequests[storyRequestKey()];
  const pendingReferenceCopy =
    !!story && !!job?.studio_selection && !!(file || referenceJob || asset);
  const isBusy = busy || visibilityBusy || trialBusy || libraryBusy || automationBusy,
    frozen =
      !!job &&
      !["needs_script", "script_review", "script_failed"].includes(job.state) &&
      job.quoteSettingsEditable !== true;
  const quoteSettingsChanged =
    job?.state === "quoted" &&
    quotedSettingsDirty(
      settings,
      job.studio_selection,
      per,
      String(job.day_limit ?? job.episode_limit),
      job.episode_limit,
      job.day_limit ?? job.episode_limit,
    );
  const currentQuote = job?.state === "quoted" && !quoteSettingsChanged
    ? Number(job.quote)
    : NaN;
  const budgetAmount = Number.isFinite(currentQuote) && currentQuote > 0
    ? currentQuote
    : estimate.upper;
  const budgetExceeded =
    budgetAmount !== null && Number(per) > 0 && budgetAmount > Number(per);
  const settingsFrozen = frozen && !pendingReferenceCopy;
  const legacy = !!job && !job.studio_selection;
  const lockedScriptModel = !!job?.studio_selection;
  const legacyStoryTiming = !!story && job?.automation_version !== 1 && scenes.length !== 5;
  useEffect(() => {
    if (job?.topic) setTopic(job.topic);
    if (job?.studio_selection) {
      const s = job.studio_selection;
      setSettings(
        Object.fromEntries(
          Object.keys(defaultSettings).map((k) => [k, s[k]]),
        ) as Settings,
      );
    }
    if (job?.automation_version === 1 && job.characterProfile) setActiveProfile(job.characterProfile);
    else if (job) setActiveProfile(null);
    setScene(-1);
  }, [job?.id]);
  function setting(k: keyof Settings, v: string) {
    setSettings((s) => ({
      ...s,
      [k]: ["duration", "clip_seconds"].includes(k) ? Number(v) : v,
    }));
  }
  function reset(useCurrentProfile = false) {
    if (useCurrentProfile) setActiveProfile(current => current
      ? profiles.find(profile => profile.id === current.id) ?? current : null);
    if (job) {
      setPerOverrides((current) => {
        const next = { ...current };
        delete next.new;
        return next;
      });
    }
    setId("new");
    setReferenceJob("");
    setTopic("");
    setScene(-1);
    setFailure("");
    pending.current = null;
  }
  function startFromCharacter() {
    if (isBusy || !job?.id || !selectedReference) return;
    const source = job.id;
    reset();
    setFile(null);
    setAsset("");
    setReferenceJob(source);
    setTab("upload");
    c.setNotice(
      "캐릭터를 선택했습니다. 새 스토리 주제를 입력하세요.",
    );
  }
  function selectFile(f: File | undefined) {
    if (!f) return;
    if (
      !["image/png", "image/jpeg"].includes(f.type) ||
      f.size > 10 * 1024 * 1024
    ) {
      setFailure("PNG/JPG, 최대 10MB 이미지를 선택하세요.");
      return;
    }
    if (story && job?.studio_selection) {
      setReferenceJob("");
      setFailure("");
      pending.current = null;
    } else reset();
    setFile(f);
    setAsset("");
    setActiveProfile(null);
    setSaveToLibrary(false);
    setLibraryMessage("");
  }
  async function saveReference(selectedFile: File) {
    const saved = savedUploads.current.get(selectedFile);
    if (saved) return saved;
    if (librarySending.current) return;
    librarySending.current = true;
    setLibraryBusy(true);
    setLibraryMessage("");
    try {
      const body = new FormData();
      body.set("csrf_token", c.view?.csrfToken ?? "");
      body.set("save_to_library", "true");
      body.set("reference", selectedFile);
      const response = await fetch("/api/studio/characters/library", {
        method: "POST",
        credentials: "same-origin",
        body,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !/^studio-[a-f0-9]{64}\.png$/.test(data.id ?? ""))
        throw Error(typeof data.detail === "string" ? data.detail : "캐릭터를 저장하지 못했습니다. 이미지와 저장 공간을 확인하세요.");
      savedUploads.current.set(selectedFile, data.id);
      setConfirmedLibraryAssets(current => ({ ...current, [data.id]: true }));
      setAsset(data.id);
      setLibraryMessage(data.created ? "참조 이미지를 보관했습니다." : "이미 보관된 참조 이미지입니다.");
      try {
        await c.load();
      } catch {
        setLibraryMessage("참조 이미지는 보관됐습니다. 목록을 보려면 화면을 새로고침하세요.");
      }
      return data.id as string;
    } catch (error) {
      setSaveToLibrary(false);
      setLibraryMessage(error instanceof Error ? error.message : "저장 결과를 확인하지 못했습니다. 저장한 참조 이미지 목록을 확인하세요.");
    } finally {
      librarySending.current = false;
      setLibraryBusy(false);
    }
  }
  async function post(url: string, body: FormData) {
    body.set("csrf_token", c.view?.csrfToken ?? "");
    const r = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      body,
    });
    const data = await r.json().catch(() => ({}));
    if (data.id) setId(data.id);
    if (data.fields) setAdjustments(data.fields);
    if (!r.ok)
      throw Object.assign(new Error(
        data.error ??
          data.detail ??
          "요청이 중단되었습니다. 작업 이력을 확인하세요. 자동 재전송하지 않습니다.",
      ), { status: r.status });
    return data;
  }
  async function changeVisibility(target: VisibilityTarget) {
    if (visibilitySending.current || busy) return;
    visibilitySending.current = true;
    setVisibilityBusy(true);
    setFailure("");
    try {
      const body = new URLSearchParams();
      body.set("csrf_token", c.view?.csrfToken ?? "");
      body.set("scope", target.scope);
      body.set("hidden", String(target.hidden));
      const response = await fetch(
        `/api/studio/characters/${target.id}/visibility`,
        {
          method: "POST",
          credentials: "same-origin",
          body,
        },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok)
        throw Error(
          typeof data.error === "string"
            ? data.error
            : typeof data.detail === "string"
              ? data.detail
              : "목록 변경을 저장하지 못했습니다. 작업 이력을 확인하세요.",
        );
      if (
        target.scope === "history" &&
        target.hidden &&
        job?.id === target.id
      ) {
        reset();
        setFile(null);
        setAsset("");
      }
      c.setNotice(
        target.scope === "history"
          ? target.hidden
            ? "작업을 휴지통으로 옮겼습니다. 원본 파일과 생성·비용 기록은 보존됩니다."
            : "작업 이력을 복원했습니다."
          : target.hidden
            ? "최근 목록에서 제거했습니다. 원본 이미지와 작업 이력은 유지됩니다."
            : "최근 사용 캐릭터 목록에 복원했습니다.",
      );
      await c.load();
    } catch (error) {
      setFailure(
        error instanceof Error
          ? error.message
          : "목록 변경 결과를 확인하지 못했습니다. 자동으로 재요청하지 않습니다.",
      );
      try {
        await c.load();
      } catch {
        /* A failed read never retries the visibility request. */
      }
    } finally {
      setVisibilityTarget(null);
      setVisibilityBusy(false);
      visibilitySending.current = false;
    }
  }
  async function autoStory() {
    const inputKey = storyRequestKey();
    if (sending.current || !ready || storyRequests[inputKey] || !activeProfile || !scriptAvailable ||
        (job?.automation_version === 1 && job.script && topic.trim() === String(job.topic).trim())) return;
    sending.current = true;
    setBusy(true);
    setFailure("");
    // New inputs get a new identity; an uncertain identical input cannot be replayed.
    const requestId = crypto.randomUUID().replaceAll("-", "");
    pending.current = requestId;
    setStoryRequests((value) => ({ ...value, [inputKey]: requestId }));
    let storyRequested = false;
    try {
      const form = new FormData();
      form.set("topic", topic.trim());
      form.set("studio_settings", JSON.stringify(settings));
      form.set("request_id", requestId);
      form.set("consent", "true");
      form.set("episode_limit", per);
      form.set("character_id", activeProfile.id);
      form.set("character_revision", String(activeProfile.revision));
      const draft = await post("/character", form);
      let data = draft;
      if (draft.created) {
        const encoded = new URLSearchParams({
          job_id: draft.id,
          consent: "true",
          csrf_token: c.view?.csrfToken ?? "",
        });
        storyRequested = true;
        const response = await fetch("/api/studio/characters/auto-story", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/x-www-form-urlencoded" },
          body: encoded,
        });
        data = await response.json().catch(() => ({}));
        if (!response.ok)
          throw Error(
            data.error ??
              "스토리 요청 결과를 확인하지 못했습니다. 작업 이력을 확인하세요. 자동 재전송하지 않습니다.",
          );
      }
      if (!["script_review"].includes(data.state))
        throw Error(
          "이 요청은 이미 저장되어 있습니다. 작업 이력의 상태를 확인하세요. 자동 재생성하지 않습니다.",
        );
      setFile(null);
      setReferenceJob("");
      setAsset("");
      setStoryRequests((value) => {
        const next = { ...value };
        delete next[inputKey];
        return next;
      });
      c.setNotice(
        "스토리가 생성·저장되었습니다. 장면을 검토한 뒤 영상 견적을 확인하세요.",
      );
    } catch (e) {
      if (!storyRequested && e instanceof Error && "status" in e && e.status === 422) {
        setStoryRequests((value) => {
          const next = { ...value };
          delete next[inputKey];
          return next;
        });
      }
      setFailure(
        e instanceof Error
          ? e.message
          : "스토리 요청 중단 · 자동 재전송하지 않습니다.",
      );
    } finally {
      try {
        await c.load();
      } catch {
        setFailure("작업 목록을 불러오지 못했습니다. 새로고침해 저장된 결과를 확인하세요.");
      } finally {
        setBusy(false);
        sending.current = false;
      }
    }
  }
  async function reuseStoryForVideo() {
    if (
      sending.current ||
      isBusy ||
      !job?.id ||
      !story ||
      !(file || referenceJob || asset || selectedReference) ||
      !job.studio_selection ||
      job.automation_version === 1 ||
      !currentModel?.audio.native ||
      storyReuseRequests[job.id]
    )
      return;
    const sourceId = String(job.id);
    const requestId = crypto.randomUUID().replaceAll("-", "");
    sending.current = true;
    setStoryReuseRequests((value) => ({ ...value, [sourceId]: requestId }));
    setBusy(true);
    setFailure("");
    try {
      const body = file ? new FormData() : new URLSearchParams();
      body.set("csrf_token", c.view?.csrfToken ?? "");
      body.set("consent", "true");
      body.set("settings", JSON.stringify(settings));
      body.set("episode_limit", per);
      body.set("request_id", requestId);
      if (file && body instanceof FormData) body.set("reference", file);
      else if (referenceJob) body.set("reference_job", referenceJob);
      else if (asset) body.set("reference_asset", asset);
      const response = await fetch(
        `/api/studio/characters/${sourceId}/reuse-story`,
        {
          method: "POST",
          credentials: "same-origin",
          body,
        },
      );
      const data = await response.json().catch(() => ({}));
      if (!response.ok)
        throw Error(
          typeof data.error === "string"
            ? data.error
            : typeof data.detail === "string"
              ? data.detail
              : typeof data.message === "string"
                ? data.message
                : "새 영상 작업을 준비하지 못했습니다. 기존 작업은 유지됩니다. 자동 재요청하지 않습니다.",
        );
      if (
        !/^[a-f0-9]{32}$/.test(data.id ?? "") ||
        data.id === sourceId ||
        data.reusedStory !== true ||
        data.additionalClaudeCalls !== 0
      ) {
        throw Error(
          "새 작업 준비 결과를 확인하지 못했습니다. 작업 이력을 확인하세요. 자동 재요청하지 않습니다.",
        );
      }
      await c.load();
      setStoryReuseRequests((value) => {
        const next = { ...value };
        delete next[sourceId];
        return next;
      });
      setId(data.id);
      setFile(null);
      setAsset("");
      setReferenceJob("");
      setTopic("");
      setScene(-1);
      pending.current = null;
      c.setNotice(
        "선택한 캐릭터로 새 영상 작업을 준비했습니다. 견적을 확인하세요.",
      );
    } catch (error) {
      setFailure(
        error instanceof Error
          ? error.message
          : "새 영상 작업 준비 결과가 불명확합니다. 자동 재요청하지 않습니다.",
      );
      try {
        await c.load();
      } catch {
        /* Never retry a local copy when its result is uncertain. */
      }
    } finally {
      setBusy(false);
      sending.current = false;
    }
  }
  async function saveSettings() {
    if (!job?.studio_selection || pendingReferenceCopy) return false;
    const form = new FormData();
    form.set("settings", JSON.stringify(settings));
    form.set("episode_limit", per);
    const encoded = new URLSearchParams();
    form.set("csrf_token", c.view?.csrfToken ?? "");
    form.forEach((v, k) => encoded.set(k, String(v)));
    const r = await fetch(`/api/studio/characters/${job.id}/settings`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: encoded,
    });
    if (!r.ok)
      throw Error(
        "영상 설정을 저장하지 못했습니다. 견적은 요청하지 않았습니다.",
      );
    const data = await r.json().catch(() => ({}));
    await c.load();
    return data.quoteRetained === true;
  }
  async function recoverStory() {
    if (!job || sending.current) return;
    sending.current = true; setBusy(true); setFailure("");
    try {
      const body = new URLSearchParams({consent: "true", csrf_token: c.view?.csrfToken ?? ""});
      const response = await fetch(`/api/studio/characters/${job.id}/recover-story`, {
        method: "POST", credentials: "same-origin", body,
      });
      if (!response.ok) throw Error("저장된 스토리 응답을 복구하지 못했습니다. 추가 AI 요청은 하지 않았습니다.");
      await c.load();
      c.setNotice("저장된 스토리를 복구했습니다. 내용을 검토한 뒤 견적을 확인하세요.");
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "복구 결과를 확인하세요. 자동 재요청하지 않습니다.");
    } finally { setBusy(false); sending.current = false; }
  }
  async function quote() {
    if (sending.current || pendingReferenceCopy || scriptDirty) return;
    sending.current = true;
    setBusy(true);
    setFailure("");
    try {
      if (await saveSettings()) {
        c.setNotice("설정을 저장했습니다. 현재 견적을 사용할 수 있습니다.");
        return;
      }
      c.open("character_act_prepare", {
        job_id: job?.id,
        state: "script_review",
      });
    } catch (e) {
      setFailure(e instanceof Error ? e.message : "영상 설정 저장 실패");
    } finally {
      setBusy(false);
      sending.current = false;
    }
  }
  function action(kind: string, label: string, allowed: string[]) {
    const connectionUnavailable = !executionEnabled && ["submit", "check", "diagnose", "retry-quote", "retry-scene"].includes(kind);
    const actionLabel = connectionUnavailable
      ? kind === "check" ? "상태 조회 연결 준비 중" : kind === "diagnose" ? "실패 상세 연결 준비 중" : kind === "retry-quote" ? "추가 견적 연결 준비 중" : "영상 생성 연결 준비 중"
      : label;
    return (
      <ActionButton
        c={c}
        id={`character_act_${kind}`}
        context={{
          job_id: job?.id,
          state: job?.state,
          quote_hash:
            kind === "retry-scene" ? job?.retry_hash : job?.quote_hash,
          retry_hash: job?.retry_hash,
          retryQuote: job?.retryQuote,
        }}
        disabled={
          isBusy ||
          !job ||
          !allowed.includes(job.state) ||
          pendingReferenceCopy ||
          connectionUnavailable ||
          (kind === "submit" && (budgetExceeded || quoteSettingsChanged))
        }
        primary
      >
        <Clapperboard size={24} />
        {actionLabel}
      </ActionButton>
    );
  }
  const myCharacters: Item[] = c.view?.catalog.myCharacters ?? [];
  const profiles: Item[] = c.view?.catalog.characterProfiles ?? [];
  const referenceAsset = file ? savedUploads.current.get(file) : asset || activeProfile?.asset;
  const referenceStored = !!referenceAsset && (myCharacters.some(row => row.id === referenceAsset)
    || confirmedLibraryAssets[referenceAsset] === true);
  const referenceStorageStatus = !reference ? "" : referenceStored ? "보관됨"
    : referenceAsset ? "아직 보관 안 됨" : "보관 여부 확인 전";
  const apiProviders: Item[] = c.view?.catalog.characterAIProviders ?? [];
  const scriptProvider = apiProviders.find((p) => p.models?.includes(settings.script_model));
  const scriptAvailable = scriptProvider?.configured === true;
  async function ensureProfileAsset() {
    if (file) return await saveReference(file) ?? "";
    if (asset || activeProfile?.asset) return asset || activeProfile?.asset;
    const existing = clonedReference || selectedReference;
    if (existing) {
      const response=await fetch(existing,{credentials:"same-origin"});
      if(!response.ok)throw Error("기존 참조 이미지를 불러오지 못했습니다.");
      const blob=await response.blob();
      if(blob.size>10*1024*1024)throw Error("참조 이미지 크기를 확인하세요.");
      return await saveReference(new File([blob],"기존 참조 이미지.png",{type:"image/png"}))??"";
    }
    return "";
  }
  function selectProfile(profile: Item | null) {
    reset(); setActiveProfile(profile); setFile(null); setAsset(profile?.asset ?? "");
    setTab("mine");
  }
  async function storeCurrentReference() {
    if (isBusy || referenceStored || !reference) return;
    if (file) { await saveReference(file); return; }
    setLibraryBusy(true);
    setLibraryMessage("");
    try {
      const response = await fetch(String(reference), { credentials: "same-origin" });
      if (!response.ok) throw Error("참조 이미지를 불러오지 못했습니다.");
      const blob = await response.blob();
      if (blob.size > 10 * 1024 * 1024) throw Error("참조 이미지 크기를 확인하세요.");
      await saveReference(new File([blob], "참조 이미지.png", { type: "image/png" }));
    } catch (error) {
      setSaveToLibrary(false);
      setLibraryMessage(error instanceof Error ? error.message : "보관 상태를 확인하지 못했습니다.");
    } finally { setLibraryBusy(false); }
  }
  let elapsed = 0;
  return (
    <>
      {referencePreview && <CharacterModal title="참조 이미지 미리보기" onClose={()=>setReferencePreview(false)}
        footer={<button type="button" onClick={()=>setReferencePreview(false)}>닫기</button>}>
        <div className="character-reference-large">{file?<LocalReference file={file}/>:reference?<img src={String(reference)} alt="선택한 캐릭터 참조 이미지 원본"/>:null}</div>
      </CharacterModal>}
      <div className="kling-character-approved" aria-busy={isBusy}>
        <div className="kling-character-tools">
          <button onClick={() => setHelp((x) => !x)}>
            <BookOpen size={16} />
            튜토리얼 보기
          </button>
          <button onClick={() => setHistory((x) => !x)}>
            <Clock3 size={16} />
            작업 이력
          </button>
        </div>
        {selectionUnavailable && (
          <p className="kling-character-error" role="alert">
            선택한 작업을 찾을 수 없습니다. 작업 이력에서 다른 작업을 선택하세요.
          </p>
        )}
        {caps?.liveTrial?.enabled === true && (
          <CharacterTrialConnection
            csrfToken={c.view?.csrfToken ?? ""}
            disabled={isBusy}
            onBusy={setTrialBusy}
            onAuthenticated={() => c.load()}
          />
        )}
        {help && (
          <div
            className="kling-character-help"
            role="region"
            aria-label="캐릭터 제작 안내"
          >
            참조 이미지 선택 → 주제 입력 → 스토리 자동 생성하기 → 장면 검토 →
            영상 설정·공식 견적 → 비용 승인 → 장면 확인 → 합성·저장. 스토리는
            선택한 AI가 캐릭터 특징과 주제로 만들며, 영상 생성은 별도의 견적 승인이 필요합니다.
          </div>
        )}
        <div className="kling-character-steps" aria-label="캐릭터 제작 흐름">
          {[
            [Bot, "캐릭터 선택", "참조 이미지로 캐릭터를 설정합니다."],
            [
              BookOpen,
              "스토리 생성",
              "주제를 입력하면 AI가 스토리를 만듭니다.",
            ],
            [
              Clapperboard,
              "영상 제작",
              "장면을 생성하고 검토 후 영상을 완성합니다.",
            ],
          ].map(([Icon, title, desc], i) => {
            const Glyph = Icon as typeof Bot;
            return (
              <div key={i}>
                <b>{i + 1}</b>
                <span className="kling-character-step-icon">
                  <Glyph />
                </span>
                <span>
                  <strong>{title as string}</strong>
                  <small>{desc as string}</small>
                </span>
                {i < 2 && <ChevronRight className="kling-character-chevron" />}
              </div>
            );
          })}
        </div>
        <div className="kling-character-columns">
          <section className="kling-character-card kling-character-reference">
            <h2>
              <em>1.</em> 캐릭터 선택 <Info size={14} />
            </h2>
            <div className="kling-character-tabs">
              <button
                aria-pressed={tab === "upload"}
                disabled={isBusy}
                onClick={() => setTab("upload")}
              >
                참조 이미지 업로드
              </button>
              <button
                aria-pressed={tab === "mine"}
                disabled={isBusy}
                onClick={() => setTab("mine")}
              >
                내 캐릭터
              </button>
            </div>
            <CharacterProfiles onBusy={setAutomationBusy} profiles={profiles} selected={activeProfile} onSelect={selectProfile}
              ensureAsset={ensureProfileAsset} model={settings.script_model} available={scriptAvailable}
              csrf={c.view?.csrfToken ?? ""} disabled={isBusy} onRefresh={c.load}
              mode={tab} images={myCharacters} selectedAsset={asset} hasReference={!!reference}
              onSelectImage={(value)=>{reset();setFile(null);setAsset(value);setActiveProfile(null);}} />
            <div className="kling-character-reference-content" data-source={tab}>
              <button type="button" className="kling-character-reference-image" aria-label="참조 이미지 크게 보기"
                disabled={!reference || isBusy} onClick={()=>setReferencePreview(true)}>
                {file ? (
                  <LocalReference file={file} />
                ) : reference ? (
                  <img
                    src={String(reference)}
                    alt="선택한 캐릭터 참조 이미지"
                  />
                ) : asset ? (
                  <Empty>내 캐릭터 참조 소재를 선택했습니다.</Empty>
                ) : (
                  <Empty>캐릭터 참조 이미지를 선택하세요.</Empty>
                )}
              </button>
              <div className="kling-character-reference-options">
                {tab === "upload" && <>
                <button
                  className="kling-character-upload"
                  disabled={isBusy}
                  onClick={() => upload.current?.click()}
                >
                  <ImagePlus size={27} />
                  <strong>이미지 업로드</strong>
                  <small>
                    PNG, JPG
                    <br />
                    (최대 10MB)
                  </small>
                </button>
                <input
                  ref={upload}
                  type="file"
                  accept="image/png,image/jpeg"
                  aria-label="캐릭터 참조 이미지 업로드"
                  hidden
                  onChange={(e) => selectFile(e.target.files?.[0])}
                />
                <label className="check character-reference-store">
                  <input
                    type="checkbox"
                    checked={referenceStored || (!!reference && saveToLibrary)}
                    disabled={isBusy || referenceStored || !reference}
                    onChange={(e) => {
                      const checked = e.target.checked;
                      setSaveToLibrary(checked);
                      if (checked) void storeCurrentReference();
                    }}
                  />
                  참조 이미지 보관
                </label>
                {referenceStorageStatus && <small role="status" aria-label="참조 이미지 보관 상태">{referenceStorageStatus}</small>}
                {libraryBusy && <small role="status">캐릭터 저장 중…</small>}
                {libraryMessage && <small role="status">{libraryMessage}</small>}

                </>}
                {tab === "mine" && <details className="character-recent-references">
                <summary>최근 작업의 참조 이미지</summary>
                <div className="kling-character-recent">
                  {jobs
                    .filter((x) => x.referenceUrl && !x.recentHidden)
                    .slice(0, 4)
                    .map((x) => (
                      <div className="kling-character-recent-item" key={x.id}>
                        <button
                          type="button"
                          disabled={isBusy}
                          title={x.topic}
                          aria-label={`캐릭터 작업 ${x.topic} 열기`}
                          onClick={() => {
                            setId(x.id);
                            setReferenceJob("");
                            setFile(null);
                            setAsset("");
                            pending.current = null;
                          }}
                        >
                          <Thumbnail src={x.referenceUrl} alt={x.topic} />
                        </button>
                        <button
                          type="button"
                          className="kling-character-recent-remove"
                          disabled={isBusy}
                          title="최근 목록에서 제거"
                          aria-label={`${x.topic} 최근 목록에서 제거`}
                          onClick={() =>
                            setVisibilityTarget({
                              id: x.id,
                              topic: x.topic,
                              scope: "recent",
                              hidden: true,
                            })
                          }
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ))}
                  {!jobs.some((x) => x.referenceUrl && !x.recentHidden) && (
                    <small>최근 사용 캐릭터 없음</small>
                  )}
                </div>
                <details className="kling-character-recent-manage">
                  <summary>최근 목록 관리</summary>
                  <small>
                    최근 목록에서만 숨기며 원본 이미지와 작업 이력은 유지합니다.
                  </small>
                  {jobs
                    .filter((x) => x.referenceUrl && x.recentHidden)
                    .map((x) => (
                      <div className="kling-character-history-row" key={x.id}>
                        <span>{x.topic}</span>
                        <button
                          type="button"
                          disabled={isBusy}
                          aria-label={`${x.topic} 최근 목록에 복원`}
                          onClick={() =>
                            void changeVisibility({
                              id: x.id,
                              topic: x.topic,
                              scope: "recent",
                              hidden: false,
                            })
                          }
                        >
                          <RotateCcw size={14} /> 복원
                        </button>
                      </div>
                    ))}
                  {!jobs.some((x) => x.referenceUrl && x.recentHidden) && (
                    <small>숨긴 캐릭터가 없습니다.</small>
                  )}
                </details>
                </details>}
              </div>
            </div>
            {selectedReference && job?.id && job?.automation_version !== 1 && (
              <button
                type="button"
                disabled={isBusy}
                onClick={startFromCharacter}
              >
                이 캐릭터로 새 작업
              </button>
            )}

          </section>
          <section className="kling-character-card kling-character-story">
            <header>
              <h2>
                <em>2.</em> 스토리 생성 <Info size={14} />
              </h2>
              <button
                className="kling-character-example"
                disabled={isBusy}
                onClick={() => {
                  setTopic(
                    "호기심 많은 캐릭터가 새로운 세상을 여행하는 이야기",
                  );
                  setFailure("");
                  pending.current = null;
                }}
              >
                <Sparkles size={14} />
                예시 주제 보기
              </button>
            </header>
            <label>대본 AI
              <select aria-label="대본 AI" disabled={isBusy || lockedScriptModel} value={scriptProvider?.id ?? ""}
                onChange={(e) => {const provider = apiProviders.find(p => p.id === e.target.value); if(provider?.models?.[0]) setting("script_model",provider.models[0]);}}>
                <option value="" disabled>API를 선택하세요</option>
                {apiProviders.map(p => <option key={p.id} value={p.id} disabled={!p.configured}>{p.label}{p.configured ? "" : " · 키 등록 필요"}</option>)}
              </select>
            </label>
            <label>
              스토리 주제
              <div className="kling-character-topic">
                <textarea
                  aria-label="스토리 주제"
                  value={topic}
                  maxLength={60}
                  placeholder="캐릭터가 어떤 이야기를 펼칠까요?"
                  disabled={isBusy}
                  onChange={(e) => {
                    setTopic(e.target.value);
                    if (e.target.value.trim() !== topic.trim()) setFailure("");
                  }}
                />
                <small>{topic.length}/60</small>
              </div>
            </label>
            <button
              className="kling-character-story-generate"
              onClick={() => void autoStory()}
              disabled={
                isBusy ||
                !ready ||
                !c.view?.commandsAvailable ||
                !topic.trim() ||
                selectionUnavailable ||
                (job?.automation_version === 1 && job.script && topic.trim() === String(job.topic).trim()) ||
                !activeProfile || !scriptAvailable ||
                blockedStoryRequest
              }
            >
              <WandSparkles size={22} />
              {busy ? "스토리 처리 중…" : "스토리 자동 생성하기"}
              <span>→</span>
            </button>
            {(failure || job?.scriptFailure?.message || blockedStoryRequest) && (
              <div className="kling-character-error" role="alert">
                {failure || job?.scriptFailure?.message || "같은 요청의 결과를 확인하세요. 주제나 참조·설정을 바꾸면 새 스토리를 만들 수 있습니다."}
                {job?.scriptFailure && job.scriptResponseSaved && " 응답은 로컬에 보존되어 있습니다."}
                {(failure || blockedStoryRequest) && (
                  <button
                    disabled={isBusy}
                    onClick={() => {
                      setFailure("");
                      pending.current = null;
                      reset(true);
                    }}
                  >
                    새 스토리 입력
                  </button>
                )}
              </div>
            )}
            {job?.state === "script_failed" && job?.scriptResponseSaved && (
              <button type="button" disabled={isBusy} onClick={recoverStory}>
                저장된 스토리 복구 · 추가 비용 없음
              </button>
            )}
            {job?.scriptRetryAllowed === true && (
              <div className="kling-character-retry">
                {action("write", "이 작업의 스토리 다시 생성하기", ["script_failed"])}
                <small>저장된 이 작업의 주제·캐릭터·설정으로 새 스토리를 요청합니다. 비용 승인은 유지됩니다.</small>
              </div>
            )}

            <p className="kling-character-consent">스토리 생성은 유료입니다. 영상 제작은 별도 승인합니다.</p>
            <CharacterTopics onBusy={setAutomationBusy} profile={activeProfile} model={settings.script_model} available={scriptAvailable}
              topic={topic} onTopic={setTopic} csrf={c.view?.csrfToken ?? ""} disabled={isBusy} />
            {!ready && (
              <p role="status">
                새 제작실 API 연결 확인 전 · 생성할 수 없습니다.
              </p>
            )}
            {story ? (
              <div className={`kling-character-story-result${job?.automation_version === 1 ? " kling-character-story-result--episode" : ""}`}>
                <header>
                  <h3>한글 스토리 · {story.title}</h3>
                  <State value={job?.state} />
                </header>
                <small>장면을 검토한 뒤 영상 제작을 승인하세요.</small>
                {job?.message && <p role="status">{job.message}</p>}
                {job?.automation_version === 1 && <CharacterScriptEditor job={job} onDirty={setScriptDirty} csrf={c.view?.csrfToken ?? ""}
                  disabled={isBusy} onRefresh={c.load} />}
                {job?.studio_selection && job.automation_version !== 1 &&
                  selectedReference &&
                  currentModel?.audio.native && (
                    <div>
                      <button
                        type="button"
                        disabled={
                          isBusy ||
                          !c.view?.commandsAvailable ||
                          !!storyReuseRequests[job.id]
                        }
                        onClick={() => void reuseStoryForVideo()}
                      >
                        <Mic size={15} /> 이 스토리로 새 영상
                      </button>
                      <small>새 영상은 견적 확인 후 승인합니다.</small>
                    </div>
                  )}
                {scenes.map((s, i) => (
                  <p key={i}>
                    <strong>
                      {i + 1}. {s.caption}
                    </strong>
                    {s.narration && <small>대사 · {s.narration}</small>}
                  </p>
                ))}
                <details>
                  <summary>영상 모델 전달용 프롬프트</summary>
                  <small>영상 모델에 전달하는 원본 지시문입니다.</small>
                  {scenes.map((s, i) => {
                    const start = scenes
                      .slice(0, i)
                      .reduce(
                        (total, item) => total + Number(item.seconds ?? 0),
                        0,
                      );
                    return (
                      <p key={i}>
                        <strong>
                          {i + 1}. {stamp(start)} -{" "}
                          {stamp(start + Number(s.seconds ?? 0))}
                        </strong>
                        <span lang="en">{s.action}</span>
                      </p>
                    );
                  })}
                </details>
              </div>
            ) : (
              <div className="kling-character-story-empty">
                <BookOpen />
                <span>생성한 스토리가 여기에 표시됩니다.</span>
              </div>
            )}
            <details className="kling-character-advanced">
              <summary>
                <Settings2 size={14} />
                스토리 세부 설정
              </summary>
              <Select
                label="대본 모델"
                disabled={isBusy || lockedScriptModel}
                value={settings.script_model}
                onChange={(v) => setting("script_model", v)}
                options={scriptProvider?.models ?? []}
              />
              <label>
                편당 최대 승인 한도 (USD)
                <input
                  value={per}
                  inputMode="decimal"
                  onChange={(e) => setPer(e.target.value)}
                  disabled={isBusy || settingsFrozen}
                />
              </label>
            </details>
          </section>
          <section className="kling-character-card kling-character-video">
            <h2>
              <em>3.</em> 영상 제작 <Info size={14} />
            </h2>
            <div className="kling-character-video-content">
              <div
                className="kling-character-video-preview"
                data-ratio={settings.aspect_ratio}
              >
                <Media
                  url={previewUrl}
                  label={`${settings.aspect_ratio} 영상 미리보기`}
                />
                {!safeMedia(previewUrl) && <span>생성·검토된 영상 없음</span>}
              </div>
              <div className="kling-character-video-settings">
                <section
                  className="kling-video-settings-card"
                  aria-label="영상 설정"
                >
                  <header>
                    <h3>
                      영상 설정 <Info size={13} />
                    </h3>
                    <button
                      type="button"
                      className="kling-video-advanced-trigger"
                      aria-expanded={videoAdvanced}
                      aria-controls="kling-video-advanced"
                      onClick={() => setVideoAdvanced((x) => !x)}
                    >
                      고급 설정 <ChevronDown size={13} />
                    </button>
                  </header>
                  <fieldset
                    className="kling-five-settings"
                    disabled={isBusy || settingsFrozen || !ready}
                  >
                    <CapabilitySelect
                      label="영상 모델"
                      icon={<Bot size={18} />}
                      value={settings.video_model}
                      onChange={changeModel}
                      disabled={job?.automation_version === 1 && !!story}
                      values={choices}
                      supported={Object.keys(choices)}
                      hint={adjustments.video_model}
                    />
                    <CapabilitySelect
                      label="영상 길이"
                      icon={<Clock3 size={18} />}
                      value={String(settings.duration)}
                      onChange={changeDuration}
                      disabled={isBusy || settingsFrozen || legacyStoryTiming || (job?.automation_version === 1 && !!story)}
                      values={Object.fromEntries(
                        (caps?.totalDurationChoices ?? Array.from({ length: 10 }, (_, i) => 15 + i * 5)).map(
                          (total: number) => [String(total), `${total}초`],
                        ),
                      )}
                      supported={
                        (caps?.totalDurationChoices ?? Array.from({ length: 10 }, (_, i) => 15 + i * 5)).map(String)
                      }
                      unsupportedHint="이 모델은 전체 길이에 필요한 장면 길이를 지원하지 않아요."
                      hint={
                        job?.automation_version === 1 && story
                          ? "모델·길이는 새 스토리를 만들기 전에 선택하세요."
                          : legacyStoryTiming
                          ? "이 스토리의 길이는 변경할 수 없습니다."
                          : settingsFrozen
                            ? "새 영상으로 복사하면 길이를 변경할 수 있습니다."
                            : undefined
                      }
                    />
                    <CapabilitySelect
                      label="영상 스타일"
                      icon={<Sparkles size={18} />}
                      value={settings.style}
                      onChange={() => {}}
                      disabled
                      values={activeProfile ? { [settings.style]: "캐릭터 고정" } : caps?.styles ?? {}}
                      supported={[settings.style]}
                      hint={adjustments.style}
                    />
                    <CapabilitySelect
                      label="화면 비율"
                      icon={<Ratio size={18} />}
                      value={settings.aspect_ratio}
                      onChange={() => {}}
                      disabled
                      values={caps?.ratios ?? {}}
                      supported={["9:16"]}
                      hint={adjustments.aspect_ratio}
                    />
                    <CapabilitySelect
                      label="모델 생성 화질"
                      icon={<Monitor size={18} />}
                      value={currentModel?.param_map?.resolution === "mode" && settings.native_resolution === "model_default" ? "std" : settings.native_resolution}
                      onChange={(v) => setting("native_resolution", v)}
                      values={{
                        model_default: "Standard 고정 화질",
                        ...Object.fromEntries(
                          (caps?.resolutionChoices ?? []).map((x: string) => [
                            x,
                            ({ std: "Standard", pro: "Pro", "4k": "4K" } as Record<string, string>)[x] ?? x,
                          ]),
                        ),
                      }}
                      supported={currentModel?.resolutions ?? []}
                      hint={adjustments.native_resolution}
                    />
                    <CapabilitySelect
                      label="최종 저장 크기"
                      icon={<Monitor size={18} />}
                      value={settings.output_quality}
                      onChange={(v) => setting("output_quality", v)}
                      values={{ "1080p": "1080p (1080×1920)" }}
                      supported={["1080p"]}
                      disabled
                    />
                    <CapabilitySelect
                      label="소리 생성"
                      ariaLabel="소리 생성"
                      icon={<Mic size={18} />}
                      value={settings.sound}
                      onChange={(v) => setting("sound", v)}
                      values={{ off: "끄기", on: "켜기 (환경음만)" }}
                      supported={
                        currentModel?.audio.native ? ["off", "on"] : ["off"]
                      }
                      hint={adjustments.sound}
                    />
                  </fieldset>
                  {videoAdvanced && (
                    <div
                      id="kling-video-advanced"
                      className="kling-video-advanced-body"
                    >
                      <p>
                        캐릭터 스타일과 화면 비율은 고정됩니다.
                      </p>
                      {job?.state === "scene_review" && !pendingSceneChecks &&
                        action("retry-quote", "실패 장면 새 견적", [
                          "scene_review",
                        ])}
                      {job?.state === "retry_quoted" &&
                        action("retry-scene", "실패 장면 추가 견적 승인", [
                          "retry_quoted",
                        ])}
                    </div>
                  )}
                </section>
                <section
                  className="kling-video-production-card"
                  aria-label="영상 비용 및 제작"
                >
                  <div className="kling-character-cost">
                    <strong>
                      <Coins size={22} /> 예상 비용 <Info size={13} />
                    </strong>
                    <b
                      title={
                        job?.quote
                          ? "공식 견적 · 실제 청구액 아님"
                          : currentModel?.pricing.note
                      }
                    >
                      {job?.quote ? `$${job.quote}` : estimate.label}
                    </b>
                  </div>
                  <div className="kling-character-generate">
                    {job?.state === "script_review" ||
                    (job?.state === "prepare_failed" &&
                      job.quoteSettingsEditable === true) ? (
                      <button
                        className="primary"
                        title="스토리 검토·공식 견적을 확인한 후 비용을 별도로 승인합니다."
                        disabled={
                          isBusy ||
                          pendingReferenceCopy ||
                          scriptDirty ||
                          legacy ||
                          !ready
                        }
                        onClick={() => void quote()}
                      >
                        <Clapperboard size={24} />
                        {job?.state === "prepare_failed"
                          ? "설정 저장·견적 확인"
                          : "영상 견적 확인"}
                      </button>
                    ) : job?.state === "quoted" ? (
                      action("submit", "영상 생성하기", ["quoted"])
                    ) : canCheckScenes ? (
                      action("check", job?.state === "scene_review" ? "남은 장면 상태 확인" : "장면 상태 확인", ["generating", "scene_review"])
                    ) : job?.state === "clips_review" ? (
                      action("render", "검토 후 영상 합성", ["clips_review"])
                    ) : job?.state === "completed" &&
                      safeMedia(job.mediaUrl) ? (
                      <a
                        href={`${job.mediaUrl}?download=true`}
                        className="primary"
                      >
                        완성 영상 저장
                      </a>
                    ) : (
                      <button disabled>
                        <Clapperboard size={24} />
                        영상 생성하기
                      </button>
                    )}
                    {job?.state === "quoted" &&
                      job.quoteSettingsEditable === true && (
                        <button
                          type="button"
                          disabled={
                            isBusy ||
                            pendingReferenceCopy ||
                            scriptDirty ||
                            legacy ||
                            !ready
                          }
                          onClick={() => void quote()}
                        >
                          설정 저장·견적 확인
                        </button>
                      )}
                  </div>
                  {sceneProgressSummary && ["generating", "scene_review", "submission_unknown", "clips_review"].includes(job?.state ?? "") && (
                    <p className="kling-field-note" role="status">{sceneProgressSummary}</p>
                  )}
                  {canDiagnoseScenes && (
                    <section aria-label="실패 상세">
                      {action("diagnose", "실패 상세 확인", ["scene_review"])}
                      <small>기존 요청의 오류 설명만 조회합니다. 새 영상·견적은 요청하지 않습니다.</small>
                      {failureDetails.map((detail) => (
                        <div className="kling-field-note" key={detail.position}>
                          <strong>장면 {detail.position}</strong>
                          {detail.diagnosed && <small>조회 상태: {detail.observed}</small>}
                          <p>{detail.message}</p>
                          {detail.mismatch && <p role="status">저장 상태와 조회 상태가 다릅니다. 기존 장면 상태는 유지됩니다.</p>}
                          {detail.checkedAt && <small>확인 시각: {detail.checkedAt}</small>}
                        </div>
                      ))}
                    </section>
                  )}
                  {scriptDirty && <p role="status">편집한 대본을 저장한 뒤 견적을 확인하세요.</p>}
                  {quoteSettingsChanged && (
                    <p role="status" className="kling-field-note">
                      설정이 바뀌었습니다. 견적을 다시 확인하세요.
                    </p>
                  )}
                  <small className="kling-cost-note">
                    {settings.duration}초 기준 ·{" "}
                    {job?.quote
                      ? "공식 견적, 실제 청구와 다름"
                      : "추정치, 공식 견적 확인 필요"}
                  </small>
                </section>
                {(
                  job?.reviewWarnings ?? [
                    caps?.stylePresets?.find(
                      (x: Item) => x.id === settings.style,
                    )?.warn,
                  ]
                )
                  .filter(Boolean)
                  .map((warning: string) => (
                    <p
                      className="kling-character-error"
                      role="note"
                      key={warning}
                    >
                      {warning}
                    </p>
                  ))}
                {Object.entries(adjustments)
                  .filter(
                    ([k]) =>
                      ![
                        "video_model",
                        "style",
                        "aspect_ratio",
                        "native_resolution",
                        "sound",
                      ].includes(k),
                  )
                  .map(([k, v]) => (
                    <p className="kling-field-note" role="status" key={k}>
                      {v}
                    </p>
                  ))}
                {caps?.cacheWarning && (
                  <p role="status" className="kling-field-note">
                    {caps.cacheWarning}
                  </p>
                )}
                {budgetExceeded && (
                  <p className="kling-character-error" role="alert">
                    예상 비용 상한이 편당 예산 ${per}를 넘습니다. 한도와 설정을
                    확인하세요.
                  </p>
                )}
                {legacy && (
                  <p className="kling-character-consent">
                    기존 모델 작업은 보존됩니다. 참조를 선택해 새 Kling 작업을
                    만드세요.
                  </p>
                )}
                {/unknown|failed/.test(job?.state ?? "") && (
                  <p role="status" className="kling-character-error">
                    작업 중단 · 결과를 확인하세요. 자동 재요청하지 않습니다.
                  </p>
                )}
              </div>
            </div>
          </section>
        </div>
        <section className="kling-character-card kling-character-storyboard">
          <header>
            <h2>
              {singleVideo ? "스토리 계획" : "생성된 장면"}{" "}
              <small>
                {singleVideo
                  ? `(${scenes.length}개 계획 · 15초 단일 영상)`
                  : `(${scenes.length}개 장면 · 최종 ${job?.duration ?? settings.duration}초)`}
              </small>
            </h2>
            <button
              onClick={() => setScene(-1)}
              disabled={!safeMedia(singleVideo ? previewUrl : job?.mediaUrl)}
            >
              <Play size={14} />
              최종 영상
            </button>
          </header>
          {job && <CharacterRegeneration onBusy={setAutomationBusy} job={job} csrf={c.view?.csrfToken ?? ""} disabled={isBusy} onRefresh={c.load} />}
          {!scenes.length && <Empty>대본을 생성하면 선택한 길이에 맞는 장면 계획이 표시됩니다.</Empty>}
          <div className="kling-character-scene-grid">
            {(scenes.length
              ? scenes
              : []
            ).map((s, i) => {
              const edited = job?.editTimeline?.[i];
              const start = edited?.start ?? elapsed;
              elapsed = edited ? edited.start + edited.seconds : elapsed + (s?.seconds ?? 0);
              const clip = clips.find((x) => x.position === i + 1);
              const media = clip?.mediaUrl;
              const planOnly = singleVideo && !clip;
              return (
                <button
                  key={i}
                  aria-pressed={scene === i}
                  disabled={!s || planOnly || !safeMedia(media)}
                  title={singleVideo ? s?.action : undefined}
                  onClick={() => {
                    if (!planOnly && safeMedia(media)) {
                      setScene(i);
                      setScenePreview({
                        url: media,
                        title: singleVideo ? "15초 전체 영상" : `장면 ${i + 1}`,
                        seconds: singleVideo
                          ? Number(job?.duration ?? 15)
                          : Number(clip?.seconds ?? s?.seconds ?? 0),
                      });
                    }
                  }}
                >
                  <div className="kling-character-scene-image">
                    <b>{i + 1}</b>
                    {safeMedia(media) ? (
                      <video src={media} preload="metadata" muted />
                    ) : (
                      <Clapperboard size={32} />
                    )}
                  </div>
                  <small>
                    {s
                      ? `${stamp(start)} - ${stamp(elapsed)}`
                      : "스토리 생성 대기"}
                  </small>
                  <strong>{s?.caption ?? `장면 ${i + 1}`}</strong>
                  {s &&
                    (planOnly ? (
                      <small>
                        스토리 계획 · 전체 영상에서 확인
                        <br />
                        별도 장면 파일 없음
                      </small>
                    ) : (
                      <>
                        {singleVideo && <small>15초 전체 영상</small>}
                        <State value={clip?.state ?? "pending"} />
                      </>
                    ))}
                </button>
              );
            })}
          </div>
        </section>
        {scenePreview && safeMedia(scenePreview.url) && (
          <CharacterDialog
            title={`${scenePreview.title} · ${scenePreview.seconds}초`}
            busy={false}
            onClose={() => setScenePreview(null)}
          >
            <video
              src={scenePreview.url}
              controls
              autoPlay
              playsInline
              preload="metadata"
              aria-label={scenePreview.title}
              style={{
                display: "block",
                width: "100%",
                maxHeight: "70vh",
                objectFit: "contain",
              }}
            />
          </CharacterDialog>
        )}
        {history && (
          <CharacterDialog
            title="작업 이력"
            busy={isBusy}
            onClose={() => setHistory(false)}
          >
            <div className="kling-character-history-tools">
              <button
                type="button"
                disabled={isBusy}
                onClick={() => {
                  reset(true);
                  setFile(null);
                  setAsset("");
                  setHistory(false);
                }}
              >
                새 작업
              </button>
              <button
                type="button"
                disabled={isBusy}
                aria-pressed={showTrash}
                onClick={() => setShowTrash((value) => !value)}
              >
                {showTrash ? "작업 이력 보기" : "휴지통 보기"}
              </button>
            </div>
            {failure && (
              <p role="alert" className="kling-character-error">
                {failure}
              </p>
            )}
            <p className="muted">
              삭제한 작업은 휴지통에서 복원할 수 있습니다. 원본 이미지·영상과
              생성·비용 기록은 삭제하지 않습니다.
            </p>
            {allJobs
              .filter((x) => Boolean(x.trashed) === showTrash)
              .map((x) => (
                <div className="kling-character-history-row" key={x.id}>
                  {showTrash ? (
                    <span>{x.topic}</span>
                  ) : (
                    <button
                      type="button"
                      className="kling-character-history-open"
                      disabled={isBusy}
                      onClick={() => {
                        setId(x.id);
                        setReferenceJob("");
                        setFile(null);
                        setAsset("");
                        pending.current = null;
                        setFailure("");
                        setHistory(false);
                      }}
                    >
                      {x.topic}
                    </button>
                  )}
                  <State value={x.state} />
                  <button
                    type="button"
                    disabled={
                      isBusy ||
                      (!showTrash && historyProtectedStates.has(x.state))
                    }
                    title={
                      !showTrash && historyProtectedStates.has(x.state)
                        ? "처리 중인 작업은 삭제할 수 없습니다."
                        : undefined
                    }
                    aria-label={`${x.topic} ${showTrash ? "작업 복원" : "작업 삭제"}`}
                    onClick={() =>
                      showTrash
                        ? void changeVisibility({
                            id: x.id,
                            topic: x.topic,
                            scope: "history",
                            hidden: false,
                          })
                        : setVisibilityTarget({
                            id: x.id,
                            topic: x.topic,
                            scope: "history",
                            hidden: true,
                          })
                    }
                  >
                    {showTrash ? (
                      <>
                        <RotateCcw size={15} /> 복원
                      </>
                    ) : (
                      <>
                        <Trash2 size={15} /> 삭제
                      </>
                    )}
                  </button>
                </div>
              ))}
            {!allJobs.some((x) => Boolean(x.trashed) === showTrash) && (
              <Empty>
                {showTrash
                  ? "휴지통이 비어 있습니다."
                  : "저장한 작업이 없습니다."}
              </Empty>
            )}
          </CharacterDialog>
        )}
        {visibilityTarget && (
          <CharacterDialog
            title={
              visibilityTarget.scope === "history"
                ? "작업 삭제 확인"
                : "최근 목록에서 제거"
            }
            busy={visibilityBusy}
            onClose={() => setVisibilityTarget(null)}
            confirmation
          >
            <p>
              <strong>{visibilityTarget.topic}</strong>
            </p>
            <p>
              {visibilityTarget.scope === "history"
                ? "작업 이력을 휴지통으로 옮깁니다. 원본 이미지·영상과 생성·비용 기록은 보존되며 나중에 복원할 수 있습니다."
                : "최근 사용 캐릭터 목록에서만 제거합니다. 원본 이미지와 작업 이력은 유지되며 최근 목록 관리에서 복원할 수 있습니다."}
            </p>
            <div className="kling-character-history-tools">
              <button
                type="button"
                disabled={visibilityBusy}
                onClick={() => setVisibilityTarget(null)}
              >
                취소
              </button>
              <button
                type="button"
                disabled={visibilityBusy}
                onClick={() => void changeVisibility(visibilityTarget)}
              >
                {visibilityBusy
                  ? "저장 중…"
                  : visibilityTarget.scope === "history"
                    ? "삭제"
                    : "최근 목록에서 제거"}
              </button>
            </div>
          </CharacterDialog>
        )}
      </div>
    </>
  );
}
