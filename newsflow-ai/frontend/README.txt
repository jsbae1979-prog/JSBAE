NewsFlow AI Studio v3 — first implementation checkpoint

Implemented: React + TypeScript + Vite dashboard and content-creation home. CSS tokens and Lucide icons follow the selected master. Existing Python engine remains in place. `/studio/dashboard`, `/studio/create`, read-only `/api/studio/workspace` are added only in this development branch.

Build with the pinned package manager/lockfile:
  pnpm install --frozen-lockfile
  pnpm run build
The FastAPI mount uses frontend/dist when present. No existing Jinja route is removed. Full engine startup validation is still blocked by the test-only native DLL boundary; do not deploy this branch.

Visual fixture preview:
  tools/studio_v3/visual_preview.py serves built React and explicit synthetic JSON on127.0.0.1:18765 only.
  Requires NEWSFLOW_VISUAL_ROOT and the already-reviewed test Guard/config in that separate directory. No operating profile, keys or external requests.
  This server is not the Python product engine. Legacy creation endpoints are deliberately disabled via absent legacyAvailable capability.
  Frontend still supports both distinct image workflows; no Carousel or new image provider is added.

Browser tests:
  frontend/tests/visual.cjs requires NEWSFLOW_VISUAL_ROOT and NEWSFLOW_PLAYWRIGHT_PACKAGE plus the reviewed Node boundary preload/config.
  Temporary USERPROFILE must contain AppData/Local and AppData/Roaming; both environment paths must match those folders.
  Browser request routing, fixed local proxy/resolver and executable hash checks stay enabled. Browser background traffic is not claimed to have OS firewall isolation.

Read-model tests:
  python -m pytest -q --confcutdir tools/studio_v3/tests tools/studio_v3/tests
  Tests use in-memory synthetic SQLite and deny network/subprocess. Do not import the operating app or use its data.
  Locally7 direct-function assertions pass under Guard; pytest console startup was blocked by a native symbol check. Windows Actions runs the scoped tests on its disposable runner.

No actual API key is part of frontend assets or bundle. API configured and API verified are separate states. Missing/failed/unknown files do not receive production demo art or automatic replay. Paid execution, retry, external-voice approval and final SNS approval remain in the existing engine.

Not complete: other10 screen groups, production data connection, write commands, actual file playback through the new UI, full engine startup/legacy bridges, real Windows DPI, full regression, signed EXE and live-account tests.

Reference/provenance and visual comparison: docs/design/studio-v3.0/implementation.
Official build guidance: https://react.dev/learn/build-a-react-app-from-scratch and https://vite.dev/guide/.