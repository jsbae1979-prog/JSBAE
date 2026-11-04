# OpenAI key registration 403 correction — 2026-11-01

Observed in user's Chrome: OpenAI image key missing; manual key-save returned 403. No real key was read, copied, logged or resubmitted by the agent.

Two code causes: React supplied `openai_api` although the server accepts `openai`; the BAT local-operation boundary also lacked an OpenAI registration path. Corrected the UI name and placed the password input in the main dialog rather than collapsed advanced fields.

Added exactly POST /api-settings/openai/key through existing LocalAccess/Origin/signed-CSRF validation. The protect-only store writes the current-profile ai-key.dpapi atomically, with the existing entropy and private ACL, preserving previous ciphertext in a private backup. It cannot read/decrypt or delete keys, call a provider, or permit unrelated endpoints. Failed protection/replace keeps the old ciphertext. Invalid values and native exceptions do not echo secrets. Original API verification invalidation is retained; saving is not verification or paid-generation approval.

64 focused tests PASS / 0 remaining FAIL / 0 ERROR. Includes isolated Chrome with synthetic key, correct POST path, local encryption, backup, cleared plaintext buffers, failed-save preservation, session/Origin/CSRF rejection, wrong-profile rejection, provider metadata and image-budget regressions with Fake adapters. Initial browser fixture failed on an unsafe temporary directory ACL; fixture now creates a fresh private synthetic directory and passes. Production ACL rules were not weakened. TypeScript/Vite build PASS (existing font/bundle/dependency warnings retained).

Actual OpenAI registration requires the user to enter the key again in Chrome after application; no real key supplied in tests. Estimate/metadata checks and paid generation remain separate. No real paid API, SNS, main merge or external distribution.

## Operating application and visible Chrome verification

- Applied code 744ee3a33794a6a515925b56e86e58581b19f2f7 through one normal Stop/Start; normal Stop exit 0.
- Six exact program/static files applied; installation-only overlays and launch policy flags preserved.
- Before/after restart: all 47 DB tables logically unchanged, 86 current-profile articles unchanged; 373 profile files preserved. Separately protected original and A/B backups unchanged.
- Existing authenticated Chrome reopened; unauthenticated local GUI request remains HTTP 403.
- User directly re-entered and saved the OpenAI key successfully. No plaintext credential was read, copied, logged, or committed by the agent.
- One read-only OpenAI model metadata check from the visible Chrome succeeded: key authentication and selected image model lookup confirmed. No generation request.
- Existing TOP 3 work loaded in visible Chrome. Local app estimate for 3 images, standard quality, 4:5: USD 0.061975; planning reserve USD 0.14 including the 2x allowance and per-image rounding. This is an app estimate, not a provider billing cap.
- Budget input remains blank; budget approval and image generation were not executed. All three result slots remain waiting.
- Focused automated checks: 64 PASS, with TypeScript and React build passed. Live key registration/model lookup are additional observed checks, not included in the automated count.
- Sensitive deployment snapshots and user-content screenshots remain local and are not included in Git.
