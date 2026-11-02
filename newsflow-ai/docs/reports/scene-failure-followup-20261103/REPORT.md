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
Prepared for exact-file operating overlay and one normal Stop/Start under standing approval, preserving data, original media and credentials. Actual supplier failure reasons and operating application verification are separate from these Fake results and will be recorded after the bounded read-only diagnostic request. Failed provider production is not asserted to be fixed by these tests.
