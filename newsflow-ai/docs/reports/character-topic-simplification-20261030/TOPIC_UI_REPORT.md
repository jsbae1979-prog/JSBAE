# Character topic panel simplification — 2026-10-30

The topic panel now separates choosing one story topic from batch production. Its default expanded view contains topic count/generation with explicit paid consent, a compact saved-topic list, current-topic selection and manual topic saving. Batch checkboxes, status editing, saved queues and CSV import are under a closed advanced section; batch and queue controls also remain closed until the user opens them.

Only `frontend/src/studio/core/CharacterAutomation.tsx` (CharacterTopics) and scoped rules in `character-studio.css` change product behavior. Character registration, image-analysis prompt/schema, story editing/regeneration, Python APIs, storage and saved records are unchanged. The user's instruction not to change the character-analysis behavior is preserved.

Queue state labels are Korean, and work buttons display topic text instead of internal identifiers. `produced` is labeled 영상 완료 rather than implying an SNS post. Quote approval fields appear when a queue's scripts have matching quotes; the existing cost/consent checks remain. Already approved execution is labeled 승인한 영상 이어서 제작 because this action may submit the next paid video; it is not described as a read-only status check. Blocked queues show their jobs for review and no resume/approval action. No new execution capability, provider request, automatic retry or global task lock was added.

Changing character or queue clears stale consent. Creating another batch clears the previous video approval inputs, and a newly returned queue appears immediately in the saved-queue selector. Single topic selection only fills the story topic; it does not create a batch or submit an API request. API failures remain visible with the failed action named.

Focused verification uses isolated synthetic profiles and Fake providers: compact selection/manual save/profile separation; explicit-consent topic generation; advanced status/batch/CSV/quote controls, blocked queue handling and new queue visibility. Two existing UI checks cover pending-request controls and compact layout. Screenshots cover 1920×1080 and 1366×768. The exact results and applied hashes are recorded in SAFE_EVIDENCE.json. Prior broader validation is reused; no full regression, packaging, Guard audit or paid supplier test is repeated.

Operating application uses the existing frontend-only procedure: back up the old index/layout, install immutable hashed JS/CSS first, then atomically switch the index, and keep old assets for rollback. No process is stopped or started. User data, launch policy, authentication, cost approvals, original DB and backups A/B remain protected. Operating Chrome refresh confirmation is recorded separately from synthetic browser tests.

No paid AI, OAuth, SNS, unsigned update, external distribution or PR merge is performed. Existing PR #36 remains unmerged; PR #35 and main are untouched.

Final focused results: 3 new tests PASS and 2 existing impact tests PASS, with 0 remaining FAIL/ERROR. TypeScript and React build passed. Initial failures were test-selector/Fake-fixture mismatches, corrected without additional product changes.

Static operating assets applied from commit `8c4d5158567461a6ad9d213177ffe9bef3f05546` without restart. All 47 table fingerprints and 169 article count remained unchanged; original DB and backups A/B matched, and launch/ACL settings were unchanged. The recorded Python process remains present; unauthenticated root returned HTTP 403. The user confirmed the simplified topic screen displays correctly in Chrome. No browser automation or authentication workaround was attempted.
