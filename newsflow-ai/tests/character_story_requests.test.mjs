// Execute the component's actual request functions with local stubs only.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../frontend/src/studio/core/CharacterStudio.tsx", import.meta.url), "utf8");
const keyFunction = source.slice(source.indexOf("  function storyRequestKey()"), source.indexOf("  const blockedStoryRequest"));
const requestFunction = source.slice(source.indexOf("  async function autoStory()"), source.indexOf("  async function reuseStoryForVideo()"));
const postFunction = source.slice(source.indexOf("  async function post("), source.indexOf("  async function changeVisibility("))
  .replace("(url: string, body: FormData)", "(url, body)");
const button = source.slice(source.indexOf('className="kling-character-story-generate"'));
const disabledExpression = button.match(/disabled=\{([\s\S]*?)\n\s+\}/)[1];

function harness({ failCreate = 0, failStatus, unknownStory = false, failLoad = false, useAsset = true } = {}) {
  const original = { id: "a".repeat(32), state: "submission_unknown", topic: "원래 스토리", script: { immutable: true } };
  const originalBytes = JSON.stringify(original);
  const posts = [], storyCalls = [];
  let sequence = 0;
  const context = {
    FormData, URLSearchParams, Error,
    topic: "토끼의 새로운 여행", settings: { video_model: "kling-video/o3/image-reference", native_resolution: "std", duration: 30, clip_seconds: 6 },
    per: "10", daily: "20", file: null,
    asset: useAsset ? `studio-${"b".repeat(64)}.png` : "",
    referenceJob: "", reference: "/local-reference.png", job: original,
    pending: { current: "0".repeat(32) }, sending: { current: false },
    ready: true, isBusy: false, failure: "참조 이미지와 새 작업 설정을 확인하세요.", storyRequests: {},
    crypto: { randomUUID: () => String(++sequence).padStart(32, "0") },
    setBusy: (value) => { context.isBusy = value; },
    setFailure: (value) => { context.failure = value; },
    setReferenceJob: (value) => { context.referenceJob = value; },
    setFile: (value) => { context.file = value; },
    setAsset: (value) => { context.asset = value; },
    setTopic: (value) => { context.topic = value; },
    setStoryRequests: (update) => { context.storyRequests = update(context.storyRequests); },
    c: { view: { csrfToken: "synthetic-csrf", commandsAvailable: true }, setNotice: () => {},
      load: async () => { if (failLoad) throw Error("synthetic list read failure"); } },
    post: async (url, form) => {
      posts.push({ url, body: Object.fromEntries(form) });
      if (failCreate-- > 0) throw Object.assign(Error("참조 이미지와 새 작업 설정을 확인하세요."), { status: failStatus });
      context.job = { id: "d".repeat(32), state: "needs_script" };
      return { id: context.job.id, created: true, state: "needs_script" };
    },
    fetch: async (url, options) => {
      storyCalls.push({ url, body: Object.fromEntries(options.body) });
      if (unknownStory) throw Error("synthetic unknown story result");
      return { ok: true, json: async () => ({ state: "script_review" }) };
    },
  };
  vm.createContext(context);
  vm.runInContext(keyFunction + requestFunction, context);
  const key = () => vm.runInContext("storyRequestKey()", context);
  const disabled = () => {
    context.blockedStoryRequest = !!context.storyRequests[key()];
    return vm.runInContext(`(${disabledExpression})`, context);
  };
  return { context, posts, storyCalls, key, disabled,
    run: () => vm.runInContext("autoStory()", context),
    assertOriginal: () => assert.equal(JSON.stringify(original), originalBytes) };
}

test("old history and an unrelated error do not disable a new saved-reference topic", async () => {
  const h = harness();
  assert.equal(h.disabled(), false);
  await h.run();
  assert.equal(h.posts.length, 1);
  assert.equal(h.posts[0].url, "/character");
  assert.equal(h.posts[0].body.topic, "토끼의 새로운 여행");
  assert.equal(h.posts[0].body.reference_asset, `studio-${"b".repeat(64)}.png`);
  assert.notEqual(h.posts[0].body.request_id, "0".repeat(32));
  assert.deepEqual(JSON.parse(h.posts[0].body.studio_settings), h.context.settings);
  assert.deepEqual(h.storyCalls, [{ url: "/api/studio/characters/auto-story", body: {
    job_id: "d".repeat(32), consent: "true", csrf_token: "synthetic-csrf",
  } }]);
  h.assertOriginal();
});

test("the real local create helper preserves the confirmed HTTP validation status", async () => {
  const context = { Error, Object, c: { view: { csrfToken: "synthetic-csrf" } },
    setId: () => assert.fail("a rejection must not select another job"), setAdjustments: () => {},
    fetch: async () => ({ ok: false, status: 422, json: async () => ({ error: "invalid local draft" }) }) };
  vm.createContext(context); vm.runInContext(postFunction, context);
  const body = new FormData();
  await assert.rejects(context.post("/character", body), (error) => error.status === 422);
  assert.equal(body.get("csrf_token"), "synthetic-csrf");
});

test("request identity uses the same reference priority as the actual form", async () => {
  const h = harness({ unknownStory: true });
  h.context.referenceJob = "e".repeat(32);
  assert.deepEqual(JSON.parse(h.key()).at(-1), ["job", "e".repeat(32)]);
  await h.run();
  assert.equal(h.posts[0].body.reference_job, "e".repeat(32));
  assert.equal(h.posts[0].body.reference_asset, undefined);
});

test("changed input after a failed create gets a fresh request ID; identical failed input stays blocked", async () => {
  const h = harness({ failCreate: 1 });
  const originalTopic = h.context.topic, originalAsset = h.context.asset;
  await h.run();
  assert.equal(h.disabled(), true);
  await h.run();
  assert.equal(h.posts.length, 1);
  h.context.topic = "토끼가 달을 여행하는 새로운 이야기";
  assert.equal(h.disabled(), false);
  await h.run();
  assert.equal(h.posts.length, 2);
  assert.notEqual(h.posts[0].body.request_id, h.posts[1].body.request_id);
  h.context.topic = originalTopic; h.context.asset = originalAsset;
  assert.equal(h.disabled(), true);
  await h.run();
  assert.equal(h.posts.length, 2);
  h.assertOriginal();
});

test("a confirmed local validation rejection allows corrected or unchanged input without a history detour", async () => {
  const h = harness({ failCreate: 1, failStatus: 422 });
  await h.run();
  assert.equal(h.storyCalls.length, 0);
  assert.equal(h.disabled(), false);
  await h.run();
  assert.equal(h.posts.length, 2); assert.equal(h.storyCalls.length, 1);
  assert.notEqual(h.posts[0].body.request_id, h.posts[1].body.request_id);
  h.assertOriginal();
});

test("an uncertain story call cannot repeat while a genuinely new reference can start a new request", async () => {
  const h = harness({ unknownStory: true });
  await h.run();
  assert.equal(h.disabled(), true);
  await h.run();
  assert.equal(h.posts.length, 1); assert.equal(h.storyCalls.length, 1);
  h.context.asset = `studio-${"c".repeat(64)}.png`;
  assert.equal(h.disabled(), false);
  await h.run();
  assert.equal(h.posts.length, 2); assert.equal(h.storyCalls.length, 2);
  assert.notEqual(h.posts[0].body.request_id, h.posts[1].body.request_id);
  h.assertOriginal();
});

test("story settings belong to request identity and equivalent budget formatting does not unlock a replay", async () => {
  const h = harness({ failCreate: 1 });
  const firstKey = h.key();
  await h.run();
  h.context.per = "10.00";
  assert.equal(h.key(), firstKey); assert.equal(h.disabled(), true);
  h.context.settings = { ...h.context.settings, duration: 45, clip_seconds: 9 };
  assert.equal(h.disabled(), false);
  await h.run();
  assert.notEqual(h.posts[0].body.request_id, h.posts[1].body.request_id);
});

test("old job reference is pinned across new job selection and a failed list refresh releases busy state", async () => {
  const h = harness({ unknownStory: true, failLoad: true, useAsset: false });
  const originalKey = h.key();
  await h.run();
  assert.equal(h.context.referenceJob, "a".repeat(32));
  assert.equal(h.key(), originalKey);
  assert.equal(h.disabled(), true);
  assert.equal(h.context.sending.current, false); assert.equal(h.context.isBusy, false);
  await h.run();
  assert.equal(h.posts.length, 1); assert.equal(h.storyCalls.length, 1);
  h.assertOriginal();
});
