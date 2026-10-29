// Execute actual UI diagnosis logic with local callbacks; no provider/browser requests.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../frontend/src/studio/core/CharacterStudio.tsx", import.meta.url), "utf8");
const dialog = readFileSync(new URL("../frontend/src/studio/CommandDialog.tsx", import.meta.url), "utf8");
const detailsLogic = source.slice(source.indexOf("  const failureDetails ="), source.indexOf("  const selectedClip ="))
  .replace("observedLabels: Record<string, string>", "observedLabels");
const actionDefinition = source.slice(source.indexOf("  function action("), source.indexOf("  const myCharacters"));
const actionSetup = actionDefinition.slice(actionDefinition.indexOf("    const connectionUnavailable"), actionDefinition.indexOf("    return ("));
const actionDisabled = actionDefinition.match(/disabled=\{([\s\S]*?)\n\s+\}/)[1];
const submitLogic = dialog.slice(dialog.indexOf("  async function submit(e:"), dialog.indexOf("  const field ="))
  .replace("submit(e: React.FormEvent)", "submit(e)");

test("diagnosis has its own consent-only external action and matches the backend registry", () => {
  const backend = JSON.parse(readFileSync(new URL("../src/newsflow/studio/actions.json", import.meta.url), "utf8"));
  const frontend = JSON.parse(readFileSync(new URL("../frontend/src/legacy-actions.json", import.meta.url), "utf8"));
  assert.deepEqual(frontend, backend);
  const actions = frontend.filter((action) => action.id === "character_act_diagnose");
  assert.equal(actions.length, 1);
  assert.equal(actions[0].path, "/character/{job_id}/diagnose");
  assert.equal(actions[0].label, "실패 상세 확인");
  assert.equal(actions[0].risk, "external");
  assert.deepEqual(actions[0].fields.map((field) => field.name), ["job_id", "consent"]);
  assert.equal(actions[0].fields.find((field) => field.name === "consent").required, true);
});

function inspect(clips, job = { state: "scene_review", studio_selection: {} }) {
  const before = JSON.stringify(clips);
  const result = vm.runInNewContext(`(() => { ${detailsLogic}\nreturn { failureDetails, canDiagnoseScenes }; })()`, { clips, job });
  assert.equal(JSON.stringify(clips), before);
  return result;
}

test("safe provider details, unavailable explanations and state mismatches remain distinct without changing failed states", () => {
  const clips = [
    { position: 1, state: "failed", status_diagnostics: { observed_state: "failed", error_message: "Synthetic provider input failure.", detail_available: true, state_mismatch: false, checked_at: "2026-10-30T01:00:00Z" } },
    { position: 2, state: "failed", status_diagnostics: { observed_state: "failed", error_message: "", detail_available: false, state_mismatch: false } },
    { position: 3, state: "failed", status_diagnostics: { observed_state: "completed", error_message: "", detail_available: false, state_mismatch: true } },
    { position: 4, state: "nsfw" }, { position: 5, state: "canceled" },
  ];
  const result = inspect(clips);
  assert.equal(result.canDiagnoseScenes, true);
  assert.equal(result.failureDetails.length, 5);
  assert.equal(result.failureDetails[0].message, "Synthetic provider input failure.");
  assert.ok(result.failureDetails[0].checkedAt);
  assert.equal(result.failureDetails[1].message, "공급사가 오류 설명을 제공하지 않았습니다.");
  assert.equal(result.failureDetails[2].observed, "완료");
  assert.equal(result.failureDetails[2].mismatch, true);
  assert.equal(result.failureDetails[3].message, "아직 실패 상세를 확인하지 않았습니다.");
  assert.equal(clips.every((clip) => ["failed", "nsfw", "canceled"].includes(clip.state)), true);
});

test("diagnosis excludes unknown or unsubmitted outcomes and requires a terminal Studio scene", () => {
  const failed = { position: 1, state: "failed" };
  for (const state of ["unknown", "submitting", "not_submitted", "downloading"]) {
    assert.equal(inspect([failed, { position: 2, state }]).canDiagnoseScenes, false);
  }
  assert.equal(inspect([failed, { position: 2, state: "submitted" }]).canDiagnoseScenes, true);
  assert.equal(inspect([{ position: 1, state: "submitted" }]).canDiagnoseScenes, false);
  assert.equal(inspect([failed], { state: "scene_review" }).canDiagnoseScenes, false);
  assert.equal(inspect([failed], { state: "generating", studio_selection: {} }).canDiagnoseScenes, false);
});

test("the diagnosis action preserves the connection gate and never uses a generation label", () => {
  const evaluate = (executionEnabled) => vm.runInNewContext(
    `(() => { ${actionSetup}\nreturn { disabled: (${actionDisabled}), label: actionLabel }; })()`, {
      kind: "diagnose", label: "실패 상세 확인", executionEnabled, isBusy: false,
      job: { state: "scene_review" }, allowed: ["scene_review"], pendingReferenceCopy: false,
      budgetExceeded: false, quoteSettingsChanged: false,
    },
  );
  assert.equal(evaluate(true).disabled, false);
  assert.equal(evaluate(true).label, "실패 상세 확인");
  assert.equal(evaluate(false).disabled, true);
  assert.equal(evaluate(false).label, "실패 상세 연결 준비 중");
});

async function diagnoseDialog({ reject = false, ack = true } = {}) {
  const calls = { requests: 0, reloads: 0, closes: 0, error: "", busy: false };
  const context = { Error, busy: false, risky: true, ack, localRender: null,
    checkingCharacterScenes: false, diagnosingCharacterScenes: true,
    effective: { id: "character_act_diagnose", path: "/character/{job_id}/diagnose" },
    values: { job_id: "a".repeat(32), consent: true }, view: {}, files: {}, context: {},
    submitOriginal: async (action, values) => {
      calls.requests++;
      assert.equal(action.id, "character_act_diagnose"); assert.equal(values.consent, true);
      if (reject) throw Error("Synthetic status lookup error.");
    },
    onSaved: () => { calls.reloads++; }, onClose: () => { calls.closes++; },
    setBusy: (value) => { calls.busy = value; }, setError: (value) => { calls.error = value; },
    setAck: () => {}, setResponseSummary: () => {},
  };
  vm.createContext(context); vm.runInContext(submitLogic, context);
  await context.submit({ preventDefault: () => {} });
  return calls;
}

test("one explicit diagnosis reloads stored details once, including after a partial error, with no replay", async () => {
  const success = await diagnoseDialog();
  assert.equal(success.requests, 1); assert.equal(success.reloads, 1); assert.equal(success.closes, 1);
  const failure = await diagnoseDialog({ reject: true });
  assert.equal(failure.requests, 1); assert.equal(failure.reloads, 1); assert.equal(failure.closes, 0);
  assert.match(failure.error, /^실패 상세 조회를 완료하지 못했습니다/);
  assert.match(failure.error, /Synthetic status lookup error/);
  assert.equal(failure.busy, false);
  const unconfirmed = await diagnoseDialog({ ack: false });
  assert.equal(unconfirmed.requests, 0); assert.equal(unconfirmed.reloads, 0);
});
