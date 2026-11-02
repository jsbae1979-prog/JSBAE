# Failed-scene quote connection — 2026-11-03

Base: b1c7e4f46541bd194f2a951752db90760e3a8e8a.

The existing Chrome retry-quote action returned a local HTTP 403 before reaching the supplier. The normal operating request wrapper only connected submit/check/diagnose. The service and both action registries already contained retry-quote.

Minimal change: connect that exact authenticated POST to CharacterService.prepare_retry. The wrapper checks the owned terminal failed receipt, intact plan/reference, episode approval, lack of active/unknown submissions, and any contradictory diagnostic result. Only the exact saved failed payload can be estimated once. The product persists retry_quoting before contact, and a failed quote cannot automatically replay. Existing quote/budget/receipt history is preserved. This change does not enable retry-scene, submission, upload, polling or download in the quote scope.

Focused Windows Python 3.14.7 Fake verification:
`python -m pytest -q -rs tools/bat_distribution/tests/test_character_retry_quote.py tools/bat_distribution/tests/test_character_manual_execution.py tools/bat_distribution/tests/test_character_status_diagnostics.py tools/bat_distribution/tests/test_character_quote_only.py tools/studio_v3/tests`

151 PASS / 0 FAIL / 0 ERROR / 0 SKIP. No real API in tests. No frontend code change; prior successful React build is reused. New tests cover consent/auth/CSRF/Origin, exact payload/receipt preservation, unsafe states, modified reference/plan, timeout no replay and inability to expand quote scope to other external actions.

Operating quote result will be recorded after the one-file overlay and normal Stop/Start. No new paid generation is authorized by this quote preparation.
