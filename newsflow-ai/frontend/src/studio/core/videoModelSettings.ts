import type { Item } from "../contracts";
export type CharacterVideoSettings = {
  video_model: string;
  script_model: string;
  style: string;
  aspect_ratio: string;
  native_resolution: string;
  output_quality: string;
  sound: string;
  clip_seconds: number;
  duration: number;
};
export function adjustModel(
  current: CharacterVideoSettings,
  model: Item,
  character: Item,
) {
  const value = { ...current, video_model: model.id };
  const notes: Record<string, string> = {};
  if (!model.aspect_ratios.includes(value.aspect_ratio)) {
    value.aspect_ratio = model.aspect_ratios.includes("9:16")
      ? "9:16"
      : model.default_aspect_ratio;
    notes.aspect_ratio = "지원되는 화면 비율로 변경했어요.";
  }
  if (!model.resolutions.includes(value.native_resolution)) {
    const rank: Record<string, number> = {
      model_default: 0,
      std: 0,
      pro: 1,
      "480p": 480,
      "720p": 720,
      "1080p": 1080,
      "4k": 2160,
    };
    const available = [...model.resolutions].sort((a, b) => rank[a] - rank[b]);
    const under = available.filter(
      (x) => rank[x] <= (rank[value.native_resolution] ?? 0),
    );
    const before = value.native_resolution;
    value.native_resolution = model.param_map?.resolution === "mode"
      ? model.default_resolution
      : under.at(-1) ?? available[0];
    notes.native_resolution = `이 모델은 ${before}를 지원하지 않아 ${value.native_resolution === "model_default" ? "모델 기본 화질" : value.native_resolution}로 변경했어요.`;
  }
  const clipDurations = model.duration_values.filter(
    (seconds: number) => Number.isInteger(seconds) && seconds >= 3 && seconds <= 12,
  );
  if (!clipDurations.includes(value.clip_seconds)) {
    value.clip_seconds = [...clipDurations].sort(
      (a, b) =>
        Math.abs(a - value.clip_seconds) - Math.abs(b - value.clip_seconds) ||
        a - b,
    )[0] ?? value.clip_seconds;
    notes.clip_seconds = `장면 길이를 지원되는 ${value.clip_seconds}초로 변경했어요.`;
  }
  if (value.sound === "on" && !model.audio.native) {
    value.sound = "off";
    notes.sound = "이 모델은 소리 생성을 지원하지 않아 꺼졌어요.";
  }
  if (character) {
    value.style = character.style_id;
    value.aspect_ratio = character.aspect_ratio;
  }
  value.duration = value.clip_seconds * 5;
  return { value, notes };
}
export function publicEstimate(
  model: Item | undefined,
  settings: CharacterVideoSettings,
) {
  const rate = model?.param_map?.resolution === "mode" && settings.native_resolution !== "std"
    ? null
    : model?.pricing?.per_second?.[settings.sound];
  if (!rate) return { lower: null, upper: null, label: "공식 견적 전 미확정" };
  const lower = Number(rate[0]) * settings.duration,
    upper = Number(rate[1]) * settings.duration;
  if (!Number.isFinite(lower) || !Number.isFinite(upper))
    return { lower: null, upper: null, label: "공식 견적 전 미확정" };
  return {
    lower,
    upper,
    label:
      lower === upper
        ? `약 $${upper.toFixed(2)}`
        : `약 $${lower.toFixed(2)}–${upper.toFixed(2)}`,
  };
}

export function quotedSettingsDirty(
  current: CharacterVideoSettings,
  saved: Partial<CharacterVideoSettings> | undefined,
  per: string,
  daily: string,
  savedPer: unknown,
  savedDaily: unknown,
) {
  const sameAmount = (left: unknown, right: unknown) => {
    const a = Number(left),
      b = Number(right);
    return (
      Number.isFinite(a) && Number.isFinite(b) && a > 0 && b > 0 && a === b
    );
  };
  return (
    !saved ||
    (Object.keys(current) as (keyof CharacterVideoSettings)[]).some(
      (key) => current[key] !== saved[key],
    ) ||
    !sameAmount(per, savedPer) ||
    !sameAmount(daily, savedDaily)
  );
}
