# Character registration, storage and preview refinement — 2026-10-30

**ACCEPTED for the requested UI/profile changes and approved operating application.** The user confirmed in the newly opened Chrome that the five required fields, reference-storage status and project-card images display normally. **Paid end-to-end video acceptance remains incomplete:** image analysis failed before a new profile/story/video was produced. No automatic paid retry was performed by this work.

## Source and operation

- Branch: `codex/newsflow-character-shorts-automation-20261030`; existing PR #36 targets `codex/newsflow-bat-distribution-prep`. PR #35/main remain untouched and unmerged.
- Deployed source: `2dcb062058edb12c485e3c65d4e3ad64568af265`.
- Installation: `C:\NewsFlowAI`; 127.0.0.1:18768; final owned Python PID 17700.
- Compact UI: `6990b4e5808f7edb924be2db695c164dd50b7a40`.
- Thumbnails/storage state: `3194494ce35fee38b901a04ae04faf08ed92512a`.
- Five-field contract/diagnostics: `2dcb062058edb12c485e3c65d4e3ad64568af265`.

The first two UI commits were applied without restart. After separate user approval, the server/profile changes were applied with normal Stop exit 0, one Start, and Chrome automatic opening accepted. No additional restart was performed for these changes. Browser automation was unavailable; the user performed and confirmed the Chrome interactions. No alternate control path, cookie copying or token extraction was used.

## Changes

Registration remains a responsive dialog with persistent save/cancel controls, keyboard/focus handling and visible failure feedback. The oversized explanation panel and the three paragraphs explicitly identified by the user were removed. Reference-image storage remains distinct from named character profiles. Long generic errors are replaced by short action-specific errors without suppressing failure.

Character-studio checkboxes now use an 18px native control beside its label; unrelated input styles are unchanged. Topic input and story generation precede collapsed topic/batch/CSV controls. Provider selection, explicit paid consent, episode limits and review requirements remain available.

The actual `myCharacters` list and successful storage receipts determine status: **보관됨**, **아직 보관 안 됨**, or **보관 여부 확인 전** when the newly selected file/historical reference has not yet been classified. Merely uploading an asset or registering profile attributes does not prove image-library storage. Already saved files are reused without duplicate POSTs, selecting another file clears the previous save choice, and unchecking never deletes an existing image.

Library/publishing/analytics cards and home recent-project cards now use the existing authenticated reference endpoint when the thumbnail is absent and kind/id match `character:<32 hex digits>`. They explicitly label the image **참조 이미지**. Final-video URLs, downloads and production status remain unchanged. Invalid/missing references keep their empty state. No new images were generated to fill cards.

Read-only diagnosis found **12 character jobs with 12 existing reference files matching saved hashes**. The blank cards came from absent thumbnail projection plus missing UI fallback, not evidence of deleted images. The existing endpoint still validates owned job/path, file existence and hash. Only its exact URL pattern was added to the frontend media validator; there is no new endpoint or authentication bypass.

## Profile contract

Required: character name, English appearance, personality, recurring setup, characteristic reaction. Missing, empty and whitespace-only values are rejected.

Optional: species, world, fixed English style, supporting-cast metadata and audience. Blank style uses the existing `config/character_studio.yaml` default, not a separate React constant. Blank world stays blank in storage; topic/script instructions may derive a setting from setup without presenting that inference as a supplied character fact. Audience retains its existing general-audience default. Additional metadata and supporting-cast/audience remain collapsed.

Existing explicit profile values and saved episode snapshots are preserved. A profile-only schema makes world optional; image-analysis response validation stays strict. No DB migration, schema-limit relaxation, extra paid inference or multi-character v1 expansion was added.

## Paid analysis observation and limits

At the first read-only observation, one Claude Sonnet 4.6 analysis request had failed with estimated usage cost US$0.013248. A later observation found **three** failed analysis records: US$0.013248, US$0.014223 and US$0.012663 estimated usage, totaling **US$0.040134**. Their combined conservative reservation ceilings total **US$0.855000**. These are not verified vendor invoices. The assistant did not submit additional requests or automatically retry. The user was told to stop further analysis clicks. No new profiles or changed episode jobs were recorded, and this work made no Higgsfield/video-generation request.

Provider usage was received before the app failed in response/envelope/JSON/schema handling. The old registration route returned a generic 409 without persisting the candidate or precise failure field. The exact historical field/format failure is therefore **NOT VERIFIED**; it was not guessed, replayed or treated as success.

The deployed diagnostic improvement returns only reviewed field names and bounded error categories, for example “외형 설명: 글자 수 초과”. It excludes response text, images, prompts, Pydantic input/context, arbitrary field names, keys and tokens. Receipt reset and unsupported-model handling prevent stale prior-request diagnostics. No paid request was used to test this improvement.

## Focused evidence

These are separate executions with overlapping existing tests; do not sum them as unique tests. Development/browser tests use synthetic data and Fake providers.

| Scope | Result |
| --- | --- |
| Registration failures, compact controls and modal behavior | 7 PASS |
| Strict thumbnail URL/type/id contract | 3 PASS |
| Library/home HTTP images, four states, missing images and no POST | 1 PASS |
| Storage status and duplicate-save prevention | 4 PASS |
| Analysis diagnostics, privacy and stale receipt | 8 PASS |
| Optional profile contract | 66 PASS: 21 new + 45 relevant existing |
| Five required fields, minimum save, preserved options, concise errors and modal regression | 5 PASS |
| TypeScript and React production build | PASS |
| Approved operating Stop/Start and preservation checks | PASS |
| User confirmation in visible Chrome | All three requested UI checks normal |

All listed runs had 0 FAIL / 0 ERROR. Prior full Python 3.12 regression (6080 PASS / 4 SKIP), CI and FFmpeg/continuation evidence were reused. Packaging, full regression and Guard audits were not repeated. New Python checks used 3.12; the installed 3.14.7 runtime started the new code normally. This does not claim a new full 3.14 run or OS-DPI certification. Existing build/deprecation warnings remain warnings.

Synthetic screenshots are in `character-profile-modal-20261030`, `character-library-preview-20261030`, and `character-five-fields-20261030` report directories. Before-captures remain in Git history. User screenshots and real character images are not committed.

## Preservation and remaining work

Final application changed four Python files plus the hashed React JS and index: six files. Prior program files/layout were backed up. The private profile backup contained 106 files and was verified before application. Post-start checks preserved **47 DB tables, 169 articles, 105 compared profile files, original DB and backups A/B**, plus launch flags and ACLs. Real API usage records created before this restart remain in the ledger.

Installed Python identity and loopback readiness were confirmed. Local authentication, CSRF, Origin, DPAPI, account separation, scheduler inactivity, manual paid approvals and unsigned-update blocking remain unchanged. No new paid generation, OAuth/SNS request, original-data deletion/merge or public distribution occurred. No credentials, databases, real media, private responses/logs or backup contents are in Git.

Remaining: identify the precise analysis response issue from a future explicitly authorized request using the new safe feedback; check the official video quote/billing within the approved budget; complete human review of generated scene continuity. UI acceptance does not certify a completed paid video.
