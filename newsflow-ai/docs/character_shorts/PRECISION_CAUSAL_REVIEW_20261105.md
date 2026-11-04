# Precision causal continuity and clip review — 2026-11-05

Base: fa4f25acb8784186f281a21160c5096eac8b9cff
Branch: codex/newsflow-character-scene-images-20261104

## Behavior

New precision works use `precision-causal-v3`. The existing quick workflow and stored
v2/no-policy works retain their previous interpretation. No existing work is migrated,
deleted, regenerated, marked reviewed, or re-quoted by this change.

Each new scene records cause/result and a prop ledger (stable ID, before/after quantity,
form/location and visible change). Local validation rejects missing causal links,
duplicate/disappearing prop IDs, mismatched inter-scene state, and unexplained changes.
Common props require a ledger. Character values are not hardcoded. Still prompts use
only starting prop state; motion prompts include causal action/result and gradual camera
movement, retaining no-dialogue/no-voices/no-music instructions.

New precision videos submit the first scene only. A downloaded scene pauses the chain.
The user can play that exact clip next to “장면 확인 · 다음 장면 만들기”. Review is bound
to the clip hash and attempt. The local review POST sends nothing externally; the existing
approved check path releases at most the next scene. Continuations use the actual final
decoded frame. Intentional cuts retain their approved starting image and require the same
review gate. Quote increases, failures and unknown results do not trigger automatic retry.
Failed-scene diagnosis and explicit retry quotes remain available with pending cuts.

## Changed areas

- `character/precision_causal.py`: versioned schema, structural checks, review receipt.
- `character/precision_contract.py`, `precision.py`, `precision_video.py`: new-work policy,
  authoring schema/instructions, image/video prompt and handoff integration.
- `character/episode_service.py`, `service.py`: sequential human-review gate and failure handling.
- `gui/character_routes.py`, `studio/read_models.py`, both action catalogs: authenticated,
  CSRF-protected local review route and derived UI state.
- `frontend/src/studio/core/CharacterPrecision.tsx`, `precisionValidation.ts`: editable causal
  and prop fields, preserving them when reopening the editor.
- `frontend/src/studio/core/CharacterStudio.tsx`: nearby clip playback, review/continue,
  waiting-state labels and explicit resume after an interrupted check.
- `tools/bat_distribution/precision_access.py`, `character_manual_execution.py`, `operation.py`:
  exact new schema/instruction binding, reviewed cut/continuation checks, exact local route.
- Three `test_precision_causal*.py` suites; v2 continuity fixture explicitly pins v2.

## Validation

Windows existing Python 3.14 environment, isolated temporary profiles, synthetic images,
Fake authoring/image/video providers, local FFmpeg and test Chromium. No real provider
request, operating app restart, operating data mutation, or user Chrome automation.

Commands used `python -m pytest -q -rs --tb=short` with isolated profile/basetemp,
local FFmpeg and timezone paths. Test targets:

- `tests/test_precision_causal.py`, `tests/test_precision_causal_runtime.py`,
  `tests/test_precision_causal_browser.py`: **27 PASS** on final focused run.
- `tests/test_character_precision.py`, `tests/test_character_precision_continuity.py`:
  **46 PASS** retained from the 67-test focused run (the other 21 are duplicated new tests).
- `tests/test_character_precision_continuity_browser.py`: **1 PASS**, also in final
  3-test browser run; its other 2 tests overlap the new suite.
- `tools/studio_v3/tests`: **58 PASS**.
- `tools/bat_distribution/tests/test_character_manual_execution.py` and
  `test_operation_character_endpoints.py`: **82 PASS**.
- Unique total: **214 PASS / 0 FAIL / 0 ERROR / 0 SKIP**. New tests: 27.
- `tsc --noEmit` and Vite production build: PASS in isolated frontend staging directory.

Earlier development runs found two mixed-conftest collection errors (resolved by separate
test processes), a route registry contract mismatch (resolved using the existing character
route grouping), a UI test's outdated button name, and a test's invalid default Host.
All affected checks were rerun. No assertions were removed, tests skipped, or auth relaxed.
Only Starlette TestClient deprecation warnings remain.

Evidence is local under `C:/Codex/NewsFlowAI/precision_scene_20261104`: final junit/log
files `precision-causal-final`, `precision-causal-browser-final`, `causal-studio-v3`,
`causal-bat`; browser screenshots are synthetic, not user media.

## Limits / deployment

CONDITIONAL: implementation and Fake checks pass; actual visual continuity is NOT VERIFIED.
Structural checks cannot prove that a model depicts a cause, obeys camera instructions,
or preserves a character. Human clip review is still required. Existing paid EP01 remains
unchanged and is not claimed repaired. No new paid image/video generation, operation
deployment/restart, SNS publication, main change or PR merge was performed.
