# Korean news image titles / immutable local corrections

Scope: Korean, untruncated headlines; remove ordinal badges/hashtags from output images; Instagram image posts at 1080x1350 (4:5). User corrected the Reels request to image posting. No MP4 or paid regeneration.

Root cause: content_for retained English source titles and excerpted them to 60 characters before dispatch. Generated text was burned into the image. New batches use complete stored Korean titles or complete Korean summary sentences. No translation API or invented translation. If no suitable Korean copy exists, preparation remains editable and dispatch preflight requires a Korean title <=100 characters before a reservation/provider call.

New versioned header layout: API leaves the top 260 pixels of the final layout blank; local Korean typography wraps at word boundaries and shrinks within a readable range without ellipsis. No rank badges/TOP labels in new image prompts. Cost estimation uses the same prompt and includes the layout in the binding; legacy request prompts/bindings remain unchanged.

Local retitle creates a separately named, hash-verified derivative with original content/file history. Completed jobs expose a free title editor only when the header geometry is known. Legacy images require explicit visual verification of header bounds; no automatic masking guesses. Publishing review saves the exact verified derivative, with separate source/generation binding checks and unchanged review/rights gates. Existing posts remain immutable. Cache-Control no-store prevents stale title images.

Prepared three local correction previews for work #53 using visually inspected header and hashtag bands. Original generated/result images are retained. No raw image, DB, key or profile file is committed.

Validation: focused title/service/budget/publishing tests 89 PASS before the final word-wrap/budget binding refinements; the final refinements are covered by additional targeted tests recorded below. TypeScript and production React build PASS. Initial new HTTP test caught the missing retitle action in the local-operation dispatcher; only that local action was added, retaining CSRF/Origin and paid-generation boundaries. No full regression, paid request, news collection, SNS call or merge.

Final targeted title/budget verification: 60 PASS (including 19 title tests). Prior unaffected publishing/selection checks are reused; counts are not additive. No paid calls occurred.

## Operating result — 2026-11-01

Applied implementation commit 4eb6f4227fba863215e09c8f6a0384192e896815 using the exact 10-file deployment plan. Deployment backup preserved 380 non-session profile files, all 47 database tables, the original 169-article database and backups A/B. A subsequent normal Stop (exit 0) / Start restored Chrome authentication; no force termination or policy change. The current live database has 86 articles; it is distinct from the preserved historical original.

Work 53: created three separate 1080x1350 JPEG derivatives, replacing only visually inspected headline and ordinal-hashtag areas. All three original JPEG hashes are unchanged. Only work 53 result/revision changed; other rows/tables, generation IDs, attempts, options, budget and provider evidence remained identical. Original result metadata is retained privately for recovery. No additional provider requests or SNS calls.

Chrome verification: authenticated app navigation to News image posts displays 3/3 complete, all three full Korean titles, original-preserved/no-extra-cost messages, free title editors and download links. Actual image pixels contain no ordinal badges or TOP hashtags. Navigation rank labels remain to identify each news result. Private screenshots and per-file SHA-256 evidence are kept locally, not uploaded with user media.

Free local correction checks: three preview/output hash matches, three unchanged original hashes, unrelated database rows unchanged, budget/evidence unchanged, Chrome rendering verified. Existing focused 60 PASS, prior 89 PASS, TypeScript and React build evidence reused (overlapping counts, not additive). New paid generation with the changed prompt was intentionally NOT VERIFIED. No automatic publication or source-fact verification is claimed.

## Individual images and publishing selection — 2026-11-01

Implementation 79ba209: recent feed history displays each successful image as a separate 4:5 card. Clicking a result or history card opens a large-image dialog, with previous/next navigation, close and download. Batch/rank selection also updates the caption panel. Files: frontend/src/studio/core/FeedImagePreview.tsx, core/feed-image-gallery.css, core/TopThreeImageStudio.tsx, management/Publishing.tsx.

Publishing root cause: kind/search filters changed the candidate list but selectedProject resolved from the unfiltered list. The editor retained a character video and its metadata under an empty image filter. Selection, drafts, review controls and platform eligibility now use the same filtered list; a hidden selection clears the form and presents an empty preview. This does not create publishing drafts or alter content data. Feed images need the existing publishing-review save action before becoming publishing candidates.

New verification: TypeScript noEmit PASS; production React build PASS. Actual authenticated Windows Chrome confirmed three individual history cards, second-image popup and rank-2 file binding, next-image rank-3 popup and file binding, close, and result-card popup. Publishing image-filter check cleared the old video/editor/platforms; returning to character restored matching content. Local screenshots retained under character_automation_operating/feed-gallery-static-20261101. Keyboard Escape was not counted because browser observation changed during that check. No paid generation, publishing, or content deletion.

Operating UI overlay uses base 4eb6f42 plus these four UI files only. Frontend entry hash: 83711f9f8f1bd9d57f6b924a50c4a834ada503068a7be6a0d47f70efdfb14dc1. Assets and layout manifest were backed up and atomically updated; no additional server restart or data changes for this UI overlay. Remote cb697a7/fda2128 were merged into development after a non-fast-forward push rejection, but their unrelated changes and pre-existing dirty edits were not deployed. Source commit and operating full-package base are deliberately distinguished.

Copyright/source: attribution alone does not provide reuse rights. Existing source and AI-image disclosures were retained; this change does not certify rights or fact-check source articles. Reference: https://www.newstore.or.kr/store/faq/selectFaqList.do?cpright=10
