# Failed-scene quote connection — 2026-11-03

Base: b1c7e4f46541bd194f2a951752db90760e3a8e8a.

The existing Chrome retry-quote action returned a local HTTP 403 before reaching the supplier. The normal operating request wrapper only connected submit/check/diagnose. The service and both action registries already contained retry-quote.

Minimal change: connect that exact authenticated POST to CharacterService.prepare_retry. The wrapper checks the owned terminal failed receipt, intact plan/reference, episode approval, lack of active/unknown submissions, and any contradictory diagnostic result. Only the exact saved failed payload can be estimated once. The product persists retry_quoting before contact, and a failed quote cannot automatically replay. Existing quote/budget/receipt history is preserved. This change does not enable retry-scene, submission, upload, polling or download in the quote scope.

Focused Windows Python 3.14.7 Fake verification:
`python -m pytest -q -rs tools/bat_distribution/tests/test_character_retry_quote.py tools/bat_distribution/tests/test_character_manual_execution.py tools/bat_distribution/tests/test_character_status_diagnostics.py tools/bat_distribution/tests/test_character_quote_only.py tools/studio_v3/tests`

151 PASS / 0 FAIL / 0 ERROR / 0 SKIP. No real API in tests. No frontend code change; prior successful React build is reused. New tests cover consent/auth/CSRF/Origin, exact payload/receipt preservation, unsafe states, modified reference/plan, timeout no replay and inability to expand quote scope to other external actions.

Operating verification completed against code 40cd0cb5fe43bc19d36d44d41f30c17e9f7d7fe2:

- One controller file applied; normal Stop (exit 0) and Start each executed once. Chrome opened successfully on loopback port 18768.
- 49 database tables and 394 current-profile articles unchanged; 428 profile files preserved. The original 169-article source and backups A/B remain unchanged. Security flags remain unchanged.
- User-visible Chrome obtained the official retry quote for failed scene 1 (4 seconds): USD 0.448, at 2026-11-03 07:51:44 KST. This is a scene-only quote, not a new quote for the entire 20-second video. Quote validity is time-limited and must be checked before execution.
- Existing scene records, attempts, budget and cost approvals were compared before/after and remain unchanged. Only the retry quote state was updated to retry_quoted.
- The quote confirmation dialog was displayed without selecting consent boxes or submitting paid generation. No new story generation, media upload, video generation or SNS publication was performed.
- Other failed scenes were not re-quoted in this turn. The existing overall USD 2.240 display is not a fresh full-video retry quote.
- Paid retry-scene remains outside the operating adapter connection implemented here. Paid retry execution is NOT VERIFIED and requires a separately prepared execution connection and explicit approval; this report does not claim it is ready.

Local private evidence: retry-quote-operating-20261103/OPERATING_RESULT.json and chrome-retry-quote.png. Private profile backups and screenshots are not committed.

Verdict: quote-only connection PASS; paid regeneration NOT VERIFIED. Existing unrelated checkout changes were preserved.
