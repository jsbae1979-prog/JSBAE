# Phase 5F.1 — Python 3.14 compatibility

Base: `feat/newsflow-phase5f` / `37597fdd25cd342326df626bd2e1390c62f2c06c`.
Branch: `feat/newsflow-phase5f1`. Status: validation in progress; not an acceptance claim.

## Implementation

- Support exactly Python 3.12 and 3.14; exclude 3.13. Keep Ruff's `py312` syntax baseline.
- Preserve an existing supported `.venv`; otherwise prefer 3.14, then 3.12. Never delete or silently replace an unsupported venv.
- Share interpreter policy and version-sensitive installation fingerprints across launcher, diagnostics and operational readiness.
- Preserve all dependency pins and migrations. Add separate Cloud/Windows 3.12/3.14 CI jobs; create each Windows venv with the matrix interpreter before BAT validation.
- Handle Windows Ctrl+Break like Ctrl+C so Uvicorn's signal replay cannot bypass resource cleanup. Test server cleanup rather than only the venv redirector exit.

## Local Windows 11 / Python 3.14.7

- Dedicated `.venv` created; all existing fixed dependencies installed with Windows native wheels; `pip check` passed.
- Core policy/launcher/wizard/startup tests: 91 passed before the final shutdown lifecycle assertion. Ruff passed.
- Actual `setup.bat` passed. Actual `run.bat`, seven-step wizard, Offline script, 30-second MP4 and installed Google Chrome playback passed.
- MP4: H.264/AAC, 1080x1920, 30 fps, 30.021354 seconds. SQLite integrity and MP4 hashes survived restart. Ctrl+Break cleanup logged `server_stop`.
- Actual scheduler/Chrome validation passed: execution, duplicate protection, restart, no missed-run catch-up. Test-only clock, unchanged production scheduler.
- Operations GUI passed with Fake registration only; no OS task was registered.
- Synthetic current-user DPAPI passed. Production-vault path hardening correctly rejected Codex-package LocalAppData redirection; the same native synthetic validation passed in an unredirected workspace directory without changing any cryptographic/security checks.
- SAPI was blocked by existing PowerShell execution policy. Policy unchanged; silent video used. Human voice/editorial quality and a directly launched, unpackaged user PowerShell session remain NOT VERIFIED.

## Regression and outstanding verification

Full local pytest and Cloud/Windows 3.12/3.14 Actions results will be recorded after completion. Existing skip conditions are retained; no security tests are removed or arbitrarily skipped.

No pre-existing NewsFlow data was found before setup. Generated local SQLite/settings/video are preserved. Codex-launched processes redirect logical LocalAppData into the Codex package's LocalCache; data from this run must not be confused with a separate directly launched user's data folder.

Paid API, OAuth/SNS execution, actual Task Scheduler registration, Python 3.12 MSI retries, main merges and changes to previous PRs: none.

## GitHub

Draft PR, Actions URL and validated code SHA: pending publication. The final checkout SHA is available with `git rev-parse HEAD`; report-only follow-up commits do not change the validated code.
