# Accepted scene failure follow-up — 2026-11-03

Base: 49382c2a029ae60a722bac991d8cb2d565fb6d0c.

## Cause and minimal changes
- The automatic scene observer required generating state and no failed scene. A single terminal result moved the job to scene_review and stopped observation of other accepted receipts.
- Legacy diagnostic preflight/UI rejected every waiting_dependency companion, hiding failure details for variable-length episodes.
- Provider status error facts were discarded by the episode check service.

Existing accepted submitted/downloading receipts now remain observable in generating/scene_review. HTTP errors and uncertain submission job states still stop automatic observation. No failed scene is replayed. After a confirmed failure, status/download work may continue but dispatch, reference upload and estimation of new continuations are held. Normal successful continuation stays unchanged.

The existing consent/authentication/CSRF/Origin-protected diagnose route accepts a valid, never-submitted episode continuation as a non-target companion; it still observes terminal owned requests only. Diagnosis never changes scene outcome, quote, attempt, handle or budget. Returned errors are sanitized and bounded. Check responses also preserve sanitized status facts.

Dependency-stop messages are read-only projections: direct/transitive failed parents display “앞 장면 실패로 중단”; other episode failures hold continuation as “작업 실패로 연결 보류”. Persistent states/history remain compatible with explicit future retries.

## Validation (Windows Python 3.14.7, Fake providers)
- python -m pytest -q -rs tests/test_character_failed_followup.py tests/test_character_episode_recovery.py tools/bat_distribution/tests/test_character_status_diagnostics.py tools/studio_v3/tests: **107 PASS, 0 FAIL, 0 ERROR, 0 SKIP**.
- python -m pytest -q -rs tests/test_character_auto_progress_browser.py: **9 PASS, 0 FAIL, 0 ERROR, 0 SKIP**.
- node --test tests/character_partial_status.test.mjs tests/character_failure_details.test.mjs: **25 PASS, 0 FAIL, 0 SKIP**.
- TypeScript --noEmit and Vite build: PASS. Existing font-resolution, lucide directive and bundle-size warnings remain.
- Total distinct focused coverage: **141 PASS**. Initial new-fixture failures (missing synthetic DB session and incompatible legacy/episode fixture) corrected without weakening product guards/assertions; all affected tests rerun.
- No new route; both action registries unchanged and matching.
- No live generation, news collection, OAuth/SNS, cancellation or retry in tests. Full regression not repeated under the focused-validation task scope.

## Operating verification
- Implementation commit: 49468c5149fcd398724a96893c01279622edcb56.
- Exactly 4 Python files and the current React index/JS/CSS (7 files) applied as an overlay of the changes from 49382c2, preserving installation-only changes. Unrelated, previously undeployed news backend changes were not applied.
- One normal Stop (exit 0) and one normal Start completed; Chrome opened through the existing authenticated launcher on loopback port 18768.
- Current database has 49 tables (the two Meta tables explain the difference from an older 47-table deployment helper), with 394 news articles. All table contents were unchanged across restart. 429 files were backed up and verified; 428 protected profile files preserved across restart after excluding normal session/lock churn. Credentials, media, original source and backups A/B retained. No migration or security-policy change.
- The stale deployment-helper table-count assertion stopped before any Stop attempt; it was corrected to the confirmed 49-table schema. The actual Stop/Start each ran once.
- User Chrome visibly shows three failed scenes and the never-submitted dependent scene as “앞 장면 실패로 중단”; it no longer presents that scene as a running generation.
- Through the existing UI consent/authenticated diagnostic action, exactly the three owned terminal receipts were queried. All returned: `Generation took too long to complete. Please try again later.` No automatic retry followed this provider message.
- Existing request parameters: O3 Standard (`std`), 9:16, sound on; submitted clip durations 4, 4 and 8 seconds. These were accepted receipts that later failed, not a demonstrated pre-submission schema rejection. The provider-reported direct reason is generation timeout; the underlying provider-internal cause is unavailable. No unsupported claim that all prompt/input choices are proven correct.
- Compared the job JSON with the pre-restart backup: only status_diagnostics fields changed. States, attempts, receipts, payloads, quote and budget are unchanged. The dependent scene still has no receipt. No new quote, reference upload, generation, paid retry or SNS request.
- Supplier console previously displayed execution times 2414–2419 seconds, with request-detail amounts totaling USD 1.792. Billing separately showed three completed usage entries and three completed refund entries, each rounded to cents and totaling USD 1.80 on each side. Billing UI did not link those rows to individual request IDs; exact per-request refund linkage remains unverified. No additional billing operation was performed.
- Private operating evidence and Chrome screenshot are retained locally, not committed (no user job/profile/prompt/image/request ID or credential upload).

## Result and remaining condition
Application observation/diagnostic fixes: PASS. Supplier generation: FAILED (timeout). New production generation and refund reconciliation: NOT VERIFIED; no retry authorized or performed in this task. Overall CONDITIONAL: the UI and read-only diagnostic path are repaired, while successful new paid generation is a separate user decision. A failed generation is not reported as a successful video.
