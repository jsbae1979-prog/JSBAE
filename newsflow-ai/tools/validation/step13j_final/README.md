# Step13J-final scoped Windows Fake checks

Only the final approved branch runs this workflow. Python 3.14.7 is required.
The workflow is not deployment and cannot publish, migrate an operating database,
connect an SNS account or use a provider key.

The disposable runner copies only source/tests/tools and required top-level launch
manifests beneath its private test root. No operating checkout, docs/reports tree,
.env file, backup or user-media directory is used. Test media is synthetic.

The five historical source fixture files come from immutable commit
0a59bfb41eec6b243e4470f67cd53c1e7cd07e52. Checkout uses command-environment
core.autocrlf=false, then git show reads binary blob bytes at the pinned commit and checks SHA-256.
Checkout CRLF/LF rules are never used as baseline evidence.
No operating Git command is used. The read-only fixture is placed at
baseline-code/files under the disposable root.

Existing Step13H/J browser, Node, FFmpeg and Job ownership helpers are reused.
The reviewed final native bridge is a test-only overlay, with executable/code
hashes, restricted entrypoints and synthetic environment handling. It does not
change the product Guard or globally allow Python/PowerShell execution.
The final native helper receives a separate tzdata-only vendor directory.

Phases and exact expected testcase counts are defined in phases-safe.json.
A failure, missing XML, duplicate test ID, skipped test, count mismatch or child
failure stops the run. Later phases are explicitly NOT RUN. No test is hidden
with skip/xfail. The workflow is a selected validation scope, not a claim that
the complete regression suite passed.

Only summary/count/ID JSON and the safe process-supervisor summaries are uploaded.
Raw logs, private configuration, SQLite, tokens, media and screenshots stay on the
throwaway runner. UTF-8 diagnostic summaries are preserved on Windows consoles.
Playwright request mocks do not prove every Chrome background request is blocked;
the summary retains that limitation and makes no complete OS-isolation claim.

This configuration was authored without running tests or dispatching/pushing.
The model phase count and exact 40 IDs are confirmed by parent-controlled local XML.
Other phase counts still require their final parent-controlled results before dispatch.

