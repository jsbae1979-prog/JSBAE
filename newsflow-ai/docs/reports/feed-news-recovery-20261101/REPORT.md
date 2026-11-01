# TOP 3 recovery, cost status and news analysis connection

Development base: f8c99ca962494ea3c2f887d5dda59694a91545a3.

## Changes

- Restore running/unknown image items only from exactly matching, locally saved terminal evidence with valid output files. Preserve attempt history, reservations and old results. Never replay a provider request to recover.
- Allow a failed/completed item to prepare a new quote locally even after quote expiry. Preserve prior outputs and keep actual generation behind separate current cost approval. Unknown/in-flight work still prevents new attempts.
- Cost status refresh is a read-only GET. Refreshing a valid unchanged quote preserves approval and reservations; expiry or changed binding requires new approval.
- Production image readiness uses cached OpenAI key/model verification only. No key decryption/network on status reads. This is PARTIAL: a verified provider/account-bound total cost ceiling is not available, so actual TOP 3 image generation remains blocked. Public token rates are not a guaranteed per-image cap.
- News collection analysis 403: the operating wrapper lacked an authenticated route/credential connection for POST /news/curation/analyze. Add that exact route with request-scoped current-profile DPAPI access, selected Claude/OpenAI provider, current collection, consent, existing per-request budget and durable no-replay claim. Other generation/search/publication routes are not granted by this change. No automatic analysis.

## Focused validation

- 46 PASS: recovery/evidence ambiguity, preserved cost approval, expiry/regeneration, key/model readiness and exact news analysis authorization (Fake providers).
- 21 PASS: synthetic browser and related news analysis/voice behavior. The new browser test initially used a wrong dialog name; corrected test selector and reran it successfully. Remaining 20 passed unchanged. Both 1366x768 and 1920x1080 checked for horizontal overflow.
- 15 PASS: operating request boundary suite, executed separately because combining both test roots selects the wrong conftest.
- Total unique final results: 82 PASS / 0 FAIL / 0 ERROR. Initial fixture failures and test-root collection errors were resolved; they are not product failures or counted as additional passes.
- TypeScript and React production build PASS. Existing font-resolution/chunk-size warnings remain.
- No paid AI, actual news collection/analysis, OAuth, SNS or content deletion was executed. No full regression/Guard/design audit repeated.

## Sources and remaining constraint

Official sources reviewed 2026-11-01:
- https://developers.openai.com/api/docs/models/gpt-image-2.5-flare
- https://developers.openai.com/api/docs/guides/image-generation
- https://developers.openai.com/api/reference/resources/images/methods/generate

Published Flare token rates (text input $5/million, image output $30/million) and image calculator estimates do not constitute a verified total request cap. No guaranteed quote/cap contract was established in this review. No claim of production image-generation completion is made.

## Preservation and acceptance

No migrations, sample assets, source data, paid provider records, keys or media are intentionally edited. Existing unrelated local changes are excluded from this commit. Deployment and actual Chrome observations are recorded separately after application.

Final implementation assessment: CONDITIONAL. Local recovery, quote preparation, cost-status preservation and the exact news-analysis connection are implemented and tested with Fake providers. Actual paid provider success/billing remains NOT VERIFIED, and production TOP 3 image cost integration remains incomplete.

## Changed files

- `frontend/src/studio/FeedCostReview.tsx`
- `frontend/src/studio/TopThreeFeeds.tsx`
- `frontend/src/studio/core/TopThreeImageStudio.tsx`
- `src/newsflow/creation/feed_costs.py`
- `src/newsflow/creation/feed_readiness.py`
- `src/newsflow/creation/top_three_feeds.py`
- `src/newsflow/gui/creation_routes.py`
- `src/newsflow/gui/curation_routes.py`
- `src/newsflow/main.py`
- `tools/bat_distribution/operation.py`
- `tools/bat_distribution/windows_live.py`
- `tools/bat_distribution/news_analysis_access.py`
- `tests/test_top_three_selection.py`
- `tests/test_feed_recovery_improvements.py`
- `tests/test_feed_cost_review_browser.py`
- `tests/test_news_analysis_access.py`
