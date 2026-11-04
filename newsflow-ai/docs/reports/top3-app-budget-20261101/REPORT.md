# TOP 3 OpenAI app-budget connection — 2026-11-01

Previous fix d3a4620 was pushed before this change. User explicitly approved estimated application budgeting, not a provider-enforced invoice cap. No real paid request was made.

## Behavior

- The existing image catalog/model/size/quality and frozen Korean news content drive an offline estimate. Official direct-image text input and image output rates are used; prompt UTF-8 bytes are an input-token estimate. The image output calculator is an estimate, not a guarantee.
- UI displays the estimate, a disclosed 2x planning reserve rounded upward to cents, and the user's per-work USD budget. Prior requests are included within this work; there is no program-wide lifetime budget.
- A stored current-key/model check is required. A quote binds the model, credential revision, article/content, batch/rank/attempt and expires within one hour. Prices expire 2026-12-01 until explicitly refreshed from official evidence.
- The current-profile key is available only inside an authenticated, Origin/CSRF-protected exact batch step with a persisted budget reservation. Other generation endpoints and general credential decryption remain closed. No environment-key fallback.
- One image is submitted per step, n=1. No automatic paid retry. Missing/malformed usage, failed/uncertain outcome, or cost above the planned reserve stops subsequent images. Overrun is included in exposure; actual invoices are never marked verified by the app.
- Existing results and failed request evidence remain. Matching saved successful output and usage can be recovered locally without a new provider request.

## Changed scope

Production wiring: main.py, bat_distribution/windows_live.py, new feed_image_access.py.
Budget services: new image_pricing.py and feed_budget.py; feed_costs.py, feed_readiness.py, top_three_feeds.py.
React: FeedCostReview.tsx, TopThreeFeeds.tsx, core/TopThreeImageStudio.tsx.
Focused tests: test_image_pricing.py, test_feed_budget.py, test_feed_budget_browser.py, existing readiness assertions in test_feed_recovery_improvements.py.
No migrations, source DBs, keys, user media, existing backups or main/PR #35 were changed by development/testing. Unrelated pre-existing local changes were excluded from this commit.

## Validation

90 distinct focused tests PASS / 0 FAIL / 0 ERROR (86 initial tests, then 25 after final guard/test additions; overlap counted once). All external generation and metadata responses were Fake, with isolated DB and Fake DPAPI.
Includes actual Images adapter wire format, key/model/content binding, request approval, budget rejection, missing usage, timeout, known HTTP failure, over-reserve stop, preserved output recovery, no unrelated endpoint opening, React approval and two viewports (1366x768 / 1920x1080) in headless Chrome.
TypeScript and Vite build PASS. Existing warnings: static font resolved at runtime, bundle size and lucide module directives; no new build errors. No claim of operating Chrome visual verification or real OpenAI billing compatibility.
Existing broad regression evidence reused; no full regression, packaging rebuild or Guard audit repeated. Python 3.14 not rerun in this change.

## Official basis and limitations

- https://developers.openai.com/api/docs/guides/image-generation
- https://developers.openai.com/api/docs/models/gpt-image-2.5-flare
- https://developers.openai.com/api/reference/resources/images/methods/generate

Public documentation/calculator reviewed 2026-11-01. No real credential/model lookup repeated. The direct Images API has no per-request USD charge cap; actual cost can exceed an estimate, even with the reserve. Model metadata visibility does not guarantee actual generation permission. Real generation and invoice verification remain untested and require separate user approval.

Implementation/Fake validation: ACCEPTED. Real paid generation/billing: NOT VERIFIED. Overall readiness for live use: CONDITIONAL.


## Operating application result

Code b8a3979 applied as 11 exact program/React files, preserving the installation's existing launch overlays and policy flags. Existing profile backup was verified before applying. Normal Stop exit 0 and Start each executed once; owned process and port 18768 responded. Normal launcher reported Chrome auto-open accepted. No bootstrap/cookie was printed or copied. Unauthenticated HTTP remained 403 as required.

All 47 operating DB tables and current 86 articles were unchanged. 373 non-session profile files were preserved (374-file backup); original 169-article source and backups A/B matched their existing hashes. Credentials, media, launch flags and ACLs were preserved. No paid AI or SNS call occurred. Operating Chrome visual inspection was NOT VERIFIED in this turn; the isolated headless Chrome UI checks above passed. No main/PR #35 merge or external distribution.
