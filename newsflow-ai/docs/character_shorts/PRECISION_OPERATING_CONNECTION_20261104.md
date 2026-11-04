# Precision production connection — 2026-11-04

Base: c944e732b07e98a639ac71c6770ab816647992f6.
Branch: codex/newsflow-character-scene-images-20261104.

## Implementation

- Reuse AuthoringAI, APIBudgetService, ImageStudio/ImageGenerationService, catalog snapshots, current-user DPAPI stores and LocalAccess. No startup provider requests or environment-key fallback.
- Connect only authenticated precision story/image POSTs, bound to work/revision, approved quote, exact draft, prompt, reference versions, account scope and budget. Preserve CSRF/Origin, unknown-outcome reservations and no automatic replay.
- Preserve each scene/version and charge exposure. Stop the remaining batch when returned usage exceeds its reserved estimate; local recovery restores known usage without another provider request. Estimates are not a vendor billing guarantee.
- Hand the confirmed still images to the existing Kling quote and submit adapters, with one exact image per scene. Preserve multi-character motion prompts and supported precision durations, including the 26-second fixture.
- Correct an existing fast-mode request check to use the job's continuity policy, matching the actual authoring instruction. No new routes or frontend design changes.

Changed product files: character/precision.py; character/service.py; gui/character_precision_routes.py.
Changed controller files: precision_access.py (new); windows_live.py; character_quote_only.py; character_manual_execution.py; character_authoring.py.
Tests: test_precision_operating_access.py (new); test_character_precision.py; test_character_operating_authoring.py.

## Focused evidence

Windows Python 3.14.7; synthetic profiles, Fake keys/transports, local browser. No live AI/SNS calls.

1. `python -m pytest -q -rs tests/test_precision_operating_access.py tests/test_character_precision.py tests/test_precision_operating_bridge.py tests/test_character_operating_authoring.py tests/test_standalone_image_access.py`: **106 PASS, 0 FAIL, 0 ERROR, 0 SKIP**.
2. Separate process (different conftest scope): `python -m pytest -q -rs tools/bat_distribution/tests/test_character_quote_only.py tools/bat_distribution/tests/test_character_manual_execution.py`: **49 PASS, 0 FAIL, 0 ERROR, 0 SKIP**.
3. After the final recovery-cost addition: `python -m pytest -q -rs tests/test_precision_operating_access.py::test_usage_above_reserved_estimate_stops_remaining_batch tests/test_precision_operating_access.py::test_local_reconciliation_restores_observed_cost_without_another_request`: **2 PASS, 0 FAIL, 0 ERROR, 0 SKIP**. One is a rerun, one newly added. These totals must not be represented as 157 unique tests.

The initial combined invocation had two conftest import errors; separate app/controller runs resolve the test-runner collision. The initial app group had 102 PASS/3 FAIL. All three failures reproduced on the base source (baseline subset: 1 PASS/3 FAIL): a catalog test passed None instead of an HTTP request; an old auth test incorrectly expected automatic expiry after 24 hours; the fast-mode adapter omitted continuity policy. Test inputs now reflect real requests and current non-expiring verification policy, including missing/future rejection and valid older authentication. The fast-mode instruction comparison is corrected, not disabled.

The synthetic EP01 uses two fixture characters and 5 scenes (5+5+6+5+5 seconds), references per scene 1/2/2/1/2. It checks isolated generation, selected regeneration, approval preservation, confirmation, five exact video-reference uploads, five quotes and five Fake submits. Also covers unauthorized calls, changed budget/account/reference, duplicate fields, prompt/quote tampering, unknown outcomes and a browser screen with an enabled story action and zero automatic requests.

## Limits

Existing frontend build/layout evidence reused; no unrelated full regression. TestClient reports an existing httpx deprecation warning. No actual provider compatibility, billing, image/video quality or continuity quality is established by Fake tests. Actual image/story/video generation requires user approval and normal saved budget/reference consent. No push, merge, SNS publish or external distribution is part of this report.
