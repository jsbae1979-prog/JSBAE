# Character studio and model selection UI — 2026-10-29

## Result

**CONDITIONAL — development implementation and focused verification complete; operating installation not changed.**

- Branch: `codex/newsflow-bat-distribution-prep`
- Base: `f0b7cef5ca37adf0ad4c5420e4a97483f82928be`
- Implementation: `487feb9fe6f7362dccf26ea89c1ee4af20bf380e`
- Authority: the user's attached character-studio PNG and seven-page model-selection PDF; latest PDF rules take precedence for character style/aspect locks and the sound toggle. The user's two-model restriction remains in force.
- No operating restart, paid provider request, OAuth, SNS, migration, package rebuild, PR #35/main change or external distribution.

## Delivered behavior

1. Character studio: reference upload/my-character tabs; original 3-column composition; reference preview and recent characters; topic input (100 characters); a single **스토리 자동 생성하기** button; video preview beside settings; five storyboard cards; compact samples/history/tutorial controls. Samples and existing uploads remain usable, with no fabricated result thumbnails or finished videos.
2. One story click performs a local draft/reference save and then one approved Claude request. There is no separate manual job-save step. It sends the selected reference (vision input), not the old fixed capybara. Stored API approval/budget and explicit click disclosure remain mandatory. A durable request identity prevents duplicate local creation; already completed/uncertain jobs do not trigger another paid request.
3. New work exposes only **Kling 3.0 Standard** and **Kling O3 Standard**. Old Seedance jobs/results remain readable without migration or conversion.
4. The video panel includes model, style, aspect ratio, native quality, scene duration, sound toggle, total duration and estimated cost. Character style and 9:16 are locked to character configuration as required by the PDF. A disabled option retains an explanatory title. Output dimensions are a separate advanced FFmpeg setting; 1080p local output is never described as native 1080p generation.
5. Scene duration is catalog-driven (currently 3–15 seconds). New stories use 3–5 scenes within 60 seconds: default 5 × 11 = 55 seconds. Legacy 30-second stories keep their old schema/composer. Changing duration after story creation requires a new story, avoiding a mismatch between quoted scenes and saved content.
6. Existing quote → story review → cost approval → submit → manual status check → clip review → FFmpeg composition remains. Settings freeze after quoting. Unknown outcomes retain the original reservation and cannot automatically replay or change models. Audio on preserves actual generated audio; requested audio missing from a clip stops composition rather than silently replacing it.

## PDF requirement mapping

| Requirement | Result and implementation |
|---|---|
| One normalized source for UI and request validation | `src/newsflow/video_models/catalog.py`; `GenerationSettings`, `validate`, `reconcile`, `build_request` |
| Data-maintained model choices | `src/newsflow/config/video_models.yaml`; exactly two enabled production models |
| No new YAML runtime dependency | `.yaml` files use JSON syntax, the YAML 1.2 subset; strict, non-executable parsing documented in `config/README.txt`. Existing 27-package runtime is not changed |
| Cache/startup/refresh/failure | Module startup loads once, serialized memory cache, 24-hour refresh of the manually maintained file, last-good fallback and safe warning on failure/option shrinkage |
| Model API discovery | No undocumented/discretionary vendor request. Manual official-schema source is used, as the PDF permits when a safe discovery endpoint is not established |
| Compatible values preserved / unsupported values adjusted | Nearest lower resolution, nearest duration, ratio default and sound-off adjustment with field notes; tested using three synthetic capability sets |
| Disabled/uncertain models hidden | Catalog `enabled` filter; the PDF's Seedance/Veo examples are not added to production |
| Recommendation | Catalog `recommended`; UI has no hardcoded recommendation or model list |
| Styles from config | `config/style_presets.yaml`, prefix/suffix, character appearance/style-lock precedence; warnings frozen into the job and human review checklist |
| Sound | A single “소리 생성” switch, no voice-ID/timbre selector; native `sound: on/off` for both approved models |
| Request mapping | `param_map`; unsupported native fields omitted, server rejects incompatible inputs before any provider request |
| Saved settings | New-work defaults from last successful validated job; reconciliation notes when needed; immutable historical jobs remain readable even after catalog deactivation, while new execution is blocked |
| Estimates and budget | Public list-price estimates/ranges update locally. Per-episode overage disables the video button and is also rejected by the service before reference upload. Official quotes and actual billing remain separate |
| Capacity/retry | No automatic paid POST replay was introduced. Existing known-failure/manual re-quote route remains; unknown outcomes cannot replay. This preserves the user's standing no-unknown-retry requirement; live capacity responses were not exercised |

## Actual Higgsfield capability mapping

| Item | Kling 3.0 Standard | Kling O3 Standard |
|---|---|---|
| API path | `kling-video/v3.0/std/image-to-video` | `kling-video/o3/image-reference` with **mode=std** |
| Reference | `image_url` | `image_urls` |
| Duration | `duration`, 3–15 seconds per scene | `duration`, 3–15 seconds per scene |
| Sound | `sound: on/off` | `sound: on/off` |
| Ratio | No native ratio field in this I2V schema. A separate owned reference is padded, then FFmpeg enforces 9:16 | Native `aspect_ratio`, character mode fixed to 9:16 |
| Native quality | No resolution input field documented. Model-default only; 480p/720p/1080p/4K choices disabled | Same; Standard is fixed with `mode=std`, no Pro/4K promotion |
| Style | Character configuration → prompt | Character configuration → prompt |
| Price | Public undiscounted range $0.084–0.126/s; audio-specific rate mapping unverified | Public list reference $0.084/s with sound off; sound-on price unverified |

At 55 seconds, the first public range displays approximately $4.62–6.93. It is not a binding maximum or invoice. O3 sound-on displays **공식 견적 전 미확정**. We did not invent an audio-specific price change from the PDF's example credits. The three-model synthetic test verifies that a catalog with known different sound prices updates the UI correctly.

Official sources read on 2026-10-29:

- [Kling 3.0 Standard model-specific API](https://open.higgsfield.ai/models/kling-video/v3.0/std/image-to-video/api-reference)
- [Kling O3 Image Reference model-specific API](https://open.higgsfield.ai/models/kling-video/o3/image-reference/api-reference)
- [Kling 3.0 public model pricing](https://open.higgsfield.ai/models/kling-video/v3.0/std/image-to-video/playground)
- [Kling O3 public model pricing](https://open.higgsfield.ai/models/kling-video/o3/image-reference/playground)
- [Higgsfield API pricing](https://open.higgsfield.ai/pricing)

## Verification

- Integrated focused run: **111 PASS**, 2 existing full-app GUI tests deselected (the local plain test runner lacks the existing `step13_isolation` fixture). Existing app/Windows evidence is reused rather than altering its Guard/fixture.
- After cache/warning/archive refinements: **65 PASS** for catalog/new-character tests. Across both clean runs: **113 unique PASS / 0 unresolved FAIL / 0 ERROR**. Counts are deduplicated, not added as 176 tests.
- TypeScript and Vite production build: **PASS**. Existing font-at-runtime, lucide module-directive and bundle-size warnings remain.
- Original production CSRF/Origin middleware body was exercised unchanged in an isolated route-only app: wrong cookie/form token and foreign Origin rejected for local upload and story generation. No exception was added to `main.py`.
- Browser: synthetic, isolated in-app Chromium UI. Two production models plus three synthetic test-only models; upload/canvas preview; one-button story response; sound-cost adjustment; unsupported sound auto-off; resolution 1080→720; duration 10→8; budget-overage denial; original review/consent dialog retained.
- 1920×1080 and 1366×768: no document horizontal overflow; primary story/video buttons reachable; portrait preview retains 9:16. Full-page captures record the content under each viewport, not OS DPI.
- Local FFmpeg: three focused checks passed, including actual synthetic MP4 composition with audio on/off and requested output dimensions, plus rejection of missing requested audio. No paid media was generated.
- Overall visual result: **MINOR**. The core three-column/reference-story-video/storyboard arrangement matches; the latest PDF intentionally adds scene duration, sound toggle and truthful capability/cost help. Synthetic/empty data, additional help height and font rendering differ from the illustration; no pixel-identity claim.
- Actual paid Kling/Claude generation, account permissions, native output quality, Korean lip-sync/audio quality, current operating GUI and real OS DPI: **NOT VERIFIED** in this task.

## Preservation

`preservation.json` confirms 47 table logical hashes unchanged; articles 169, AI processing records 48, drafts 6, video projects 7 and image posts 3. All 26 protected credential/media file hashes and the original/A/B DB hashes match the previous baseline. No key/token plaintext is in code, evidence or Git.

Home, content-production home, the other core studios, management screens, samples, distribution/security code and migrations are unchanged. New CSS selectors all require the character screen scope. The shared `CoreStudios.tsx` change is limited to the character title/subtitle. Existing untracked `validation/` is preserved and excluded from commits. Current operating PID was observed present; no operating Start/Stop command was sent.

## Operating application and next approval

**Not deployed.** This change adds Python routes/service logic and three packaged configuration files, so replacing static CSS/JS alone is insufficient. Operating application requires a reviewed installation-file update/manifest refresh and **one separately approved normal Stop/Start**, preserving the existing Chrome authentication and all data/security settings. Existing external-execution, API approval, SNS, scheduler and unsigned-update restrictions must remain; this task grants no paid execution.

No user confirmation is needed for the completed development work. Operating application/restart is the remaining approval boundary. No operation/paid generation was attempted to make development tests appear successful.

## Evidence

- [Before/after viewer](visual-comparison.html)
- [Unique test summary](TEST_SUMMARY.json)
- [Preservation](preservation.json)
- [Changed files](CHANGED_FILES.txt)
- [Semantic implementation diff](IMPLEMENTATION.diff) (ignores the existing CRLF/LF discrepancy)
- [Original user input hashes](INPUTS.json)

One attempted multipart-middleware edit was rejected by automatic review for possible CSRF weakening. It was not applied. The final implementation uses the existing `/character` local upload and a separately CSRF-protected URL-encoded story call; production security middleware remains unchanged, with a focused test of its original body.
