# Request progress and standalone image dispatch — 2026-11-03

## Findings
- Operating analysis #93 was created at 22:44:06 KST and finished as `failed` at 22:46:51, with `analysis_schema`. The server was listening. This was not evidence of an ongoing successful generation. No replay was made.
- The stored diagnostic does not identify the invalid field or preserve the rejected response. The exact provider-output defect remains NOT VERIFIED; no unsupported cause or successful recovery is claimed.
- Standalone image draft #49 was saved with no generation record or budget reservation. The operating request boundary did not connect `/image-studio/{id}/generate`, while TOP 3 used a separately authorized path. This explains the pre-dispatch 403.

## Changes
- Added elapsed time, indeterminate waiting indicator, last server check, persisted work ID, and separate running/delayed/disconnected/completed/failed states to the command dialog. No invented completion percentage. Terminal status stops the spinner; closing does not resubmit.
- Added an authenticated, read-only GET for the exact existing curation claim. It returns fixed status fields only and does not call a provider, decrypt keys, or write job records. A failed old claim is visible when the analysis dialog opens again.
- Scoped standalone image execution to one exact saved draft, original prompt/model, signed local session, Origin/CSRF, consent/review, verified key/model and stored per-work budget. Atomic claim/reservation and existing result reuse prevent paid replay. All other blocked paths remain blocked.
- Standalone reference-image editing remains blocked with an explicit message because the existing pricing model covers text-only input. No invented reference-input pricing was introduced. Draft #49 has no reference image and uses the supported path.
- Existing production `windows_live.py` differs from the development base around portable installation. Preserve that difference; apply only this task's five installation lines in the staged operating file. Do not import unrelated portable-install changes.

## Validation
Python 3.14.7, temporary profiles, Fake DPAPI/image adapters and local test browser only.

- Unique Python checks after targeted fixes: 188 PASS / 0 FAIL / 0 SKIP. Includes 58 studio_v3 checks and 3 browser scenarios.

- Frontend contracts: 53 PASS / 0 FAIL / 0 SKIP. Typecheck and React build passed.
- Initial failures: five synthetic rows omitted a required `message`; then the new status GET was not yet registered in the operating read boundary; browser cleanup and duplicate close-button selectors were corrected. Latest affected checks pass. One initial frontend glob ran from the wrong directory and discovered zero tests; it is not counted. Correct-directory execution discovered and passed 53.
- Commands: `python -m pytest -q -rs` with targeted test paths; `node --test tests/*.test.mjs` from newsflow-ai; `tsc --noEmit`; `vite build --configLoader runner` on a clean staged frontend excluding unrelated work.
- No real paid generation, collection, OAuth or SNS test. Existing failed results and cost uncertainty are preserved. CI not rerun by this task.

## Operating application
See operating-result.json after exact-file update and one normal Stop/Start. No database content, credentials, media or backups are intentionally changed. Final hashes/table fingerprints are checked separately. Real Claude analysis success is not certified by these Fake tests.


Applied source: `12da40c5919ac9a7028732c855a1bdd694f9d900`. Normal Stop/Start completed once; server listening on loopback 18768, Chrome launch accepted. All DB-table fingerprints and pre-existing protected profile files match; original and backup hashes match. No generation reservation remained active. Analysis #93 remains the original failed record and draft #49 still has zero generation records; neither was resent.

The operating source contains the documented pre-existing Windows launcher overlay plus the five targeted installation lines. Repository HEAD alone is therefore not a claim that every operating file equals the entire repository tree. Only the eight manifest-listed files were applied.
