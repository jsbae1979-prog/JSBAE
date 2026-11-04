# TOP 3 complete-feed production check — 2026-11-03

User approved saving a per-work USD 1 image budget and generating three images via the operating Chrome UI. No new analysis, collection, SNS publication, or automatic retries were authorized/executed.

## Minimal settings fix

Product commit: `52fbeea9ca7c254a27ca1cf67c37883946b2c5b0`.
The image-budget button previously used the generic text-provider configuration POST, rejected by the operating dispatcher (HTTP 403). A dedicated authenticated, CSRF/Origin-protected `/api/feed-image-budget` POST now stores the image budget separately from text-token settings. Registered in both action catalogs. Existing approval revocation and invalid-limit rejection remain enforced. No credential changes.

Focused Windows Python 3.14.7 validation: 47 PASS (image budget/complete feed contracts), 58 PASS (studio_v3), 0 FAIL / 0 ERROR. React typecheck and production build PASS. These are focused results, not a repeated full regression. Earlier full-suite evidence remains separate.

## Live result (separate from Fake tests)

Chrome work 84, saved analysis 79, style `ai_design_v1`, model `gpt-image-2.5-flare-2026-09-08`, medium, 4:5. Exactly three OpenAI generation requests completed successfully on attempt 1. Outputs are 1080×1350, stored individually; original work 80 images unchanged. Settings budget USD 1 applied without repeated per-image approval. Reserved planning budget USD 0.16; response-usage calculation USD 0.044860. Provider invoice NOT VERIFIED; this app budget is not a provider charge guarantee.

All three Chrome result selections were inspected. Stored originals contain complete Korean text without edge clipping. The expanded popup overflows the viewport at the observed screen size; this is a remaining display defect, not missing pixels in the files.

## Editorial limitations

Generation success does not equal publication approval. TOP 1 uses photorealistic people; likeness/rights and separation from real event photography need human review. TOP 2 headline is longer than the intended concise editorial style. TOP 3 background contains unsourced percentage labels (-3.21%, -2.87%, -3.56%, -4.12%); do not treat those as reported market facts. No additional paid edits were submitted to fix these results.

## Preservation

Before/after table digests changed only `ai_usage`, `app_settings`, `intelligence_runs`, corresponding to the authorized budget and generation. Other tables unchanged. Existing profile-file hashes changed only runtime session/browser-launch records. Original DB/backup A/B hashes and existing generated-image hashes preserved. No SNS calls or deletion.

## Result hashes

- TOP 1: `feed-84-1-1.jpg` — `c3ecfdf08246332851564ed71e822403ff77810d2f4f0a9a4b05fd25f7f46c75`
- TOP 2: `feed-84-2-1.jpg` — `21f57c37e279cc79bf00bb9b1c21b532c3f0bad253d94e8a9fcdfe768e8cd097`
- TOP 3: `feed-84-3-1.jpg` — `036e977511a04d40d667bbac99e16a6060a029168e6d55c658a40dcdf64b40e1`
