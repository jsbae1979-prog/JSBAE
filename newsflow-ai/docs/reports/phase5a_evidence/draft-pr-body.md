NewsFlow AI previously required separate collection, AI, video and publishing steps. Phase 5A connects those services into an explicit local workflow with an Easy home screen and guided review steps.

- Durable jobs, stage history and artifact references; cancellation, explicit recovery and duplicate-news protection.
- Default synthetic RSS and offline scripts produce watermarked review MP4s with FFmpeg, independently validate the media and save a local publishing draft.
- Existing human-review flags and production OAuth/SNS blocks remain in force. No real account connection, token issuance, upload or publishing is enabled.
- Additive migration 0008; existing studio routes retained under advanced navigation.

Validation: Cloud full regression 914 passed / 6 skipped / 0 failed (one existing warning). Chromium exercised easy/guided 30-second MP4 creation, actual playback, local queue, script editing, restart persistence, cancellation and responsive layout. Windows Actions run 38666644966 passed: 919 passed / 1 skipped / 0 failed, actual BAT, Chrome, DPAPI, two 30-second MP4s and restart persistence. See docs/reports/phase5a_autopilot_easyui_report.md and its downloadable evidence ZIP.

Scope: only newsflow-ai and its new Windows workflow. Base is feat/newsflow-phase4b2b; main and PRs #1–#7 remain unchanged. Phase 5B and real OAuth/SNS execution are excluded.
