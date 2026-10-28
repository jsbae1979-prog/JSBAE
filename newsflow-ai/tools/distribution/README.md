# Windows private deployment preparation

Internal build and synthetic filesystem retention contracts only. This directory
does not authorize public release, execution against the operating profile,
production migrations, real credentials, paid APIs, or publishing.

## Components

- `newsflow-candidate.spec` / `build_candidate.py`: reuse the reviewed PyInstaller
  6.22.3 onedir layout with Python 3.14.7. Include the reviewed React build,
  runtime resources, sample catalog and pinned FFmpeg/FFprobe. Do not include test
  runners or verification Guard modules. Build output must be a new separate path.
- `app_entry.py`: private frozen entry with pinned bundled-media verification.
  Only the exact SAPI worker operation or the new `newsflow.distribution.launch`
  desktop entry is accepted. The desktop entry uses a protected per-user
  `%LOCALAPPDATA%\NewsFlowAI-Desktop\v1` root, an OS-assigned port excluding 8765,
  and an expiring one-time browser bootstrap outside the existing app CSRF layer.
  Only the SAPI worker has been launched locally. Full first-run testing still
  requires a clean test profile/environment with no real credentials.
- `newsflow-private.iss`: uncompiled per-user Inno Setup definition, lowest
  privileges, no startup/shortcut/run section, no user-data deletion. Selection of
  an installer is provisional until compilation and real lifecycle tests pass.
- `package_contract.py`: inventory, exact payload comparison and an owned synthetic
  filesystem model. The model's staged versions and rollback pointer are **not an
  implementation or test of Inno Setup's update/rollback behavior**.
- `test_install_contract.py`: 13 focused model cases. Two directory names under
  one Windows account do not prove Windows user/SID isolation. Opaque key sentinels
  do not prove native DPAPI encryption/decryption or credential recovery.
- `validate_payload.py`: package inclusion audit, private ZIP, and actual payload
  staging through the model. Never launches the app or installs/registers software.

## Reproduction prerequisites

Use Windows Python **3.14.7**, the existing reviewed PyInstaller **6.22.3** build
runtime, a new private output directory, and media files matching the pins in
`build_candidate.py`. Do not install packages into or modify a retained backup.
The build subprocess receives a restricted environment and new temporary/cache
paths. It never receives application keys or OAuth settings.

From a fresh synthetic workspace, the operations are:

```powershell
# Paths are explicit operator-selected test paths, never operating data.
& $BuildPython -I -B tools/distribution/build_candidate.py --output $NewBuild --media-dir $ReviewedMedia
$env:NEWSFLOW_INSTALL_CONTRACT_WORKSPACE = $NewOwnedTestDirectory
& $Python3147 -B tools/distribution/test_install_contract.py
& $BuildPython -I -B tools/distribution/validate_payload.py --build $NewBuild --workspace $NewStage
```

Do not execute these examples with placeholders or operating paths. The ZIP is an
internal payload, **not a Windows Setup installer**. Hashes establish equality
against a trusted manifest, not publisher identity: signed updates and an
authenticated distribution channel remain release requirements.

## Release gates

See `docs/reports/distribution-gates-20261028/DISTRIBUTION_GATES_REPORT.md` (current) and the retained deployment-preparation report (historical).
Sample redistribution rights, FFmpeg/component license delivery, Windows
cross-user HTTP authorization and ACL proof, signed installer/update behavior,
clean-PC runtime tests and real OS DPI validation remain open.

New focused checks: test_distribution_boundaries.py (ASGI and stub signature contracts), probe_windows_profile.py (new synthetic ACL/DPAPI/ports), probe_voice.py (offline Python/frozen SAPI), private_installer_ci.py (actual Setup only in disposable CI). No real cross-Windows-user or public signing success is implied.
