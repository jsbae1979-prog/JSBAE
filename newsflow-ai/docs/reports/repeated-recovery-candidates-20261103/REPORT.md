# Saved story recovery and bounded news analysis

Base: 8773464339ee49e0efba1bb4b8d225034d5a789d. Windows Python 3.14.7. No paid generation, collection, authentication, or publishing requests were made.

## Causes and changes

- A complete paid story response contained the selected Korean character name inside English action/camera fields. Revalidating the unchanged response repeatedly hit the same pattern error. Resolve only the exact selected proper name to `the character`, keep the original provider response and billing receipts unchanged, and retain every schema/timing check. Other Korean prose and unrelated names still fail. The writing instruction now requests this English alias. Recovery errors expose bounded field reasons, never raw provider exceptions.
- The latest collection had 651 eligible articles, exceeding the 400-article analysis contract before a run or provider call was created. The durable curation claim then blocked future clicks as duplicates even though nothing was sent.
- Analyze at most 30 latest articles per category (including a bounded unclassified bucket), with the candidate count disclosed before consent. This is a deterministic local shortlist, NOT a claimed popularity TOP 30. The final TOP 3 formula remains responsible for ranking. Collection/lifecycle files and stored articles are unchanged. Current read-only selection: seven categories, 210 candidates from 651 articles.
- Keep the existing request identity so a completed or unknown old request cannot be bypassed by selection changes. A failed preflight with no run, or an explicitly recorded `not_sent` failed run, permits a subsequent consented request. Preserve all previous attempts in history. No automatic loop, paid replay, or unknown-outcome retry was added.

## Validation

- Focused Python: 116 PASS / 0 FAIL / 0 ERROR / 0 SKIP. Includes new selected-name isolation, retained raw response, zero-call recovery, category bounds, deterministic selection, preflight history and unknown/in-flight replay rejection.
- Frontend contracts: 48 PASS. TypeScript and React build: PASS (existing bundle-size/font-resolution warnings only).
- Direct tools/studio_v3/tests: 58 PASS. tools/feed_top3/tests: 25 PASS.
- A private isolated copy of the real saved response recovered to script_review: five scenes, 19.5 s against the existing 20 s target. No timing stretching, AI translation or provider calls. Original file hashes unchanged.
- Initial test run: 69 PASS / 4 FAIL from new synthetic fixtures missing the required IntelligenceRun.message field; fixture corrected, final focused run above passed.
- Existing complete-program regression evidence at 8773464 reused; no full-suite rerun or live provider quality claim.

Commands use the existing Python environment and isolated temporary APPDATA/LOCALAPPDATA/TEMP; the focused command was `python -m pytest -q -rs --tb=short` for test_repeated_failure_recovery, test_curation_all, test_episode_saved_candidate, test_character_episode_schema, test_character_story_preflight, test_google_news_trends, test_character_episode_recovery, test_news_analysis_access. Frontend: tsc --noEmit, vite build, node --test tests/*.test.mjs. Route suites run directly with their own confcutdir.

## Limits

Provider errors after dispatch still require result/billing review; generic automatic paid retries are intentionally not enabled. Local candidate selection uses recency rather than paid scoring. No articles are deleted or restored. No new POST endpoints, migration, security relaxation, main merge, or UI redesign.

## Operating result

Code commit: a3c44c951032e94c3f1e88437d0d1d9b6002f799, pushed to codex/newsflow-character-shorts-automation-20261030.

Applied 13 exact program/static files; no operating overlays were overwritten. At the final deployment check the server was running, so one normal Stop and one Start were performed. Normal Chrome launch was accepted; port 18768 is listening. Saved response recovered locally to script_review without paid replay, and the original response, reference image and cost history remain preserved.

All DB table contents match the pre-deployment snapshot. Original/backup A/B hashes, launch settings, keys and other profile files remain unchanged; only the intended recovered job and normal session lifecycle files changed. A consistent SQLite backup, this job's rollback files, changed program-file backups and private hash inventories are retained locally. No bulk duplicate media backup was created.

The user was asked to confirm the visible story and 651→210 candidate count in Chrome; visual confirmation remains pending. No analysis, collection, paid generation, SNS request or merge was executed. Private input, database, token, media and rollback copies are excluded from Git.
