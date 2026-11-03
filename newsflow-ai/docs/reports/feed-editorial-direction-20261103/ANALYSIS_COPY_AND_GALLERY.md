# TOP 3 feed copy and image selection — 2026-11-03

New TOP 3 analyses now produce Korean feed titles and short explanations in the existing analysis request. Original article titles, summaries, scripts, saved analyses and previous images remain unchanged. Image requests use these exact strings and the earlier image-led dark navy/charcoal, white type, warm orange accent design. The image model handles composition and typography rather than another rewrite of the facts.

## Implementation
- `intelligence/feed_copy.py`: versioned same-call instructions and bounded strict copy schema.
- `intelligence/curation.py`, `service.py`, `api_providers.py`: new TOP 3 contract/schema, group-specific numeric validation, Claude wire output; old TOP 3/TOP 10 contracts remain readable.
- `publishing/image_selection.py`, `creation/top_three_feeds.py`: independent copy retained per rank and frozen into image jobs; existing script text does not override it.
- `creation/complete_feed.py`: revision 4 exact analysis-copy design, exact manual edits. Existing revisions 1–3 stay unchanged.
- `frontend/src/studio/core/FeedImageHistory.tsx`, `feed-image-gallery.css`: checkbox placed over each image, selected border, removed the separate per-card selection/delete row. Shared selection/delete/confirmation/trash restore retained; no real image deleted.

## Verification
Windows Python 3.14.7, isolated profiles and Fake providers only. No paid API, collection, OAuth or SNS request.
- Focused run: 209 PASS / 1 FAIL; failure was a test expectation omitting the existing `dispatch_state=sent_or_unknown` field already present at base HEAD `bea17139dbb25a069b311e104e7a21544bc40a0d`. Expected result now explicitly checks it without weakening diagnostics.
- Affected numeric suite recheck: 34 PASS / 0 FAIL.
- Browser integration: 4 PASS. Overlay lies inside image bounds, selecting does not open preview, cancelled deletion sends no removal request, synthetic selected deletion/restore preserves media, refresh failure is not treated as failed deletion.
- `tools/studio_v3/tests`: 58 PASS.
- Latest result per unique test: **272 PASS / 0 FAIL / 0 ERROR / 0 SKIP**. Rechecks are not counted twice.
- TypeScript and Vite build: PASS. Clean build includes HEAD plus these two frontend edits; unrelated local edits excluded.
- Initial run (202 PASS / 8 FAIL) exposed outdated fake response fixtures and two new test setup errors. Fixtures were updated to the versioned contract, not by relaxing production validation. Final outcomes above supersede these failures.

Commands used existing interpreter with `python -m pytest -q -rs --tb=short`, explicit isolated basetemp and JUnit output, targeting `test_analysis_feed_copy`, TOP 3 curation/diagnostic/numeric/wire/grounding, google/global news fixtures, image selection, complete-feed/budget suites. Browser target: `test_feed_connections_browser.py test_complete_feed_editorial_browser.py`. Studio target: `--confcutdir tools/studio_v3/tests tools/studio_v3/tests`. Build: `tsc --noEmit`, `vite build --configLoader runner`.

## Preserved boundaries and limits
- No extra copy-generation request; same analysis call has a larger response, so token cost can change within existing budget controls.
- Tests prove data propagation and instructions, not actual AI typography, originality, legal clearance or artistic quality. Real output requires a later explicitly authorized generation and review.
- Old analyses without `feed_copy` continue the old path; no automatic reanalysis or regeneration. Existing image job reservations/prompts remain frozen.
- No migrations, new POST endpoints, settings or cost/consent gate changes. No operating user content deleted. Deployment evidence appended after normal Stop/Start.

## Operating application
Applied code commit 563e7586da5521c9622260da50ef53de7f39f20f, 10 changed program/bundle files, after private rollback backup and active-work check. Normal Stop/Start once succeeded, loopback port 18768, Chrome launch accepted. All database table fingerprints, protected profile file hashes, original and backup hashes unchanged. No paid calls, SNS, real content deletion, reanalysis or regeneration. User-visible operating screen appearance awaits user confirmation; isolated browser checks above passed.
