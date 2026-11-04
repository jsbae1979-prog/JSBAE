# Explicit failed-scene retry operating connection — 2026-11-03

Base: e53f492470cf615384ccf6467e7f88a35b130c62.

Connected the existing authenticated retry-scene route to CharacterService.retry_scene for modern episode jobs. No new POST route was introduced; both action registries already contain the route. No provider or frontend API contract was changed.

The adapter verifies the exact owned confirmed-failure receipt, quoted payload, selected scene, plan/reference, original attempt and fresh quote approval. The existing service checks the 15-minute quote lifetime, key identity and episode budget, journals the new attempt and cost reservation before IO, and retains the previous failure/receipt in history. Only the quoted target can submit once in this request scope. All other scenes must remain unchanged. Upload, estimates, status, diagnosis and download cannot run inside the retry scope. Unknown outcomes retain their reservation and cannot replay automatically.

Windows Python 3.14.7 verification (temporary data and Fake providers only):

`python -m pytest -q -rs tools/bat_distribution/tests/test_character_retry_execution.py tools/bat_distribution/tests/test_character_retry_quote.py tools/bat_distribution/tests/test_character_manual_execution.py tools/bat_distribution/tests/test_character_status_diagnostics.py tools/bat_distribution/tests/test_character_quote_only.py tests/test_character_episode_recovery.py tests/test_character_per_execution_limits.py tools/studio_v3/tests`

Initial run: 191 PASS / 1 FAIL / 0 ERROR / 0 SKIP. The new corrupted-plan negative test correctly triggered rejection, but its final assertion attempted to deserialize that deliberately invalid plan. Corrected the assertion to verify unchanged persisted bytes instead. Re-ran all 20 tests in the changed test file: 20 PASS / 0 FAIL / 0 ERROR / 0 SKIP. Combined distinct final coverage: 192 PASS; no unresolved failures. No real API calls. Frontend/build unchanged, previous evidence reused.

Changed files:
- tools/bat_distribution/character_manual_execution.py
- tools/bat_distribution/tests/test_character_manual_execution.py (fixture and exact-route expectations)
- tools/bat_distribution/tests/test_character_retry_quote.py (missing paid approval remains blocked)
- tools/bat_distribution/tests/test_character_retry_execution.py (20 focused cases)

Real paid regeneration has not been executed. An explicit user approval with a currently valid quote remains necessary. Expired quotes are rejected; the previous quote is not an indefinite spending authorization. Legacy non-episode retries remain blocked in this operating adapter.

Operating application: code 44c5f4683f367d6737dddb348e8918ba29ad7210 applied as one controller file. Normal Stop exit 0, Start each once. PID changed to 36336 on 127.0.0.1:18768. Chrome opened normally. 49 tables, 394 current-profile articles and 428 profile files preserved; original 169-article source and backups A/B unchanged. Launch/security flags and stored credentials unchanged. No paid API or SNS call during deployment. Local rollback snapshot: 429 files.
Chrome verification: opened the existing job and its failed-scene quote approval dialog. It displays scene 1 / USD 0.448, with all consent boxes unchecked and submission disabled. No submit action was performed. The job file remains byte-identical to the pre-application backup after this UI check. Private screenshot: retry-execution-operating-20261103/chrome-ready.png (not committed).

Verdict: implementation, Fake tests and operating application PASS. Real paid generation and supplier completion remain NOT VERIFIED; no video completion is claimed.
