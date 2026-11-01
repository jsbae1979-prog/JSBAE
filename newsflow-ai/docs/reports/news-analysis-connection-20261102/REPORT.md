# Selected article analysis connection — 2026-11-02

## Finding and correction

The screenshot shows the selected-article analysis dialog, not the collection TOP-3 dialog. No new analysis run was persisted after the previously successful analysis #42. The installed request boundary only connected `/news/curation/analyze`; `/ai/analyze` accepted only the offline provider. A selected Claude/OpenAI analysis was therefore denied before reaching the analysis service. The screenshot itself contains no error message, so this is a confirmed reachable code defect, not evidence of a new Claude response failure.

The existing `/ai/analyze` route now uses the scoped operating analysis service for the selected provider. Its wrapper inspects a bounded form and replays the original bytes through unchanged local authentication, Origin and CSRF middleware. The underlying service still requires explicit consent, valid articles, model/settings approval and budget reservation. Only the active request's provider key is accessible. Offline analysis remains offline; script generation and unrelated paths remain outside this connection. No new POST routes were added.

## Collection status clarification

Stored collection #57 requested four categories with a 24-hour period. IT/science stored and retained 98 articles; culture failed with `bad_response`; entertainment and sports were never requested after that failure. Failed/unrequested counts are no longer displayed as successful zero-result searches. Actual successful zero results remain zero. The raw supplier response was not retained, so the exact failing response field is NOT VERIFIED. No retry, new search, allowance expansion or charge claim was made.

## Related feed boundary

The preceding photo-feed simplification remains installed. Synthetic feed outputs remain visible in the library but are excluded from publishing candidates and posting-copy preparation, preserving the existing simulation boundary. Real completed feed images still require explicit rights/source/image-safety review before preparation; publication approval is never set by navigation.

## Focused verification

- 39 PASS: selected analysis operating boundary (Claude/OpenAI success/failure), consent, invalid articles, provider isolation, duplicate-provider input, bounded body, authentication, Origin, CSRF, unrelated-route denial, feed/publishing projection and collection browser states.
- 58 PASS: `tools/studio_v3/tests`, run separately.
- Total: 97 PASS, 0 FAIL, 0 ERROR. Earlier 18-pass subset is not counted again.
- TypeScript and React production build passed. Existing bundle-size/module-directive/font-runtime warnings remain non-fatal.
- Providers and data were synthetic. Browser tests used isolated local Playwright, not the user's Chrome session. No paid API/news collection/SNS calls.
- Existing full-regression evidence is reused; no full Python/Guard/design audit repeated.

## Operating application

Source commit: `e5268ff19c2aee2ac89bb01d5e28a9644f101c47`.
Eight exact program/static files were staged, backed up and applied with manifest hashes. Normal Stop exited 0, Start ran once, Chrome opening was accepted. New PID 31368 listens on the existing loopback port 18768. The local deployment helper initially retained the prior expected commit and stopped before any operating mutation; its comparison was corrected to the committed source before proceeding.

The 47-table database and current 184 articles were unchanged across this restart; 425 non-session files, keys/media/settings ACLs, historical originals and backup A/B were verified preserved. Backup snapshot contains 426 files. Existing user changes since prior verification are preserved; the historic 169-article source is not overwritten. No paid analysis was clicked after deployment. Actual supplier compatibility/charging is not retested.

## Remaining limits

- Culture SerpApi `bad_response` needs more precise safe diagnostics or a separately approved request to identify the response field; no claim of correction to that unknown supplier response.
- The user can inspect the reopened Chrome dialog. No new live analysis success is claimed.
- Existing unrelated local modifications are excluded from the commit. No main/PR merge, external deployment, credentials or user DB/media uploads.
