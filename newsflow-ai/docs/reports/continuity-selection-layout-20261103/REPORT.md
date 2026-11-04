# Collection recommendation, video continuity and studio selection/layout — 2026-11-03

Base: `7e3bb05730c765afed5952b12d51add09067d612`; branch `codex/newsflow-character-shorts-automation-20261030`.

## Changes
- Category RSS pools feeds within each category, filters the chosen period, deduplicates and ranks **before storage**. SerpApi uses the same local selection. At most 30 per category; fewer valid candidates remain fewer, with no older backfill. Default all-category UI passes the eight explicit categories. Registered RSS/global paths remain distinct. Existing rows are not retroactively deleted by this change.
- The score reuses recency, multiple publishers, topic importance and video/domestic relevance. This is a transparent heuristic recommendation, **not measured search/view popularity**. Missing dates remain unknown. Raw candidates, selected counts, exclusion reasons and ranking evidence are separate.
- New short-scene jobs with first-frame support freeze `single_incident_v1`. All subsequent scene requests depend on the preceding clip's last frame and previous action; location, weather, props and movement continuity are explicit. Legacy quotes, jobs and received clips stay unchanged. Actual AI visual consistency still requires user review; existing teleportation cannot be repaired by merely joining clips.
- Local captions use short timed bold hook/beat/payoff styling, contrast outline and brief motion. The classic preset remains supported. Existing final MP4s are not overwritten; new AI-written captions improve only future stories.
- New successful image backgrounds are shown instead of silently retaining the previous saved edit background. Existing versions remain saved, and local edits record the generation they target. Existing job reuse is labeled honestly; history is collapsed and latest completed analysis is preferred.
- Cost UI retains estimate, budget and approval behavior; repeated pricing paragraphs are collapsed. No approval/unknown-outcome restrictions are bypassed.
- News preview requires a real selected draft ID. Two absent IDs can no longer match a character video.
- Character numbered step headers and panels share grid tracks/gaps. Video previews fill their allocated columns without cropping or distortion. Synthetic browser checks cover 1366 and 1920 widths.

## Validation
- full-python: 92 PASS / 0 FAIL / 0 ERROR / 0 SKIP
- studio-v3: 58 PASS / 0 FAIL / 0 ERROR / 0 SKIP
- top3-tools: 25 PASS / 0 FAIL / 0 ERROR / 0 SKIP
- frontend-contracts: 48 PASS / 0 FAIL / 0 ERROR / 0 SKIP
- React build and TypeScript type check PASS. Test commands are preserved alongside this report.
- A validation attempt stalled in the Windows asyncio loopback test-client initialization before app work. Only that test process was stopped; the same suite completed with normal local test networking. No security exception was added.
- Earlier failures exposed a legacy `story_format=None` case and test locators/implicit job selection; these were corrected. The final tests use the explicit synthetic job and preserve approval/expired-quote assertions.
- Focused suite finished 91 PASS / 1 FAIL (the preview-width assertion compared outer border width to inner width). The test now checks usable inner width, and the 2-test browser follow-up passes. Aggregated Python counts count each test once, taking the last result. Preview height cap was also removed and the frontend rebuilt.
- No full regression repeat: previous full-suite evidence is reused for unrelated code. These results do not establish real provider output quality, actual collection ranking, billing, or SNS publishing.

## Preservation and scope
Development uses Fake providers and temporary data. No real collection, AI generation or SNS request is sent. No original DB, generated media, saved image version, credential or backup is committed. Existing unrelated local changes are excluded. Operating application result is recorded separately after normal Stop/Start.

## Operating application
- Applied source `0481821cc7efe309ebb8365d4e85adb7ca506a05` to 17 exact program/static-asset files, with no pre-existing operating overlays detected.
- Normal Stop completed; Start performed once. Server listens on 127.0.0.1:18768; Chrome launch accepted. User-visible Chrome inspection is left to the user; development layout checks used isolated synthetic Chromium.
- All SQLite tables were compared by row hashes and counts before/after; unchanged. A consistent private SQLite backup and prior program-file copies were retained locally. Credential/media/profile file hashes unchanged except expected local session/start-stop markers. Original DB and A/B backup hashes unchanged.
- Existing job JSON, received clips, final videos, image versions, API keys and settings were not edited. No paid request, live collection, or SNS call performed. No deletion, external distribution or merge.
- Existing jumps/captions in previously saved videos remain unchanged. Continuity policy affects new eligible jobs; revised caption rendering applies when a local composition is explicitly performed.
