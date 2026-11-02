# News list and analysis connection follow-up — 2026-11-03

Base: c17e63ff1afaf0ba83a3a2e61cb7ec1709833232, branch `codex/newsflow-character-shorts-automation-20261030`.

## Changes

- Reuse the already tested 49382c2 news read-model correction: remove the 100-row cap only for the news article list, retaining hidden-record filtering, and expose collection/unique/overlap/time-filter summary. Apply only those two hunks to the operating overlay.
- Add `frontend/src/studio/AnalysisConnectionCheck.tsx` in the existing selected-article and collection analysis dialogs. An explicit click uses the existing authenticated, CSRF-protected provider metadata check. It clears analysis consent, refreshes the local view and never submits/replays the paid analysis. Provider errors are not echoed verbatim. The 24-hour verification TTL, key/model binding, per-request budget and unknown-result reservations are unchanged.
- No new POST route, migration, key changes, collection or generation. Existing action catalog entries remain unchanged.

## Validation (Windows Python 3.14.7, synthetic profiles/Fake transport only)

- `python -m pytest -q -rs tests/test_analysis_connection_inline.py tests/test_news_list_counts.py tests/test_api_connection.py tests/test_provider_connection_tests.py tests/test_news_analysis_access.py tests/test_meta_direct.py tests/test_meta_automatic_upload.py`: **132 PASS / 0 FAIL / 0 ERROR / 0 SKIP**. Three new browser cases cover Claude success, OpenAI rejection and network failure; opening/checking never posts analysis, consent remains required, raw provider messages are not displayed.
- `python -m pytest -q -rs tools/studio_v3/tests`: **58 PASS / 0 FAIL / 0 ERROR / 0 SKIP**, separately invoked because the two suites import different files named `conftest`. A first combined invocation had 4 collection import errors, resolved by using their independent existing suite contexts; no assertions were removed.
- `node --test tests/*.test.mjs`: **48 PASS / 0 FAIL / 0 SKIP**.
- Frontend `tsc --noEmit`, `vite build`: PASS. Existing bundle/font warnings remain; built index uses `/studio/` asset paths.
- No full regression rerun, real credential test, paid provider call, file upload or SNS publication. These focused results do not establish real-provider acceptance or all-app quality.

## Instagram image direct transmission

Existing implementation uses direct Facebook photo/video and Instagram video transport, and signed external media URLs for Instagram images. Fake direct/upload boundary tests passed above. Do not label Instagram image binary transmission implemented.

Official documentation retrieval on 2026-11-03 was inconclusive: Meta content-publishing and IG-user media pages returned HTTP 429; the Meta-owned Postman collection rendered only its shell. No speculative image binary endpoint or image-to-video workaround was added. Actual image direct-upload support and real Meta acceptance remain NOT VERIFIED. Existing S3-compatible automatic upload remains available only after user configuration/approval; no storage was configured or accessed in this work.

Official reference URLs attempted:
- https://developers.facebook.com/docs/instagram-platform/content-publishing/
- https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/
- https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api

## Operating application

See the follow-up operating result after the approved normal Stop/Start. Preserve current profile, encrypted credentials, media, original source DB and A/B backups. Do not reset unknown paid requests or invoke pending generation.

## Operating result

Applied source `3e61eec0dceca91958e9f250e3cad9dc51e455e0` to four files (the two read-model hunks plus React index/JS/CSS). Installation-only Python overlays and previous assets were preserved. Normal Stop exit 0, one Start, Chrome opened; port 18768, PID 39916 at verification.

Before/after: 49 tables and 394 stored articles unchanged, 429 files backed up, 428 protected profile files checked unchanged apart from normal session/lock artifacts; encrypted keys/media and original/A/B backups preserved. Launch/security flags unchanged. No provider check, paid generation, collection, upload or publication was invoked.

User Chrome showed 372 visible articles (50 initially rendered), collection unique total 372 and cross-category overlap 1. The stored total 394 includes records outside the current visible list; records were not deleted. The new API recheck button was visible, analysis consent unchecked and paid action disabled. The recheck button was not executed on the real provider. Browser left on the news screen. Screenshots and private backup manifests remain local and are not uploaded to GitHub.

Final: implemented/application changes ACCEPTED; real-provider verification and Instagram storage-free image transmission remain NOT VERIFIED. Existing paid scene retry and real SNS publication remain user approval/testing items.
