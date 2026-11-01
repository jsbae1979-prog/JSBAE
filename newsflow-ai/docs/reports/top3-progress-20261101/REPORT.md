# TOP 3 image generation and progress display

User authorized three images with an app work budget of USD0.14. The visible Chrome workflow saved that exact budget and submitted one sequential generation run. All three items completed; provider-response usage calculation displayed USD0.041570. Actual invoice billing is separate. No retry, SNS action, or additional generation was performed.

The core React layout omitted the controller's existing runningRank. Added a scoped progress panel above the results: current TOP item, success count, completed-item percentage, spinner, and distinct completed/paused/failed/unknown states. Cards now show the currently submitted item as running. Stopping visibly waits for the current response; no in-flight request cancellation or replay was added. Budget-only actions no longer show a generation stop control.

Changed files: TopThreeFeeds.tsx, core/TopThreeImageStudio.tsx, core/FeedGenerationProgress.tsx, core/feed-generation-progress.css, tests/feed-generation-progress.test.cjs.

Validation: eight synthetic progress-state tests PASS; TypeScript PASS; production React build PASS. Initial test harness failed because TypeScript7 lacks the older transpileModule API; harness uses the project's existing native type-strip pattern and final tests passed. No paid calls were made for the UI fix. No Python, database, credential, provider, reservation, or retry logic changed. Full regression was not repeated per user scope.

Progress means completed images (0/3, 1/3, 2/3, 3/3), not invented provider-internal percentage or time remaining. Generated files remain local and are not committed.

## Operating deployment and visible Chrome verification

Deployed the three built static assets at code commit 3ad4e62414c2881aab007dc51d2079e95699dc22 without restarting the server. Preserved all 47 database tables, the launch configuration and session record; PID unchanged and previous static assets retained for recovery.

The user's Chrome showed work #53 / analysis #42, all three successful result images and the accessible progress panel reading 3/3 complete / 100%. Selected TOP 1, 2 and 3 to inspect their result details. TOP 3's English headline is shortened in its rendered image and needs editorial review before publication; no paid regeneration or publishing was performed. User acceptance of the image content is still pending.

Local-only screenshot: C:/Codex/NewsFlowAI/character_automation_operating/top3-progress-static-20261101/results.jpg. Deployment evidence is retained in the same local directory. No operating data, credentials or generated media are uploaded to GitHub.
