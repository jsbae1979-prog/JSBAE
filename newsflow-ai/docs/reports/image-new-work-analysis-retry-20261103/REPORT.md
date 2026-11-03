# Image creation UX and explicit analysis retry

## Changes
- Standalone image studio: New image action clears the input/selection only; preserves old drafts/results; selects the newly saved draft. Optional short text is included in the saved generation prompt, not a separate paid call. Model settings remain selected.
- Result click and recent-image click open a viewport-contained modal with Escape, close, save and focus restoration.
- Image generation uses one explicit consent checkbox mapped to both existing consent/reviewed backend fields. Existing stored budget, local authentication, CSRF and provider checks remain.
- Definite completed analysis failures expose a confirmation to make one new request. Exact previous failed run ID is checked under the existing file lock. Old claim/history and run remain. Running/unknown/timeouts do not become retryable; repeated successful submissions return the existing result. A new failure requires a new confirmation.
- No new POST route. Both action registries include the optional retry run ID, hidden from user input.

## Validation (Windows Python 3.14.7, synthetic data/Fake providers only)
- `python -m pytest -q -rs tests/test_analysis_confirmed_retry.py tests/test_analysis_progress.py tests/test_news_analysis_access.py tests/test_standalone_image_access.py tests/test_google_news_trends.py`: 63 PASS.
- `python -m pytest -q -rs tests/test_analysis_retry_boundary.py`: 1 PASS, operating auth wrapper + Fake Claude schema failure and confirmed retry.
- `python -m pytest -q -rs tools/studio_v3/tests`: 58 PASS, separate invocation to avoid their existing conftest name collision.
- `python -m pytest -q -rs tests/test_request_progress_browser.py tests/test_image_new_work_browser.py`: 6 PASS, isolated headless Chrome, no external requests.
- `node --test tests/*.test.mjs`: 53 PASS, 0 FAIL/SKIP.
- TypeScript typecheck and Vite build: PASS. Existing font resolution/bundle-size warnings remain; operating font is retained.
- Total: 181 PASS / 0 FAIL / 0 ERROR / 0 SKIP in final runs. No full regression repeated.

Initial validation found the existing VM extractors needed the changed submit signature, a terminal-render type branch, a mock-browser pending-request teardown, and separate test-conftest invocation. These were corrected without deleting safety assertions. The Claude-only retry boundary fixture explicitly selects Claude.

## Limitations
No paid request was made. AI rendering of Korean text still requires user review. Retry does not repair a provider's malformed response or guarantee the next response. Old operating failure records and costs are preserved. Operating verification is recorded separately after deployment.
