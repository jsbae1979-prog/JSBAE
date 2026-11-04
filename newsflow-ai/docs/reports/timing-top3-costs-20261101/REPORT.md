# Natural story timing and TOP 3 cost approval preparation

Base: 4b5e2563599d4345e54d9710e1a57716a7b03720, branch codex/newsflow-character-shorts-automation-20261030.

## Implemented
- User-approved 1–2 second story variance. Upper bound target+2; preserve the previously accepted lower target-2.1 boundary (0.1 s rounding compatibility). No scene count, source clip duration, schema, rights, or audio rules removed.
- Validation, saved-response review, instructions and FFmpeg timeline agree. Keep authored timing at 30 fps instead of padding/cutting the final shot to hit the target. Previously composed files are untouched.
- Cached server-owned TOP 3 cost bounds bind batch, source, content, model, attempt and account. Expiry, consent, per-batch limit, durable pre-dispatch reservation and no duplicate request enforced. Existing reservations remain after failure/requote; not represented as invoices.
- Local cost review endpoint/UI retains LocalAccess, CSRF, Origin. Unknown and known failures stop remaining images. Operating POST generation boundary unchanged.

## Focused verification
Python 3.12: 111 PASS, 0 FAIL, 0 ERROR; Fake-only providers and isolated DBs. Includes local FFmpeg outputs at 27.9 and 20.1667 s without stretching, preserved paid response/receipt with free recovery, stale/expired/changed-account quote rejection, invalid budgets, failure stop and CSRF. TypeScript and React production build PASS. Existing Starlette warning and asset chunk/font build warnings retained. Python 3.14 not rerun.

## Actual image API limitation (CONDITIONAL)
The default production application does not inject a cached quote/account verifier: real paid image execution remains blocked. No live request was made. Browser-entered unit prices are not accepted as price evidence; no fixed image price or billing success is invented.
Official source checked 2026-11-01: https://developers.openai.com/api/docs/models/gpt-image-2.5-flare . Standard token rates are documented but this does not establish an exact per-image quote or enforceable per-request dollar cap. The GPT Image 2 calculator explicitly does not estimate GPT Image 2.5 token consumption. A verified production cost-bound source and account/model readiness are still required before live activation. This is cost-approval plumbing, not a completed live OpenAI connector.

No real AI generation, SNS, collection, migration, content deletion or security relaxation. Personal response bodies, databases and captures excluded from this report and Git.
