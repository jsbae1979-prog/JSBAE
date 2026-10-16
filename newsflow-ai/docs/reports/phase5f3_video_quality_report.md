# Phase 5F.3 — Korean shorts quality

The user subsequently prioritized Azure/Google API integration in this same phase. See `phase5f3_tts_api_report.md` for the final scope, live-usage verification limitation and latest results. The minimum layout work below is retained; no larger redesign was added.

## Original analysis

Base: `e2904c6335954c7fb71becf02dc4c94c059bcd43` (Phase 5F.2).
Inspected the user-evaluated `video-4594b5e463da4c859f7e58e6d820eb79.mp4` in the existing LocalCache data directory. It exists; SHA256 `f3d01f04487d64e111ba88584e423697936f151d22754636c0ec8735f960b1f3`.

- Original narration used three generic trial-review scenes, not a substantive news report. This phase keeps those raw texts for comparison; it does not invent facts or improve the offline script generator.
- Static captions were scene summaries, not the words being narrated. Only scene boundaries followed measured audio; no sentence timing existed.
- Character-by-character wrapping split Korean words in the title; repeated generic graphics left large unused space.
- FFmpeg silence detection found approximately 3.5-second silent tails between/after scenes and some internal pauses over a second. This detects silence, not exact words or pronunciation errors. Original intermediate WAVs were already cleaned up by the coordinator, so original WAV-level boundaries cannot be recovered exactly.
- Heami pronunciation quality was reported by the user; automation did not listen or independently diagnose individual phonemes.

## Changes

- `video/speech_audio.py`, `video/windows_sapi.py`, `video/tts.py`: synthesize bounded sentence/clause units, preserve numeric tokens, trim only exterior silence with 80ms handles, retain internal pauses, add the selected inter-unit pause, bounded peak gain (maximum 4x, peak at most 24575/32768), return measured PCM intervals. No SSML/user-code execution or PowerShell policy change.
- `video/speech_text.py`: small local IT pronunciation dictionary. Existing date/number/currency/percent rules and raw stored narration stay intact.
- `video/engine.py`: sentence captions use raw narration and actual unit WAV lengths, not character proportions. Blank periods stay blank; scene boundaries retain audio plus a 350ms tail. Overlong audio fails before encoding; it is never truncated or automatically sped up. Word alignment is not claimed. Titles, scene summaries, spoken subtitles and sources are separate; word-aware wrapping, 56px sample captions, contrast panel/outline, numeric emphasis, three selectable palettes, scene progress and a 120ms entry fade reuse Pillow/FFmpeg. Local images and guarded labelled AI clip inputs remain supported.
- `video/service.py`, `gui/video_routes.py`, `gui/templates/video.html`: reuse existing Studio render/re-render and Easy UI voice/setup controls. Studio adds speed/pause selection and closed theme/style choices; save them in existing JSON snapshots, with no migration. Persist measured subtitle cues in the existing subtitle table.
- `tests/test_video_quality.py`, `tests/test_video.py`, `tools/ci_quality_validation.py`, `.github/workflows/newsflow-phase5f3-windows.yml`: focused unit/integration and actual native-render checks.

## Validation

- Local Windows 11 / Python 3.14.7, FFmpeg 9.0.2, Microsoft Heami Desktop: PASS for WAV generation, bounded PCM peaks and a 30.027018-second H.264/AAC 1080x1920 MP4.
- Six measured reading-unit cues: 0–2.769, 3.019–6.984, 10.221–13.865, 14.115–16.023, 19.260–22.225 and 22.475–26.764 seconds. These bound complete synthesized units, including retained handles; they are not phoneme/word timestamps. Video frame quantization and AAC priming can add small offsets; no forced alignment claim.
- All raw narration words appear in the cues in order. Actual decoded MP4 audio has signal. Every scene leaves at least 350ms after its WAV; total is within 0.1 seconds of 30.
- Core suite: 303 passed, 16 pre-existing conditional skips; two subsequently added settings/timed-input tests passed. No test deleted or newly skipped, no full regression repetition. Initial sandbox TEMP errors were environmental; the focused suite passed using an explicit workspace temp directory.
- A first-frame fade issue discovered in decoded screenshots was fixed by placing `fps=30` before fade; only the affected render was repeated. CI checks non-black frames and changed sentence captions.
- Installed Google Chrome (headless decoding test): actual `currentTime > 2`, duration 30.027018, 1080x1920, playing with no media error. Also opened a visible Chrome preview for the user. This is technical playback evidence, not human listening.
- Existing SQLite read-only `quick_check`: `ok`; original MP4 files retained. No dependency, migration, DPAPI, CSRF, SSRF, TLS or external-call policy change. Actual paid AI/OAuth/SNS/Task Scheduler calls: zero.
- Final Windows Actions and validated implementation SHA: pending below; final results will be recorded after the single run.

## Local review material (not committed)

Project-relative directory: `validation-output/phase5f3/`.
- Original screenshot: `before.png`.
- Improved screenshots: `final/after-first.png`, `final/after.png`, `final/chrome.png`.
- Improved video: `final/result.mp4`.
- Korean number/IT WAV: `final/korean-reading.wav`; narration WAVs: `final/scene-000.wav` through `scene-002.wav`.
- Measured cues and metadata: `final/quality.json`; visible local preview: `final/preview.html`.

## Human review / limits

Pronunciation, naturalness, subtitle readability, perceived sync and composition remain **NOT VERIFIED** until the user evaluates this version. Heami's voice model/prosody is unchanged; a future alternate TTS provider requires separate approval and no paid provider was called. Short source scripts still leave reading/review space to reach 30 seconds; this change does not manufacture extra narration. No word-level alignment, LUFS mastering or professional quality certification is claimed. Rate -1 / pause 250ms is a review candidate, not a universal best setting. Extremely long unbroken tokens or oversized captions safely fail instead of being omitted. Source footer density and safe-area fit still need human phone-screen review. Phase 5G/6 and main merge are excluded.
