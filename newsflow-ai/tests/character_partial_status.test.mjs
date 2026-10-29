// Actual component logic with local callbacks only; no browser/provider requests.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const studio = readFileSync(new URL("../frontend/src/studio/core/CharacterStudio.tsx", import.meta.url), "utf8");
const dialog = readFileSync(new URL("../frontend/src/studio/CommandDialog.tsx", import.meta.url), "utf8");
const progressLogic = studio.slice(studio.indexOf("  const pendingSceneChecks ="), studio.indexOf("  const failureDetails ="));
const checkAction = studio.match(/action\("check", job\?\.state[^\n]+/)[0].trim();
const submitLogic = dialog.slice(dialog.indexOf("  async function submit(e:"), dialog.indexOf("  const field ="))
  .replace("submit(e: React.FormEvent)", "submit(e)");

function progress(states) {
  const clips = states.map((state, index) => ({ position: index + 1, state }));
  const original = JSON.stringify(clips);
  const context = { clips, job: { state: "scene_review" }, action: (kind, label, allowed) => ({ kind, label, allowed }) };
  const result = vm.runInNewContext(`(() => { ${progressLogic}\nreturn { pendingSceneChecks, canCheckScenes, sceneProgressSummary }; })()`, context);
  assert.equal(JSON.stringify(clips), original);
  return { result, action: () => vm.runInNewContext(checkAction, context) };
}

test("a failed scene preserves a manual check action for four already-submitted scenes", () => {
  const h = progress(["failed", "submitted", "submitted", "submitted", "submitted"]);
  assert.equal(h.result.pendingSceneChecks, true);
  assert.equal(h.result.canCheckScenes, true);
  assert.equal(h.result.sceneProgressSummary, "실패 1 · 상태 확인 대기 4");
  const action = h.action();
  assert.equal(action.kind, "check");
  assert.equal(action.label, "남은 장면 상태 확인");
  assert.equal(action.allowed.includes("scene_review"), true);
});

test("downloaded and unknown scenes remain distinct from confirmed failures", () => {
  const complete = progress(["failed", "downloaded", "downloaded", "downloaded", "downloaded"]).result;
  assert.equal(complete.canCheckScenes, false);
  assert.equal(complete.sceneProgressSummary, "실패 1 · 저장 4");
  const mixed = progress(["failed", "unknown", "submitted", "downloaded", "submitted"]).result;
  assert.equal(mixed.canCheckScenes, true);
  assert.equal(mixed.sceneProgressSummary, "실패 1 · 상태 확인 대기 2 · 저장 1 · 결과 불명 1");
});

async function submitDialog({ check = true, reject = true, ack = true } = {}) {
  const calls = { requests: 0, reloads: 0, closes: 0, error: "", busy: false };
  const context = { Error, busy: false, risky: true, ack, localRender: null,
    checkingCharacterScenes: check, diagnosingCharacterScenes: false, effective: {}, values: {}, view: {}, files: {}, context: {},
    submitOriginal: async () => { calls.requests++; if (reject) throw Error("이전 요청 결과를 확인하세요. 자동 재전송하지 않습니다."); },
    onSaved: () => { calls.reloads++; }, onClose: () => { calls.closes++; },
    setBusy: (value) => { calls.busy = value; }, setError: (value) => { calls.error = value; },
    setAck: () => {}, setResponseSummary: () => {},
  };
  vm.createContext(context); vm.runInContext(submitLogic, context);
  await context.submit({ preventDefault: () => {} });
  return calls;
}

test("a status-check error reloads stored state once without repeating the provider request", async () => {
  const calls = await submitDialog();
  assert.equal(calls.requests, 1); assert.equal(calls.reloads, 1); assert.equal(calls.closes, 0);
  assert.equal(calls.busy, false);
  assert.match(calls.error, /^상태 조회가 중단됐습니다/);
  assert.match(calls.error, /이전 요청 결과를 확인하세요/);
  assert.equal(calls.error.includes("공급사 실패"), false);
});

test("unrelated errors keep their prior behavior and successful checks still reload only once", async () => {
  const unrelated = await submitDialog({ check: false });
  assert.equal(unrelated.requests, 1); assert.equal(unrelated.reloads, 0);
  assert.equal(unrelated.error, "이전 요청 결과를 확인하세요. 자동 재전송하지 않습니다.");
  const success = await submitDialog({ reject: false });
  assert.equal(success.requests, 1); assert.equal(success.reloads, 1); assert.equal(success.closes, 1);
});

test("manual status checks retain the explicit confirmation gate", async () => {
  const blocked = await submitDialog({ ack: false });
  assert.equal(blocked.requests, 0); assert.equal(blocked.reloads, 0);
});
