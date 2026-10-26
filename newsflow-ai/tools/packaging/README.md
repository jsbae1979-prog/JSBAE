# Internal Windows technical bundle (Step 15-A)

This is a synthetic-only engineering artifact, not a consumer release or installer.
The existing product source and engines are included. A separate entry point enforces
a marked synthetic data root and blocks supplier execution. It never selects an existing
NewsFlow profile. Keep the complete onedir folder beside the EXE; it is not a one-file binary.

## Rebuild

Use a separate Windows Python 3.14.7 venv with requirements-dev.lock and PyInstaller==6.22.3.
Run build_technical.py --output NEW_SEPARATE_FOLDER --media-dir TRUSTED_FFMPEG_BIN.
The builder strips inherited provider variables, uses private temporary folders and records hashes.
No EXE is uploaded by the validation workflow.

## Internal execution

The new synthetic root must contain synthetic-only.json with exactly:
{"kind":"NewsFlow-Step15A-SYNTHETIC","port":18765}

Run NewsFlowAI-Technical.exe probe SYNTHETIC_ROOT for TestClient/Fake/real FFmpeg checks,
or serve SYNTHETIC_ROOT for the bundled local server. Use an owning Windows Job supervisor.
The process receives a credential-free environment and no Python directory in PATH.
All outputs go to this root. Never use an operating DB or credential store as input.

The technical media validator reuses the reviewed test Guard parser and allowlist.
File reads are limited to the bundle, explicit EXE archive, synthetic root and Windows runtime.
Writes/SQLite are limited to the synthetic root. External sockets, shell execution and arbitrary
executables are denied. The existing product and test Guard are not globally modified.
Browser inspection uses the existing temporary-profile Playwright boundary independently;
request mocks do not prove OS-wide Chrome background traffic isolation.

## Scope and release gates

Included: Python runtime, existing GUI/engines, HTML/CSS/JS/SVG/WebP, character fonts,
FFmpeg/ffprobe. Node/Chrome are test/browser dependencies, not embedded app runtimes.
Optional Supertonic models/onnxruntime, SAPI voice availability and live provider access
are not proven by FakeTTS. No paid image, voice or video generation is performed.
A clean PC without Python, consumer entry point, installer, signing, antivirus reputation,
license redistribution obligations, multi-user ACLs and update/uninstall/rollback remain
separate approval gates. This artifact must not be distributed to general users.

PyInstaller was selected after an actual Python 3.14.7 build. Nuitka's Python support alone
does not establish this application's build; no redundant second compiler build was run.
