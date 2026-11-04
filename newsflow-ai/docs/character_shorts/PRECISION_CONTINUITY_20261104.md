# Precision scene continuity — 2026-11-04

Status: CONDITIONAL. Development implementation and focused Fake validation complete. No production deployment, paid generation, or existing media modification performed.

## Cause and correction

The precision handoff forced every scene to `cut`, with no preceding scene reference. Thus approved still images became independent clip starts even for a continuous incident. Merely concatenating those clips cannot restore missing action or geography.

New works snapshot `precision-continuity-v2`. Their plan records connection, set ID, environment, start/end state and transition reason. Continue scenes must share cast/location/environment and start from the preceding end state. Intentional cuts require an explanation. Image prompts describe the beginning of the action; motion prompts carry preceding action and scene boundaries separately. New continuous videos use the existing sequential dependency engine and actual final decoded frame. Kling 3 uses image_url; O3 uses its catalog mapping. Failed/unknown parents and increased dependency quotes do not dispatch children.

Legacy saved works retain their original interpretation. A local connection-revision action creates a separate unapproved draft, keeps old assets as reference history, and requires editing/validation before any new paid request. It cannot bypass unresolved image/video requests. Existing generated clips are not repaired by this code change.

## Changed files

- src/newsflow/character/precision_contract.py: versioned plan and prompt contract.
- src/newsflow/character/precision.py: validation and original-preserving revision draft.
- src/newsflow/character/precision_video.py: scene dependency handoff and invariant checks.
- src/newsflow/character/episode_service.py: exact last-frame extraction for the new policy.
- src/newsflow/gui/character_precision_routes.py: local revision endpoint.
- src/newsflow/studio/actions.json and frontend/src/legacy-actions.json: route registration.
- src/newsflow/studio/read_models.py: continuity mode projection.
- frontend/src/studio/core/CharacterPrecision.tsx: connection editor/revision action.
- frontend/src/studio/core/precisionValidation.ts: matching client validation.
- frontend/src/studio/core/CharacterStudio.tsx: legacy versus connected mode text.
- tests/test_character_precision.py: explicit legacy fixture.
- tests/test_character_precision_continuity.py: new Fake regression cases.
- tests/test_character_precision_continuity_browser.py: Windows Chrome synthetic workflow.

## Validation

Windows Python 3.14.7, temporary isolated profiles and local images only. No real provider requests.

| Scope | PASS | FAIL | ERROR | SKIP |
| --- | ---: | ---: | ---: | ---: |
| New continuity unit/integration cases | 18 | 0 | 0 | 0 |
| New continuity browser workflow | 1 | 0 | 0 | 0 |
| Existing precision contract cases | 28 | 0 | 0 | 0 |
| Existing precision handoff/fast-mode browser cases | 3 | 0 | 0 | 0 |
| tools/studio_v3/tests | 58 | 0 | 0 | 0 |
| Total distinct Python tests | 108 | 0 | 0 | 0 |

Commands used: `python -m pytest -q -rs` with each focused set above, isolated basetemp, and JUnit output; `node --test tests/precision-handoff-quote.test.cjs` (5 PASS); TypeScript no-emit check; Vite production build; git diff --check. The frontend checks passed. Full regression was not repeated.

During implementation, tests exposed a missing `from` dependency in the handoff and an outdated browser-build fixture; both were fixed and their cases rerun successfully. The final new-test run contains 19 PASS. Earlier failed browser evidence is superseded only for that rerun case, not silently counted as passing.

The five-scene Fake flow covers [5,5,6,5,5] seconds and local FFmpeg output. It does not establish actual provider image/video quality, physical continuity, real billing, or user review acceptance. Original media and approvals remain preserved. No real user assets are included in this commit.
