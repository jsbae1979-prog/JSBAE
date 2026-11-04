# Stored status refresh and news list counts — 2026-11-03

Base: 178629d4949a9063d62b9e8bda551e0ee4a85098, branch codex/newsflow-character-shorts-automation-20261030.

## Findings and changes

- Home kept the workspace loaded before visiting API settings. Returning to Home did not refresh it, unlike the creation home. Stored successful provider probes were therefore displayed as unchecked. Refresh on Home entry now reuses the authenticated read-only workspace projection; no provider request or key decryption is added. Labels distinguish verified, recheck needed, and stored-but-unchecked. A key alone is not evidence of authentication or model permission.
- Scene polling only exists while the character studio is mounted. Navigating elsewhere stops future polling, not an already submitted vendor job. There was no visible explanation for unavailable commands or a slow pending response. Added explicit unavailability, paused and slow-response text, and last successful check time. A delayed check is NOT aborted or retried, and no additional submit/retry/quote path was added. Progress remains downloaded clips / total, not a fabricated vendor percentage.
- The observed operating job had three submitted receipts and one dependency-waiting scene. The server process remained alive. No new vendor lookup, generation, restart, or forced state change was performed for diagnosis. Current vendor completion and billing remain NOT VERIFIED; these UI improvements do not establish a vendor failure cause.
- News collection counters represented complete category results, but the news projection truncated articles at 100. News now returns all non-hidden articles; UI shows 50 initially and offers more, searches the entire loaded list, and distinguishes loaded/filtered/displayed counts. Category source overlap and unknown/older dates remain explicit. No collection/filter/lifecycle policy changed and no articles were deleted.
- The analysis authentication error after 24 hours is an existing expiry policy. It is retained; this change neither bypasses authentication nor initiates analysis.

## Validation (Windows, Python 3.14.7; isolated data and Fake providers)

| Command/scope | Final result |
|---|---|
| `python -m pytest tools/studio_v3/tests tests/test_provider_connection_tests.py tests/test_category_collection.py` | 108 PASS, 0 FAIL/ERROR/SKIP |
| `python -m pytest tests/test_provider_connection_browser.py tests/test_character_auto_progress_browser.py tests/test_news_list_counts.py tests/test_category_collection_browser.py` | 12 initially PASS; two new clock-based tests initially failed because virtual time advanced before React loaded |
| Re-run the two new progress tests after waiting for the rendered UI before advancing virtual time | 2 PASS, 0 FAIL/ERROR/SKIP; assertions retained |
| `node --test tests/*.test.mjs` | 47 PASS, 0 FAIL/SKIP |
| `tsc --noEmit`, `vite build` | PASS; existing font resolution, dependency directive and chunk-size warnings |

The final 14-test browser target is covered by the 12 unchanged passes plus two corrected-fixture passes. No external paid API, live collection, upload or SNS publication was executed. Full unrelated regression was not repeated. Existing local changes were preserved.

## Operating boundary

Only static frontend assets may be applied without a restart. The news backend projection remains pending until the active video work can safely be left untouched during a normal restart. Preserve backend source SHA, launch configuration, session, credentials, data and media. Do not report the 100-article backend limit as fixed in the running process before that separate application.
