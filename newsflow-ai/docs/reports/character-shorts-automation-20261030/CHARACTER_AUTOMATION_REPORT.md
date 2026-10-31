# Character shorts automation implementation

Final judgment: **ACCEPTED for development and Fake-provider validation**. No operating deployment or paid generation was performed. Real provider quality/billing and operating rollout require separate user-PC approval.

구현과 개발 검증을 완료했습니다. 운영본은 변경하지 않았으며, 실제 유료 생성과 장면 품질 검수는 별도 승인 후 사용자 PC에서 확인해야 합니다.

## Scope and provenance

- Base: `codex/newsflow-bat-distribution-prep` at `5a2c17d5565dc84d250e92dc8f32295a84e7f122`.
- Specification imported unchanged from `docs/newsflow-character-shorts-spec-20261030`, commit `a3a7a856b1c358ffc011ff85afc83b616ed0a838`.
- Work branch: `codex/newsflow-character-shorts-automation-20261030`; PR #36 targets the existing BAT development branch, not main.
- The user approved reusing the existing development checkout after the original checkout was found to have unrelated local edits. No worktree, reset, clean, stash or force push was used. Pre-existing untracked `validation/` remains outside these commits.
- No running NewsFlow installation was changed, restarted, stopped or used for API tests. No real AI generation, OAuth or SNS request was performed.

## Specification versus actual code

The pre-implementation comparison is in `docs/character_shorts/IMPLEMENTATION_REVIEW.md`. Actual code already had a React character studio and versioned local job storage, so the change extends that path. The active files are `frontend/src/studio/core/CharacterStudio.tsx`, `src/newsflow/gui/character_routes.py`, `src/newsflow/character/service.py`, and `src/newsflow/studio/read_models.py`; the specification's example paths were not treated as mandatory new modules.

The existing image registry stored an asset and label, not editable character attributes. The old writer stripped character context, selected only Claude, and produced five equal clips. Native dialogue/lip-sync prompts and plain concatenation belonged to that old contract. New profile-backed jobs use a version 3 episode schema; historical saved jobs, media and parsers remain readable. No database migration was needed; published migrations are unchanged.

The latest explicit requirements take precedence over conflicting document examples: no hardcoded mascot or bundled 50-topic character seed; no global daily/cumulative spending block; no automatic submission retry even after 408/429. Only a known failed request can be explicitly retried after a new quote and approval. Unknown outcomes retain their reservations and are never automatically replayed. The new version supports the requested SFX/caption editor, while old jobs preserve their prior plain-composition behavior.

## Implemented behavior

1. Character profiles: multiple registered assets, editable appearance/personality/style/comedy formula, isolated per-character topics, revision checks, asset hashes, three AI analysis candidates with explicit user selection, rejected-analysis handling. Deleting a profile does not delete historical job media.
2. Topic generation: selected character input, 1–50 topics, exact duplicate rejection, category/joke diversity, CSV import, status tracking and manual post-upload `produced` marking. Topic/script generation sends text; image analysis is an explicit separate operation.
3. Script generation: selected Claude or OpenAI adapter, structured episode validation, coherent location/action continuity, cut/continue relationships, speed/freeze strength, SFX, captions and upload fields. Validation feedback includes bounded field names and error types, not raw prompts or credentials.
4. Timing: 15–60 seconds in 5-second steps; scene count varies with duration and selected model limits. Edited duration is checked, and the final MP4 is padded to the selected duration within 0.1 second. The five-equal-clips rule remains only in historical readers where required for compatibility.
5. Video generation: camera effects and environmental sound are requested from the selected video model. Every new prompt contains `no dialogue, no voices, no music`; no Korean dialogue or lip-sync instruction is added. Independent cuts can submit concurrently. A continuation waits for its source clip, extracts and uploads its owned final frame, and uses the catalog's continuation parameter.
6. Catalog and settings: reference-image and 9:16 capable models are loaded from the existing catalog; model parameters use its `param_map`. Unsupported sound is disabled. Model and duration cannot silently invalidate an already generated script. Turning sound off clears sound instructions locally and invalidates the quote without another AI call.
7. Local editing: 1080×1920/30fps H.264 with AAC 48kHz, configurable speed/hold strength, original code-generated comedy SFX, Noto Sans KR ASS captions, audio-only crossfade and loudness normalization. Zoom/shake are not added by FFmpeg. SFX provenance and the existing font license are retained.
8. Approval and recovery: per-episode exposure includes prior attempts; official estimates are distinct from real billing. Quote hashes, script review, explicit submission consent, deterministic idempotency keys and saved request/download ownership are checked. Reopening an accepted request polls/downloads that request rather than creating another. Regeneration covers only selected scenes and their dependent continuations, with separate approval and retained prior output.
9. UI and batch queue: the existing three-column design is retained. Profile editing, topic generation, Claude/OpenAI selection, per-scene previews, script editing, explicit regeneration and sequential approved batch execution are connected to Python routes. Batch execution never supplies human review or SNS publishing automatically.

## Operating integration boundary

The development BAT policy adds only the required local profile/topic/script-save/read and owned-media routes. It does not globally enable new paid endpoints or modify the installed operating dispatcher. A later user-approved deployment must connect and verify the new paid workflow on the user PC, including real model availability, permissions, estimates and billing. This PR does not claim that Fake adapters prove those external conditions.

## Verification

The complete per-commit file list is in `CHANGE_MANIFEST.json`. The implementation commits were separated by responsibility:

| Work | Main implementation | Commit |
| --- | --- | --- |
| Specification comparison | imported spec, implementation review | ea43310 |
| Character persistence | registry.py | b58ae27 |
| Topics and AI authoring | topics.py, authoring.py | 113af61 |
| Episode schema/edit settings | episode_story.py, episode_policy.py, edit_presets.yaml, sfx_map.yaml | 2ec30ac |
| Model/timing mapping | kling.py, catalog.py, video_models.yaml | 0df8822 |
| Generation/continuation/recovery | episode_service.py, episode_regeneration.py, service.py | 2539fa4 |
| React and Python route integration | CharacterAutomation.tsx, CharacterStudio.tsx, route/read-model files | 96b9d2e |
| FFmpeg editing and Fake E2E | editing.py, compose_studio.py, SFX provenance | 9215621 |
| Episode queues and approval exposure | queue.py, authoring/service budget integration | 068526e |
| Legacy boundary and media route cleanup | service/read models, BAT local-only route policy | b282966 |
| UI race/validation hardening | scoped character component and service checks | 22c38f7 |
| Concurrent authoring receipts | caller-local results and serialized shared transport | 40cb7fb |
| Actual audio overlap | reflected outgoing tail, incoming original audio at each cut | c7a8d82 |

The audio crossfade uses a bounded 150 ms reflected tail from the outgoing track, mixed with the incoming track at the exact video cut. This replaces an initially detected silence-tail fade and prevents progressive audio timing drift. A real PCM test checks both frequencies during overlap and the exact total length. It does not certify the subjective sound of real generated scenes.

| Requirement | Focused evidence |
| --- | --- |
| Multiple character profiles, edit/revision/isolation | test_character_registry_v3.py |
| Image analysis candidates/rejection and Claude/OpenAI envelopes | test_character_authoring_v3.py |
| Topic counts, duplicates, CSV and statuses | test_character_topics_v3.py |
| 15/20/35/50/60 boundaries, variable scenes, continuation rules, prompts | test_character_episode_schema.py |
| Catalog capability and parameter mapping | test_character_episode_catalog.py |
| Approval, concurrent cuts, dependent start frames | test_character_episode_automation.py |
| Interrupted accepted requests, ownership and no automatic replay | test_character_episode_recovery.py |
| Selected regeneration and dependent descendants | test_character_episode_regeneration.py |
| Explicit batch approval and sequential progress | test_character_episode_queue.py |
| Speed/holds/SFX/captions/crossfade and exact MP4 timing | test_character_episode_editing.py |
| Two characters, generated topics, 15/35/60 final MP4 | test_character_episode_end_to_end.py |
| React/Python routes and actual isolated Chrome UI | test_character_automation_routes.py, test_character_automation_browser.py |
| Sanitized bounded failure feedback | test_character_validation_feedback.py |

Tested source: `c7a8d824a742e636d40ce062327edbda42be2e38`. The final documentation commit is recorded in the PR/branch history.

| Execution | Result |
| --- | --- |
| Windows 11 build 26300, Python 3.12.10, `python -m pytest -q -rs` | **6080 PASS / 0 FAIL / 0 ERROR / 4 SKIP**, 2277.34 seconds |
| Windows CI Python 3.12 | **148 PASS**, 0 FAIL/ERROR |
| Windows CI Python 3.14 | **148 PASS**, 0 FAIL/ERROR |
| Frontend contracts, each CI matrix | **31 PASS** |
| TypeScript and React production build, each CI matrix | **PASS** |

CI: https://github.com/jsbae1979-prog/JSBAE/actions/runs/41010344831 . The hosted OS is Windows Server 2025; it is not Windows 11 DPI evidence. Local browser tests use isolated synthetic profiles. No operating Chrome session or user database was used.

The full local run used the locked Python dependencies, isolated FFmpeg/FFprobe 9.0.2 on PATH, packaged NotoSansKR, tzdata 2026.5 and the existing historical Step13 test inputs. Five baseline code blobs were checked against the committed SHA-256 manifest for `0a59bfb41eec6b243e4470f67cd53c1e7cd07e52`; current source was not substituted for an old baseline. Test credentials were synthetic and live AI/RSS flags were off.

The run emitted 18 warnings, including dependency deprecation, legacy SQLAlchemy null-identity lookups and JUnit property compatibility. These are recorded separately from failures; no unrelated product changes were introduced to suppress them.

Skipped test names/reasons are recorded in `FULL_TEST_RESULTS.json`; they are not counted as PASS. Raw logs, temporary databases and media remain local. The first in-progress full run reported 5681 PASS / 248 FAIL / 66 ERROR / 49 SKIP and was used only for diagnosis, not acceptance. A later in-progress run was interrupted to correct the audio-overlap issue; only the final completed run above is acceptance evidence. Focused reruns and CI are separate executions, not additional unique tests to sum into the full-suite count.

`CHANGE_MANIFEST.json` records every phase commit, changed file and capture hash. DB migration files, management screen source, sample originals and the shell route file have no changes against the base. The running installation, real databases, keys, media, backups, main and PR #35 were not modified by this task.

Captures (synthetic profiles, full-page screenshots at the named viewport):
- [1920×1080 viewport](captures/character-automation-1920x1080.png)
- [1366×768 viewport](captures/character-automation-1366x768.png)

 Initial full-suite failures included old fixtures that still required the previously removed cumulative budgets, old fixed-clip assumptions and missing historical harness inputs. Those fixtures were updated to the already accepted per-execution policy; production limits were not loosened to make tests pass.

The end-to-end Fake test registers two distinct synthetic characters, generates topics, uses both Claude and OpenAI response envelopes, creates clips, runs real isolated FFmpeg and verifies 15-, 35- and 60-second MP4 outputs. These tests cannot judge real model visual consistency or guarantee that a provider will never generate speech despite the prompt.

## Remaining user-PC checks

- Deploy only after separate approval; the running installation is unchanged.
- With explicit per-request paid approval, verify selected Claude/OpenAI models, character-image analysis permission, Higgsfield model parameters, final-frame continuation, quote/actual billing and retrieval after interruption.
- Human review must confirm character appearance, camera continuity, no dialogue/music, comedy timing, caption readability and SFX levels.
- Real Windows 11 interactive GUI/DPI and actual provider quality are not established by Windows Server CI or headless synthetic browser tests.
- No public release, operating restart, main merge or PR #35 modification is included.
