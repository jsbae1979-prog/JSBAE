# Korean news image titles / immutable local corrections

Scope: Korean, untruncated headlines; remove ordinal badges/hashtags from output images; Instagram image posts at 1080x1350 (4:5). User corrected the Reels request to image posting. No MP4 or paid regeneration.

Root cause: content_for retained English source titles and excerpted them to 60 characters before dispatch. Generated text was burned into the image. New batches use complete stored Korean titles or complete Korean summary sentences. No translation API or invented translation. If no suitable Korean copy exists, preparation remains editable and dispatch preflight requires a Korean title <=100 characters before a reservation/provider call.

New versioned header layout: API leaves the top 260 pixels of the final layout blank; local Korean typography wraps at word boundaries and shrinks within a readable range without ellipsis. No rank badges/TOP labels in new image prompts. Cost estimation uses the same prompt and includes the layout in the binding; legacy request prompts/bindings remain unchanged.

Local retitle creates a separately named, hash-verified derivative with original content/file history. Completed jobs expose a free title editor only when the header geometry is known. Legacy images require explicit visual verification of header bounds; no automatic masking guesses. Publishing review saves the exact verified derivative, with separate source/generation binding checks and unchanged review/rights gates. Existing posts remain immutable. Cache-Control no-store prevents stale title images.

Prepared three local correction previews for work #53 using visually inspected header and hashtag bands. Original generated/result images are retained. No raw image, DB, key or profile file is committed.

Validation: focused title/service/budget/publishing tests 89 PASS before the final word-wrap/budget binding refinements; the final refinements are covered by additional targeted tests recorded below. TypeScript and production React build PASS. Initial new HTTP test caught the missing retitle action in the local-operation dispatcher; only that local action was added, retaining CSRF/Origin and paid-generation boundaries. No full regression, paid request, news collection, SNS call or merge.

Final targeted title/budget verification: 60 PASS (including 19 title tests). Prior unaffected publishing/selection checks are reused; counts are not additive. No paid calls occurred.
