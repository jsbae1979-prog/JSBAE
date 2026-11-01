# TOP 3 image generation and progress display

User authorized three images with an app work budget of USD0.14. The visible Chrome workflow saved that exact budget and submitted one sequential generation run. All three items completed; provider-response usage calculation displayed USD0.041570. Actual invoice billing is separate. No retry, SNS action, or additional generation was performed.

The core React layout omitted the controller's existing runningRank. Added a scoped progress panel above the results: current TOP item, success count, completed-item percentage, spinner, and distinct completed/paused/failed/unknown states. Cards now show the currently submitted item as running. Stopping visibly waits for the current response; no in-flight request cancellation or replay was added. Budget-only actions no longer show a generation stop control.

Changed files: TopThreeFeeds.tsx, core/TopThreeImageStudio.tsx, core/FeedGenerationProgress.tsx, core/feed-generation-progress.css, tests/feed-generation-progress.test.cjs.

Validation: eight synthetic progress-state tests PASS; TypeScript PASS; production React build PASS. Initial test harness failed because TypeScript7 lacks the older transpileModule API; harness uses the project's existing native type-strip pattern and final tests passed. No paid calls were made for the UI fix. No Python, database, credential, provider, reservation, or retry logic changed. Full regression was not repeated per user scope.

Progress means completed images (0/3, 1/3, 2/3, 3/3), not invented provider-internal percentage or time remaining. Generated files remain local and are not committed.
