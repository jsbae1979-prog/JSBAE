import test from "node:test";
import assert from "node:assert/strict";
import { quotedSettingsDirty } from "../src/studio/core/videoModelSettings.ts";
const settings = {
  video_model: "synthetic",
  script_model: "synthetic",
  style: "synthetic",
  aspect_ratio: "9:16",
  native_resolution: "model_default",
  output_quality: "720p",
  sound: "off",
  clip_seconds: 3,
  duration: 15,
};
test("unchanged saved quote accepts decimal-equivalent limits", () => {
  assert.equal(
    quotedSettingsDirty(
      settings,
      { ...settings, fingerprint: "ignored" },
      "10.00",
      "20",
      "10",
      "20.00",
    ),
    false,
  );
});
test("changed model, sound or limits marks old quote stale", () => {
  for (const changed of [
    { ...settings, video_model: "other" },
    { ...settings, sound: "on" },
  ])
    assert.equal(
      quotedSettingsDirty(changed, settings, "10", "20", "10", "20"),
      true,
    );
  assert.equal(
    quotedSettingsDirty(settings, settings, "11", "20", "10", "20"),
    true,
  );
  assert.equal(
    quotedSettingsDirty(settings, settings, "", "20", "10", "20"),
    true,
  );
});
