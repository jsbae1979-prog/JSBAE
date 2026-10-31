// Read and execute the component's actual budget selection/save logic with local stubs.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../frontend/src/studio/core/CharacterStudio.tsx", import.meta.url), "utf8");
const selection = source.slice(source.indexOf("  const perKey ="), source.indexOf("  const caps ="))
  .replace("setPer(value: string)", "setPer(value)");
const saveFunction = source.slice(source.indexOf("  async function saveSettings()"), source.indexOf("  async function quote()"));
const resetFunction = source.slice(source.indexOf("  function reset("), source.indexOf("  function startFromCharacter()"));

function contextFor(job, perOverrides = {}) {
  const sent = [];
  const context = { job, perOverrides, FormData, URLSearchParams, pendingReferenceCopy: false, scriptDirty: false,
    settings: { duration: 30, clip_seconds: 6 }, pending: { current: null }, preparedStory: {current:null},
    setStoryReview:()=>{}, setStoryReviewConsent:()=>{},
    c: { view: { csrfToken: "synthetic-csrf" }, load: async () => {} },
    setPerOverrides: (update) => { context.perOverrides = update(context.perOverrides); },
    setId: () => { context.job = undefined; }, setReferenceJob: () => {}, setTopic: () => {},
    setScene: () => {}, setFailure: () => {},
    fetch: async (_url, options) => { sent.push(Object.fromEntries(options.body)); return { ok: true, json: async () => ({ quoteRetained: false }) }; },
  };
  vm.createContext(context);
  vm.runInContext(saveFunction + resetFunction, context);
  const render = () => {
    const result = vm.runInContext(`(() => { ${selection}\nreturn { per, setPer }; })()`, context);
    context.per = result.per;
    return result;
  };
  return { context, sent, render, save: () => vm.runInContext("saveSettings()", context),
    reset: () => vm.runInContext("reset()", context) };
}

test("an existing 5.00 execution limit is used on the first render and saved unchanged", async () => {
  const job = { id: "a".repeat(32), episode_limit: "5.00", studio_selection: {} };
  const before = JSON.stringify(job);
  const h = contextFor(job);
  assert.equal(h.render().per, "5.00");
  await h.save();
  assert.equal(h.sent[0].episode_limit, "5.00");
  assert.equal(JSON.stringify(job), before);
});

test("same-job refresh follows the latest saved limit until the user explicitly edits it", async () => {
  const h = contextFor({ id: "a", episode_limit: "5.00", studio_selection: {} });
  assert.equal(h.render().per, "5.00");
  h.context.job = { ...h.context.job, episode_limit: "3.50" };
  assert.equal(h.render().per, "3.50");
  await h.save();
  assert.equal(h.sent[0].episode_limit, "3.50");
});

test("explicit edits survive same-job refresh and remain isolated by job ID", () => {
  const h = contextFor({ id: "a", episode_limit: "5.00" });
  h.render().setPer("7.25");
  h.context.job = { id: "a", episode_limit: "4.00" };
  assert.equal(h.render().per, "7.25");
  h.context.job = { id: "b", episode_limit: "2.00" };
  assert.equal(h.render().per, "2.00");
  h.context.job = { id: "a", episode_limit: "4.00" };
  assert.equal(h.render().per, "7.25");
});

test("only a new draft defaults to 10 and an existing job never receives a silent fallback increase", () => {
  const h = contextFor(undefined);
  assert.equal(h.render().per, "10");
  h.render().setPer("6");
  assert.equal(h.render().per, "6");
  h.context.job = { id: "a", episode_limit: "5.00" };
  assert.equal(h.render().per, "5.00");
  h.reset();
  assert.equal(h.render().per, "10");
  h.context.job = { id: "missing-limit" };
  assert.equal(h.render().per, "");
});

test("requested implementation descriptions are absent while setting labels and paid approval remain", () => {
  for (const text of ["Claude 추가 호출 없음", "currentModel?.quality_note", "최종 파일:",
    "소리 켜짐", "미지원 aspect_ratio", "발음·입 모양·음색 일관성"]) {
    assert.equal(source.includes(text), false, text);
  }
  for (const text of ['label="영상 길이"', 'label="모델 생성 화질"', 'label="최종 저장 크기"',
    'label="소리 생성"', "스토리 생성은 유료입니다. 영상 제작은 별도 승인합니다.", 'kind === "submit" && (budgetExceeded || quoteSettingsChanged)']) {
    assert.equal(source.includes(text), true, text);
  }
});

test("quote-only connections show disabled generation and status actions with clear labels", () => {
  const definition = source.slice(source.indexOf("  function action("), source.indexOf("  const myCharacters"));
  const setup = definition.slice(definition.indexOf("    const connectionUnavailable"), definition.indexOf("    return ("));
  const disabled = definition.match(/disabled=\{([\s\S]*?)\n\s+\}/)[1];
  const check = (kind, executionEnabled) => vm.runInNewContext(
    `(() => { ${setup}\nreturn { disabled: (${disabled}), label: actionLabel }; })()`, {
      kind, label: "원래 실행 이름", executionEnabled, isBusy: false, job: { state: "quoted" },
      allowed: ["quoted"], pendingReferenceCopy: false, scriptDirty: false, budgetExceeded: false, quoteSettingsChanged: false,
    },
  );
  assert.equal(check("submit", false).disabled, true);
  assert.equal(check("submit", false).label, "영상 생성 연결 준비 중");
  assert.equal(check("check", false).disabled, true);
  assert.equal(check("check", false).label, "상태 조회 연결 준비 중");
  assert.equal(check("retry-scene", false).disabled, true);
  assert.equal(check("submit", true).disabled, false);
  assert.equal(check("submit", true).label, "원래 실행 이름");
});

test("manual execution catalog flag honors quote-only state and keeps existing trial and old-catalog behavior", () => {
  const line = source.match(/  const executionEnabled =[^\n]+/)[0];
  const enabled = (caps, trialEnabled = false) => vm.runInNewContext(`${line}\nexecutionEnabled`, { caps, trialEnabled });
  assert.equal(enabled({ manualExecutionEnabled: false }), false);
  assert.equal(enabled({ manualExecutionEnabled: false }, true), true);
  assert.equal(enabled({ manualExecutionEnabled: true }), true);
  assert.equal(enabled({}), true);
});

test("a retained quote is reused after loading settings while expired quotes open a fresh prepare approval", async () => {
  const quoteFunction = source.slice(source.indexOf("  async function quote()"), source.indexOf("  function action("));
  for (const retained of [true, false]) {
    const events = [];
    const context = { FormData, URLSearchParams, job: { id: "a", studio_selection: {} },
      pendingReferenceCopy: false, scriptDirty: false, per: "5.00", settings: {}, sending: { current: false },
      setBusy: () => {}, setFailure: () => {},
      c: { view: { csrfToken: "synthetic-csrf" }, load: async () => { events.push("loaded"); },
        setNotice: (value) => { events.push(value); }, open: (id) => { events.push(id); } },
      fetch: async () => ({ ok: true, json: async () => ({ quoteRetained: retained, state: retained ? "quoted" : "script_review" }) }),
    };
    vm.createContext(context); vm.runInContext(saveFunction + quoteFunction, context);
    await vm.runInContext("quote()", context);
    assert.deepEqual(events, retained
      ? ["loaded", "설정을 저장했습니다. 현재 견적을 사용할 수 있습니다."]
      : ["loaded", "character_act_prepare"]);
    assert.equal(context.sending.current, false);
  }
});


test("unsaved edited script cannot save settings or open a quote approval", async () => {
 const quoteFunction=source.slice(source.indexOf("  async function quote()"),source.indexOf("  function action("));
 const context={sending:{current:false},pendingReferenceCopy:false,scriptDirty:true};
 vm.createContext(context);vm.runInContext(quoteFunction,context);
 await vm.runInContext("quote()",context);
 assert.equal(context.sending.current,false);
});
