# Feed usability, source linkage and durable connection status — 2026-11-04

Base: bc90ff01f236762786c972e0d99e62049cf1c660. Branch: codex/newsflow-character-shorts-automation-20261030.
Local Windows Python 3.14.7, isolated profiles, Fake providers only. These results do not certify real provider access, billing or publishing. Existing unrelated modifications remain outside this change.

## Causes and changes

- ProviderConnections discarded confirmation after 24 hours even with unchanged encrypted key/model. API readiness independently applied the same cutoff. Confirmation now persists with its original timestamp. Key replacement/removal, changed model, explicit failed checks, invalid dates and interrupted checks still invalidate the appropriate status. Read-only status requests never decrypt keys or call providers. Billing freshness, budget limits, consent, auth/CSRF/Origin and duplicate-request checks are unchanged. A cached confirmation is the last verified result, not continuous monitoring of provider health.
- Standalone image descriptions repeated the app-generated instruction. Display now extracts user intent, retaining the full stored prompt and collapsible original input.
- Feed deduplication discarded meaningful article query IDs, wrongly merging distinct articles from one publisher. Identity now retains meaningful query parameters while removing tracking parameters; overlapping article IDs/exact duplicate URLs/titles still reject duplicates. Legacy claims are compared against their frozen sources.
- Completed feed popups reuse the fit-to-viewport image viewer. Production status is in the right editor column for both AI-complete and photo layouts. Version selection, thumbnails, preview, zoom and download use explicit attempt/hash URLs, with loading/error states instead of a stale image.
- Selected-news script generation was omitted from the operating request/key scope. Only the existing exact route is added; invalid auth/CSRF/Origin/consent/rank and unrelated paths remain blocked. Completed requests reuse saved results; failed calls are not automatically replayed. No new POST route was introduced.
- Existing successful-collection cleanup already deletes unused old articles and preserves content-linked ones. It now also preserves article references in feed batches before a publishing image post exists. Empty/failed collection protections remain. No live collection or article deletion was performed.
- Home workspace omitted feed-batch images even though the library included them. Home now uses the same visible image projection with correct batch/rank destination; library aggregation stays unchanged to avoid duplicates. Deleted items remain hidden.

## Validation

| Scope | PASS | FAIL | ERROR | SKIP |
|---|---:|---:|---:|---:|
| Feed selection, completed feeds, scoped news script, curation | 50 | 0 | 0 | 0 |
| Cleanup/content preservation, library/home linkage, image posts | 48 | 0 | 0 | 0 |
| Connections, API settings, metadata checks, image budget | 133 | 0 | 0 | 0 |
| Isolated browser: versions, popup sizes, right status, image intent/linkage | 8 | 0 | 0 | 0 |
| Frontend contracts | 58 | 0 | 0 | 0 |
| tools/studio_v3/tests | 58 | 0 | 0 | 0 |

Total 355 PASS; TypeScript and Vite production build also passed. A Starlette test-client deprecation warning remains. No full regression rerun. Earlier browser test-harness failures (route interception and implicit-label selector) were corrected; the final 8 browser checks pass, including actual pixel changes and zero POST requests. No assertion was removed or skipped.

Commands, from newsflow-ai with temporary test profiles and existing FFmpeg:

```text
python -m pytest -q -rs tests/test_top_three_selection.py tests/test_complete_feed.py tests/test_news_analysis_access.py tests/test_curation_all.py
python -m pytest -q -rs tests/test_workspace_cleanup.py tests/test_feed_library_edit_connections.py tests/test_image_posts.py
python -m pytest -q -rs tests/test_provider_connection_tests.py tests/test_api_settings.py tests/test_api_connection.py tests/test_feed_budget.py
python -m pytest -q -rs tests/test_feed_versions_browser.py tests/test_image_new_work_browser.py tests/test_feed_connections_browser.py
python -m pytest -q -rs tools/studio_v3/tests
node --test tests/*.test.mjs
tsc --noEmit
vite build --configLoader runner
```

Browser evidence uses generated solid-color fixtures, never private user images. Old/latest pixel colors, current-attempt URL refresh, popup bounds at 1366x768, 900x600 and 390x650, and right-column placement at 1600 pixels were checked.

## Preservation and operating application

No content restoration, real analysis, generation, SNS, key changes or migrations are included. Deployment status and hash/table preservation evidence are recorded separately after the authorized normal Stop/Start. Original/backup and user media hashes are kept locally in protected rollback evidence, not committed. CI was not represented as run by these local checks.
