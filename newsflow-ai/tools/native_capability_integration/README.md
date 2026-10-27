# Verification-only Guard/filelock contract integration

This folder is not a product dependency and does not replace filelock.
The approved native adapter and verification gate are reused without changes.

## What is implemented
- Named, registered synthetic capability sessions over the existing real byte lock.
- Same-thread reentrant counting and acquire-context/with-context behavior.
- Explicit finite 0–2 s timeout, nonblocking attempt and owner-only force release.
- Unheld release is a no-op. Failed acquisition does not change another owner.
- Unlock failure retains held state; post-unlock close failure records unheld
  cleanup-required state. Neither permits automatic reacquisition.
- Atomic synthetic state journals; journal failure blocks new execution.
- Explicit deterministic cleanup, no new subprocess or owner/PID inspection.

The name **ContractSession** is intentional. It is not filelock.FileLock,
BaseFileLock or an import shim. There is no monkey patch, extracted module
execution, preimport, raw native proxy or package dependency removal.

## What remains BLOCKED
- Existing step13_guard.py has no reviewed capability registration hook.
  Its DLL and symbol policy still rejects the current upstream import contract.
- Upstream filelock package runtime import/integration is NOT VERIFIED.
- Caller-owned CRT descriptor callbacks/lock_descriptor, arbitrary paths,
  pre-existing lock files, default unlink behavior, infinite timeout, singleton,
  cross-thread sharing, lifetime/stale-owner recovery, soft fallback, async/RW.
- OpenProcess/GetProcessTimes, arbitrary DLL/pointer/handle export.
- Full app execution and Windows 11 local integration/DPI.

Unsupported features raise CompatibilityBlocked rather than silently adopting
different semantics. Stable synthetic lock files are preserved; upstream default
delete-on-release compatibility is not claimed. GC cleanup compatibility is
not claimed; the test registry must be explicitly closed.

## Source evidence, not runtime substitution
contract_snapshot.json records the installed local filelock 3.32.7 metadata,
normalized AST hashes and real source line ranges. contract_probe.py reads the
upstream package installed in Windows CI without importing/executing it and
compares all eight source fingerprints. A source match only validates the
contract under review; it does not prove unmodified filelock runtime success.

run_integration.py installs the test gate before native binding, rejects product
and upstream-package imports, runs 24 new cases and 8 selected prior boundary
cases, checks source hashes, retains journal evidence, then removes all synthetic
data. Existing 39 PASS is reused and not rerun wholesale.

The security model remains a trusted verification harness, not an OS sandbox
against arbitrary Python reflection or compromised code. The operating Guard,
filelock installation and product entry points are never modified.
