# AI image creation, recent gallery and curation recency — 2026-11-04

## Result
337 focused tests pass; TypeScript and Vite build pass. No paid API, news collection, SNS, or real-content deletion was executed. Library UI is unchanged per the user's correction.

## Changes
- AI image new work accepts a prompt without a mandatory reference attachment. A local JSON draft response binds the confirmation to the exact new draft. Creating a draft does not dispatch the image provider.
- The image request defaults to generating short Korean copy and visual design together. Manual exact copy and no-copy remain selectable. This is one image prompt, not another text-provider call.
- Standalone recent images reuse the news gallery's checkbox, select all, deselect, and selected-delete confirmation. Existing authenticated, CSRF-protected trash API is reused; originals and generation records remain intact. Image draft reads exclude trash markers before limiting rows. Restore makes the result visible again.
- Analysis #95 was recorded as `curation_recency` failure. The original model response was not retained, so its exact offending numeric value cannot be recovered. Code comparison reproduced the mismatch between AI-assigned recency and the existing richest-summary representative rule. New flagged Claude five-component requests omit model-generated recency and use the same frozen source-derived value as strict validation; unknown remains null. Legacy/global validation and other scoring, grounding and coverage rules stay intact. Existing failed records are unchanged; no analysis was re-requested.

## Verification
- Curation and related boundaries: 167 PASS.
- Image preparation, authentication, trash/restore and existing library boundaries: 52 PASS.
- Browser tests with local fake responses: 5 PASS. Prompt entry without attachment, compact single consent, popup, checkbox isolation, select/deselect, cancel, exact image identity, deletion failure/no retry, reload persistence verified.
- Frontend contracts: 55 PASS. Auto/manual/no-copy prompt contracts included.
- studio_v3: 58 PASS.
- TypeScript and isolated Vite build pass.
- Existing timeout test failures reproduced on HEAD (8 PASS/4 FAIL). Their route fixture still expected 81 after the existing 30-per-category shortlist produced 31; only that count and unique-ID assertion were aligned. Separate 81-article transport tests still pass.
- Browser mock cleanup now waits for route handlers before closing contexts; no assertion or safety checks removed.

## Limits
No real image quality or external provider reliability claim is made by fake tests. Old analysis response cannot be reconstructed. Operating application validation is recorded separately after exact-file deployment. No schema migration, credential change, original-media deletion, or library UI redesign.
