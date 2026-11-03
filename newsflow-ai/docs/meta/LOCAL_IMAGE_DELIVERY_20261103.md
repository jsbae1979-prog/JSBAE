# Local Instagram image delivery — 2026-11-03

Branch: `codex/newsflow-character-shorts-automation-20261030`.
Base: `63fbbd96bc088aa71bce3bb2ebe91e76d319fea7`.

## Result and boundaries

Implemented an optional local JPEG delivery path, not a new Instagram binary-upload API. The existing Instagram `image_url` container and final publication flow remain unchanged. No external file-storage account is required by this new path, but a third-party HTTPS tunnel carries the image traffic. It is not an offline/direct socket connection to Meta.

The development implementation is complete with Fake and local-loopback verification. Operational availability is **CONDITIONAL**: the optional official `cloudflared.exe` has not been installed/provisioned; no real Quick Tunnel, Meta fetch, upload, or publication has been tested. No operating application deployment/restart took place. Existing database, keys, settings, media, backup and unrelated local source changes were not modified.

## Implementation

- `src/newsflow/meta/local_images.py`: immutable in-memory copies of explicitly approved JPEGs only. Random 256-bit capability paths; exact GET/HEAD routes; no directory listing, operational API, filesystem route or upload endpoint. Maximum 8 MB per JPEG and eight images per session. Session expires after one hour. Repeat fetches during that window are allowed for Meta processing; tokens are not consumed by a HEAD/probe. No access-log output. URL capabilities are not stored in the settings database or returned to the settings UI.
- `local_image_tunnel.py`: optional helper executable with an explicitly provisioned SHA-256; no PATH search, download, installer, automatic update, admin elevation, firewall changes or service registration. Separate IPv4 loopback-only HTTP listener, fixed selected port, Windows exclusive bind, no port fallback. Isolated empty helper configuration and minimal child environment exclude application/provider secrets. Helper diagnostics are privately drained. Startup is bounded; no automatic reconnection. Normal cleanup addresses only the owned helper and listener, never processes found by name. A helper that does not exit is reported as unknown rather than successful termination.
- `local_delivery.py`: owner-scoped persisted opt-in and port. Settings/status reads never open a tunnel or read credentials. Candidate media must be inside that owner's data root, without symlink/junction traversal; byte hash must match the reviewed file. Public HTTPS GET must return matching bytes before the existing Meta container POST. A failed local path never silently falls back to another storage provider.
- `media.py`, `publishing.py`, `routes.py`: integrate the optional mode into the existing per-owner publication lock, explicit send consent, durable state machine and final publication approval. Missing tools cannot mark transmission ready. Failed/unknown submissions are not replayed. Existing Facebook/reel direct transfer and S3 delivery remain available as before.
- `tools/bat_distribution/windows_live.py`: constructs the optional helper factory from the installation and closes local delivery on normal application shutdown. `meta_access.py` forwards only the exact local configuration path to existing LocalAccess/Origin/CSRF checks.
- `frontend/src/studio/management/MetaAccounts.tsx`, `MetaPublishPanel.tsx`: optional, collapsed “이 PC에서 이미지 전달 · 시험 연결”; truthful missing-tool status, explicit port choice, no disclosure of capability URLs, transmission/PC-uptime explanation. No file is exposed by saving settings.
- New POST `/api/meta/local-images` is registered in both `src/newsflow/studio/actions.json` and `frontend/src/legacy-actions.json`.

## Windows Python 3.14.7 verification

All files and accounts were synthetic. The actual tunnel executable was never run; helper-process behavior used a Fake process. The image HTTP test used loopback only.

| Command / check | PASS | FAIL | ERROR | SKIP |
| --- | ---: | ---: | ---: | ---: |
| `python -m pytest -q -rs tests/test_meta_local_images.py tests/test_meta_accounts.py tests/test_meta_direct.py tests/test_meta_automatic_upload.py` | 124 | 0 | 0 | 0 |
| `python -m pytest -q -rs tests/test_meta_local_images_browser.py tests/test_meta_automatic_browser.py` | 4 | 0 | 0 | 0 |
| `python -m pytest -q -rs tools/studio_v3/tests` | 58 | 0 | 0 | 0 |
| `node --test tests/*.test.mjs` from the project root | 48 | 0 | 0 | 0 |

Total: 234 PASS, not a full-regression or real-provider claim. `tsc --noEmit`, React build, new-file Ruff and diff whitespace checks passed. Existing font/bundle/deprecation warnings remain. The initial JavaScript invocation from `frontend/` found zero tests; it was corrected to the project root and is not counted as a successful test run.

New tests cover settings without exposure, unavailable tooling, protected ports, capability expiry/revocation, exact GET/HEAD behavior, no listing/API/POST, JPEG/hash/size failures, owner isolation, CSRF/Origin checks, selected-target container creation, separate final publication, no retransmit/fallback, helper hash mismatch, fixed-port conflict, filtered child environment, normal cleanup, route registration and browser settings/port persistence.

## Provisioning and real verification still required

1. Obtain the official Windows AMD64 cloudflared release and license/provenance, verify its publisher/materials, and explicitly register `tools/cloudflared.exe` and its hash in the existing installation inventory. Set `app/layout.json` `localImageTunnelSha256` to that reviewed hash. A hash match alone does not prove publisher identity. No binary or installation manifest was changed in this work.
2. Deploy the reviewed program changes using the existing protected operating procedure. The setting remains off by default; no application profile is silently enabled.
3. In a separately authorized synthetic external test, verify the selected fixed port, actual helper command compatibility, temporary public HTTPS byte fetch and expiry/normal-stop cleanup. Fake tests do not establish any of these Internet/Windows-helper results.
4. Separately authorize a specific image/account for Meta container processing and, independently, final publication. Keep the PC/app online until media processing completes. Closing the app invalidates local image delivery; a new start does not restore or automatically resubmit old publications.

Cloudflare describes Quick Tunnels as account/domain-free temporary URLs for testing/development, with changing hostnames and no uptime guarantee. Therefore this implementation must not be presented as an unattended production publishing service. Official reference: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

Implementation command flags were also compared with the official source: https://github.com/cloudflare/cloudflared/blob/master/cmd/cloudflared/tunnel/cmd.go . No authenticated Meta request, paid generation, news collection, user-file upload or SNS publication occurred.

## UI simplification follow-up

The local delivery settings are now a compact card: title, trial badge, current status and one enable/disable button. Port configuration and transport limitations are collapsed under “연결 설정 · 안내”. Port saving is separate from enabling delivery; it does not expose files. The actual local transport, approval checks and unknown-result behavior are unchanged. An enabled mode can be disabled even if its optional tool is no longer available.

Validation: 4 isolated browser tests PASS, 0 FAIL / ERROR / SKIP; desktop and narrow viewport screenshots checked. Tests verify missing-tool disabled state, collapsed details, explicit port persistence without enabling, and no bridge/Meta call on settings actions. TypeScript and React build PASS. Prior backend/route evidence is reused rather than counted again. Operating installation, user data and external connections were not changed.
