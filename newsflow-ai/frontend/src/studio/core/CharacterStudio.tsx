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

import {
  adjustModel,
  publicEstimate,
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
                  ? "이 모델에서는 지원하지 않아요"
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
const defaultSettings: Settings = {
  video_model: "",
  script_model: "",
  style: "",
  aspect_ratio: "9:16",
  native_resolution: "model_default",
  output_quality: "1080p",
  sound: "off",
  clip_seconds: 11,
  duration: 55,
};
const stamp = (n: number) =>
  `${Math.floor(n / 60)}:${String(n % 60).padStart(2, "0")}`;

export default function CharacterStudio({ c }: { c: Controller }) {
  const [id, setId] = useState(""),
    [topic, setTopic] = useState(""),
    [scene, setScene] = useState(-1);
  const [settings, setSettings] = useState<Settings>(defaultSettings),
    [tab, setTab] = useState("upload");
  const [file, setFile] = useState<File | null>(null);
  const [asset, setAsset] = useState("");
  const [busy, setBusy] = useState(false),
    [history, setHistory] = useState(false),
    [help, setHelp] = useState(false),
    [videoAdvanced, setVideoAdvanced] = useState(false);
  const [per, setPer] = useState("10"),
    [daily, setDaily] = useState("20"),
    [failure, setFailure] = useState("");
  const pending = useRef<string | null>(null),
    upload = useRef<HTMLInputElement>(null),
    sending = useRef(false);
  const jobs = c.list("jobs"),
    job =
      id === "new"
        ? undefined
        : (jobs.find((x) => String(x.id) === id) ?? jobs[0]);
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
  const [adjustments, setAdjustments] = useState<Record<string, string>>({});
  const estimate = publicEstimate(currentModel, settings);
  const budgetExceeded =
    estimate.upper !== null && Number(per) > 0 && estimate.upper > Number(per);
  useEffect(() => {
    if (ready && !job?.studio_selection) {
      setSettings(caps.defaults);
      setAdjustments(caps.restoredNotes ?? {});
    }
  }, [caps?.revision, job?.id]);
  function changeModel(id: string) {
    const model = caps?.modelsDetailed?.find((m: Item) => m.id === id);
    if (!model) return;
    const adjusted = adjustModel(settings, model, caps.character);
    setSettings(adjusted.value);
    setAdjustments(adjusted.notes);
  }
  function changeLength(v: string) {
    const n = Number(v);
    setSettings((x) => ({
      ...x,
      clip_seconds: n,
      duration: n * Math.min(5, Math.floor(60 / n)),
    }));
  }
  const story = job?.story,
    scenes: Item[] = story?.scenes ?? [],
    clips: Item[] = job?.scenes ?? [];
  const selectedClip = clips.find((x) => x.position === scene + 1);
  const selectedReference =
    job?.referenceUrl === `/api/studio/characters/${job?.id}/reference`
      ? job.referenceUrl
      : null;
  const reference = file || selectedReference;
  const isBusy = busy,
    frozen =
      !!job &&
      !["needs_script", "script_review", "script_failed"].includes(job.state);
  const legacy = !!job && !job.studio_selection;
  const lockedDuration = !!job?.studio_selection;
  useEffect(() => {
    if (job?.studio_selection) {
      const s = job.studio_selection;
      setSettings(
        Object.fromEntries(
          Object.keys(defaultSettings).map((k) => [k, s[k]]),
        ) as Settings,
      );
      setPer(job.episode_limit);
      setDaily(job.day_limit);
    }
    setScene(-1);
  }, [job?.id]);
  function setting(k: keyof Settings, v: string) {
    setSettings((s) => ({
      ...s,
      [k]: ["duration", "clip_seconds"].includes(k) ? Number(v) : v,
    }));
  }
  function reset() {
    setId("new");
    setTopic("");
    setScene(-1);
    setFailure("");
    pending.current = null;
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
    reset();
    setFile(f);
    setAsset("");
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
      throw Error(
        data.error ??
          data.detail ??
          "요청이 중단되었습니다. 작업 이력을 확인하세요. 자동 재전송하지 않습니다.",
      );
    return data;
  }
  async function autoStory() {
    if (sending.current || !ready) return;
    sending.current = true;
    setBusy(true);
    setFailure("");
    // One durable request identity per click/uncertain outcome. Reload/history never retries it.
    pending.current ??= crypto.randomUUID().replaceAll("-", "");
    try {
      const form = new FormData();
      form.set("topic", topic.trim());
      form.set("studio_settings", JSON.stringify(settings));
      form.set("request_id", pending.current);
      form.set("consent", "true");
      form.set("episode_limit", per);
      form.set("day_limit", daily);
      if (file) form.set("reference", file);
      else if (asset) form.set("reference_asset", asset);
      else if (job?.id) form.set("reference_job", job.id);
      else throw Error("참조 캐릭터 이미지를 먼저 선택하세요.");
      const draft = await post("/character", form);
      let data = draft;
      if (draft.created) {
        const encoded = new URLSearchParams({
          job_id: draft.id,
          consent: "true",
          csrf_token: c.view?.csrfToken ?? "",
        });
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

      setAsset("");
      setTopic("");
      c.setNotice(
        "스토리가 생성·저장되었습니다. 장면을 검토한 뒤 영상 견적을 확인하세요.",
      );
    } catch (e) {
      setFailure(
        e instanceof Error
          ? e.message
          : "스토리 요청 중단 · 자동 재전송하지 않습니다.",
      );
    } finally {
      await c.load();
      setBusy(false);
      sending.current = false;
    }
  }
  async function saveSettings() {
    if (!job?.studio_selection) return;
    const form = new FormData();
    form.set("settings", JSON.stringify(settings));
    form.set("episode_limit", per);
    form.set("day_limit", daily);
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
    await c.load();
  }
  async function quote() {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setFailure("");
    try {
      await saveSettings();
      c.open("character_act_prepare", { job_id: job?.id, state: job?.state });
    } catch (e) {
      setFailure(e instanceof Error ? e.message : "영상 설정 저장 실패");
    } finally {
      setBusy(false);
      sending.current = false;
    }
  }
  function action(kind: string, label: string, allowed: string[]) {
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
          (kind === "submit" && budgetExceeded)
        }
        primary
      >
        <Clapperboard size={24} />
        {label}
      </ActionButton>
    );
  }
  const refAssets = c.view?.catalog.referenceAssets ?? [];
  let elapsed = 0;
  return (
    <>
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
        {help && (
          <div
            className="kling-character-help"
            role="region"
            aria-label="캐릭터 제작 안내"
          >
            참조 이미지 선택 → 주제 입력 → 스토리 자동 생성하기 → 장면 검토 →
            영상 설정·공식 견적 → 비용 승인 → 장면 확인 → 합성·저장. 스토리는
            Claude 1회 요청이며, 영상 생성은 별도의 견적 승인이 필요합니다.
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
                onClick={() => setTab("upload")}
              >
                참조 이미지 업로드
              </button>
              <button
                aria-pressed={tab === "mine"}
                onClick={() => setTab("mine")}
              >
                내 캐릭터
              </button>
            </div>
            <div className="kling-character-reference-content">
              <div className="kling-character-reference-image">
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
              </div>
              <div className="kling-character-reference-options">
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
                <h3>최근 사용 캐릭터</h3>
                <div className="kling-character-recent">
                  {jobs
                    .filter((x) => x.referenceUrl)
                    .slice(0, 4)
                    .map((x) => (
                      <button
                        key={x.id}
                        disabled={isBusy}
                        title={x.topic}
                        aria-label={`캐릭터 작업 ${x.topic} 열기`}
                        onClick={() => {
                          setId(x.id);
                          setFile(null);

                          setAsset("");
                          pending.current = null;
                        }}
                      >
                        <Thumbnail src={x.referenceUrl} alt={x.topic} />
                      </button>
                    ))}
                  {!jobs.length && <small>저장된 캐릭터 없음</small>}
                </div>
              </div>
            </div>
            {tab === "mine" && (
              <Select
                label="저장한 참조 소재"
                disabled={isBusy}
                value={asset}
                onChange={(v) => {
                  reset();
                  setAsset(v);
                  setFile(null);
                }}
                options={Object.fromEntries(
                  refAssets.map((x: Item | string) =>
                    typeof x === "string"
                      ? [x, x]
                      : [x.id ?? x.key, x.label ?? x.title],
                  ),
                )}
              />
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
                  pending.current = null;
                }}
              >
                <Sparkles size={14} />
                예시 주제 보기
              </button>
            </header>
            <label>
              스토리 주제
              <div className="kling-character-topic">
                <textarea
                  aria-label="스토리 주제"
                  value={topic}
                  maxLength={100}
                  placeholder="캐릭터가 어떤 이야기를 펼칠까요?"
                  disabled={isBusy}
                  onChange={(e) => {
                    setTopic(e.target.value);
                    if (!failure) pending.current = null;
                  }}
                />
                <small>{topic.length}/100</small>
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
                (!reference && !asset) ||
                !!failure
              }
            >
              <WandSparkles size={22} />
              {busy ? "스토리 처리 중…" : "스토리 자동 생성하기"}
              <span>→</span>
            </button>
            <p className="kling-character-consent">
              클릭하면 주제·참조 이미지를 Claude에 보내 스토리 1회를
              생성·저장합니다. 저장된 API 승인·사용 한도가 적용되며 영상 생성
              비용은 별도 승인합니다.
            </p>
            {!ready && (
              <p role="status">
                새 제작실 API 연결 확인 전 · 생성할 수 없습니다.
              </p>
            )}
            {failure && (
              <div className="kling-character-error" role="alert">
                {failure}
                <button
                  disabled={isBusy}
                  onClick={() => {
                    setFailure("");
                    pending.current = null;
                    reset();
                  }}
                >
                  작업 이력 확인 후 새 작업
                </button>
              </div>
            )}
            {story ? (
              <div className="kling-character-story-result">
                <header>
                  <h3>{story.title}</h3>
                  <State value={job?.state} />
                </header>
                {scenes.map((s, i) => (
                  <p key={i}>
                    <strong>
                      {i + 1}. {s.caption}
                    </strong>
                    <span>{s.action}</span>
                    {s.narration && <small>대사 · {s.narration}</small>}
                  </p>
                ))}
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
                label="Claude 모델"
                disabled={isBusy || lockedDuration}
                value={settings.script_model}
                onChange={(v) => setting("script_model", v)}
                options={c.view?.catalog.apiModels?.claude_api ?? []}
              />
              <p>
                전체 {settings.duration}초 ·{" "}
                {Math.min(5, Math.floor(60 / settings.clip_seconds))}장면. 장면
                길이는 영상 설정에서 선택합니다.
              </p>
              <label>
                편당 최대 승인 한도 (USD)
                <input
                  value={per}
                  inputMode="decimal"
                  onChange={(e) => setPer(e.target.value)}
                  disabled={isBusy || frozen}
                />
              </label>
              <label>
                일일 최대 승인 한도 (USD)
                <input
                  value={daily}
                  inputMode="decimal"
                  onChange={(e) => setDaily(e.target.value)}
                  disabled={isBusy || frozen}
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
                  url={scene >= 0 ? selectedClip?.mediaUrl : job?.mediaUrl}
                  label={`${settings.aspect_ratio} 영상 미리보기`}
                />
                {!safeMedia(
                  scene >= 0 ? selectedClip?.mediaUrl : job?.mediaUrl,
                ) && <span>생성·검토된 영상 없음</span>}
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
                    disabled={isBusy || frozen || !ready}
                  >
                    <CapabilitySelect
                      label="영상 모델"
                      icon={<Bot size={18} />}
                      value={settings.video_model}
                      onChange={changeModel}
                      values={choices}
                      supported={Object.keys(choices)}
                      hint={adjustments.video_model}
                    />
                    <CapabilitySelect
                      label="영상 스타일"
                      icon={<Sparkles size={18} />}
                      value={settings.style}
                      onChange={() => {}}
                      disabled
                      values={caps?.styles ?? {}}
                      supported={[caps?.character?.style_id ?? ""]}
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
                      label="화질"
                      icon={<Monitor size={18} />}
                      value={settings.native_resolution}
                      onChange={(v) => setting("native_resolution", v)}
                      values={{
                        model_default: "모델 기본 (Standard)",
                        ...Object.fromEntries(
                          (caps?.resolutionChoices ?? []).map((x: string) => [
                            x,
                            x,
                          ]),
                        ),
                      }}
                      supported={currentModel?.resolutions ?? []}
                      hint={adjustments.native_resolution}
                    />
                    <CapabilitySelect
                      label="음성"
                      ariaLabel="소리 생성"
                      icon={<Mic size={18} />}
                      value={settings.sound}
                      onChange={(v) => setting("sound", v)}
                      values={{ off: "끄기 (무음)", on: "켜기 (모델 소리)" }}
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
                      <CapabilitySelect
                        label="장면 길이 (초)"
                        value={String(settings.clip_seconds)}
                        onChange={changeLength}
                        disabled={isBusy || frozen || lockedDuration}
                        values={Object.fromEntries(
                          (caps?.durationChoices ?? []).map((x: number) => [
                            String(x),
                            `${x}초`,
                          ]),
                        )}
                        supported={(currentModel?.duration_values ?? []).map(
                          String,
                        )}
                        hint={
                          adjustments.clip_seconds ??
                          `전체 ${settings.duration}초 · 스토리 생성 후 고정`
                        }
                      />
                      <Select
                        label="최종 저장 크기 · 로컬 FFmpeg"
                        disabled={isBusy || frozen}
                        value={settings.output_quality}
                        onChange={(v) => setting("output_quality", v)}
                        options={caps?.outputQualities ?? {}}
                      />
                      <p>
                        캐릭터 스타일·9:16은 캐릭터 설정으로 고정됩니다.
                        스타일은 프롬프트에 반영되며 결과는 모델마다 다를 수
                        있습니다.
                      </p>
                      <p>
                        화질은 모델의 네이티브 지원값만 전송합니다. 로컬 1080p
                        저장에는 확대가 포함될 수 있으며, 네이티브 1080p 생성과
                        다릅니다.
                      </p>
                      <p>
                        {currentModel?.aspect_ratio_mode === "reference-padding"
                          ? "비율: 별도 참조 복사본 여백 조정 → 최종 합성. 미지원 aspect_ratio는 보내지 않습니다."
                          : "비율: 모델의 aspect_ratio와 최종 합성에 반영합니다."}
                      </p>
                      <p>
                        소리 생성은 대사·효과음·배경음을 함께 생성할 수
                        있습니다. 목소리 종류 선택은 지원하지 않으며 한국어
                        발음·입 모양·음색 일관성은 별도 검수가 필요합니다.
                      </p>
                      {job?.state === "scene_review" &&
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
                    {job?.state === "script_review" ? (
                      <button
                        className="primary"
                        title="스토리 검토·공식 견적을 확인한 후 비용을 별도로 승인합니다."
                        disabled={isBusy || legacy || !ready || budgetExceeded}
                        onClick={() => void quote()}
                      >
                        <Clapperboard size={24} />
                        영상 생성하기
                      </button>
                    ) : job?.state === "quoted" ? (
                      action("submit", "영상 생성하기", ["quoted"])
                    ) : job?.state === "generating" ? (
                      action("check", "장면 상태 확인", ["generating"])
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
                  </div>
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
              생성된 장면{" "}
              <small>
                ({scenes.length}개 장면 ·{" "}
                {scenes.reduce((n, s) => n + s.seconds, 0)}초)
              </small>
            </h2>
            <button
              onClick={() => setScene(-1)}
              disabled={!safeMedia(job?.mediaUrl)}
            >
              <Play size={14} />
              최종 영상
            </button>
          </header>
          <div className="kling-character-scene-grid">
            {(scenes.length
              ? scenes
              : Array.from({ length: 5 }, () => null)
            ).map((s, i) => {
              const start = elapsed;
              elapsed += s?.seconds ?? 0;
              const media = clips.find((x) => x.position === i + 1)?.mediaUrl;
              return (
                <button
                  key={i}
                  aria-pressed={scene === i}
                  disabled={!s}
                  onClick={() => setScene(i)}
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
                  {s && (
                    <State
                      value={
                        clips.find((x) => x.position === i + 1)?.state ??
                        "pending"
                      }
                    />
                  )}
                </button>
              );
            })}
          </div>
        </section>
        {history && (
          <section
            className="kling-character-card kling-character-history"
            aria-label="캐릭터 작업 이력"
          >
            <header>
              <h2>작업 이력</h2>
              <button onClick={reset}>새 작업</button>
            </header>
            {jobs.length ? (
              jobs.map((x) => (
                <button
                  key={x.id}
                  disabled={isBusy}
                  onClick={() => {
                    setId(x.id);
                    setFile(null);

                    setAsset("");
                    pending.current = null;
                    setFailure("");
                  }}
                >
                  <span>{x.topic}</span>
                  <State value={x.state} />
                </button>
              ))
            ) : (
              <Empty>저장한 작업이 없습니다.</Empty>
            )}
          </section>
        )}
      </div>
    </>
  );
}
