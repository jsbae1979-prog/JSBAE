# News preview, selected content and character analysis repair — 2026-10-30

**ACCEPTED for these repairs and their approved operating application.** The user confirmed in the newly opened Chrome that news images and selected-library-content navigation both work normally. Character analysis review handling passed Fake tests; no new paid analysis or video generation was submitted. Existing failed requests were not replayed or removed. Paid end-to-end film acceptance remains incomplete.

## Source and scope

- Branch: `codex/newsflow-character-shorts-automation-20261030`.
- Development baseline: `3be8f0eadc87b7152b0a5968f452c70c1d1ea8d5`.
- Species review: `46cbd9f`; selected content: `2843344`; news previews / combined build source: `7b4685964088241859c60f17f66508a5b3f24e14`.
- Existing PR #36 remains unmerged. PR #35 and main were not changed.
- Previous operating source: `2dcb062058edb12c485e3c65d4e3ad64568af265`; applied source: `7b4685964088241859c60f17f66508a5b3f24e14`.
- Operating installation `C:\NewsFlowAI`, port 18768, final owned Python PID 28460.

## News Studio images

Read-only aggregate inspection found **169 articles, 77 stored source-thumbnail records, and 92 articles without source-thumbnail records**. The latest 20 article records all have thumbnail metadata. No article bodies, keys or source URLs were printed or committed. No DB write, collection or external-image fetch was performed by the diagnosis.

The operating BAT request boundary inherited the validation route restriction and rejected `GET /news/{article_id}/thumbnail` before the existing image endpoint could run. The React read model also assigned that URL to every article regardless of stored image metadata. These are separate defects; an absent preview is not evidence of a deleted image.

`OperatingRequests` now delegates only exact GET `/news/[1-9][0-9]*/thumbnail` to the existing inner application. Restored validation mode, HEAD/POST and other paths remain unchanged. LocalAccess, Origin/CSRF, source-DB lookup and the existing HTTPS/DNS-pinning/robots/redirect/raster limits remain in force. A cache miss can perform public source-image and robots GETs, without API keys or paid AI calls. No arbitrary URL parameter, article scraping, paid-provider, OAuth, SNS or collection capability was added.

The news read model returns a thumbnail URL only when a source record exists. News Studio distinguishes loaded images, **출처 이미지 없음**, and **이미지를 불러오지 못했습니다**, with a neutral source/news icon. No fabricated image substitutes for missing source material. A saved URL does not guarantee that its remote source is still accessible. The user confirmed recent news images in operating Chrome after application; this does not certify every one of the 77 remote source URLs.

Changed: `src/newsflow/studio/read_models.py`, `tools/bat_distribution/operation.py`, `frontend/src/studio/core/NewsStudio.tsx`, scoped news rules in `core-studios.css`.

## Selected library content

The library already linked to `/studio/characters?job_id=<selected job>`, but CharacterStudio ignored the query and defaulted to the newest job. It now opens the selected saved reference, topic, story and state. Missing/invalid IDs show an unavailable notice instead of another job. Entry without a selected ID retains the existing latest-job behavior. Library and studio collection limits are compatible; no new detail endpoint was needed.

Changed: `frontend/src/studio/core/CharacterStudio.tsx`. No stored job, card link, generation state or reference file was changed.

## Optional species analysis overflow

The user's latest screenshot identifies `species` (종류) exceeding the existing 40-character response limit. This confirms that displayed failure; it does not reconstruct the older responses, which were not persisted by request ID. Provider response text cannot be recovered after restart, and no recovery or success is claimed for past failed analyses.

The instruction now asks for a short species label without appearance details. If and only if the sole validation failure is species length, the complete original response passes text safety, the species is at most 400 characters, and all other strict fields/candidates validate, the app returns an explicit review draft with species blank. The bounded original remains available in a collapsed review section. The user chooses a candidate and may enter a short species label or leave the optional field blank before saving.

Normal provider and persisted-profile species limits remain 40. There is no silent truncation, auto-save, automatic retry or acceptance of unsafe/extra/other-invalid fields. The original failed usage receipt remains unchanged; the UI presents this as a review draft, not a fully validated provider response. The safe draft is only available in the same response handling, not a historical recovery feature.

Changed: `src/newsflow/character/authoring.py`, `frontend/src/studio/core/CharacterAutomation.tsx`.

Anthropic documents that string `maxLength` is not a supported structured-output constraint; it must still be checked by the application. Reference: [official structured-output limitations](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).

## Focused validation

All new development/browser checks used synthetic data and Fake providers; browser traffic was restricted to the isolated loopback app.

| New scope | PASS | FAIL | ERROR |
| --- | ---: | ---: | ---: |
| Species review backend and HTTP contract | 17 | 0 | 0 |
| Review UI: blank/short species, candidate selection, explicit save | 2 | 0 | 0 |
| Library selected episode navigation | 4 | 0 | 0 |
| News exact route, auth, raster, absent/failing source, cache | 15 | 0 | 0 |
| News Chrome rendering at 1920×1080 and 1366×768 | 1 | 0 | 0 |
| **New tests total** | **39** | **0** | **0** |

Eight existing analysis diagnostic tests were also rechecked: 8 PASS. TypeScript, final combined React build, independent diff review and `git diff --check` passed. Existing font/bundle and Starlette deprecation warnings were not newly introduced. An initial browser-test selector mistake was corrected; the final two review tests passed. These development results are separate from the user's later operating Chrome confirmation.

Prior full Python 3.12 regression, BAT/start-stop, DB, media, packaging and security evidence were reused. No full regression, Guard audit, V3 diagnosis, package regeneration or paid-provider test was repeated. No new Python 3.14 full-suite or OS DPI claim is made.

Synthetic screenshots are preserved in `character-library-navigation-20261030/captures` and `news-source-preview-20261030/captures`. Real user screenshots and character source files are not included.

## Operation and paid-test status

After the user's explicit approval, six exact application files were applied with source/destination hashes; existing operating overlays were preserved using unique diff context. A preliminary port query showed no listener, but the follow-up process check found the recorded owned Python PID 17700 still alive. The existing Stop BAT therefore performed one normal Stop, exit 0; no force termination or extra attempt was used. A verified 106-file profile snapshot and program rollback copies were created before applying files. One Start opened Chrome through the existing normal authentication flow; final owned PID is 28460.

The observed four failed Claude analysis requests have aggregate estimated usage US$0.053022 and conservative reservation ceilings US$1.140000. These are not verified invoices. No new profiles or changed episode jobs were found since the existing baseline. This work made no paid request or retry.

Post-start comparison confirmed 47 DB tables / 169 articles unchanged, 105 compared profile files preserved, source original and backups A/B unchanged, ACLs and launch/security flags preserved. Expected session/browser-launch records changed as part of the normal restart. No key or token was printed or committed. No migration, paid generation, SNS, update, deployment to another user or PR merge occurred.

The user answered **두 항목 모두 정상** when asked to check (1) recent News Studio article images and (2) selecting a library card then opening its matching topic/character in the studio. Browser automation remained unused; no session token/cookie was copied or displayed. New paid image-analysis behavior is intentionally not re-tested against a supplier, and prior failed response bodies remain unrecoverable. No further restart or automatic retry was performed.
