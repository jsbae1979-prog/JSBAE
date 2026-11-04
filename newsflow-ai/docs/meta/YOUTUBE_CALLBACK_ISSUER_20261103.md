# YouTube callback compatibility — 2026-11-03

## Outcome

Code and operating update completed; actual Google login/channel connection remains NOT VERIFIED pending user interaction. No upload, publishing, paid generation or live OAuth exchange was performed in this work.

- Branch: `codex/newsflow-character-shorts-automation-20261030`
- Tested/deployed code: `7f776a50094c0cf454f7817a9eb4a7627f709dc2`
- Previous source HEAD: `14495da6622de4deb66796527a1a77e287768223`
- Previous operating source: `4011e9e3906666ac9d20ca6c571e68473ccf5962`

## Evidence and limits

The saved YouTube record was not connected, not API-ready, and had no credential reference. Its error was `callback_unknown_field`. The displayed label “YouTube 연결 중” was a saved label, not proof of an active connection.

The callback rejected the optional `iss` field. Google advertises authorization-response issuer support and the exact issuer `https://accounts.google.com` in its [discovery document](https://accounts.google.com/.well-known/openid-configuration). Its [OpenID reference](https://developers.google.com/identity/openid-connect/reference) references the issuer response standard. [RFC 9207](https://www.rfc-editor.org/rfc/rfc9207.html) specifies exact issuer comparison.

A local synthetic callback with the correct issuer reproduced HTTP 400 before the fix (1 FAIL). The historical rejected field was not recorded, so the historical error cannot conclusively be attributed to `iss`. No old callback URL, code, state, cookie or token was recovered or logged.

## Minimal change

- `src/newsflow/oauth/callback.py`: accept optional `iss` only when exactly equal to Google's issuer; add a fixed, non-reflecting rejection reason for mismatches.
- `tests/test_youtube_callback_issuer.py`: 11 synthetic cases covering success, altered issuers, empty/duplicate/unknown fields, wrong state, denial and replay.
- Existing state/PKCE, account/scopes binding, loopback/Host/Origin, request limits, single-use and no-retry protections remain unchanged. Absence of `iss` preserves existing callback compatibility.
- No migration, UI redesign, credential change or new endpoint.

## Local verification

Windows Python 3.14.7, isolated temporary data and Fake providers/local synthetic HTTP only:

```text
python -m pytest -q -rs -o faulthandler_timeout=30 --tb=short -o junit_family=legacy -p no:cacheprovider --basetemp=<isolated-temp> --junitxml=<local-evidence> tests/test_youtube_callback_issuer.py tests/test_oauth_callback.py tests/test_youtube_connection.py tests/test_oauth_operations_flow.py
```

164 PASS / 0 FAIL / 0 ERROR / 0 SKIP, 19.20 seconds. One existing Starlette/httpx deprecation warning. Full regression and unrelated builds were not repeated. These results do not establish real Google account access or publishing readiness.

## Operating application

One callback Python file applied in `C:\NewsFlowAI`, with its layout integrity entry/source updated. Existing overlay and launch/security flags were preserved. Normal Stop returned 0, followed by one Start; Chrome opened normally. New server PID 35304, loopback port 18768.

Before restart/application, 429 profile files were backed up. After restart, 428 protected files and their ACLs were verified; expected launcher/session changes were excluded. All 49 database tables' logical contents and 394 current articles were unchanged. Original dataset and A/B backups retained their hashes. Existing keys/media and unrelated working-tree changes were preserved.

Chrome displayed Settings → YouTube account settings → account connection dialog. The user must complete their Google sign-in and review the requested permissions. Connection remains unverified until that flow succeeds. No login consent, upload or publish action was submitted by the agent.

Private rollback evidence and screenshot remain local under `character_automation_operating/youtube-issuer-operating-20261103`; credentials, database, private backups and screenshots were not committed.
