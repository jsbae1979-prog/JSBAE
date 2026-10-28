# Windows 11 local synthetic validation runner

Status: **CONDITIONAL**. The original three startup rejections are resolved.
One diagnostic run and one corrected app/HTTP run were executed on Windows 11
Python 3.14.7. The corrected run recorded no Guard/gate/policy rejection.
12 screen entries, nine decoded sample images, three HTTP sample MP4 playback
sessions, and a draft save/reopen were observed. Full product acceptance is pending.

This is a separate local entry, not a CI runner with its checks removed. No CI
variable is spoofed. Production Guard, installed filelock, product sources,
sample originals, DPAPI, OAuth and approval policies remain unchanged.

## Minimal startup fixes

`runtime_fixes.bounded_import_paths` removes unused search entries outside the
already registered read roots. One stale editable-install source directory was
removed; it was being scanned by Pydantic's optional plugin metadata discovery.
No new file read permission or Pydantic validation bypass is added.

The reviewed, source-hash-pinned `filelock._strict._probe_link_follow_symlinks`
optional capability probe receives NotImplementedError for exactly its throwaway
`Temp/.../probe-source -> probe-link`, `follow_symlinks=False` request. The unchanged
probe treats that as unsupported. No link syscall occurs. Every other link call
still reaches the unchanged Guard denial. WindowsFileLock acquisition/release,
native ownership and lock semantics are untouched; no lockless substitution.

`local_policy` logs the denied event, normalized non-secret target and source
frames. A caught PermissionError cannot authorize the next startup phase.

## Boundaries

Only fresh synthetic profile/SQLite/media/settings are used. The child inherits
minimal system variables and no keys, tokens, proxies or real profile. Source,
runtime, built React assets and samples are read only. The only server listener
is owned IPv4 127.0.0.1:18765; 8765 is excluded. Outgoing DNS/connections, shell,
arbitrary workers, paid generation, OAuth and SNS routes remain denied.
Product Origin/CSRF and FileResponse/Range are unchanged. ASGI lifespan is not
entered; scheduler and background workers do not start.

This is a trusted Python test harness, not OS isolation against hostile Python
reflection. FileLock ownership is still tied to its original thread. Nested
character locks and other unregistered lock paths have not been authorized.
No actual supplier generation, posting, Windows task registration or DPI change.

## Known remaining limits

- Following explicit approval, only exact GET `/api/feed-batches` is added to
  the local HTTP surface. No HEAD, POST, prefix, generation or publishing grant.
  A saved synthetic batch is seeded without generation; actual GET returned 200
  and the batch state/revision remained unchanged after GUI reads.
- The narrow pointer issue was reproduced as a product CSS overlap: flex items
  shrank below their no-wrap text width. Four scoped CSS lines prevent menu
  button shrinking and keep horizontal scrolling. Explicit-coordinate pointer
  checks passed at nominal 545px and 1366px browser widths; no event handler changed.
- Actual OS DPI 100/125/150/200% and full production lifespan remain NOT VERIFIED.
- Image/video generation and character write stages were not exercised here.

Normal stop uses the owned synthetic profile's STOP file. Exceptional forced
cleanup is separately recorded, never counted as normal shutdown. Both current
attempts exited normally and left zero handles, descriptors, buffers, SQLite
connections, owned test threads or 18765 listener.

New focused tests: `python -B -m unittest test_initialization_fixes -v` (8 PASS).
The prior `test_local_policy` eight-test result is reused, not reported as a new run.

Evidence: `docs/reports/windows11-local-block-fix-20261028/LOCAL_BLOCK_FIX_REPORT.md`.
The previous BLOCKED attempt/report is retained as historical evidence.

Latest focused acceptance: `docs/reports/windows11-final-residual-20261028/FINAL_RESIDUAL_REPORT.md`.
New HTTP-surface contracts: `python -B -m unittest test_feed_read_surface -v` (5 PASS).
The earlier checks and 12-screen/media results were reused, not rerun in full.
