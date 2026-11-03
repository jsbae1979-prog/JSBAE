# Analysis request scope and image controls — 2026-11-03

Base: 1203344a064fe6281344b8a7fbfed8bf53af90a8. Branch: codex/newsflow-character-shorts-automation-20261030.

## Changes
- News analysis previously inherited a provider-wide block from completed unknown character-story requests. Only unchanged, explicitly previously reviewed character journals may be excluded for a server-created running news-analysis request. Readiness and transactional reservation use the same review proof. Historical status, reserved cost, keys and records remain unchanged. Active, unreviewed, mutated and same-analysis unknown requests remain blocked. No automatic retry or provider call was added.
- Connection-check success now describes model access only, without implying all execution conditions are satisfied.
- Image controls retain scope/style/model-quality/status. Cost details open on the image-generation button; regeneration concerns the selected result only. Existing cost approval and per-job limits remain. Original tools move next to the result. No generation on opening the dialog.
- Character video settings use a 200–230px rail, giving the remaining width to the preview. Shared step/panel alignment remains.

## Focused verification
- Python/Fake and synthetic browser: initial 71 PASS / 2 FAIL. Both failures were old UI selectors after the intentional flow change; updated their navigation and retained assertions. Follow-up 2 PASS. Final unique coverage: 73 PASS.
- Frontend contracts 48 PASS; TypeScript and React build PASS.
- studio_v3 58 PASS; feed_top3 tools 25 PASS.
- Total final unique focused checks: 204 PASS / 0 unresolved FAIL / 0 ERROR / 0 SKIP. No full-regression repetition. Build retains existing font-at-build-time and bundle-size warnings.
- No paid calls, collection, OAuth, SNS, content deletion or regeneration. Existing overall regression evidence is reused, not claimed as newly run.

## Read-only operating findings
- 0 active Claude reservations; 3 finished unknown character requests matched exact prior user-review fingerprints; 0 other unknown requests. No acknowledgement or status was created or changed.
- Library's missing coffee-errand short already has a permanent-deletion tombstone and no current final.mp4. The other completed short remains. No restoration/deletion is performed in this task.
- Actual paid analysis and visual quality of new generated videos remain unverified.
