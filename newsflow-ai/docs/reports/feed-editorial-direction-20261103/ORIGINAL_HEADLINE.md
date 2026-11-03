# Feed headline originality revision 3 — 2026-11-03

## Reason and change
Live comparison images from the preceding user-approved experiment still copied the opening clause (TOP 2) or essentially the complete source title (TOP 3). The image API did not reliably obey the broad rewrite instruction. This change strengthens the instruction; it does not claim pixel-level or legal validation.

`creation/complete_feed.py` creates revision-3 plans. Within the same image request the model must extract supported facts, consider three alternative headlines, reject verbatim titles/opening-clause extracts/synonym-only rewrites, choose an independently structured headline, and add one supported detail in the explanation. Proper names, numbers, attribution and uncertainty must be preserved. Questions are optional, and a pending event cannot become a completed event. Synthetic examples are explicitly excluded as sources of article facts. No new text API, OCR, automatic paid retries or extra image requests are added.

Revision-2 and older saved prompts stay unchanged. Only a newly created plan or explicit regeneration uses revision 3. User-supplied exact-copy edits bypass the new rewrite instruction. Existing article data, caption drafts, images and history are untouched. No claim that paraphrasing establishes copyright permission is made. Real-person likeness instructions remain in place, but the prior live comparison shows instructions alone cannot ensure accurate real photos. No additional live generation was performed for this revision.

## Validation
Windows Python 3.14.7, synthetic profiles, Fake providers, no real keys or external calls.

Command: `python -m pytest -q -rs` with the eight focused test files (`test_complete_feed_original_copy`, `test_complete_feed_editorial`, `test_complete_feed`, `test_feed_image_budget_settings`, `test_feed_budget`, `test_feed_costs`, `test_feed_new_background`, `test_insta_feed_safety`). First run: 97 PASS / 0 FAIL / 1 ERROR / 0 SKIP, caused by a missing fixture import in the new test module. After importing the existing fixture, all five new tests passed. Combined unique final result: 98 PASS / 0 FAIL / 0 ERROR / 0 SKIP. Existing httpx/Starlette deprecation warning remains.

New coverage: two synthetic article inputs; immutable revision-2 instruction and payload; exact user copy; one Fake call per generated image; explicit regeneration upgrades only the selected plan, changes the budget binding, retains old images/history and leaves other ranks unchanged; viewing and completed steps do not trigger another request.

No frontend or POST-route changes; existing frontend build and studio route evidence reused. Full repository regression not repeated. Actual quality of newly generated pixels remains NOT VERIFIED until a separately requested live comparison. Existing comparison images were not regenerated or edited.
