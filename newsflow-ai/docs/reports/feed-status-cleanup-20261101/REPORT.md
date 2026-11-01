# Feed editor status cleanup — 2026-11-01

Scope: frontend only; existing image dimensions, popup, credits, approvals and immutable image versions remain unchanged.

- Opening a saved version no longer marks it unsaved. Duplicate export is disabled until an edit occurs. Editing immediately clears the stale saved-version download link; preview still updates locally.
- An acknowledged recent-image deletion remains acknowledged if refreshing the list fails. The item remains hidden and the message asks only for a list refresh. No mutation retry is issued. Unknown deletion responses retain their original protection.
- Collapsed manual performance records are loaded only when expanded, once per mounted result. Loading/failure is distinguished from an empty record list. Existing records are retained.

## New validation

Windows Python 3.12: 6 synthetic Chrome browser tests PASS; `tools/studio_v3/tests` directly executed separately: 58 PASS. TypeScript and React build PASS. 0 FAIL / 0 ERROR.

Browser tests cover old-version viewing without a POST, edit/download state, latest-preview response order, exact saved pixels, rank isolation, no duplicate performance lookup, successful deletion followed by failed refresh, restoration, and preservation of original synthetic image files. External browser requests are blocked. No operating data or real provider requests are used.

Existing broader regression evidence was reused. Existing unrelated local changes were not staged. Operating application is applied as a static frontend overlay, with deployment evidence recorded separately. No restart, collection, paid generation, SNS action or actual content deletion is required. User-visible Chrome verification remains manual.
