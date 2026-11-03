# News feed factual copy and real-photo editing — 2026-11-03

## Change

- New `ai_design_v1` plans freeze `editorial_revision: 2` and the source title, summary and references. Within the existing single image request, the model is instructed to write original concise Korean copy from supported facts, rather than render extracted article wording verbatim.
- Preserve attribution, uncertainty, actors, dates, units and event status. Missing/conflicting facts require review. Do not invent chart percentages or decorative statistics. This is an instruction to the model, not an automated factual or copyright certification.
- AI-only artwork uses symbolic objects/illustrative scenery, not fabricated portraits of people named in news or reconstructed incident photographs. Actual rights-cleared photographs can be selected/uploaded through the existing local editor, preserving original pixels and storing separate rendered versions and credits.
- The AI complete-feed panel now opens that existing free photo editor. No new API endpoint or action registry entry was necessary. No automatic fetching of source photographs was added.
- Explicit user copy edits retain exact title/description/line breaks. Historic jobs lacking revision 2 retain their exact prompt and budget binding. Existing generated images and source summaries are not rewritten or regenerated.
- Original text in edit fields remains reference text until the user edits it. Text created inside generated pixels is not claimed to be OCR-synchronized with the caption. Existing caption/source data and publishing review remain intact; review/rewrite the posting caption separately. No additional text-model call was introduced.

## Focused verification

Windows Python 3.14.7, existing virtual environment, synthetic temporary profiles; all external and operating network requests denied by fixtures. Local headless Chrome uses a separate synthetic profile, not the user's authenticated Chrome session.

| Check | PASS | FAIL | SKIP |
|---|---:|---:|---:|
| `python -m pytest -q -rs tests/test_complete_feed_editorial.py tests/test_complete_feed.py tests/test_feed_image_budget_settings.py tests/test_photo_feed_editor.py tests/test_insta_feed_safety.py` | 71 | 0 | 0 |
| `python -m pytest -q -rs --confcutdir tools/studio_v3/tests tools/studio_v3/tests` | 58 | 0 | 0 |
| `python -m pytest -q -rs tests/test_complete_feed_editorial_browser.py` | 1 | 0 | 0 |
| React TypeScript check / Vite production build | PASS | 0 | — |

Seven new tests cover frozen per-news facts, no cross-news mixing, real-person instructions, exact historic prompt compatibility, explicit edited copy, local image preservation/rank isolation, and the actual browser photo-edit/save/reopen workflow. Browser POSTs were exclusively the existing local `/design` endpoint; no generation requests occurred.

The first restricted-host test run stopped after six checks because Windows asyncio's internal socket pair stalled before TestClient initialization; rerunning on the normal host with the same external-network-denying fixtures passed. The initial browser test used the old mounted frontend; the fixture was corrected to mount the clean new build before app initialization, then passed. Neither issue was hidden by skips or product-policy changes.

One existing Starlette/httpx deprecation warning remains. No full unrelated regression, live generation, news collection, OAuth, upload or SNS publishing was run.

## Preserved boundaries and remaining review

- No DB migration, key changes, content deletion, settings/budget relaxation, or automatic retry.
- Existing unrelated working-tree changes were excluded from this commit/build.
- New AI output quality, factual fidelity and literal text require a later approved live generation and human review. Prompt tests do not guarantee future image pixels or legal clearance.
- A real photograph needs a suitable license/permission; being in a news article is not evidence of reuse rights. This implementation does not obtain or certify such permission.
- Existing AI-generated TOP 3 images are preserved; they are not converted into genuine photographs.
