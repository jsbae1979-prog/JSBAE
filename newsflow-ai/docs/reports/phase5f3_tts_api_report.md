# Phase 5F.3 — Korean TTS API integration

## Result and boundary

Azure/Google REST adapters, Korean model choices, DPAPI key registration, protected settings/preview forms, measured sentence captions and conservative durable usage reservations are implemented and tested with injected Fake responses. **Live account-usage/free-entitlement verification is not implemented. Production cloud synthesis and preview therefore remain BLOCKED, even with a saved key and approval.** The connection control performs local configuration checks only and explicitly does not claim a successful live connection. No checkbox, environment setting or local counter can establish verified supplier usage. This is a material remaining limitation, not a verified free API service.

No real Azure/Google/OpenAI/Higgsfield synthesis, authentication exchange, OAuth/SNS, task registration or paid call was made. Heami/offline remain usable. Existing user DB and videos were not used by the new Fake validations; previous read-only SQLite check was `ok`, and both prior MP4s remain present. Dependencies, Python 3.12/3.14 policy, security middleware, TLS/public-DNS pinning and migrations are unchanged.

## Official policy comparison (checked 2026-10-16)

| Service/model | Recurring published free amount | Beyond allowance / conditions |
| --- | --- | --- |
| Azure Neural, F0 | 500,000 characters/month | F0 is a resource tier, not a claim about this user's subscription. Region, availability and quotas require account verification. Current Microsoft terms grant prebuilt Neural output use, including commercial use, to **paid-tier customers only**; F0 must not be advertised as free commercial narration. S0 regional pricing must be checked in the actual account; the public page did not provide a reliable numeric regional quote. |
| Google Standard / WaveNet | 4,000,000 characters/month | Published price beyond allowance: USD 4/million characters. Billing-enabled account/project and applicable model SKU matter. |
| Google Neural2 | 1,000,000 characters/month | USD 16/million beyond allowance. |
| Google Chirp3 HD | 1,000,000 characters/month | USD 30/million beyond allowance. This integration conservatively supports default speed only. |

Sources: [Azure price/F0](https://azure.microsoft.com/en-us/pricing/details/speech/), [Azure limits](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits), [Microsoft current TTS output terms](https://www.microsoft.com/licensing/terms/productoffering/MicrosoftAzure/MCA), [Google model pricing](https://cloud.google.com/text-to-speech/pricing). Google permits output in applications/media subject to its terms and applicable law: [Google basics](https://docs.cloud.google.com/text-to-speech/docs/basics). These statements do not validate the user's license or actual account benefits.

New-customer credits are separate: [Azure](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account) advertises USD 200/30 days; [Google](https://docs.cloud.google.com/free/docs/free-cloud-features) USD 300/90 days for eligible new accounts. Google paid billing accounts automatically charge beyond applicable free usage/credits; its unupgraded Free Trial has separate spending protections and can stop resources. No credit balance was queried or assumed.

## Implementation / reuse

- `video/cloud_tts.py`: Azure SSML REST and Google LINEAR16 REST, closed Korean model/region choices, escaped text, fixed public HTTPS hosts through the existing pinned transport, bounded WAV decoding, sentence/reading-unit PCM intervals and no automatic retry/fallback. [Azure REST](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/rest-text-to-speech), [Google REST](https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize), [Azure voices](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts), [Google voices](https://docs.cloud.google.com/text-to-speech/docs/list-voices-and-types).
- Reuse `AIKeyStore` DPAPI with separate Azure/Google files and entropy. Keys never enter SQLite, rendered pages, URLs or logs.
- Reuse existing SQLite `AppSetting` transactions for settings and a bounded durable ledger; no migration. Record submitted characters, conservative UTF-8/SSML reservation units, estimated upper USD, provider/model, request hash and success/unknown state. These are local records, **not supplier usage or bills**. Unknown results reserve their full estimate; stable job/scene/unit IDs prevent replay after restart. Task/month limits and consent revocation are checked before requests. Verified usage must match provider/model/credential/month and be fresh; missing/stale/error evidence blocks before POST.
- `gui/tts_settings_routes.py`, `templates/tts_settings.html`, existing voices/simple-settings/Video Studio: provider/model/key forms, local connection-readiness check, fixed preview, estimated sample characters/cost, local month totals, approval state and explicit verification warnings. Real-content Studio renders require per-request consent; trial/automatic previews stay local. External errors require manual SAPI selection.
- Earlier Phase 5F.3 sentence timing/contrast/word wrapping is reused. Large screen redesign was not expanded after the new instruction. Existing source images and labelled AI clip composition remain intact. No word-level alignment claim.

## Tests and samples

- Azure/Google Fake contracts, WAV/cue generation, missing/stale/wrong account evidence, plaintext prevention, limits, persistent unknown results, 302/401/403/408/429/500 no replay, free-overflow and approval revocation: 28 focused cases verified across initial and added-test runs. Settings/Studio/voice integration: 76 passed. Ruff passed. Tests were neither deleted nor newly skipped.
- Actual Heami Korean WAV and improved 30.027018-second H.264/AAC 1080x1920 video: `validation-output/phase5f3/final/result.mp4`; numeral/IT sample `final/korean-reading.wav`. Six measured narration cues, full narration preserved, peak at most 24575, non-silent decoded MP4. Chrome playback advanced beyond two seconds with no media error; a visible review preview was opened. Human pronunciation/readability/perceived sync remain **NOT VERIFIED**.
- Fake API -> actual FFmpeg video: `validation-output/phase5f3/fake-cloud/result.mp4`, 30.021354 seconds. Its audio is a synthetic tone, **not Azure/Google Korean speech**. All sample media/captures/temporary DBs remain local, outside Git commits.
- Original/improved frames: `validation-output/phase5f3/before.png`, `final/after-first.png`, `final/after.png`; Chrome capture `final/chrome.png`.
- Earlier rendering-only Actions `38875471972` passed 264 focused cases per Python and native/silent MP4, then found one deterministic screenshot test expecting the old background RGB. The expectation was updated to the intentional new background, retaining its AI-label/security assertions; its focused retest passed. Latest TTS-scope Windows Actions result and implementation SHA will be recorded after the final run.

## Remaining acceptance work

An authenticated, provider-authoritative account usage/free-entitlement verifier is still required before live cloud synthesis can be enabled. Speech API key validity, a voices-list GET, published free amounts or manually entered usage cannot safely substitute for it. Actual authentication/model access/usage/billing, Azure F0 commercial eligibility and neural voice quality are NOT VERIFIED. The current user-facing UI is intentionally explicit about this limitation. User must listen/watch the Heami sample and later separately authorize any real API validation. Phase 5G/6, previous PRs #1–#17 and main remain untouched. Draft PR #18 is reused for this same Phase 5F.3 branch.
