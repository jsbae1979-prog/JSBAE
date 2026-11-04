# News collection categories and feed image connections

## Changes
- News Studio: collection categories are now visible on the collection panel, separate from the stored-article filter. RSS/SerpApi confirmation receives the selected scope. No collection executes on selection.
- Library: completed TOP 3 images are projected individually, preferring verified saved photo-edit versions. A matching review copy is not duplicated. Missing/pending media is not reported as generated. Exact batch/rank links reopen the intended image, including older batches.
- Editor: selecting a distinct background updates the local preview and credit automatically, retaining unsaved text/layout. Identical background bytes/kind/credit are grouped; historical background IDs and saved versions remain usable. Applying/error status is visible beside the preview, and saving waits for the preview to finish.
- Recent images: individual/multiple selection, confirmation and reversible removal through the existing library API. Gallery/library/review-copy visibility remains consistent; Library Trash restores the item. Shared feed originals are protected from permanent purge. No actual user content was deleted.
- All preview/export edits remain local. Paid generation, publishing and collection are not executed. No new POST route or approval bypass was introduced.

## Verification
- 163 distinct targeted cases PASS, final FAIL 0 / ERROR 0. Includes 58 studio_v3 cases run directly and separately; previous unrelated PASS evidence is not included.
- TypeScript and React build PASS. Windows headless Chrome against a synthetic local server; external requests blocked. Operating Chrome is left for the user's manual check.
- Earlier intermediate failures: optional trash-field compatibility, a missing publisher in a synthetic fixture, and a minimal view fixture without the optional TOP 3 service. Corrected and the affected cases rerun. A build invocation with an unsupported CLI argument was corrected; final build succeeded.
- Verified background pixels change without saving/regeneration, exact TOP/rank navigation, no autosave on edits, deletion cancellation, multi-delete/restore, original hashes/state preservation, invalid identifiers/CSRF, valid saved-version preference and no implicit publishing candidates.
- `focused-results.json` contains final per-case results; captures are synthetic, not user media.

## Preservation and limits
- No migrations, credentials, existing content, user DB rows or API budget settings changed by development/testing. Existing uncommitted changes left untouched.
- Reversible feed deletion hides results; it does not destroy shared originals or financial/audit history.
- A different edit version can reuse the same background. Use “저장된 편집 버전” for its complete text/layout, and “배경 이미지” for image replacement.
- Existing 24-hour news filter and TOP 3 ranking logic unchanged.
- Operating application outcome will be recorded separately after the single normal Stop/Start.
