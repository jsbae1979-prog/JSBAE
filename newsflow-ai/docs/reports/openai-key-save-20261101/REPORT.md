# OpenAI key registration 403 correction — 2026-11-01

Observed in user's Chrome: OpenAI image key missing; manual key-save returned 403. No real key was read, copied, logged or resubmitted by the agent.

Two code causes: React supplied `openai_api` although the server accepts `openai`; the BAT local-operation boundary also lacked an OpenAI registration path. Corrected the UI name and placed the password input in the main dialog rather than collapsed advanced fields.

Added exactly POST /api-settings/openai/key through existing LocalAccess/Origin/signed-CSRF validation. The protect-only store writes the current-profile ai-key.dpapi atomically, with the existing entropy and private ACL, preserving previous ciphertext in a private backup. It cannot read/decrypt or delete keys, call a provider, or permit unrelated endpoints. Failed protection/replace keeps the old ciphertext. Invalid values and native exceptions do not echo secrets. Original API verification invalidation is retained; saving is not verification or paid-generation approval.

64 focused tests PASS / 0 remaining FAIL / 0 ERROR. Includes isolated Chrome with synthetic key, correct POST path, local encryption, backup, cleared plaintext buffers, failed-save preservation, session/Origin/CSRF rejection, wrong-profile rejection, provider metadata and image-budget regressions with Fake adapters. Initial browser fixture failed on an unsafe temporary directory ACL; fixture now creates a fresh private synthetic directory and passes. Production ACL rules were not weakened. TypeScript/Vite build PASS (existing font/bundle/dependency warnings retained).

Actual OpenAI registration requires the user to enter the key again in Chrome after application; no real key supplied in tests. Estimate/metadata checks and paid generation remain separate. No real paid API, SNS, main merge or external distribution.
